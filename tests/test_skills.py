"""
Testes do catálogo de skills (editor_skills).

Cobrem a consistência entre o que está em ./skills e o que o agente enxerga:
inventário do catálogo, as dez seções numeradas e sua ordem, frontmatter,
honestidade sobre as ferramentas realmente chamáveis do agente, carregamento
com proteção de path, truncamento, catálogo para o prompt de sistema e a
sugestão por palavra-chave.

Os testes que dependem do conteúdo real usam ``SKILLS`` (caminho absoluto do
repositório) em vez do ``Path("./skills")`` relativo ao cwd. Os casos de
carga/defeito constroem árvores sintéticas em ``tmp_path`` e nunca escrevem
dentro de ./skills.
"""

import re
from pathlib import Path

import pytest

import editor_skills
import timeline_agent
from editor_project import ProjectError

RAIZ = Path(__file__).resolve().parents[1]
SKILLS = RAIZ / "skills"

# As dez seções obrigatórias, exatamente como _REQUIRED do carregador.
SECOES = [f"## {i}." for i in range(1, 11)]
SECOES_INDICES = list(range(1, 11))

# Limite de descrição: catalog_text() corta em 140 por padrão, então uma
# descrição mais longa seria mutilada no prompt de sistema. 20 caracteres é o
# mínimo para descrever um fluxo em vez de jogar uma palavra solta.
DESCRICAO_MINIMA = 20
DESCRICAO_MAXIMA = 140

MARCA_TRUNCAMENTO = "[skill truncada por limite de contexto]"

# TODO/TBD valem apenas na forma em maiúsculas e como token isolado: em
# português "todo/toda/todos" é palavra comum ("em todo corte") e uma busca
# case-insensitive marcaria prosa legítima como se fosse placeholder.
PLACEHOLDER_TOKEN = re.compile(r"\b(?:TODO|TBD)\b")
PLACEHOLDER_TEXTO = re.compile(r"lorem\s+ipsum|completar aqui", re.IGNORECASE)

CAMPOS_OBRIGATORIOS = {
    "name", "title", "description", "triggers", "tools",
    "complete", "missing_sections", "path",
}


def _nomes_das_skills() -> list[str]:
    """Pastas de ./skills que têm um SKILL.md, na ordem do catálogo."""
    return sorted(
        pasta.name for pasta in SKILLS.iterdir()
        if pasta.is_dir() and (pasta / "SKILL.md").is_file()
    )


SKILLS_INSTALADAS = _nomes_das_skills()


def _ferramentas_do_agente() -> dict[str, str]:
    """
    Deriva os nomes chamáveis de timeline_agent.TOOLS.

    As entradas podem ser funções nuas ou invólucros do decorador do LM Studio;
    procura __name__ (depois __wrapped__) e cai em .name antes de desistir.
    """
    nomes: dict[str, str] = {}
    for entrada in timeline_agent.TOOLS:
        alvo = getattr(entrada, "__wrapped__", entrada)
        nome = (
            getattr(alvo, "__name__", None)
            or getattr(alvo, "name", None)
            or getattr(entrada, "name", None)
        )
        assert nome, f"entrada de TOOLS sem nome chamável: {entrada!r}"
        nomes[str(nome)] = str(nome)
    assert len(nomes) == len(timeline_agent.TOOLS), "TOOLS tem entradas duplicadas"
    return nomes


@pytest.fixture(autouse=True)
def skills_do_repositorio(monkeypatch):
    """Garante que o catálogo lido é o do repositório, independentemente do cwd."""
    monkeypatch.setattr(editor_skills, "SKILLS_DIR", SKILLS)
    return SKILLS


def _escreve_skill(tmp_path: Path, nome: str, texto: str) -> Path:
    pasta = tmp_path / nome
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / "SKILL.md"
    arquivo.write_text(texto, encoding="utf-8")
    return arquivo


def _corpo(nome: str) -> str:
    """Só o corpo (sem frontmatter), como o carregador o vê."""
    texto = (SKILLS / nome / "SKILL.md").read_text(encoding="utf-8")
    return editor_skills._split_frontmatter(texto)[1]


def _item(nome: str) -> dict:
    for item in editor_skills.list_skills():
        if item["name"] == nome:
            return item
    raise AssertionError(f"skill {nome!r} não aparece em list_skills()")


# ------------------------------------------------------------------ catálogo


def test_catalogo_tem_ao_menos_vinte_e_uma_skill():
    itens = editor_skills.list_skills()
    assert len(itens) >= 21, f"esperava >= 21 skills, obtive {len(itens)}"


def test_cada_pasta_de_skill_aparece_exatamente_uma_vez_no_catalogo():
    no_disco = sorted(p.name for p in SKILLS.iterdir() if p.is_dir())
    itens = editor_skills.list_skills()
    catalogadas = [item["name"] for item in itens]
    duplicadas = sorted({n for n in catalogadas if catalogadas.count(n) > 1})
    assert not duplicadas, f"skills duplicadas no catálogo: {duplicadas}"
    faltando = sorted(set(no_disco) - set(catalogadas))
    sobrando = sorted(set(catalogadas) - set(no_disco))
    assert not faltando, f"pastas com SKILL.md ausentes do catálogo: {faltando}"
    assert not sobrando, f"skills no catálogo sem pasta correspondente: {sobrando}"
    assert len(itens) == len(no_disco) == len(SKILLS_INSTALADAS)


@pytest.mark.parametrize("nome", SKILLS_INSTALADAS)
def test_entrada_do_catalogo_tem_todos_os_campos(nome):
    item = _item(nome)
    assert CAMPOS_OBRIGATORIOS <= set(item), (
        f"{nome}: campos ausentes {sorted(CAMPOS_OBRIGATORIOS - set(item))}"
    )
    arquivo = Path(item["path"])
    assert arquivo.is_file() and arquivo.name == "SKILL.md"
    assert arquivo.parent.name == nome, f"{nome}: path aponta para outra pasta"


# -------------------------------------------------------- as dez seções


@pytest.mark.parametrize("nome", SKILLS_INSTALADAS)
def test_skill_completa_sem_secoes_faltando(nome):
    item = _item(nome)
    assert item["complete"] is True, (
        f"{nome}: skill incompleta, faltam as seções {item['missing_sections']}"
    )
    assert item["missing_sections"] == []


@pytest.mark.parametrize("nome", SKILLS_INSTALADAS)
def test_dez_secoes_numeradas_em_ordem_crescente(nome):
    corpo = _corpo(nome)
    numeradas = [(int(m.group(1)), m.start()) for m in re.finditer(r"^##\s+(\d+)\.", corpo, re.M)]
    achadas = [n for n, _ in numeradas]
    assert achadas == SECOES_INDICES, (
        f"{nome}: as seções devem aparecer uma vez cada, em ordem 1..10; "
        f"encontrei {achadas}"
    )
    posicoes = [p for _, p in numeradas]
    assert posicoes == sorted(posicoes), f"{nome}: a ordem das seções não é crescente"
    assert len(set(posicoes)) == len(posicoes)


@pytest.mark.parametrize("nome", SKILLS_INSTALADAS)
def test_toda_secao_obrigatoria_presente_no_corpo(nome):
    corpo = _corpo(nome)
    faltando = [secao for secao in SECOES if secao not in corpo]
    assert not faltando, f"{nome}: corpo sem as seções {faltando}"


# ------------------------------------------------------------- frontmatter


@pytest.mark.parametrize("nome", SKILLS_INSTALADAS)
def test_name_do_frontmatter_bate_com_a_pasta_e_e_kebab_case(nome):
    item = _item(nome)
    assert item["name"] == nome, f"{nome}: frontmatter diz {item['name']!r}"
    assert editor_skills._NAME_RE.match(item["name"]), (
        f"{nome}: name {item['name']!r} não satisfaz _NAME_RE "
        "(minúsculas, dígitos e hífen, 2 a 61 caracteres)"
    )


@pytest.mark.parametrize("nome", SKILLS_INSTALADAS)
def test_description_existe_e_cabe_no_catalogo(nome):
    descricao = _item(nome)["description"]
    assert descricao.strip(), f"{nome}: description vazia"
    assert len(descricao) >= DESCRICAO_MINIMA, (
        f"{nome}: description com {len(descricao)} caracteres é vaga demais "
        f"(mínimo {DESCRICAO_MINIMA})"
    )
    assert len(descricao) <= DESCRICAO_MAXIMA, (
        f"{nome}: description com {len(descricao)} caracteres estoura o catálogo "
        f"(máximo {DESCRICAO_MAXIMA}, que é o corte padrão de catalog_text)"
    )


@pytest.mark.parametrize("nome", SKILLS_INSTALADAS)
def test_title_nao_e_vazio(nome):
    assert _item(nome)["title"].strip(), f"{nome}: title vazio"


@pytest.mark.parametrize("nome", SKILLS_INSTALADAS)
def test_triggers_sao_lista_nao_vazia_de_itens_usaveis(nome):
    triggers = _item(nome)["triggers"]
    assert isinstance(triggers, list) and triggers, f"{nome}: triggers vazio"
    ruins = [t for t in triggers if len(t) < 2 or t != t.strip()]
    assert not ruins, f"{nome}: gatilhos malformados {ruins}"


@pytest.mark.parametrize("nome", SKILLS_INSTALADAS)
def test_tools_sao_lista_nao_vazia_de_itens_usaveis(nome):
    tools = _item(nome)["tools"]
    assert isinstance(tools, list) and tools, f"{nome}: tools vazio"
    ruins = [t for t in tools if not t.strip() or t != t.strip()]
    assert not ruins, f"{nome}: ferramentas malformadas {ruins}"


# ------------------------------------------------- honestidade de capacidade


@pytest.mark.parametrize("nome", SKILLS_INSTALADAS)
def test_ferramentas_declara_existe_no_agente(nome):
    """Uma skill que anuncia ferramenta inexistente ensina o modelo a errar."""
    ferramentas = _ferramentas_do_agente()
    declaradas = _item(nome)["tools"]
    desconhecidas = sorted(t for t in declaradas if t not in ferramentas)
    assert not desconhecidas, (
        f"{nome}: declara {len(desconhecidas)} ferramenta(s) que o agente não pode "
        f"chamar: {desconhecidas}. Ferramentas reais: {sorted(ferramentas)}"
    )


def test_ferramentas_do_agente_vem_de_tools_e_nao_de_lista_fixa():
    """Os nomes vêm de timeline_agent.TOOLS; conferir o tamanho atual só avisa drift."""
    ferramentas = _ferramentas_do_agente()
    assert len(ferramentas) == len(timeline_agent.TOOLS)
    assert len(ferramentas) >= 19, (
        f"esperava ao menos 19 ferramentas chamáveis, obtive {len(ferramentas)}"
    )


# ------------------------------------------------- conteúdo legível pelo agente


@pytest.mark.parametrize("nome", SKILLS_INSTALADAS)
def test_arquivo_e_utf8_valido(nome):
    arquivo = SKILLS / nome / "SKILL.md"
    try:
        arquivo.read_bytes().decode("utf-8")
    except UnicodeDecodeError as e:  # pragma: no cover - defeito de dados
        pytest.fail(f"{nome}: SKILL.md não é UTF-8 válido ({e})")


@pytest.mark.parametrize("nome", SKILLS_INSTALADAS)
def test_sem_texto_de_placeholder(nome):
    corpo = _corpo(nome)
    tokens = sorted(set(PLACEHOLDER_TOKEN.findall(corpo)))
    frases = sorted({m.lower() for m in PLACEHOLDER_TEXTO.findall(corpo)})
    assert not tokens and not frases, (
        f"{nome}: contém placeholder {tokens + frases} no corpo da skill"
    )


@pytest.mark.parametrize("nome", SKILLS_INSTALADAS)
def test_nenhuma_secao_vazia(nome):
    corpo = _corpo(nome)
    marcacoes = list(re.finditer(r"^##\s+\d+\..*$", corpo, re.M))
    assert len(marcacoes) == 10
    vazias = []
    for i, m in enumerate(marcacoes):
        fim = marcacoes[i + 1].start() if i + 1 < len(marcacoes) else len(corpo)
        bloco = corpo[m.end():fim]
        conteudo = [
            linha for linha in bloco.splitlines()
            if linha.strip() and not linha.lstrip().startswith("#")
        ]
        if not conteudo:
            vazias.append(m.group(0).strip())
    assert not vazias, f"{nome}: seções sem corpo logo após o título: {vazias}"


@pytest.mark.parametrize("nome", SKILLS_INSTALADAS)
def test_skill_cabe_inteira_no_contexto(nome):
    """Nenhuma skill real deveria ser cortada; se for, o agente perde o procedimento."""
    texto = (SKILLS / nome / "SKILL.md").read_text(encoding="utf-8")
    assert len(texto) <= editor_skills.MAX_SKILL_CHARS, (
        f"{nome}: {len(texto)} caracteres > MAX_SKILL_CHARS "
        f"({editor_skills.MAX_SKILL_CHARS}); o conteúdo seria cortado"
    )


# --------------------------------------------------------------- load_skill


@pytest.mark.parametrize("nome", ["video-editor-core", "short-form-vertical"])
def test_load_skill_de_skill_real(nome):
    skill = editor_skills.load_skill(nome)
    assert set(skill) == {
        "name", "title", "content", "sections", "complete", "missing_sections", "truncated",
    }
    assert skill["name"] == nome
    assert skill["sections"] == 10, f"{nome}: sections={skill['sections']}"
    assert skill["complete"] is True and skill["missing_sections"] == []
    assert skill["truncated"] is False, f"{nome}: a skill não cabe no orçamento de contexto"
    assert len(skill["content"]) <= editor_skills.MAX_SKILL_CHARS
    assert "## 10." in skill["content"], f"{nome}: conteúdo sem a última seção"


@pytest.mark.parametrize(
    "nome",
    [
        "skill-que-nao-existe", "Nao-Existe", "", " ", "../skills", "..",
        "a/b", "skills/x", "/etc/passwd", "x" * 80, "Skill-Com-Maiuscula",
        "com espaço", "ponto.", ".escondida",
    ],
)
def test_load_skill_rejeita_nome_invalido_sem_tocar_no_disco(nome, skills_do_repositorio):
    antes = sorted(p.name for p in skills_do_repositorio.iterdir())
    with pytest.raises(ProjectError):
        editor_skills.load_skill(nome)
    # nada foi criado ou movido: ./skills continua exatamente como estava
    assert sorted(p.name for p in skills_do_repositorio.iterdir()) == antes


def test_nome_de_skill_nao_escapa_de_skills_dir(skills_do_repositorio):
    """Nenhum nome com "/" ou ".." passa pelo filtro, e nada resolve fora de ./skills."""
    raiz = skills_do_repositorio.resolve()
    candidatos = [
        "..", "../skills", "../skills/video-editor-core", "a/../../etc",
        "..\\..\\skills", "skills/../x", "/etc/passwd", "", "/", "x" * 200,
        "a b", "SKILL.md", "-x", "./skills",
    ]
    for nome in candidatos:
        with pytest.raises(ProjectError):
            editor_skills.load_skill(nome)
    assert [c for c in candidatos if editor_skills._NAME_RE.match(c)] == [], (
        "algum nome perigoso passou no _NAME_RE e seria aberto no disco"
    )
    # e todo nome que o filtro aceita resolve dentro de ./skills
    for nome in SKILLS_INSTALADAS:
        destino = (raiz / nome / "SKILL.md").resolve()
        assert raiz in destino.parents, f"{nome}: resolvida fora de {raiz}"


def test_load_skill_de_skill_inexistente_mas_valida_projeta_project_error(skills_do_repositorio):
    with pytest.raises(ProjectError, match="não encontrada"):
        editor_skills.load_skill("skill-bem-formatada-mesmo")


# ----------------------------------------------------- carga em árvore sintética


def _arvore(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(editor_skills, "SKILLS_DIR", tmp_path)
    return tmp_path


def test_load_skill_trunca_corpo_acima_do_limite(tmp_path, monkeypatch):
    arvore = _arvore(tmp_path, monkeypatch)
    cabecalhos = "\n".join(f"## {i}. Seção {i}\nConteúdo da seção {i}." for i in range(1, 11))
    recheio = "p" * (editor_skills._LIMITE + 500)
    _escreve_skill(
        arvore, "skill-gigante",
        f"---\nname: skill-gigante\ntitle: Gigante\ndescription: Skill enorme.\n---\n\n{cabecalhos}\n{recheio}\n",
    )
    skill = editor_skills.load_skill("skill-gigante")
    assert skill["sections"] == 10 and skill["complete"] is True
    assert len(skill["content"]) <= editor_skills.MAX_SKILL_CHARS, (
        "o conteúdo devolvido não pode estourar o orçamento de contexto"
    )


def test_load_skill_marca_a_truncamento_no_conteudo(tmp_path, monkeypatch):
    arvore = _arvore(tmp_path, monkeypatch)
    cabecalhos = "\n".join(f"## {i}. Seção {i}\nConteúdo da seção {i}." for i in range(1, 11))
    recheio = "p" * (editor_skills.MAX_SKILL_CHARS + 2000)
    _escreve_skill(
        arvore, "skill-gigante",
        f"---\nname: skill-gigante\ntitle: Gigante\ndescription: Skill enorme.\n---\n\n{cabecalhos}\n{recheio}\n",
    )
    skill = editor_skills.load_skill("skill-gigante")
    assert skill["truncated"] is True, "o corte precisa aparecer no metadado"
    assert MARCA_TRUNCAMENTO in skill["content"], (
        "conteúdo cortado sem avisar o agente que faltou texto"
    )
    assert len(skill["content"]) <= editor_skills.MAX_SKILL_CHARS
    assert skill["content"].startswith("---"), "o frontmatter continua entregue"


def test_skill_incompleta_e_reportada_com_as_secoes_exatas(tmp_path, monkeypatch):
    arvore = _arvore(tmp_path, monkeypatch)
    _escreve_skill(
        arvore, "skill-pela-metade",
        "---\nname: skill-pela-metade\ntitle: Pela Metade\ndescription: Falta seção.\n"
        "triggers: teste\ntools: validate_timeline\n---\n\n"
        "## 1. Objetivo\nTexto.\n\n## 3. Procedimento\nTexto.\n",
    )
    item = editor_skills.list_skills()[0]
    assert item["complete"] is False
    assert item["missing_sections"] == [
        "## 2.", "## 4.", "## 5.", "## 6.", "## 7.", "## 8.", "## 9.", "## 10.",
    ]
    assert item["tools"] == ["validate_timeline"]
    skill = editor_skills.load_skill("skill-pela-metade")
    assert skill["complete"] is False and skill["sections"] == 2
    assert skill["missing_sections"] == item["missing_sections"]


def test_sem_frontmatter_o_nome_cai_na_pasta_e_o_title_e_derivado(tmp_path, monkeypatch):
    arvore = _arvore(tmp_path, monkeypatch)
    corpo = "\n".join(f"## {i}. Seção\nConteúdo {i}.\n" for i in range(1, 11))
    _escreve_skill(arvore, "minha-skill-semeta", corpo)
    itens = {i["name"]: i for i in editor_skills.list_skills()}
    assert set(itens) == {"minha-skill-semeta"}, "a skill sem frontmatter deveria entrar"
    item = itens["minha-skill-semeta"]
    assert item["title"] == "Minha Skill Semeta", item["title"]
    assert item["description"] == ""
    assert item["triggers"] == [] and item["tools"] == []
    assert item["complete"] is True
    assert editor_skills.load_skill("minha-skill-semeta")["name"] == "minha-skill-semeta"


def test_frontmatter_malformada_nao_engole_o_corpo(tmp_path, monkeypatch):
    arvore = _arvore(tmp_path, monkeypatch)
    # abre '---' e nunca fecha: o carregador trata o arquivo inteiro como corpo
    corpo = "---\nname: sem-fechamento\ntitle: Sem Fechamento\n" + "\n".join(
        f"## {i}. Seção\nConteúdo {i}.\n" for i in range(1, 11)
    )
    _escreve_skill(arvore, "sem-fechamento", corpo)
    item = editor_skills.list_skills()[0]
    assert item["name"] == "sem-fechamento"
    assert item["complete"] is True, item["missing_sections"]


def test_pasta_sem_skill_md_e_nome_fora_do_padrao_sao_ignoradas(tmp_path, monkeypatch):
    arvore = _arvore(tmp_path, monkeypatch)
    dez = "\n".join(f"## {i}. Seção\nConteúdo {i}.\n" for i in range(1, 11))
    (arvore / "sem-arquivo").mkdir()
    _escreve_skill(arvore, "Nome-Grande", f"---\nname: Nome-Grande\n---\n\n{dez}")
    assert editor_skills.list_skills() == [], (
        "pasta sem SKILL.md e skill com name fora do padrão não podem entrar no catálogo"
    )
    with pytest.raises(ProjectError, match="não encontrada"):
        editor_skills.load_skill("sem-arquivo")
    with pytest.raises(ProjectError, match="inválido"):
        editor_skills.load_skill("Nome-Grande")


def test_list_skills_sem_diretorio_devolve_lista_vazia(tmp_path, monkeypatch):
    monkeypatch.setattr(editor_skills, "SKILLS_DIR", tmp_path / "inexistente")
    assert editor_skills.list_skills() == []
    assert editor_skills.catalog_text() == ""
    assert editor_skills.choose_skills("corte o podcast") == []


# ---------------------------------------------------------------- catálogo


def test_catalog_text_devolve_uma_linha_por_skill(skills_do_repositorio):
    linhas = editor_skills.catalog_text().splitlines()
    itens = editor_skills.list_skills()
    assert len(linhas) == len(itens) >= 21
    assert all(linha.startswith("- ") for linha in linhas)
    esperadas = [f"- {item['name']}: {item['description']}" for item in itens]
    assert linhas == esperadas, "com o limite padrão nenhuma descrição deveria ser cortada"
    nomes = {item["name"] for item in itens}
    assert {linha.split(": ", 1)[0].removeprefix("- ") for linha in linhas} == nomes


def test_catalog_text_recorta_a_descricao_no_tamano_pedido(skills_do_repositorio):
    limite = 40
    linhas = editor_skills.catalog_text(limite).splitlines()
    itens = editor_skills.list_skills()
    assert len(linhas) == len(itens)
    for linha, item in zip(linhas, itens):
        descricao = item["description"]
        if len(descricao) > limite:
            cortada = descricao[: limite - 1] + "…"
            assert linha == f"- {item['name']}: {cortada}", (
                f"{item['name']}: corte errado: {linha!r}"
            )
            assert len(linha.split(": ", 1)[1]) == limite
        else:
            assert linha == f"- {item['name']}: {descricao}"


def test_catalog_text_com_limite_pequeno_encurta_a_linha(skills_do_repositorio):
    longas = editor_skills.catalog_text().splitlines()
    curtas = editor_skills.catalog_text(30).splitlines()
    assert len(longas) == len(curtas)
    assert sum(len(l) for l in curtas) < sum(len(l) for l in longas)
    assert all(len(c) < len(l) for c, l in zip(curtas, longas))
    assert all(c.endswith("…") for c in curtas), "toda descrição cortada ganha ellipsis"


# -------------------------------------------------------- escolha por palavra


def test_choose_skills_para_pedido_de_corte_e_ritmo():
    nomes = {item["name"] for item in editor_skills.list_skills()}
    escolha = editor_skills.choose_skills("corta os silêncios e faz o ritmo do vlog")
    assert escolha, "nenhuma skill sugerida para um pedido claro de corte e ritmo"
    assert set(escolha) <= nomes, f"sugestões fora do catálogo: {set(escolha) - nomes}"


def test_choose_skills_respeita_o_limit():
    texto = "corta os silêncios e faz o ritmo do vlog, com legenda e áudio"
    maximo = editor_skills.choose_skills(texto, limit=99)
    for limite in (1, 2, 3):
        escolha = editor_skills.choose_skills(texto, limit=limite)
        assert len(escolha) <= limite, f"limit={limite} devolveu {len(escolha)}"
        assert escolha == maximo[:limite], "o corte precisa ser o topo da mesma lista ordenada"


@pytest.mark.parametrize("nome", SKILLS_INSTALADAS)
def test_choose_skills_prioriza_a_skill_citada_pelo_nome(nome):
    """Citar o nome exato vale +5 no score; nenhum gatilho isolado (+1) vence isso."""
    escolha = editor_skills.choose_skills(f"aja conforme {nome}", limit=3)
    assert escolha and escolha[0] == nome, (
        f"{nome!r} citada por extenso deveria ser a primeira sugestão, veio {escolha}"
    )


@pytest.mark.parametrize("texto", ["", None, "   ", "\n\t", "  ,, .. "])
def test_choose_skills_com_texto_vazio_devolve_lista_vazia(texto):
    assert editor_skills.choose_skills(texto) == []


@pytest.mark.parametrize(
    "texto",
    [
        "zzzz qqqq wwww",
        "receita de lasanha com bechamel",
        "quantas horas tem o fuso de Tóquio",
        "<script>alert(1)</script>",
        "0000",
    ],
)
def test_choose_skills_nao_quebra_com_texto_inexistente(texto):
    nomes = {item["name"] for item in editor_skills.list_skills()}
    escolha = editor_skills.choose_skills(texto)
    assert isinstance(escolha, list)
    assert set(escolha) <= nomes
    assert not escolha, f"texto sem relação com edição sugeriu {escolha}"


def test_choose_skills_usa_substring_e_pode_casar_por_acidente():
    """O casamento é por substring: '../skills' contém o gatilho 'kills' do gaming.

    Não é defeito de dados nem falha de segurança (a sugestão só devolve nomes
    reais), mas vale registrar o comportamento do pontuador.
    """
    nomes = {item["name"] for item in editor_skills.list_skills()}
    escolha = editor_skills.choose_skills("../skills")
    assert set(escolha) <= nomes


def test_choose_skills_limite_zero_devolve_vazio():
    assert editor_skills.choose_skills("podcast", limit=0) == []
