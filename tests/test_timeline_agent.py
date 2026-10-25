"""
Testes do agente de timeline (timeline_agent) com o LM Studio simulado.

Nada aqui fala com a GPU: o que se prova é o contrato entre a IA e o motor, que
é justamente a parte que não pode falhar quando o modelo decide chamar uma
ferramenta. O SDK é simulado no ponto exato em que ele entra — AsyncClient,
list_loaded/list_downloaded/model e .act() —, com o mesmo wire format camelCase
que o SDK 1.5.0 usa.

Coberto:
- a superfície de ferramentas é fechada e nenhuma aceita comando de shell;
- toda ferramenta devolve JSON com "ok" e valida antes de tocar na timeline;
- operação rejeitada não move nada, não apaga nada e não gasta undo;
- exclusão exige aval explícito do usuário;
- cada edição aprovada é exatamente um passo de undo;
- o resumo enviado ao modelo tem teto, para não estourar a janela de contexto;
- o turno reporta o LM Studio fora do ar, o modelo ausente, a ambiguidade entre
  vários modelos e o estouro de prazo em linguagem acionável.
"""

import asyncio
import inspect
import json
import shutil
from types import SimpleNamespace

import lmstudio as lms
import pytest

import agent
import editor_render
import editor_project as ep
import timeline_agent
from conftest import MEDIA, requires_media
from editor_project import ProjectStore, get_clip


# --------------------------------------------------------------------- infra


@pytest.fixture
def loja(tmp_path, monkeypatch) -> ProjectStore:
    """Loja isolada para o agente, sem conversa pendente entre testes."""
    nova = ProjectStore(root=tmp_path / "projetos")
    monkeypatch.setattr(timeline_agent, "STORE", nova)
    timeline_agent.reset_chat()
    yield nova
    timeline_agent.reset_chat()


def _resposta(texto: str) -> dict:
    """Toda ferramenta devolve uma string JSON; jamais um rastreio."""
    assert isinstance(texto, str), "ferramenta precisa devolver texto"
    dados = json.loads(texto)
    assert isinstance(dados, dict)
    assert "ok" in dados
    return dados


def _projeto(nova: ProjectStore, nome: str = "Projeto IA") -> str:
    projeto = nova.create(nome, 1280, 720, 30)
    nova.set_active(projeto["id"])
    return projeto["id"]


def _por_nome(nome: str):
    for ferramenta in timeline_agent.TOOLS:
        if ferramenta.__name__ == nome:
            return ferramenta
    raise AssertionError(f"ferramenta {nome} não está registrada")


def _partes(mensagem) -> list[dict]:
    """Extrai o texto de uma entrada do Chat sem depender de atributo privado."""
    converter = getattr(mensagem, "to_dict", None)
    dados = converter() if callable(converter) else {"content": getattr(mensagem, "content", [])}
    conteudo = (dados or {}).get("content") or []
    partes = []
    for parte in conteudo:
        if isinstance(parte, dict):
            partes.append(parte)
        elif hasattr(parte, "to_dict"):
            partes.append(parte.to_dict())
        else:
            partes.append({"text": str(parte)})
    return partes


def _roda(coro):
    """Cada teste abre o próprio event loop; não dependemos de plugin asyncio."""
    return asyncio.run(coro)


async def _sem_eventos(evento: dict) -> None:
    return None


ID_AUSENTE = "p_0000000000"

# Algumas ferramentas validam os próprios argumentos antes de abrir o projeto;
# um argumento real é o que faz o caminho chegar até a loja e devolver 404.
_ARGUMENTOS_MINIMOS = {
    "configure_edit_project": {"width": 1920},
    "set_timeline_clip": {"clip_id": "c_qualquer", "volume": 0.5},
}


# ------------------------------------------------------------------ registro

NOMES_ESPERADOS = {
    "create_edit_project",
    "inspect_edit_project",
    "configure_edit_project",
    "add_timeline_clip",
    "add_timeline_text",
    "add_timeline_subtitles",
    "move_timeline_clip",
    "trim_timeline_clip",
    "split_timeline_clip",
    "delete_timeline_clip",
    "duplicate_timeline_clip",
    "fine_timeline_edit",
    "set_timeline_clip",
    "add_timeline_marker",
    "validate_timeline",
    "render_timeline",
    "check_render_job",
    "list_editor_skills",
    "load_editor_skill",
}


def test_conjunto_de_ferramentas_e_fechado_e_sem_duplicata():
    """
    A lista é o que o modelo pode tocar. Mudá-la passa por aqui, o que força a
    decisão de segurança de cada ferramenta nova.
    """
    nomes = {f.__name__ for f in timeline_agent.TOOLS}
    assert nomes == NOMES_ESPERADOS
    assert len(timeline_agent.TOOLS) == len(nomes)


def test_nenhuma_ferramenta_aceita_comando_de_shell():
    """Só o motor chega ao FFmpeg; a IA nunca recebe linha de comando nem caminho raiz."""
    proibidos = {"command", "cmd", "args", "argv", "shell", "script", "ffmpeg", "path"}
    for ferramenta in timeline_agent.TOOLS:
        argumentos = set(inspect.signature(ferramenta).parameters)
        assert not (argumentos & proibidos), f"{ferramenta.__name__} expõe {argumentos & proibidos}"
    fontes = open(timeline_agent.__file__, encoding="utf-8").read()
    for marca in ("subprocess", "os.system", "Popen", "eval(", "exec("):
        assert marca not in fontes, f"timeline_agent importa {marca}"


def test_toda_ferramenta_tem_docstring_que_o_modelo_le():
    for ferramenta in timeline_agent.TOOLS:
        doc = (ferramenta.__doc__ or "").strip()
        assert len(doc) > 40, f"{ferramenta.__name__} está sem docstring útil"


def test_prompt_de_sistema_declara_os_limites_do_motor():
    prompt = timeline_agent._system_prompt()
    assert "confirm=true" in prompt
    assert "Nunca invente" in prompt
    assert "check_render_job" in prompt
    for assunto in ("keyframe", "rastreamento", "transcri"):
        assert assunto in prompt, f"{assunto} não aparece na lista do que não prometer"


@pytest.mark.parametrize(
    "nome",
    sorted(
        f.__name__
        for f in timeline_agent.TOOLS
        if "project_id" in inspect.signature(f).parameters
    ),
)
def test_toda_ferramenta_de_projeto_traduz_id_desconhecido_em_json(nome, loja):
    """Nenhuma ferramenta deixa o erro virar exceção: o modelo precisa ler a resposta."""
    params = inspect.signature(_por_nome(nome)).parameters
    argumentos = dict(_ARGUMENTOS_MINIMOS.get(nome, {}))
    argumentos["project_id"] = ID_AUSENTE
    if "confirm" in params:
        argumentos["confirm"] = True
    resposta = _resposta(_por_nome(nome)(**argumentos))
    assert resposta["ok"] is False
    assert "não encontrado" in resposta["erro"]


# ------------------------------------------------------------------- projetos


def test_create_edit_project_deixa_o_novo_como_ativo(loja):
    resposta = _resposta(timeline_agent.create_edit_project("Aula", width=1080, height=1920))
    assert resposta["ok"] is True
    pid = resposta["project_id"]
    projeto = loja.get(pid)
    assert projeto["name"] == "Aula"
    assert (projeto["settings"]["width"], projeto["settings"]["height"]) == (1080, 1920)
    assert loja.get_active() == pid


def test_create_edit_project_recusa_nome_vazio_e_largura_impar(loja):
    assert _resposta(timeline_agent.create_edit_project(" "))["ok"] is False
    assert _resposta(timeline_agent.create_edit_project("Ímpar", width=1281))["ok"] is False
    assert loja.list_projects() == []


def test_configure_edit_project_exige_pelo_menos_um_campo(loja):
    pid = _projeto(loja)
    resposta = _resposta(timeline_agent.configure_edit_project(pid))
    assert resposta["ok"] is False
    assert "ao menos um campo" in resposta["erro"]
    assert loja.history(pid)["undo"] == []


def test_configure_edit_project_muda_resolucao_com_um_undo(loja):
    pid = _projeto(loja)
    assert _resposta(timeline_agent.configure_edit_project(pid, width=1920, height=1080))["ok"] is True
    assert loja.get(pid)["settings"]["width"] == 1920
    assert loja.history(pid)["undo"] == ["Alterar configurações"]


def test_inspect_sem_projeto_ativo_diz_o_que_fazer(loja):
    resposta = _resposta(timeline_agent.inspect_edit_project())
    assert resposta["ok"] is False
    assert "Nenhum projeto ativo" in resposta["erro"]


@requires_media
def test_inspect_devolve_tempos_e_ids_que_as_ferramentas_aceitam(loja):
    pid = _projeto(loja)
    with loja.edit(pid, "adicionar") as vivo:
        clipe = ep.add_clip(vivo, track_id="v1", source=str(MEDIA / "clipe_a.mp4"))
    resposta = json.loads(timeline_agent.inspect_edit_project(pid))
    assert resposta["ok"] is True
    assert resposta["project_id"] == pid
    assert resposta["duracao"] == "00:00:04"
    assert clipe["id"] in resposta["resumo"]
    assert resposta["erros"] == []


def test_brief_tem_teto_de_contexto(loja):
    """
    O resumo entra no prompt. Sem teto, um projeto grande empurra as instruções
    e os primeiros resultados para fora da janela e o modelo passa a inventar.
    """
    pid = _projeto(loja)
    with loja.edit(pid, "muitos titulos") as vivo:
        for i in range(120):
            ep.add_text_clip(vivo, "t1", text=f"titulo {i}", start=i * 10, duration=5)
    assert len(ep.project_summary(loja.get(pid))) > 5000
    resumo = json.loads(timeline_agent.inspect_edit_project(pid))["resumo"]
    assert len(resumo) <= 5000 + len("\n[resumo truncado]")
    assert resumo.endswith("[resumo truncado]")


# ------------------------------------------------------------------- edições


@requires_media
def test_add_clip_rejeita_arquivo_inexistente_sem_tocar_na_timeline(loja):
    pid = _projeto(loja)
    resposta = _resposta(timeline_agent.add_timeline_clip(pid, source="C:/nada/aqui.mp4"))
    assert resposta["ok"] is False
    assert "não encontrado" in resposta["erro"]
    assert loja.history(pid)["undo"] == []
    assert _faixa(loja.get(pid), "v1")["clips"] == []


@requires_media
def test_add_clip_recusa_colisao_na_mesma_faixa(loja):
    pid = _projeto(loja)
    primeiro = _resposta(timeline_agent.add_timeline_clip(
        pid, source=str(MEDIA / "clipe_a.mp4"), track="v1"))
    assert primeiro["ok"] is True
    conflito = _resposta(timeline_agent.add_timeline_clip(
        pid, source=str(MEDIA / "clipe_b.mp4"), track="v1", start=1))
    assert conflito["ok"] is False
    assert "colidir" in conflito["erro"]
    assert loja.history(pid)["undo"] == ["Adicionar clipe"]
    assert len(_faixa(loja.get(pid), "v1")["clips"]) == 1


@requires_media
def test_add_clip_recusa_velocidade_e_volume_fora_da_faixa(loja):
    pid = _projeto(loja)
    assert _resposta(timeline_agent.add_timeline_clip(
        pid, source=str(MEDIA / "clipe_a.mp4"), speed=99))["ok"] is False
    assert _resposta(timeline_agent.add_timeline_clip(
        pid, source=str(MEDIA / "clipe_a.mp4"), volume=9))["ok"] is False
    assert loja.history(pid)["undo"] == []


def test_cor_de_titulo_e_canonicizada_ou_recusada_antes_do_render(loja):
    pid = _projeto(loja)
    inventada = _resposta(timeline_agent.add_timeline_text(pid, text="Oi", color="cor-de-urubu"))
    assert inventada["ok"] is False
    assert "inválida" in inventada["erro"]
    assert _resposta(timeline_agent.add_timeline_text(pid, text="Oi", color="amarelo"))["ok"] is True
    cores = [c["text"]["color"] for c in _faixa(loja.get(pid), "t1")["clips"]]
    assert cores == ["#FFFF00"], "o motor guarda a forma hex que os dois filtros entendem"


def test_valor_fora_da_faixa_e_recusado_e_nao_gasta_undo(loja):
    pid = _projeto(loja)
    titulo = _resposta(timeline_agent.add_timeline_text(pid, text="Créditos", duration=2))
    resposta = _resposta(timeline_agent.set_timeline_clip(pid, clip_id=titulo["clip_id"], volume=99))
    assert resposta["ok"] is False
    assert loja.history(pid)["undo"] == ["Adicionar título"]


def test_set_sem_propriedade_alguma_e_recusado(loja):
    pid = _projeto(loja)
    titulo = _resposta(timeline_agent.add_timeline_text(pid, text="Créditos", duration=2))
    resposta = _resposta(timeline_agent.set_timeline_clip(pid, clip_id=titulo["clip_id"]))
    assert resposta["ok"] is False
    assert "Nenhuma propriedade" in resposta["erro"]
    assert loja.history(pid)["undo"] == ["Adicionar título"]


def test_propriedade_valida_altera_o_clipe_e_faz_um_undo(loja):
    pid = _projeto(loja)
    titulo = _resposta(timeline_agent.add_timeline_text(pid, text="Abertura", duration=2))
    resposta = _resposta(timeline_agent.set_timeline_clip(
        pid, clip_id=titulo["clip_id"], font_size=72, position="topo"))
    assert resposta["ok"] is True
    assert loja.history(pid)["undo"] == ["Alterar propriedades do clipe", "Adicionar título"]
    clipe = get_clip(loja.get(pid), titulo["clip_id"])[1]
    assert clipe["text"]["font_size"] == 72
    assert clipe["text"]["position"] == "topo"


def test_clipe_inexistente_e_reportado_com_o_id_que_o_modelo_usou(loja):
    pid = _projeto(loja)
    resposta = _resposta(timeline_agent.move_timeline_clip(pid, clip_id="c_fantasma", start=3))
    assert resposta["ok"] is False
    assert "c_fantasma" in resposta["erro"]
    assert loja.history(pid)["undo"] == []


def test_operacao_fina_so_aceita_slip_slide_roll(loja):
    pid = _projeto(loja)
    resposta = _resposta(timeline_agent.fine_timeline_edit(pid, clip_id="x", operation="warp"))
    assert resposta["ok"] is False
    assert "slip, slide ou roll" in resposta["erro"]
    assert loja.history(pid)["undo"] == []


def test_delete_sem_aval_do_usuario_nao_executa(loja):
    pid = _projeto(loja)
    titulo = _resposta(timeline_agent.add_timeline_text(pid, text="Para remover", duration=2))
    resposta = _resposta(timeline_agent.delete_timeline_clip(pid, clip_id=titulo["clip_id"]))
    assert resposta["ok"] is False
    assert resposta["requires_confirmation"] is True
    assert "confirm=true" in resposta["mensagem"]
    assert len(_faixa(loja.get(pid), "t1")["clips"]) == 1
    assert loja.history(pid)["undo"] == ["Adicionar título"]


def test_delete_com_aval_remove_e_continua_desfazivel(loja):
    pid = _projeto(loja)
    titulo = _resposta(timeline_agent.add_timeline_text(pid, text="Para remover", duration=2))
    removido = _resposta(timeline_agent.delete_timeline_clip(
        pid, clip_id=titulo["clip_id"], confirm=True))
    assert removido["ok"] is True
    assert _faixa(loja.get(pid), "t1")["clips"] == []
    assert loja.history(pid)["undo"] == ["Remover clipe", "Adicionar título"]
    loja.undo(pid)
    assert [c["id"] for c in _faixa(loja.get(pid), "t1")["clips"]] == [titulo["clip_id"]]


@requires_media
def test_split_e_duplicate_devolvem_os_novos_ids(loja):
    pid = _projeto(loja)
    clipe = _resposta(timeline_agent.add_timeline_clip(
        pid, source=str(MEDIA / "clipe_a.mp4"), track="v1"))
    dividido = _resposta(timeline_agent.split_timeline_clip(pid, clip_id=clipe["clip_id"], at=2))
    assert dividido["ok"] is True
    assert len(dividido["clip_ids"]) == 2
    duplicado = _resposta(timeline_agent.duplicate_timeline_clip(
        pid, clip_id=dividido["clip_ids"][0]))
    assert duplicado["ok"] is True
    assert duplicado["clip_id"] not in dividido["clip_ids"]
    assert len(_faixa(loja.get(pid), "v1")["clips"]) == 3
    assert loja.history(pid)["undo"] == ["Duplicar clipe", "Dividir clipe", "Adicionar clipe"]


def test_marcador_devolve_id_e_fica_na_timeline(loja):
    pid = _projeto(loja)
    resposta = _resposta(timeline_agent.add_timeline_marker(pid, time=12.5, label="pausa"))
    assert resposta["ok"] is True
    assert resposta["marker_id"].startswith("m")
    assert loja.get(pid)["markers"][0]["label"] == "pausa"


@requires_media
def test_validate_aponta_o_arquivo_que_sumiu_do_disco(loja, tmp_path):
    origem = tmp_path / "depois-sumiu.mp4"
    shutil.copyfile(MEDIA / "clipe_a.mp4", origem)
    pid = _projeto(loja)
    assert _resposta(timeline_agent.add_timeline_clip(
        pid, source=str(origem), track="v1"))["ok"] is True
    origem.unlink()
    resposta = _resposta(timeline_agent.validate_timeline(pid))
    assert resposta["ok"] is False
    assert [i for i in resposta["issues"] if i["severity"] == "error"]


def test_validate_de_projeto_vazio_nao_e_aprovado(loja):
    assert _resposta(timeline_agent.validate_timeline(_projeto(loja)))["ok"] is False


# ------------------------------------------------------------------- render


def test_render_devolve_o_job_sem_esperar_o_ffmpeg(loja, monkeypatch):
    chamadas: list[tuple[str, dict]] = []

    class _Fila:
        def submit(self, project_id, options):
            chamadas.append((project_id, options))
            return {"id": "job_abc", "status": "queued", "output_name": "Projeto-IA_preview.mp4"}

    monkeypatch.setattr(timeline_agent, "MANAGER", _Fila())
    pid = _projeto(loja)
    resposta = _resposta(timeline_agent.render_timeline(pid))
    assert resposta["ok"] is True
    assert resposta["job_id"] == "job_abc"
    assert resposta["output_name"] == "Projeto-IA_preview.mp4"
    assert "check_render_job" in resposta["mensagem"]
    assert chamadas == [(pid, {"preview": True, "format": "mp4"})]


def test_render_repassa_as_escolhas_de_exportacao(loja, monkeypatch):
    chamadas: list[dict] = []

    class _Fila:
        def submit(self, project_id, options):
            chamadas.append(options)
            return {"id": "job_x", "status": "queued", "output_name": "final.mkv"}

    monkeypatch.setattr(timeline_agent, "MANAGER", _Fila())
    pid = _projeto(loja)
    _resposta(timeline_agent.render_timeline(
        pid, preview=False, filename="Final", crf=18, format="mkv"))
    assert chamadas == [{"preview": False, "format": "mkv", "filename": "Final", "crf": 18}]


def test_render_de_projeto_sem_ipes_e_recusado_antes_de_abrir_thread(loja, monkeypatch, render_dir):
    fila = editor_render.RenderManager(store=loja)
    monkeypatch.setattr(timeline_agent, "MANAGER", fila)
    pid = _projeto(loja)
    resposta = _resposta(timeline_agent.render_timeline(pid, preview=True))
    assert resposta["ok"] is False
    assert resposta["erro"]
    assert fila.list(pid) == []


def test_check_render_job_mostra_status_progresso_e_qc(loja, monkeypatch):
    job = {
        "id": "job_1", "status": "done", "progress": 100, "message": "Concluído",
        "output_name": "P_preview.mp4", "error": None,
        "qc": {"ok": True, "issues": [{"code": "aviso"}] * 20,
               "measurements": {"duration": 4.0}},
    }
    monkeypatch.setattr(timeline_agent, "MANAGER", SimpleNamespace(get=lambda job_id: job))
    resposta = _resposta(timeline_agent.check_render_job("job_1"))
    assert resposta["ok"] is True
    assert resposta["arquivo"] == "P_preview.mp4"
    assert resposta["qc"]["measurements"]["duration"] == 4.0
    assert len(resposta["qc"]["issues"]) == 12, "a lista vem limitada para caber no contexto"


def test_check_render_job_em_andamento_nao_diz_que_acabou(loja, monkeypatch):
    job = {"id": "job_2", "status": "running", "progress": 40, "message": "Codificando",
           "output_name": None, "error": None, "qc": None}
    monkeypatch.setattr(timeline_agent, "MANAGER", SimpleNamespace(get=lambda job_id: job))
    resposta = _resposta(timeline_agent.check_render_job("job_2"))
    assert resposta["ok"] is False
    assert resposta["qc"] is None
    assert resposta["progress"] == 40


def test_check_render_job_de_id_inexistente_devolve_erro_legivel(loja):
    resposta = _resposta(timeline_agent.check_render_job("job_que_nao_existe"))
    assert resposta["ok"] is False
    assert "não encontrada" in resposta["erro"]


# ------------------------------------------------------------------- skills


def test_list_editor_skills_so_anuncia_skill_completa(loja):
    resposta = json.loads(timeline_agent.list_editor_skills())
    assert resposta["skills"]
    assert all(item["complete"] for item in resposta["skills"])
    assert all(item["name"] and item["description"] for item in resposta["skills"])


def test_load_editor_skill_devolve_o_procedimento(loja):
    resposta = json.loads(timeline_agent.load_editor_skill("video-editor-core"))
    assert resposta["name"] == "video-editor-core"
    assert "## 10." in resposta["content"]


def test_load_editor_skill_inexistente_devolve_erro(loja):
    assert _resposta(timeline_agent.load_editor_skill("faz-cafe"))["ok"] is False


# -------------------------------------------------------- turno com LM Studio


class _ModeloFalso:
    """Imita o .act() do SDK: entrega eventos no wire format e devolve o texto."""

    def __init__(self, ao_atuar):
        self._ao_atuar = ao_atuar

    async def act(self, chat, tools, on_message=None, **_kwargs):
        return await self._ao_atuar(chat, tools, on_message)


class _LlmFalso:
    def __init__(self, carregados=(), baixados=(), modelo=None, erro_modelo=None):
        self.carregados = list(carregados)
        self.baixados = list(baixados)
        self.modelo = modelo
        self.erro_modelo = erro_modelo
        self.carga: dict = {}

    async def list_loaded(self):
        return self.carregados

    async def list_downloaded(self):
        return self.baixados

    async def model(self, key, **kwargs):
        self.carga = {"key": key, **kwargs}
        if self.erro_modelo:
            raise self.erro_modelo
        return self.modelo


class _ClienteFalso:
    def __init__(self, llm, erro_entrada=None):
        self.llm = llm
        self.erro_entrada = erro_entrada
        self.fechado = False

    async def __aenter__(self):
        if self.erro_entrada:
            raise self.erro_entrada
        return self

    async def __aexit__(self, *exc):
        self.fechado = True
        return False


def _instala_cliente(monkeypatch, cliente, modelo_nome=""):
    """Põe o cliente simulado no lugar do SDK e trava a escolha de modelo."""
    monkeypatch.setattr(timeline_agent, "AsyncClient", lambda **kwargs: cliente)
    monkeypatch.setattr(agent, "MODEL_NAME", modelo_nome)
    return cliente


def _turno_chamando(nome, argumentos, texto_final):
    async def ao_atuar(chat, tools, on_message):
        ferramenta = {f.__name__: f for f in tools}[nome]
        on_message({"content": [{"type": "toolCallRequest", "toolCallRequest": {
            "name": nome, "id": "call_1", "arguments": argumentos}}]})
        on_message({"content": [{"type": "toolCallResult", "toolCallId": "call_1",
                                "content": ferramenta(**argumentos)}]})
        on_message({"content": [{"type": "text", "text": texto_final}]})
    return _ModeloFalso(ao_atuar)


def test_turno_chama_a_ferramenta_e_reporta_cada_evento_na_ordem(loja, monkeypatch):
    pid = _projeto(loja)
    final = "Abertura colocada na timeline."
    modelo = _turno_chamando("add_timeline_text", {"project_id": pid, "text": "Abertura"}, final)
    cliente = _instala_cliente(monkeypatch, _ClienteFalso(_LlmFalso(carregados=[modelo])))

    eventos: list[dict] = []

    async def on_event(evento):
        eventos.append(evento)

    resposta = _roda(timeline_agent.run_timeline_turn(pid, "põe um título de abertura", on_event))
    assert resposta == final
    assert cliente.fechado is True
    assert [e["kind"] for e in eventos] == ["tool_call", "tool_result", "text", "answer"]
    assert eventos[0]["name"] == "add_timeline_text"
    assert eventos[0]["args"] == {"project_id": pid, "text": "Abertura"}
    assert eventos[1]["name"] == "add_timeline_text", "o resultado é entregue com o nome da chamada"
    assert json.loads(eventos[1]["result"])["ok"] is True
    assert eventos[3]["duration"] >= 0
    assert len(_faixa(loja.get(pid), "t1")["clips"]) == 1


def test_turno_de_ferramenta_recusada_nao_edita_nem_esconde_o_motivo(loja, monkeypatch):
    pid = _projeto(loja)
    modelo = _turno_chamando(
        "delete_timeline_clip", {"project_id": pid, "clip_id": "c_qualquer"}, "preciso de aval")
    _instala_cliente(monkeypatch, _ClienteFalso(_LlmFalso(carregados=[modelo])))

    eventos: list[dict] = []

    async def on_event(evento):
        eventos.append(evento)

    _roda(timeline_agent.run_timeline_turn(pid, "apaga tudo", on_event))
    resultado = json.loads(eventos[1]["result"])
    assert resultado["requires_confirmation"] is True
    assert _faixa(loja.get(pid), "t1")["clips"] == []


def test_turno_guarda_a_conversa_por_projeto_e_o_reset_escolhe_o_escopo(loja, monkeypatch):
    um = _projeto(loja, "Um")
    dois = _projeto(loja, "Dois")
    modelo = _turno_chamando("add_timeline_marker", {"project_id": um, "time": 1}, "ok")
    _instala_cliente(monkeypatch, _ClienteFalso(_LlmFalso(carregados=[modelo])))

    async def silencioso(evento):
        return None

    _roda(timeline_agent.run_timeline_turn(um, "marcador", silencioso))
    assert set(timeline_agent._chats) == {um}
    _roda(timeline_agent.run_timeline_turn(dois, "marcador", silencioso))
    assert timeline_agent._chats[um] is not timeline_agent._chats[dois]

    timeline_agent.reset_chat(um)
    assert set(timeline_agent._chats) == {dois}
    timeline_agent.reset_chat()
    assert timeline_agent._chats == {}


def test_turno_cadastra_o_contexto_do_projeto_na_mensagem_do_usuario(loja, monkeypatch):
    pid = _projeto(loja, "Aula de física")
    visto: dict = {}

    def texto_da(mensagem) -> str:
        # o SDK 1.5.0 não expõe get_messages(); o histórico vive em _messages
        return " ".join(str(p.get("text", "")) for p in _partes(mensagem))

    async def guardar(chat, tools, on_message):
        visto["system"] = texto_da(chat._messages[0])
        visto["user"] = texto_da(chat._messages[1])

    _instala_cliente(monkeypatch, _ClienteFalso(_LlmFalso(carregados=[_ModeloFalso(guardar)])))

    _roda(timeline_agent.run_timeline_turn(pid, "analisa", _sem_eventos))
    assert pid in visto["user"]
    assert "Aula de física" in visto["user"]
    assert "1280x720" in visto["user"]
    assert "analisa" in visto["user"]
    assert "inspect_edit_project" in visto["system"]


def test_turno_sem_texto_do_modelo_devolve_aviso_em_lugar_de_resposta_vazia(loja, monkeypatch):
    async def sem_fala(chat, tools, on_message):
        return None

    _instala_cliente(monkeypatch, _ClienteFalso(
        _LlmFalso(carregados=[_ModeloFalso(sem_fala)])))
    pid = _projeto(loja)

    eventos: list[dict] = []

    async def on_event(evento):
        eventos.append(evento)

    resposta = _roda(timeline_agent.run_timeline_turn(pid, "oi", on_event))
    assert resposta == "A IA terminou sem texto de resposta."
    assert eventos[-1]["kind"] == "answer"


def test_turno_reporta_lm_studio_fora_do_ar_com_o_que_abrir(loja, monkeypatch):
    _instala_cliente(monkeypatch, _ClienteFalso(
        _LlmFalso(),
        erro_entrada=ConnectionRefusedError("[WinError 10061] Nenhuma conexão pôde ser feita")))
    pid = _projeto(loja)

    with pytest.raises(timeline_agent.TimelineAgentError) as info:
        _roda(timeline_agent.run_timeline_turn(pid, "corte o clipe", _sem_eventos))
    assert "LM Studio não acessível" in str(info.value)
    assert "Developer" in str(info.value)


def test_turno_traduz_a_recusa_de_token_deformada_pelo_sdk(loja, monkeypatch):
    """O SDK 1.5.0 esconde a recusa de token num ValueError genérico."""
    _instala_cliente(monkeypatch, _ClienteFalso(
        _LlmFalso(), erro_entrada=ValueError("dictionary update sequence element #0")))
    pid = _projeto(loja)

    with pytest.raises(timeline_agent.TimelineAgentError) as info:
        _roda(timeline_agent.run_timeline_turn(pid, "corte", _sem_eventos))
    assert "autenticação" in str(info.value)
    assert "127.0.0.1" in str(info.value)


def test_turno_sem_modelo_baixado_manda_baixar_na_aba_discover(loja, monkeypatch):
    _instala_cliente(monkeypatch, _ClienteFalso(_LlmFalso()))
    pid = _projeto(loja)

    with pytest.raises(timeline_agent.TimelineAgentError) as info:
        _roda(timeline_agent.run_timeline_turn(pid, "corte", _sem_eventos))
    assert "Nenhum modelo de linguagem baixado" in str(info.value)
    assert "Discover" in str(info.value)


def test_dois_modelos_baixados_sem_nenhum_carregado_pedem_escolha_explicita(loja, monkeypatch):
    class _Baixado:
        def __init__(self, chave):
            self.model_key = chave

    # _resolve_llm filtra por isinstance(m, lms.AsyncDownloadedLlm); trocando a
    # classe pelo stub o teste simula o SDK sem construir um objeto real.
    monkeypatch.setattr(lms, "AsyncDownloadedLlm", _Baixado)
    pid = _projeto(loja)
    llm = _LlmFalso(baixados=[_Baixado("qwen/um"), _Baixado("qwen/dois")])
    _instala_cliente(monkeypatch, _ClienteFalso(llm))

    with pytest.raises(timeline_agent.TimelineAgentError) as info:
        _roda(timeline_agent.run_timeline_turn(pid, "corte", _sem_eventos))
    assert "CLIPMIND_MODEL" in str(info.value)
    assert "qwen/um" in str(info.value) and "qwen/dois" in str(info.value)


def test_descoberta_carrega_o_unico_modelo_baixado_com_o_contexto_configurado(
    loja, monkeypatch
):
    class _Baixado:
        model_key = "qwen/qwen3.8-27b"

    monkeypatch.setattr(lms, "AsyncDownloadedLlm", _Baixado)
    monkeypatch.setattr(agent, "CONTEXT_LENGTH", 8192)

    async def sem_edicao(chat, tools, on_message):
        return None

    modelo = _ModeloFalso(sem_edicao)
    llm = _LlmFalso(baixados=[_Baixado()], modelo=modelo)
    _instala_cliente(monkeypatch, _ClienteFalso(llm))
    pid = _projeto(loja)

    _roda(timeline_agent.run_timeline_turn(pid, "só pensar", _sem_eventos))
    assert llm.carga["key"] == "qwen/qwen3.8-27b"
    assert llm.carga["config"] == {"contextLength": 8192}
    assert callable(llm.carga["on_load_progress"])


def test_modelo_configurado_inexistente_lista_os_baixados(loja, monkeypatch):
    llm = _LlmFalso(
        baixados=[SimpleNamespace(model_key="qwen/qwen3.8-27b")],
        erro_modelo=lms.LMStudioModelNotFoundError("não tem"),
    )
    _instala_cliente(monkeypatch, _ClienteFalso(llm), modelo_nome="qwen/nao-baixado")
    pid = _projeto(loja)

    with pytest.raises(timeline_agent.TimelineAgentError) as info:
        _roda(timeline_agent.run_timeline_turn(pid, "corte", _sem_eventos))
    assert "qwen/nao-baixado" in str(info.value)
    assert "não existe no LM Studio" in str(info.value)
    assert "qwen/qwen3.8-27b" in str(info.value)


def test_turno_estoura_o_prazo_e_libera_a_interface(loja, monkeypatch):
    async def lento(chat, tools, on_message):
        await asyncio.sleep(1)

    cliente = _instala_cliente(monkeypatch, _ClienteFalso(
        _LlmFalso(carregados=[_ModeloFalso(lento)])))
    monkeypatch.setattr(timeline_agent, "TURN_TIMEOUT", 0.05)
    pid = _projeto(loja)

    with pytest.raises(timeline_agent.TimelineAgentError) as info:
        _roda(timeline_agent.run_timeline_turn(pid, "faz um resumo longo", _sem_eventos))
    assert "interrompido" in str(info.value)
    assert "tente de novo com um pedido menor" in str(info.value)
    assert cliente.fechado is True


def test_turno_apos_o_prazo_mantem_o_que_o_modelo_ja_disse(loja, monkeypatch):
    async def fala_e_dorme(chat, tools, on_message):
        on_message({"content": [{"type": "text", "text": "Cortei a primeira parte."}]})
        await asyncio.sleep(1)

    _instala_cliente(monkeypatch, _ClienteFalso(
        _LlmFalso(carregados=[_ModeloFalso(fala_e_dorme)])))
    monkeypatch.setattr(timeline_agent, "TURN_TIMEOUT", 0.05)
    pid = _projeto(loja)

    with pytest.raises(timeline_agent.TimelineAgentError):
        _roda(timeline_agent.run_timeline_turn(pid, "continua", _sem_eventos))
    historico = [str(m) for m in timeline_agent._chats[pid]._messages]
    assert any("Cortei a primeira parte." in m for m in historico)


def test_turno_devolve_erro_legivel_em_lugar_de_rastreio_para_a_interface(
    loja, monkeypatch
):
    async def explode(chat, tools, on_message):
        raise RuntimeError("boom bem interno de editor_api")

    _instala_cliente(monkeypatch, _ClienteFalso(
        _LlmFalso(carregados=[_ModeloFalso(explode)])))
    pid = _projeto(loja)

    with pytest.raises(timeline_agent.TimelineAgentError) as info:
        _roda(timeline_agent.run_timeline_turn(pid, "vai", _sem_eventos))
    assert "boom bem interno" in str(info.value)
    assert "Traceback" not in str(info.value)


def test_turno_em_projeto_inexistente_nao_chega_a_falar_com_o_modelo(loja):
    with pytest.raises(ep.ProjectError):
        _roda(timeline_agent.run_timeline_turn(ID_AUSENTE, "oi", _sem_eventos))


# ------------------------------------------------------------------ faixas


def _faixa(projeto: dict, track_id: str) -> dict:
    for faixa in projeto["tracks"]:
        if faixa["id"] == track_id:
            return faixa
    raise AssertionError(f"faixa {track_id} ausente")
