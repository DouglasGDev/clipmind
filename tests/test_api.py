"""
Testes da camada HTTP de editor_api (as rotas do editor profissional).

Cobrem a página, o status, o CRUD de projetos, as operações de timeline,
undo/redo, versões, validação, o serviço de mídia, o catálogo de skills, as
tarefas de render e o comportamento diante de corpos malformados.

O app é montado à mão (FastAPI + router) para não arrastar a rota de WebSocket
de server.py. O chat (POST /api/editor/projects/{id}/chat e /chat/reset) e o
WebSocket NÃO são exercitados aqui: exigem o LM Studio de pé.

Os handlers usam o STORE singleton de editor_project, que tests/conftest.py já
isolou em CLIPMIND_PROJECTS, apontando para uma árvore descartável.
"""

import json
import re
import time
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import editor_api
import editor_skills
from conftest import MEDIA, requires_media

ID_PROJETO = re.compile(r"^p_[a-f0-9]{10}$")
_CHAVES_PAYLOAD = {"project", "issues", "history", "summary", "active"}


# -------------------------------------------------------------------- infra


@pytest.fixture
def app() -> FastAPI:
    """App mínimo: só o router do editor, sem WebSocket e sem herdar server.py."""
    nova_app = FastAPI()
    nova_app.include_router(editor_api.router)
    return nova_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    # raise_server_exceptions=False: um erro não tratado vira resposta 500 e o
    # teste consegue conferir o código em vez de estourar o rastreio para fora.
    with TestClient(app, raise_server_exceptions=False) as novo_cliente:
        yield novo_cliente


@pytest.fixture(autouse=True)
def eventos() -> list[dict]:
    """
    Instala um sink de broadcast trivial e devolve o que foi emitido.

    _emit() já tolera _sink ausente (não quebraria os testes), mas o sink
    gravador prova que as rotas disparam os eventos que a interface escuta e
    ainda isola o global entre testes.
    """
    registrados: list[dict] = []

    async def sink(evento: dict) -> None:
        registrados.append(evento)

    anterior = editor_api._sink
    editor_api._sink = sink
    try:
        yield registrados
    finally:
        editor_api._sink = anterior


def _criar(client: TestClient, nome: str = "Projeto HTTP", **campos) -> dict:
    corpo: dict = {"name": nome, "width": 1280, "height": 720, "fps": 30}
    corpo.update(campos)
    resposta = client.post("/api/editor/projects", json=corpo)
    assert resposta.status_code == 200, resposta.text
    payload = resposta.json()
    assert payload["active"] == payload["project"]["id"]
    return payload


def _operacao(client: TestClient, project_id: str, operacao: str, **params) -> dict:
    resposta = client.post(
        f"/api/editor/projects/{project_id}/operations",
        json={"operation": operacao, "params": params},
    )
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def _faixa(payload: dict, track_id: str) -> dict:
    for faixa in payload["project"]["tracks"]:
        if faixa["id"] == track_id:
            return faixa
    raise AssertionError(f"faixa {track_id} ausente no payload")


def _clipes(payload: dict, track_id: str) -> list[dict]:
    return _faixa(payload, track_id)["clips"]


def _conferir_payload(payload: dict) -> None:
    """Confere o formato que static/editor.js consome em applyPayload()."""
    assert _CHAVES_PAYLOAD <= set(payload)
    projeto = payload["project"]
    assert ID_PROJETO.match(projeto["id"])
    assert isinstance(projeto["name"], str) and projeto["name"]
    assert {"schema", "settings", "tracks", "markers", "regions", "media",
            "duration", "missing_media", "created_at", "updated_at"} <= set(projeto)
    assert isinstance(projeto["duration"], (int, float))
    for faixa in projeto["tracks"]:
        assert {"id", "type", "name", "clips", "muted", "hidden", "locked", "end"} <= set(faixa)
        for clipe in faixa["clips"]:
            assert {"id", "type", "source", "name", "start", "in", "out",
                    "duration", "end", "speed", "volume"} <= set(clipe)
    for issue in payload["issues"]:
        assert {"severity", "code", "message"} <= set(issue)
        assert issue["severity"] in {"error", "warning", "info"}
    assert {"undo", "redo"} <= set(payload["history"])
    assert all(isinstance(item, str) for item in payload["history"]["undo"])
    assert isinstance(payload["summary"], str) and payload["summary"]
    assert payload["active"] is None or ID_PROJETO.match(payload["active"])


# ------------------------------------------------------------- página/status


def test_pagina_do_editor_devolve_o_esqueleto_html(client: TestClient):
    resposta = client.get("/editor")
    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("text/html")
    html = resposta.text
    assert "ClipMind" in html
    assert 'id="project-select"' in html
    assert 'id="timeline-content"' in html
    assert 'id="program-video"' in html
    assert "/static/editor.js" in html


def test_status_devolve_dicionario_renderizavel(client: TestClient):
    resposta = client.get("/api/editor/status")
    assert resposta.status_code == 200
    status = resposta.json()
    # chaves comuns aos dois ramos de agent_status() + o acréscimo desta rota
    assert {"connected", "model", "skills"} <= set(status)
    assert isinstance(status["connected"], bool)
    assert isinstance(status["model"], str) and status["model"]
    assert status["skills"] == len(editor_skills.list_skills())
    if status["connected"]:
        assert isinstance(status["has_matching_model"], bool)
        assert isinstance(status["loaded_models"], list)
        assert isinstance(status["downloaded_count"], int)
    else:
        assert isinstance(status["error"], str) and status["error"]


def test_rota_inexistente_devolve_404_sem_rastreio(client: TestClient):
    resposta = client.get("/api/editor/nao-existe")
    assert resposta.status_code == 404
    assert "Traceback" not in resposta.text


# ----------------------------------------------------------------- CRUD


def test_criar_projeto_devolve_timeline_com_faixas_padrao(client: TestClient):
    payload = _criar(client, "Meu filme", width=1920, height=1080, fps="30000/1001")
    _conferir_payload(payload)
    projeto = payload["project"]
    assert projeto["name"] == "Meu filme"
    assert projeto["settings"]["width"] == 1920
    assert projeto["settings"]["height"] == 1080
    assert projeto["settings"]["fps"] == pytest.approx(29.97, abs=0.01)
    assert [faixa["id"] for faixa in projeto["tracks"]] == ["v1", "v2", "t1", "s1", "a1"]
    assert projeto["duration"] == 0.0
    assert projeto["tracks"][0]["clips"] == []


def test_listar_projetos_inclui_o_criado_com_resumo(client: TestClient):
    pid = _criar(client, "Na lista")["project"]["id"]
    resposta = client.get("/api/editor/projects")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert {"projects", "active"} <= set(corpo)
    assert corpo["active"] == pid
    itens = {item["id"]: item for item in corpo["projects"]}
    assert pid in itens
    item = itens[pid]
    assert {"id", "name", "updated_at", "created_at", "duration", "clip_count",
            "width", "height", "fps"} <= set(item)
    assert item["name"] == "Na lista"
    assert item["clip_count"] == 0
    assert item["width"] == 1280


@requires_media
def test_obter_projeto_devolve_timeline_versoes_e_tarefas(client: TestClient):
    pid = _criar(client, "Detalhe")["project"]["id"]
    _operacao(client, pid, "add_clip", track_id="v1", source=str(MEDIA / "clipe_a.mp4"))
    resposta = client.get(f"/api/editor/projects/{pid}")
    assert resposta.status_code == 200
    corpo = resposta.json()
    _conferir_payload(corpo)
    assert {"versions", "jobs"} <= set(corpo)
    assert isinstance(corpo["versions"], list)
    assert corpo["jobs"] == []
    clipe = _clipes(corpo, "v1")[0]
    assert clipe["name"] == "clipe_a.mp4"
    assert clipe["duration"] == pytest.approx(4.0, abs=0.1)
    assert clipe["source_duration"] == pytest.approx(4.0, abs=0.1)


@pytest.mark.parametrize("project_id", ["p_0000000000"])
def test_obter_projeto_inexistente_e_recurso_ausente(client: TestClient, project_id: str):
    resposta = client.get(f"/api/editor/projects/{project_id}")
    assert resposta.status_code == 404
    assert "não encontrado" in resposta.json()["detail"]


@pytest.mark.parametrize("project_id", ["nao-existe", "p_ZZZZZZZZZZ", "p_00"])
def test_obter_projeto_com_id_fora_do_formato_e_erro_de_cliente(client: TestClient, project_id: str):
    resposta = client.get(f"/api/editor/projects/{project_id}")
    assert resposta.status_code == 400
    assert "inválido" in resposta.json()["detail"]


def test_obter_projeto_com_traversal_no_id_e_recusado(client: TestClient):
    resposta = client.get(f"/api/editor/projects/{quote('../../etc/passwd', safe='')}")
    assert 400 <= resposta.status_code < 500
    assert "root:" not in resposta.text


def test_ativar_projeto_muda_o_ativo(client: TestClient):
    um = _criar(client, "Um")["project"]["id"]
    dois = _criar(client, "Dois")["project"]["id"]
    resposta = client.post(f"/api/editor/projects/{um}/activate")
    assert resposta.status_code == 200
    assert resposta.json()["active"] == um
    assert client.get("/api/editor/projects").json()["active"] == um
    assert client.post(f"/api/editor/projects/{dois}/activate").json()["active"] == dois
    assert client.post("/api/editor/projects/p_0000000000/activate").status_code == 404


def test_excluir_sem_confirmacao_preserva_o_projeto(client: TestClient):
    pid = _criar(client, "Quase excluído")["project"]["id"]
    resposta = client.delete(f"/api/editor/projects/{pid}")
    assert resposta.status_code == 400
    assert "confirmação" in resposta.json()["detail"]
    assert client.get(f"/api/editor/projects/{pid}").status_code == 200
    assert pid in [item["id"] for item in client.get("/api/editor/projects").json()["projects"]]


def test_excluir_com_confirmacao_some_da_lista(client: TestClient, eventos: list[dict]):
    pid = _criar(client, "Excluído")["project"]["id"]
    eventos.clear()
    resposta = client.delete(f"/api/editor/projects/{pid}", params={"confirm": "true"})
    assert resposta.status_code == 200
    assert resposta.json() == {"ok": True}
    assert client.get(f"/api/editor/projects/{pid}").status_code == 404
    assert pid not in [item["id"] for item in client.get("/api/editor/projects").json()["projects"]]
    assert {"type": "editor_projects"} in eventos


@pytest.mark.parametrize(
    "corpo",
    [
        {"name": "   "},                      # o motor rejeita nome em branco
        {"name": "x" * 121},                  # limite de 120 caracteres
        {"name": "Ruim", "width": 1921},      # ímpar: o H.264 não aceita
        {"name": "Ruim", "height": 1081},
        {"name": "Ruim", "width": 10, "height": 10},
        {"name": "Ruim", "height": 9000},
        {"name": "Ruim", "fps": 500},         # fora de 1..240
        {"name": "Ruim", "fps": 0.5},
        {"name": "Ruim", "fps": "vinte"},
        {"name": "Ruim", "width": "abc"},     # int("abc") -> ValueError tratado
    ],
)
def test_criar_projeto_com_corpo_invalido_devolve_400(client: TestClient, corpo: dict):
    resposta = client.post("/api/editor/projects", json=corpo)
    assert resposta.status_code == 400
    assert resposta.json()["detail"]
    assert "Traceback" not in resposta.text


def test_criar_projeto_deixa_os_campos_ausentes_nos_padroes(client: TestClient):
    """
    Campo omitido usa o padrão; campo presente com valor sem sentido é erro.
    Engolir name:"" e width:0 atrás de `or` criava projetos impossíveis de
    encontrar na lista e resoluções que o FFmpeg não codifica.
    """
    resposta = client.post("/api/editor/projects", json={"name": "So o nome"})
    assert resposta.status_code == 200
    assert resposta.json()["project"]["settings"] == {
        "width": 1920, "height": 1080, "fps": 30.0, "audio_rate": 48000,
    }


@pytest.mark.parametrize(
    "corpo",
    [
        {"name": ""},
        {"name": "Zeros", "width": 0, "fps": 0},
        {"name": "Zeros", "height": 0},
    ],
)
def test_criar_projeto_com_valor_falsy_e_recusado(client: TestClient, corpo: dict):
    resposta = client.post("/api/editor/projects", json=corpo)
    assert resposta.status_code == 400
    assert "Traceback" not in resposta.text


# --------------------------------------------------------------- operações


@requires_media
def test_operacao_add_clip_devolve_payload_com_midia(client: TestClient, eventos: list[dict]):
    pid = _criar(client, "Operações")["project"]["id"]
    eventos.clear()
    payload = _operacao(client, pid, "add_clip", track_id="v1", source=str(MEDIA / "clipe_a.mp4"))
    _conferir_payload(payload)
    clipe = _clipes(payload, "v1")[0]
    assert clipe["type"] == "video"
    assert clipe["start"] == 0.0
    assert clipe["in"] == 0.0
    assert clipe["out"] == pytest.approx(4.0, abs=0.1)
    assert clipe["duration"] == pytest.approx(4.0, abs=0.1)
    assert clipe["end"] == pytest.approx(4.0, abs=0.1)
    assert clipe["source_duration"] == pytest.approx(4.0, abs=0.1)
    assert clipe["has_video"] is True
    assert clipe["missing"] is False
    assert payload["project"]["duration"] == pytest.approx(4.0, abs=0.1)
    assert Path(clipe["source"]).is_file()
    assert clipe["source"] in payload["project"]["media"]
    assert payload["project"]["missing_media"] == []
    assert payload["history"]["undo"] == ["add_clip"]
    assert payload["history"]["redo"] == []
    assert pid in payload["summary"]
    assert eventos == [
        {"type": "editor_project_changed", "project_id": pid, "operation": "add_clip"}
    ]


@requires_media
def test_ciclo_de_edicoes_pela_rota_de_operacoes(client: TestClient):
    pid = _criar(client, "Montagem")["project"]["id"]

    a = _operacao(client, pid, "add_clip", track_id="v1", source=str(MEDIA / "clipe_a.mp4"), start=0)
    ida = _clipes(a, "v1")[0]["id"]
    b = _operacao(client, pid, "add_clip", track_id="v1", source=str(MEDIA / "clipe_b.mp4"), start=6)
    idb = _clipes(b, "v1")[1]["id"]
    assert [c["id"] for c in _clipes(b, "v1")] == [ida, idb]

    texto = _operacao(client, pid, "add_text", track_id="t1", text="Abertura", start=0, duration=2)
    assert _clipes(texto, "t1")[0]["text"]["content"] == "Abertura"

    dividido = _operacao(client, pid, "split", clip_id=ida, at=2.0)
    clipes = _clipes(dividido, "v1")
    assert len(clipes) == 3
    assert clipes[0]["out"] == clipes[1]["in"], "a divisão não pode duplicar nem pular quadros"
    primeiro = clipes[0]["id"]

    movido = _operacao(client, pid, "move", clip_id=idb, start=10)
    assert _procurar(_clipes(movido, "v1"), idb)["start"] == 10.0

    cortado = _operacao(client, pid, "trim", clip_id=primeiro, out_point=1.0)
    assert _procurar(_clipes(cortado, "v1"), primeiro)["duration"] == pytest.approx(1.0)

    ajustado = _operacao(client, pid, "set", clip_id=primeiro, volume=0.5, transform_scale=1.25)
    alvo = _procurar(_clipes(ajustado, "v1"), primeiro)
    assert alvo["volume"] == 0.5
    assert alvo["transform"]["scale"] == 1.25

    marcado = _operacao(client, pid, "add_marker", time=1.5, label="capítulo")
    assert marcado["project"]["markers"][0]["label"] == "capítulo"
    assert marcado["project"]["markers"][0]["time"] == pytest.approx(1.5)

    renomeado = _operacao(client, pid, "settings", name="Montagem final", fps=25)
    assert renomeado["project"]["name"] == "Montagem final"
    assert renomeado["project"]["settings"]["fps"] == 25.0

    excluido = _operacao(client, pid, "delete", clip_id=alvo["id"])
    assert alvo["id"] not in [c["id"] for c in _clipes(excluido, "v1")]
    assert excluido["history"]["undo"][0] == "delete"
    _conferir_payload(excluido)


def _procurar(clipes: list[dict], clip_id: str) -> dict:
    return next(c for c in clipes if c["id"] == clip_id)


@requires_media
def test_colisao_na_api_devolve_400_e_grava_nada(client: TestClient):
    pid = _criar(client, "Colisão")["project"]["id"]
    _operacao(client, pid, "add_clip", track_id="v1", source=str(MEDIA / "clipe_a.mp4"), start=0)
    resposta = client.post(
        f"/api/editor/projects/{pid}/operations",
        json={"operation": "add_clip",
              "params": {"track_id": "v1", "source": str(MEDIA / "clipe_b.mp4"), "start": 1}},
    )
    assert resposta.status_code == 400
    assert "colidiria" in resposta.json()["detail"]
    # a tentativa falha não mexeu na timeline nem no histórico de undo
    atual = client.get(f"/api/editor/projects/{pid}").json()
    assert len(_clipes(atual, "v1")) == 1
    assert atual["history"]["undo"] == ["add_clip"]


def test_operacao_desconhecida_e_parametros_ruins_devolvem_400(client: TestClient):
    pid = _criar(client, "Erros de operação")["project"]["id"]

    resposta = client.post(f"/api/editor/projects/{pid}/operations", json={"operation": "explode"})
    assert resposta.status_code == 400
    assert "Operação desconhecida" in resposta.json()["detail"]

    resposta = client.post(f"/api/editor/projects/{pid}/operations",
                           json={"operation": "add_text", "params": ["v1"]})
    assert resposta.status_code == 400
    assert "params precisa ser um objeto" in resposta.json()["detail"]

    resposta = client.post(f"/api/editor/projects/{pid}/operations", json={"operation": ""})
    assert resposta.status_code == 400

    resposta = client.post(f"/api/editor/projects/{pid}/operations",
                           json={"operation": "add_text", "params": {"texto_errado": 1}})
    assert resposta.status_code == 400
    assert "Parâmetros inválidos" in resposta.json()["detail"]

    resposta = client.post(f"/api/editor/projects/{pid}/operations",
                           json={"operation": "add_text", "params": {"track_id": "t1", "text": "Ok"}})
    assert resposta.status_code == 200

    resposta = client.post("/api/editor/projects/p_0000000000/operations",
                           json={"operation": "add_text", "params": {"track_id": "t1", "text": "Ok"}})
    assert resposta.status_code == 404


@pytest.mark.parametrize("operacao", ["add_clip", "split", "delete"])
def test_operacao_sem_parametros_obrigatorios_e_erro_de_cliente(
    client: TestClient, operacao: str
):
    pid = _criar(client, "Sem params")["project"]["id"]
    resposta = client.post(f"/api/editor/projects/{pid}/operations", json={"operation": operacao})
    assert resposta.status_code == 400
    assert "Parâmetros inválidos" in resposta.json()["detail"]


def test_propriedade_inexistente_no_set_e_rejeitada(client: TestClient):
    pid = _criar(client, "Set inválido")["project"]["id"]
    titulo = _operacao(client, pid, "add_text", track_id="t1", text="Créditos", duration=2)
    clipe_id = _clipes(titulo, "t1")[0]["id"]
    resposta = client.post(f"/api/editor/projects/{pid}/operations",
                           json={"operation": "set", "params": {"clip_id": clipe_id, "cor_troxa": 1}})
    assert resposta.status_code == 400
    assert "não suportada" in resposta.json()["detail"]


def test_operacao_sem_efeito_nao_consome_undo_nem_versao(client: TestClient):
    """
    "settings" sem campo não muda o projeto: nem passo de undo, nem snapshot.
    Encher a pilha de no-ops faria o usuário apertar Ctrl+Z várias vezes sem
    ver diferença e empurraria edições reais para fora do histórico.
    """
    pid = _criar(client, "No-op")["project"]["id"]
    antes = client.get(f"/api/editor/projects/{pid}").json()
    versoes_antes = client.get(f"/api/editor/projects/{pid}/versions").json()["versions"]

    payload = _operacao(client, pid, "settings")
    assert payload["project"]["settings"]["width"] == 1280
    assert payload["history"]["undo"] == []
    assert payload["project"]["updated_at"] == antes["project"]["updated_at"]
    assert payload["project"]["recent_operations"] == antes["project"]["recent_operations"]
    assert client.get(f"/api/editor/projects/{pid}/versions").json()["versions"] == versoes_antes

    # e o undo continua funcionando depois do no-op
    _operacao(client, pid, "add_text", track_id="t1", text="Depois", duration=2)
    desfazer = client.post(f"/api/editor/projects/{pid}/undo")
    assert desfazer.status_code == 200
    assert _clipes(desfazer.json(), "t1") == []


def test_repetir_a_mesma_configuracao_e_no_op(client: TestClient):
    pid = _criar(client, "Repetido")["project"]["id"]
    real = _operacao(client, pid, "settings", width=1920)
    assert real["history"]["undo"] == ["settings"]
    versoes = client.get(f"/api/editor/projects/{pid}/versions").json()["versions"]

    payload = _operacao(client, pid, "settings", width=1920)
    assert payload["history"]["undo"] == ["settings"]
    assert payload["project"]["settings"]["width"] == 1920
    assert client.get(f"/api/editor/projects/{pid}/versions").json()["versions"] == versoes


# ---------------------------------------------------------------- undo/redo


def test_undo_redo_pela_api_desfaz_e_refaz_a_edicao(client: TestClient, eventos: list[dict]):
    pid = _criar(client, "Desfazer")["project"]["id"]
    adicionado = _operacao(client, pid, "add_text", track_id="t1", text="Olá", duration=2)
    clipe_id = _clipes(adicionado, "t1")[0]["id"]
    eventos.clear()

    desfazer = client.post(f"/api/editor/projects/{pid}/undo")
    assert desfazer.status_code == 200
    payload = desfazer.json()
    _conferir_payload(payload)
    assert _clipes(payload, "t1") == []
    assert payload["history"]["undo"] == []
    assert payload["history"]["redo"] == ["add_text"]

    refazer = client.post(f"/api/editor/projects/{pid}/redo")
    assert refazer.status_code == 200
    payload = refazer.json()
    assert [c["id"] for c in _clipes(payload, "t1")] == [clipe_id]
    assert payload["history"]["undo"] == ["add_text"]
    assert payload["history"]["redo"] == []

    assert eventos == [
        {"type": "editor_project_changed", "project_id": pid, "operation": "undo"},
        {"type": "editor_project_changed", "project_id": pid, "operation": "redo"},
    ]
    # um GET simples enxerga o mesmo estado refeito
    gravado = client.get(f"/api/editor/projects/{pid}").json()
    assert [c["id"] for c in _clipes(gravado, "t1")] == [clipe_id]


def test_undo_e_redo_com_pilha_vazia_sao_erro_de_cliente(client: TestClient):
    pid = _criar(client, "Sem histórico")["project"]["id"]
    resposta = client.post(f"/api/editor/projects/{pid}/undo")
    assert resposta.status_code == 400
    assert "desfazer" in resposta.json()["detail"]

    resposta = client.post(f"/api/editor/projects/{pid}/redo")
    assert resposta.status_code == 400
    assert "refazer" in resposta.json()["detail"]

    assert client.post("/api/editor/projects/p_0000000000/undo").status_code == 404
    assert client.post("/api/editor/projects/p_0000000000/redo").status_code == 404


# ----------------------------------------------------------------- versões


def test_versoes_e_restaurar_a_penultima_reverte_a_timeline(client: TestClient):
    pid = _criar(client, "Versões")["project"]["id"]
    _operacao(client, pid, "add_text", track_id="t1", text="Um", start=0, duration=2)
    depois_da_primeira = client.get(f"/api/editor/projects/{pid}/versions").json()["versions"]
    assert depois_da_primeira, "cada alteração salva um snapshot"
    nome_primeira = depois_da_primeira[0]["name"]

    _operacao(client, pid, "add_text", track_id="t1", text="Dois", start=6, duration=2)

    resposta = client.get(f"/api/editor/projects/{pid}/versions")
    assert resposta.status_code == 200
    versoes = resposta.json()["versions"]
    assert len(versoes) >= 2
    assert {"name", "label", "size", "modified"} <= set(versoes[0])
    assert all(v["name"].endswith(".json") and v["size"] > 0 for v in versoes)
    assert all(isinstance(v["label"], str) and v["label"] for v in versoes)
    # a mais nova primeiro, como a interface lista
    assert [v["modified"] for v in versoes] == sorted([v["modified"] for v in versoes], reverse=True)
    assert versoes[0]["name"] != nome_primeira

    antiga = versoes[1]["name"]  # newest-but-one: estado depois da primeira edição
    restaurar = client.post(f"/api/editor/projects/{pid}/versions/{antiga}/restore")
    assert restaurar.status_code == 200
    payload = restaurar.json()
    _conferir_payload(payload)
    assert [c["text"]["content"] for c in _clipes(payload, "t1")] == ["Um"]
    atual = client.get(f"/api/editor/projects/{pid}").json()
    assert [c["text"]["content"] for c in _clipes(atual, "t1")] == ["Um"]
    # restaurar também é desfazível
    desfazer = client.post(f"/api/editor/projects/{pid}/undo")
    assert desfazer.status_code == 200
    assert len(_clipes(desfazer.json(), "t1")) == 2


@pytest.mark.parametrize("nome", ["../project.json", "..%2fproject.json", "sub/past.json"])
def test_restaurar_nome_maligno_e_recusado(client: TestClient, nome: str):
    """
    O roteador separa/aparthe o caminho antes do handler: o traversing morre em
    404; um nome só inválido chega ao motor e devolve 400. Nos dois casos a
    recusa é de cliente (4xx) e o projeto fica intacto.
    """
    pid = _criar(client, "Refém")["project"]["id"]
    _operacao(client, pid, "add_text", track_id="t1", text="Intocado", duration=2)
    antes = client.get(f"/api/editor/projects/{pid}").json()

    resposta = client.post(f"/api/editor/projects/{pid}/versions/{quote(nome, safe='')}/restore")
    assert resposta.status_code in (400, 404)

    depois = client.get(f"/api/editor/projects/{pid}").json()
    assert depois["project"] == antes["project"]


def test_restaurar_versao_inexistente_devolve_404(client: TestClient):
    pid = _criar(client, "Sem a versão")["project"]["id"]
    resposta = client.post(f"/api/editor/projects/{pid}/versions/9999-inexistente.json/restore")
    assert resposta.status_code == 404
    assert "Versão não encontrada" in resposta.json()["detail"]
    assert client.get(f"/api/editor/projects/{pid}").status_code == 200


def test_versoes_de_projeto_inexistente_devolvem_404(client: TestClient):
    assert client.get("/api/editor/projects/p_0000000000/versions").status_code == 404


# -------------------------------------------------------------- validação


def test_validar_projeto_vazio_aponta_erros(client: TestClient):
    pid = _criar(client, "Vazio")["project"]["id"]
    resposta = client.get(f"/api/editor/projects/{pid}/validate")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert {"issues", "ok"} <= set(corpo)
    assert corpo["ok"] is False
    codigos = {item["code"] for item in corpo["issues"]}
    assert {"empty_project", "zero_duration"} <= codigos
    for item in corpo["issues"]:
        assert {"severity", "code", "message"} <= set(item)
        assert item["message"]
    assert any(item["severity"] == "error" for item in corpo["issues"])


def test_validar_projeto_bem_formado_nao_tem_erros(client: TestClient):
    pid = _criar(client, "Sadio")["project"]["id"]
    _operacao(client, pid, "add_text", track_id="t1", text="Título são", duration=2)
    corpo = client.get(f"/api/editor/projects/{pid}/validate").json()
    assert corpo["ok"] is True
    assert [item for item in corpo["issues"] if item["severity"] == "error"] == []
    assert {item["severity"] for item in corpo["issues"]} <= {"warning", "info", "error"}


def test_validar_projeto_inexistente_e_recurso_ausente(client: TestClient):
    assert client.get("/api/editor/projects/p_0000000000/validate").status_code == 404


# ------------------------------------------------------------------- mídia


@requires_media
def test_midia_do_projeto_e_servida_em_bytes(client: TestClient):
    pid = _criar(client, "Mídia OK")["project"]["id"]
    payload = _operacao(client, pid, "add_clip", track_id="v1", source=str(MEDIA / "clipe_a.mp4"))
    fonte = _clipes(payload, "v1")[0]["source"]

    resposta = client.get("/api/editor/media", params={"path": fonte})
    assert resposta.status_code == 200
    assert resposta.headers["content-type"] == "video/mp4"
    assert len(resposta.content) == Path(fonte).stat().st_size
    assert resposta.content[:64] == Path(fonte).read_bytes()[:64]

    if (Path.cwd() / "test_videos" / "clipe_a.mp4").is_file():
        # caminho relativo resolve na mesma raiz já liberada pelo projeto
        relativo = client.get("/api/editor/media", params={"path": "test_videos/clipe_a.mp4"})
        assert relativo.status_code == 200
        assert len(relativo.content) == len(resposta.content)


@pytest.mark.parametrize(
    "caminho",
    [
        "C:/Windows/win.ini",
        "../../windows/win.ini",
        "E:/editor-video/server.py",
        str(MEDIA / "legenda.srt"),
    ],
)
def test_midia_fora_das_raizes_e_recusada_sem_vazar_o_arquivo(client: TestClient, caminho: str):
    resposta = client.get("/api/editor/media", params={"path": caminho})
    assert resposta.status_code == 404
    assert resposta.json()["detail"] == "Mídia não encontrada neste projeto"
    assert len(resposta.content) < 200
    for vazamento in (b"for 16-bit app", b"@router", b"WEBVTT", b"1 00:00:00"):
        assert vazamento not in resposta.content


def test_arquivo_de_midia_inexistente_devolve_4xx(client: TestClient):
    resposta = client.get("/api/editor/media", params={"path": str(MEDIA / "nao-existe.mp4")})
    assert resposta.status_code == 404
    assert "Traceback" not in resposta.text

    resposta = client.get("/api/editor/media", params={"path": str(MEDIA)})  # é diretório
    assert resposta.status_code == 404

    resposta = client.get("/api/editor/media")  # falta o query param obrigatório
    assert resposta.status_code == 422


def test_listar_uploads_devolve_so_media(client: TestClient):
    resposta = client.get("/api/editor/uploads")
    assert resposta.status_code == 200
    itens = resposta.json()["uploads"]
    assert isinstance(itens, list)
    assert len(itens) <= 80
    for item in itens:
        assert {"name", "path", "kind", "size", "modified"} <= set(item)
        assert item["kind"] in {"video", "audio", "image"}
        assert item["size"] > 0
        assert Path(item["path"]).is_file()
    modificados = [item["modified"] for item in itens]
    assert modificados == sorted(modificados, reverse=True)


# ------------------------------------------------------------------ skills


def test_listar_skills_devolve_o_catalogo(client: TestClient):
    resposta = client.get("/api/editor/skills")
    assert resposta.status_code == 200
    skills = resposta.json()["skills"]
    assert skills, "o repositório traz skills de exemplo"
    for item in skills:
        assert {"name", "title", "description", "triggers", "tools", "complete",
                "missing_sections", "path"} <= set(item)
        assert isinstance(item["triggers"], list)
        assert isinstance(item["complete"], bool)


def test_carregar_skill_devolve_o_conteudo_completo(client: TestClient):
    nomes = [item["name"] for item in client.get("/api/editor/skills").json()["skills"]]
    nome = nomes[0]
    resposta = client.get(f"/api/editor/skills/{nome}")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert {"name", "title", "content", "sections", "complete", "missing_sections"} <= set(corpo)
    assert corpo["name"] == nome
    assert corpo["content"] and "##" in corpo["content"]
    assert 0 <= corpo["sections"] <= 10


@pytest.mark.parametrize("nome", ["Nao-Existe", "nao-existe", "a", "../etc"])
def test_skill_invalida_e_erro_de_cliente(client: TestClient, nome: str):
    resposta = client.get(f"/api/editor/skills/{quote(nome, safe='')}")
    assert resposta.status_code in (400, 404)
    if resposta.status_code == 400:
        assert "skill" in resposta.json()["detail"].lower()
    assert "Traceback" not in resposta.text


# ------------------------------------------------------------------- jobs


def test_jobs_e_previews_de_projeto_novo_sao_listas_vazias(client: TestClient):
    pid = _criar(client, "Sem tarefas")["project"]["id"]
    resposta = client.get(f"/api/editor/projects/{pid}/jobs")
    assert resposta.status_code == 200
    assert resposta.json() == {"jobs": []}
    assert client.get(f"/api/editor/projects/{pid}/preview").json() == {"job": None}


def test_tarefa_desconhecida_e_recusada(client: TestClient):
    """RenderError vira 409 em _handle, inclusive para id inexistente."""
    resposta = client.get("/api/editor/jobs/nao-existe")
    assert resposta.status_code == 409
    assert "Tarefa não encontrada" in resposta.json()["detail"]
    assert client.delete("/api/editor/jobs/nao-existe").status_code == 409
    assert client.post("/api/editor/jobs/nao-existe/validate").status_code == 409


def test_listar_tarefas_valida_o_id_do_projeto(client: TestClient):
    """A rota de filas segue as rotas irmãs: id desconhecido é recurso ausente."""
    resposta = client.get("/api/editor/projects/p_0000000000/jobs")
    assert resposta.status_code == 404
    assert client.get("/api/editor/projects/p_0000000000/preview").status_code == 404


def test_render_com_timeline_invalida_devolve_409(client: TestClient):
    pid = _criar(client, "Vazio para render")["project"]["id"]
    resposta = client.post(f"/api/editor/projects/{pid}/render", json={"preview": True})
    assert resposta.status_code == 409
    assert resposta.json()["detail"]


@requires_media
def test_render_de_previa_gera_arquivo_validavel(client: TestClient, render_dir: Path):
    """Único render real da suíte: clipe de 4 s em prévia barata (144p, ultrafast)."""
    pid = _criar(client, "Render HTTP", width=640, height=360, fps=30)["project"]["id"]
    _operacao(client, pid, "add_clip", track_id="v1", source=str(MEDIA / "clipe_a.mp4"))
    assert client.get(f"/api/editor/projects/{pid}/validate").json()["ok"] is True

    resposta = client.post(
        f"/api/editor/projects/{pid}/render",
        json={"preview": True, "format": "mp4", "crf": 32, "preset": "ultrafast",
              "max_height": 144, "filename": "teste_api_previa"},
    )
    assert resposta.status_code == 200, resposta.text
    job = resposta.json()["job"]
    assert {"id", "project_id", "kind", "status", "progress", "message", "output_path",
            "output_name", "error", "qc", "created_at", "started_at", "finished_at",
            "options"} <= set(job)
    assert job["kind"] == "preview"
    assert job["status"] in {"queued", "running", "done"}
    assert Path(job["output_path"]).parent.resolve() == render_dir.resolve()

    limite = time.monotonic() + 120
    while time.monotonic() < limite:
        atual = client.get(f"/api/editor/jobs/{job['id']}")
        assert atual.status_code == 200
        job = atual.json()["job"]
        if job["status"] in {"done", "error", "cancelled"}:
            break
        time.sleep(0.5)
    assert job["status"] == "done", job["error"] or job["message"]
    assert job["progress"] == 100
    assert Path(job["output_path"]).is_file()
    assert Path(job["output_path"]).stat().st_size > 0
    assert job["qc"]["ok"] is True
    assert job["qc"]["measurements"]["duration"] == pytest.approx(4.0, abs=0.3)

    tarefas = client.get(f"/api/editor/projects/{pid}/jobs").json()["jobs"]
    assert [item["id"] for item in tarefas] == [job["id"]]

    previa = client.get(f"/api/editor/projects/{pid}/preview").json()
    assert previa["job"]["id"] == job["id"]
    assert previa["url"] == f"/preview/{job['output_name']}"
    assert previa["download_url"] == f"/download/{job['output_name']}"

    conferido = client.post(f"/api/editor/jobs/{job['id']}/validate")
    assert conferido.status_code == 200
    assert {"ok", "issues", "measurements", "probe"} <= set(conferido.json()["qc"])


# -------------------------------------------------------- corpos malformados


@pytest.mark.parametrize(
    "rota,corpo",
    [
        ("/api/editor/projects", "{isso não é json"),
        ("/api/editor/projects", "[]"),
        ("/api/editor/projects", '"só uma string"'),
        ("/api/editor/projects", "null"),
        ("/api/editor/projects/p_0000000000/operations", "42"),
        ("/api/editor/projects/p_0000000000/operations", "null"),
        ("/api/editor/projects/p_0000000000/render", "<html>"),
        ("/api/editor/projects/p_0000000000/chat", "[1, 2]"),
    ],
)
def test_corpo_invalido_e_erro_de_cliente(client: TestClient, rota: str, corpo: str):
    resposta = client.post(rota, content=corpo, headers={"Content-Type": "application/json"})
    assert resposta.status_code == 400
    assert "JSON" in resposta.json()["detail"]


@pytest.mark.parametrize(
    "corpo",
    [
        {},                        # corpo ausente: o nome continua obrigatório
        {"nome": "português"},     # chave fora do contrato do modelo de projeto
        {"name": "Ok", "extra": 1},
        {"name": "Ok", "width": "1920x1080"},
    ],
)
def test_corpo_valido_fora_do_contrato_e_recusado(client: TestClient, corpo: dict):
    resposta = client.post("/api/editor/projects", json=corpo)
    assert resposta.status_code == 400


@pytest.mark.parametrize(
    "rota,corpo",
    [
        ("/api/editor/projects", "{isso não é json"),
        ("/api/editor/projects", "[]"),
        ("/api/editor/projects/p_0000000000/operations", "null"),
        ("/api/editor/projects/p_0000000000/render", "<html>"),
    ],
)
def test_corpo_invalido_nao_vaza_detalhes_internos(client: TestClient, rota: str, corpo: str):
    """O erro diz o que falta, não como o servidor é feito."""
    resposta = client.post(rota, content=corpo, headers={"Content-Type": "application/json"})
    assert resposta.status_code == 400
    assert "Traceback" not in resposta.text
    assert "editor_api" not in resposta.text
    assert "AttributeError" not in resposta.text
    assert "JSONDecodeError" not in resposta.text
