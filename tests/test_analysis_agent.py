"""
Testes do contrato entre a análise de conteúdo e as ferramentas do agente.

O que `editor_analysis` mede de FFmpeg já está coberto em tests/test_analysis.py;
aqui o que se prova é a beirada: a ferramenta devolve tempo de timeline (não de
arquivo), `apply_candidates` grava tudo num passo só de undo, o modelo recebe o
grupo para poder limpar, e nada disso apaga o que o editor marcou à mão.
"""

import inspect

from conftest import MEDIA, requires_media

import editor_project as ep
import timeline_agent
from test_timeline_agent import _por_nome, _projeto, _resposta


# ------------------------------------------------------------------ registro


def test_as_duas_ferramentas_de_analise_estao_registradas():
    nomes = {f.__name__ for f in timeline_agent.TOOLS}
    assert {"analyze_timeline_clip", "clear_timeline_annotations"} <= nomes


def test_analyze_nao_expoe_caminho_de_arquivo_nem_comando():
    """A IA mede um clipe do projeto; nunca um arquivo à escolha dela."""
    argumentos = set(inspect.signature(_por_nome("analyze_timeline_clip")).parameters)
    assert "source" not in argumentos
    assert "path" not in argumentos


def test_prompt_obriga_a_medir_antes_de_propor_corte():
    prompt = timeline_agent._system_prompt()
    assert "analyze_timeline_clip" in prompt
    assert "meça antes" in prompt


# ------------------------------------------------------------------- medir


@requires_media
def _projeto_com_pausas(loja):
    pid = _projeto(loja)
    with loja.edit(pid, "adicionar") as vivo:
        clipe = ep.add_clip(vivo, "v1", str(MEDIA / "video_com_pausas.mp4"), start=10.0)
    return pid, clipe["id"]


@requires_media
def test_analyze_devolve_tempos_de_timeline_da_faixa_escolhida(loja):
    pid, cid = _projeto_com_pausas(loja)
    resposta = _resposta(timeline_agent.analyze_timeline_clip(pid, clip_id=cid, kind="silence"))
    assert resposta["ok"] is True
    assert resposta["grupo"] == "pausas"
    assert resposta["total_candidatos"] == 2
    # O clipe começa em 10 s de timeline; as pausas estão em 2-4 s e 6-8 s do arquivo.
    assert [(c["start"], c["end"]) for c in resposta["candidatos"]] == [(12.0, 14.0), (16.0, 18.0)]
    assert resposta["candidatos"][0]["source_start"] == 2.0


@requires_media
def test_analyze_de_clipe_inexistente_nao_toca_na_timeline(loja):
    pid = _projeto(loja)
    resposta = _resposta(timeline_agent.analyze_timeline_clip(pid, clip_id="c_fantasma"))
    assert resposta["ok"] is False
    assert "não encontrado" in resposta["erro"]
    assert loja.history(pid)["undo"] == []


@requires_media
def test_analyze_de_material_sem_audio_vira_erro_legivel(loja):
    pid = _projeto(loja)
    with loja.edit(pid, "adicionar") as vivo:
        clipe = ep.add_clip(vivo, "v1", str(MEDIA / "cores.mp4"))
    resposta = _resposta(timeline_agent.analyze_timeline_clip(pid, clip_id=clipe["id"], kind="silence"))
    assert resposta["ok"] is False
    assert "não tem áudio" in resposta["erro"]
    assert loja.get(pid)["regions"] == []
    assert loja.history(pid)["undo"] == ["adicionar"]


@requires_media
def test_analyze_loudness_mede_sem_produzir_candidato(loja):
    pid, cid = _projeto_com_pausas(loja)
    resposta = _resposta(timeline_agent.analyze_timeline_clip(pid, clip_id=cid, kind="loudness"))
    assert resposta["candidatos"] == []
    assert resposta["medicoes"]["integrated_lufs"] == -4.6
    assert resposta["grupo"] == ""


# ---------------------------------------------------------------- gravar


@requires_media
def test_apply_candidates_grava_tudo_em_um_passo_de_undo(loja):
    pid, cid = _projeto_com_pausas(loja)
    resposta = _resposta(timeline_agent.analyze_timeline_clip(
        pid, clip_id=cid, kind="silence", apply_candidates=True
    ))
    assert resposta["anotacao"]["regions"] == 2
    projeto = loja.get(pid)
    assert [(r["start"], r["end"]) for r in projeto["regions"]] == [(12.0, 14.0), (16.0, 18.0)]
    assert {r["group"] for r in projeto["regions"]} == {"pausas"}
    assert loja.history(pid)["undo"] == ["Anotar pausas", "adicionar"]
    loja.undo(pid)
    assert loja.get(pid)["regions"] == []


@requires_media
def test_aplicar_de_novo_substitui_os_candidatos_sem_empilhar(loja):
    pid, cid = _projeto_com_pausas(loja)
    timeline_agent.analyze_timeline_clip(pid, clip_id=cid, kind="silence", apply_candidates=True)
    segunda = _resposta(timeline_agent.analyze_timeline_clip(
        pid, clip_id=cid, kind="silence", min_pause=1.5, apply_candidates=True
    ))
    assert segunda["anotacao"]["regions"] == 2
    assert len(loja.get(pid)["regions"]) == 2


@requires_media
def test_aplicar_em_loudness_avisa_em_vez_de_gravar_nada(loja):
    pid, cid = _projeto_com_pausas(loja)
    resposta = _resposta(timeline_agent.analyze_timeline_clip(
        pid, clip_id=cid, kind="loudness", apply_candidates=True
    ))
    assert resposta["ok"] is True
    assert resposta["anotacao"] is None
    assert "Nada para gravar" in resposta["aviso"]
    assert loja.get(pid)["regions"] == []
    assert loja.history(pid)["undo"] == ["adicionar"]


@requires_media
def test_clear_timeline_annotations_preserva_o_marcador_manual(loja):
    pid, cid = _projeto_com_pausas(loja)
    with loja.edit(pid, "marcar à mão") as vivo:
        ep.add_marker(vivo, 3.0, "capítulo meu")
    _resposta(timeline_agent.analyze_timeline_clip(
        pid, clip_id=cid, kind="silence", apply_candidates=True
    ))
    assert len(loja.get(pid)["regions"]) == 2
    limpo = _resposta(timeline_agent.clear_timeline_annotations(pid, group="pausas"))
    assert limpo["ok"] is True
    projeto = loja.get(pid)
    assert projeto["regions"] == []
    assert [m["label"] for m in projeto["markers"]] == ["capítulo meu"]


def test_clear_sem_grupo_e_rejeitado(loja):
    pid = _projeto(loja)
    resposta = _resposta(timeline_agent.clear_timeline_annotations(pid, group=""))
    assert resposta["ok"] is False
    assert "grupo" in resposta["erro"]
