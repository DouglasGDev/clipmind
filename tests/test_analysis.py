"""
Testes da análise de conteúdo (editor_analysis) e das anotações que ela grava.

Metade do arquivo lê logs capturados do FFmpeg de verdade — os leitores são
função pura e são exercitados com a saída real, não com texto inventado. A outra
metade roda FFmpeg contra ./test_videos e confere número que já foi conferido à
mão: as pausas de `video_com_pausas.mp4` estão em 2–4 s e 6–8 s do arquivo, a
troca de cena de `cores.mp4` está em 2,0 s com score 15,6, e o loudness do
arquivo inteiro dá -4,6 LUFS com pico de 3,9 dBFS.

O teste do pico inteiro existe por um motivo: medir com `-ss` antes de `-i`
devolveu 0,1 dBFS para o mesmo material, 3,8 dBFS abaixo do valor real, porque o
seek de entrada descarta o priming do decodificador AAC. O recorte passou a
acontecer em `atrim`, dentro do filtro.
"""

import pytest

import editor_analysis
from conftest import MEDIA, requires_media
from editor_project import (
    ProjectError,
    add_clip,
    add_marker,
    add_region,
    annotate,
    clear_annotations,
    remove_region,
)

# ------------------------------------------------------------------ leitores


def test_parse_scene_log_ordena_e_remove_repeticoes():
    log = (
        '[Parsed_scdet_0 @ 0x1] lavfi.scd.score: 22.5, lavfi.scd.time: 3.5\n'
        '[Parsed_scdet_0 @ 0x1] lavfi.scd.score: 15.625, lavfi.scd.time: 2\n'
        '[Parsed_scdet_0 @ 0x1] lavfi.scd.score: 15.625, lavfi.scd.time: 2\n'
    )
    assert editor_analysis.parse_scene_log(log) == [
        {"time": 2.0, "score": 15.6},
        {"time": 3.5, "score": 22.5},
    ]


def test_parse_silence_log_emparelha_inicio_e_fim():
    log = (
        "[Parsed_silencedetect_0 @ 0x1] silence_start: 2\n"
        "[Parsed_silencedetect_0 @ 0x1] silence_end: 4.000021 | silence_duration: 2.000021\n"
        "[Parsed_silencedetect_0 @ 0x1] silence_start: 6\n"
        "[Parsed_silencedetect_0 @ 0x1] silence_end: 8.000021 | silence_duration: 2.000021\n"
    )
    pausas = editor_analysis.parse_silence_log(log, 10.0)
    assert [(p["start"], p["end"]) for p in pausas] == [(2.0, 4.0), (6.0, 8.0)]
    assert pausas[0]["duration"] == pytest.approx(2.0)


def test_parse_silence_log_sem_fim_usa_o_total_da_janela():
    """Silêncio que chega ao fim do recorte não tem `silence_end`; a janela fecha."""
    log = "[Parsed_silencedetect_0 @ 0x1] silence_start: 7.5\n"
    assert editor_analysis.parse_silence_log(log, 10.0) == [
        {"start": 7.5, "end": 10.0, "duration": 2.5}
    ]


def test_parse_silence_log_ignora_tempo_fora_da_janela():
    log = "[Parsed_silencedetect_0 @ 0x1] silence_start: 12\n"
    assert editor_analysis.parse_silence_log(log, 10.0) == []


def test_parse_ebur128_fica_no_resumo_e_nas_linhas_de_quadro():
    log = (
        "[Parsed_ebur128_0 @ 0x1] t: 0.1  TARGET:-23 LUFS  I: -70.0 LUFS  LRA: 0.0 LU  FTPK: 3.9 dBFS  TPK: 3.9 dBFS\n"
        "[Parsed_ebur128_0 @ 0x1] Summary:\n"
        "\n  Integrated loudness:\n    I:          -4.6 LUFS\n    Threshold: -14.8 LUFS\n"
        "\n  Loudness range:\n    LRA:         3.0 LU\n    Threshold: -27.3 LUFS\n"
        "    LRA low:    -8.9 LUFS\n    LRA high:   -5.9 LUFS\n"
        "\n  True peak:\n    Peak:        3.9 dBFS\n"
    )
    assert editor_analysis.parse_ebur128(log) == {
        "integrated_lufs": -4.6,
        "lra_lu": 3.0,
        "true_peak_dbfs": 3.9,
    }


def test_parse_ebur128_sem_medida_devolve_vazio():
    assert editor_analysis.parse_ebur128("nada aqui") == {}


def test_parse_black_log_devolve_pares():
    log = "[Parsed_blackdetect_0 @ 0x1] black_start:1.5 black_end:2.25 black_duration: 0.75\n"
    assert editor_analysis.parse_black_log(log) == [[1.5, 2.25]]


# -------------------------------------------------------------- parâmetros


def test_arquivo_inexistente_da_erro_antes_de_chamar_ffmpeg():
    with pytest.raises(ProjectError, match="Arquivo não encontrado"):
        editor_analysis.silence_ranges(MEDIA / "nao-existe.mp4")


@requires_media
def test_janela_invertida_e_rejeitada():
    with pytest.raises(ProjectError, match="maior que o início"):
        editor_analysis.loudness(MEDIA / "video_com_pausas.mp4", 5, 2)


@requires_media
def test_janela_que_passa_do_arquivo_e_rejeitada():
    with pytest.raises(ProjectError, match="passa do arquivo"):
        editor_analysis.scene_cuts(MEDIA / "cores.mp4", 0, 40)


@pytest.mark.parametrize(
    "funcao,argumentos,mensagem",
    [
        ("scene_cuts", {"threshold": 0}, "entre 1 e 100"),
        ("scene_cuts", {"threshold": 400}, "entre 1 e 100"),
        ("silence_ranges", {"min_pause": 0.01}, "entre 0,05 e 60"),
        ("silence_ranges", {"min_pause": 90}, "entre 0,05 e 60"),
        ("silence_ranges", {"noise": -180}, "entre -90 e 0"),
        ("silence_ranges", {"noise": 3}, "entre -90 e 0"),
    ],
)
@requires_media
def test_parametros_fora_da_faixa_sao_rejeitados(funcao, argumentos, mensagem):
    """Os filtros do FFmpeg aceitariam lixo e devolveriam lixo; a checagem é aqui."""
    with pytest.raises(ProjectError, match=mensagem):
        getattr(editor_analysis, funcao)(MEDIA / "video_com_pausas.mp4", **argumentos)


def test_ffmpeg_ausente_vira_mensagem_de_instalacao(monkeypatch):
    monkeypatch.setattr(editor_analysis, "FFMPEG", "ffmpeg-que-nao-esta-no-path")
    with pytest.raises(ProjectError, match="FFmpeg não encontrado"):
        editor_analysis.run_ffmpeg_log(["-version"])


def test_ffmpeg_com_saida_nao_zero_traz_a_ultima_linha_do_log(monkeypatch):
    monkeypatch.setattr(editor_analysis, "FFMPEG", "ffmpeg")
    with pytest.raises(ProjectError, match="Falha na análise"):
        editor_analysis.run_ffmpeg_log(["-i", "nao-existe.mp4"])


# ------------------------------------------------------------- medição real


@requires_media
def test_silence_ranges_mede_as_pausas_reais_do_material():
    pausas = editor_analysis.silence_ranges(MEDIA / "video_com_pausas.mp4")
    assert [(p["start"], p["end"]) for p in pausas] == [(2.0, 4.0), (6.0, 8.0)]


@requires_media
def test_silence_ranges_devolve_tempo_relativo_a_janela():
    pausas = editor_analysis.silence_ranges(MEDIA / "video_com_pausas.mp4", 1, 9)
    assert [(p["start"], p["end"]) for p in pausas] == [(1.0, 3.0), (5.0, 7.0)]


@requires_media
def test_scene_cuts_acha_a_troca_de_cena_real_com_score():
    cenas = editor_analysis.scene_cuts(MEDIA / "cores.mp4")
    assert len(cenas) == 1
    assert cenas[0]["time"] == pytest.approx(2.0)
    assert cenas[0]["score"] == pytest.approx(15.6, abs=0.5)


@requires_media
def test_loudness_do_arquivo_inteiro_bate_com_a_leitura_sem_seek():
    """
    A medição da janela inteira tem que ser a medição do arquivo.

    Com `-ss 0` antes de `-i` o FFmpeg descarta o priming do decodificador AAC e o
    true peak saía 0,1 dBFS em vez de 3,9 dBFS. O recorte passou a ser feito com
    `atrim` dentro do filtro, e este teste é o que impede a volta do seek.
    """
    medidas = editor_analysis.loudness(MEDIA / "video_com_pausas.mp4")
    assert medidas["integrated_lufs"] == pytest.approx(-4.6, abs=0.2)
    assert medidas["lra_lu"] == pytest.approx(3.0, abs=0.4)
    assert medidas["true_peak_dbfs"] == pytest.approx(3.9, abs=0.2)


@requires_media
def test_loudness_de_um_recorte_nao_e_a_medida_do_arquivo_todo():
    recorte = editor_analysis.loudness(MEDIA / "video_com_pausas.mp4", 2, 6)
    inteiro = editor_analysis.loudness(MEDIA / "video_com_pausas.mp4")
    assert recorte["true_peak_dbfs"] < inteiro["true_peak_dbfs"] - 1.0


@requires_media
def test_cenas_recusam_material_sem_video():
    with pytest.raises(ProjectError, match="não tem vídeo"):
        editor_analysis.scene_cuts(MEDIA / "fala_com_pausas.m4a")


@requires_media
@pytest.mark.parametrize("funcao", ["silence_ranges", "loudness"])
def test_medições_de_áudio_recusam_material_sem_áudio(funcao):
    with pytest.raises(ProjectError, match="não tem áudio"):
        getattr(editor_analysis, funcao)(MEDIA / "cores.mp4")


# ------------------------------------------------------------ tempo de timeline


def _projeto_com_clipe(store, fonte, **recorte) -> tuple[str, str]:
    """Projeto com um único clipe de mídia na faixa v1; devolve (project_id, clip_id)."""
    projeto = store.create("Análise", 1280, 720, 30)
    with store.edit(projeto["id"], "montar") as vivo:
        clipe = add_clip(vivo, "v1", str(MEDIA / fonte), **recorte)
    return projeto["id"], clipe["id"]


@requires_media
def test_analyze_devolve_janela_grupo_e_candidatos(store):
    pid, cid = _projeto_com_clipe(store, "video_com_pausas.mp4")
    analise = editor_analysis.analyze_clip(store.get(pid), cid, "silence")
    assert analise["kind"] == "silence"
    assert analise["group"] == "pausas"
    assert analise["window"]["file_start"] == 0.0
    assert analise["window"]["file_end"] == 10.0
    assert len(analise["candidates"]) == 2
    assert "2 pausa(s)" in analise["summary"]


@requires_media
def test_analyze_mapeia_pausas_para_a_timeline_na_velocidade_2x(store):
    """
    O clipe roda a 2x: dois segundos de arquivo viram um segundo de timeline.

    É a conta que a interface usa para mover um corte, então o teste confere os
    quatro números de cada pausa — tempo no arquivo e tempo na timeline.
    """
    pid, cid = _projeto_com_clipe(
        store, "video_com_pausas.mp4", start=20.0, in_point=1.0, out_point=9.0, speed=2.0
    )
    analise = editor_analysis.analyze_clip(store.get(pid), cid, "silence")
    assert [(c["start"], c["end"], c["source_start"], c["source_end"])
            for c in analise["candidates"]] == [
        (20.5, 21.5, 2.0, 4.0),
        (22.5, 23.5, 6.0, 8.0),
    ]
    assert analise["candidates"][0]["label"] == "Pausa 1.0s"
    assert analise["candidates"][0]["duration"] == pytest.approx(1.0)
    assert analise["candidates"][0]["source_duration"] == pytest.approx(2.0)


@requires_media
def test_analyze_mapeia_cena_para_a_timeline_deslocada(store):
    pid, cid = _projeto_com_clipe(store, "cores.mp4", start=30.0)
    analise = editor_analysis.analyze_clip(store.get(pid), cid, "scenes")
    cena = analise["candidates"][0]
    assert cena["time"] == pytest.approx(32.0)
    assert cena["source_time"] == pytest.approx(2.0)
    assert cena["label"] == "Cena 00:00:32"


@requires_media
def test_analyze_loudness_mede_mas_nao_produz_candidato(store):
    pid, cid = _projeto_com_clipe(store, "video_com_pausas.mp4")
    analise = editor_analysis.analyze_clip(store.get(pid), cid, "loudness")
    assert analise["candidates"] == []
    assert analise["group"] == ""
    assert analise["measurements"]["integrated_lufs"] == pytest.approx(-4.6, abs=0.2)
    assert "LUFS integrado" in analise["summary"]


@requires_media
def test_analyze_diz_quando_nao_acha_nada_com_aqueles_parametros(store):
    pid, cid = _projeto_com_clipe(store, "video_com_pausas.mp4")
    analise = editor_analysis.analyze_clip(store.get(pid), cid, "silence", min_pause=8.0)
    assert analise["candidates"] == []
    assert "nada encontrado com esses parâmetros" in analise["summary"]


def test_analyze_recusa_kind_que_nao_existe(store):
    projeto = store.create("Sem Mídia")
    with pytest.raises(ProjectError, match="Análise desconhecida"):
        editor_analysis.analyze_clip(projeto, "c_qualquer", "rostos")


def test_analyze_recusa_clipe_inexistente(store):
    projeto = store.create("Sem Mídia")
    with pytest.raises(ProjectError, match="não encontrado"):
        editor_analysis.analyze_clip(projeto, "c_inexistente", "scenes")


@requires_media
def test_analyze_recusa_titulo_e_legenda(store):
    from editor_project import add_text_clip

    projeto = store.create("Só Texto")
    with store.edit(projeto["id"], "título") as vivo:
        titulo = add_text_clip(vivo, "t1", text="abertura", duration=3)
    with pytest.raises(ProjectError, match="Só clipes de mídia"):
        editor_analysis.analyze_clip(store.get(projeto["id"]), titulo["id"], "scenes")


# ------------------------------------------------------- candidatos → anotação


def test_build_annotations_cenas_viram_marcadores():
    analise = {"kind": "scenes", "candidates": [{"time": 4.0, "label": "Cena 00:00:04"}]}
    assert editor_analysis.build_annotations(analise) == {
        "group": "cenas",
        "markers": [{"time": 4.0, "label": "Cena 00:00:04", "color": "#fbbf24"}],
        "regions": [],
    }


def test_build_annotations_pausas_viram_regioes():
    analise = {
        "kind": "silence",
        "candidates": [{"start": 2.0, "end": 4.0, "label": "Pausa 2.0s"}],
    }
    assert editor_analysis.build_annotations(analise) == {
        "group": "pausas",
        "markers": [],
        "regions": [{"start": 2.0, "end": 4.0, "label": "Pausa 2.0s", "color": "#4f8cff"}],
    }


def test_build_annotations_loudness_nao_grava_nada():
    assert editor_analysis.build_annotations({"kind": "loudness", "candidates": []}) == {
        "group": "",
        "markers": [],
        "regions": [],
    }


# ----------------------------------------------------------------- annotate


def test_annotate_grava_marcadores_e_regioes_em_um_passo_de_undo(store):
    projeto = store.create("Anotar")
    pid = projeto["id"]
    with store.edit(pid, "análise") as vivo:
        resultado = annotate(
            vivo,
            group="pausas",
            markers=[{"time": 1.0, "label": "um"}, {"time": 2.0, "label": "dois"}],
            regions=[{"start": 4.0, "end": 6.0, "label": "pausa"}],
        )
    assert resultado == {"group": "pausas", "markers": 2, "regions": 1, "duplicates_skipped": 0}
    snapshot = store.view(pid)
    assert [m["group"] for m in snapshot["markers"]] == ["pausas", "pausas"]
    assert snapshot["regions"][0]["group"] == "pausas"
    assert store.history(pid)["undo"] == ["análise"]
    store.undo(pid)
    vazio = store.view(pid)
    assert vazio["markers"] == [] and vazio["regions"] == []


def test_annotate_rodado_duas_vezes_nao_empilha_candidatos(store):
    projeto = store.create("Repetida")
    pid = projeto["id"]
    candidatos = [{"time": 1.0, "label": "cena"}, {"time": 2.0, "label": "cena"}]
    with store.edit(pid, "primeira") as vivo:
        annotate(vivo, group="cenas", markers=candidatos)
    with store.edit(pid, "segunda") as vivo:
        annotate(vivo, group="cenas", markers=candidatos)
    assert len(store.view(pid)["markers"]) == 2


def test_annotate_preserva_o_que_o_editor_fez_a_mao(store):
    projeto = store.create("Misturado")
    pid = projeto["id"]
    with store.edit(pid, "à mão") as vivo:
        add_marker(vivo, 1.0, "capítulo meu")
        add_region(vivo, 8.0, 9.0, "abertura minha")
    with store.edit(pid, "análise") as vivo:
        resultado = annotate(
            vivo,
            group="cenas",
            markers=[{"time": 1.0, "label": "repetido"}, {"time": 5.0, "label": "novo"}],
        )
    assert resultado["duplicates_skipped"] == 1
    snapshot = store.view(pid)
    rotulos = {m["label"]: m.get("group") for m in snapshot["markers"]}
    assert rotulos == {"capítulo meu": None, "novo": "cenas"}
    assert snapshot["regions"][0]["label"] == "abertura minha"
    assert "group" not in snapshot["regions"][0]


def test_annotate_sem_nada_para_gravar_e_rejeitado(store):
    projeto = store.create("Vazia")
    with pytest.raises(ProjectError, match="não trouxe anotação nova"):
        with store.edit(projeto["id"], "nada") as vivo:
            annotate(vivo, group="cenas", markers=[])
    assert store.history(projeto["id"])["undo"] == []


def test_annotate_com_demasiados_candidatos_e_rejeitado(store):
    projeto = store.create("Enchida")
    demais = [{"time": float(i), "label": f"c{i}"} for i in range(401)]
    with pytest.raises(ProjectError, match="candidatos demais"):
        with store.edit(projeto["id"], "inundar") as vivo:
            annotate(vivo, group="cenas", markers=demais)


def test_annotate_invalida_tempo_e_cor_do_candidato(store):
    projeto = store.create("Lixo")
    with pytest.raises(ProjectError, match="cor do marcador"):
        with store.edit(projeto["id"], "cor hostil") as vivo:
            annotate(vivo, group="cenas", markers=[{"time": 1.0, "color": "<script>"}])


def test_clear_annotations_tira_so_o_grupo(store):
    projeto = store.create("Limpar")
    pid = projeto["id"]
    with store.edit(pid, "à mão") as vivo:
        add_marker(vivo, 1.0, "meu")
    with store.edit(pid, "análise") as vivo:
        annotate(vivo, group="pausas", regions=[{"start": 2.0, "end": 4.0, "label": "pausa"}])
    with store.edit(pid, "limpar") as vivo:
        removido = clear_annotations(vivo, "pausas")
    assert removido == {"group": "pausas", "markers": 0, "regions": 1}
    snapshot = store.view(pid)
    assert [m["label"] for m in snapshot["markers"]] == ["meu"]
    assert snapshot["regions"] == []


def test_clear_annotations_em_grupo_vazio_diz_iso(store):
    projeto = store.create("Sem Anotação")
    with pytest.raises(ProjectError, match="Nenhuma anotação no grupo"):
        with store.edit(projeto["id"], "limpar") as vivo:
            clear_annotations(vivo, "pausas")


def test_clear_annotations_exige_grupo(store):
    projeto = store.create("Sem Nome")
    with pytest.raises(ProjectError, match="grupo"):
        with store.edit(projeto["id"], "limpar tudo") as vivo:
            clear_annotations(vivo, "")


def test_remove_region_apaga_por_id_e_rejeita_desconhecida(store):
    projeto = store.create("Regiões")
    pid = projeto["id"]
    with store.edit(pid, "criar") as vivo:
        regiao = add_region(vivo, 2.0, 4.0, "pausa")
    with store.edit(pid, "apagar") as vivo:
        assert remove_region(vivo, regiao["id"])["label"] == "pausa"
        with pytest.raises(ProjectError, match="Região não encontrada"):
            remove_region(vivo, "r_fantasma")
    assert store.view(pid)["regions"] == []


# ------------------------------------------------------------------ rota HTTP


@pytest.fixture
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import editor_api

    app = FastAPI()
    app.include_router(editor_api.router)
    with TestClient(app, raise_server_exceptions=False) as novo:
        yield novo


@pytest.fixture
def projeto_http(client) -> str:
    resposta = client.post(
        "/api/editor/projects", json={"name": "HTTP", "width": 1280, "height": 720, "fps": 30}
    )
    return resposta.json()["project"]["id"]


def _clipe_http(client, pid: str, fonte: str) -> str:
    resposta = client.post(
        f"/api/editor/projects/{pid}/operations",
        json={"operation": "add_clip", "params": {"track_id": "v1", "source": str(MEDIA / fonte)}},
    )
    assert resposta.status_code == 200, resposta.text
    return resposta.json()["project"]["tracks"][0]["clips"][0]["id"]


@requires_media
def test_rota_de_analise_mede_sem_tocar_no_projeto(client, projeto_http):
    pid = projeto_http
    cid = _clipe_http(client, pid, "video_com_pausas.mp4")
    resposta = client.post(f"/api/editor/projects/{pid}/analyze", json={"clip_id": cid, "kind": "silence"})
    assert resposta.status_code == 200, resposta.text
    dados = resposta.json()
    assert [c["start"] for c in dados["analysis"]["candidates"]] == [2.0, 6.0]
    assert dados["analysis"]["group"] == "pausas"
    assert "annotations" not in dados
    assert dados["project"]["regions"] == []


@requires_media
def test_rota_de_analise_com_apply_grava_e_mostra_o_que_veio_do_projeto(client, projeto_http):
    pid = projeto_http
    cid = _clipe_http(client, pid, "video_com_pausas.mp4")
    resposta = client.post(
        f"/api/editor/projects/{pid}/analyze", json={"clip_id": cid, "kind": "silence", "apply": True}
    )
    assert resposta.status_code == 200, resposta.text
    dados = resposta.json()
    assert dados["annotations"] == {"group": "pausas", "markers": 0, "regions": 2}
    regioes = dados["project"]["regions"]
    assert [(r["start"], r["end"]) for r in regioes] == [(2.0, 4.0), (6.0, 8.0)]
    assert regioes[0]["color"] == "#4F8CFF"


@requires_media
def test_rota_de_analise_com_apply_emite_o_evento_que_a_interface_escuta(client, projeto_http, monkeypatch):
    import editor_api

    eventos: list[dict] = []

    async def capturar(evento: dict) -> None:
        eventos.append(evento)

    anterior = editor_api._sink
    editor_api._sink = capturar
    try:
        pid = projeto_http
        cid = _clipe_http(client, pid, "cores.mp4")
        resposta = client.post(
            f"/api/editor/projects/{pid}/analyze", json={"clip_id": cid, "kind": "scenes", "apply": True}
        )
    finally:
        editor_api._sink = anterior
    assert resposta.status_code == 200, resposta.text
    assert eventos[-1]["operation"] == "annotate"
    assert eventos[-1]["project_id"] == pid
    assert resposta.json()["annotations"]["markers"] == 1


@requires_media
def test_rota_de_analise_sem_candidato_para_gravar_e_400(client, projeto_http):
    pid = projeto_http
    cid = _clipe_http(client, pid, "video_com_pausas.mp4")
    resposta = client.post(
        f"/api/editor/projects/{pid}/analyze", json={"clip_id": cid, "kind": "loudness", "apply": True}
    )
    assert resposta.status_code == 400
    assert "candidato" in resposta.json()["detail"]


@requires_media
def test_rota_de_analise_valida_entrada(client, projeto_http):
    pid = projeto_http
    cid = _clipe_http(client, pid, "video_com_pausas.mp4")
    assert client.post(f"/api/editor/projects/{pid}/analyze", json={"clip_id": cid, "kind": "carrossel"}).status_code == 400
    resposta = client.post(f"/api/editor/projects/{pid}/analyze", json={"clip_id": cid, "kind": "silence", "min_pause": 900})
    assert resposta.status_code == 400
    assert "0,05 e 60" in resposta.json()["detail"]


def test_rota_de_analise_em_projeto_inexistente_e_404(client):
    """Id bem formado que não existe é busca; id torto é entrada inválida."""
    faltando = client.post("/api/editor/projects/p_aaaaaaaa11/analyze", json={"clip_id": "c_1"})
    assert faltando.status_code == 404
    torto = client.post("/api/editor/projects/qualquer-coisa/analyze", json={"clip_id": "c_1"})
    assert torto.status_code == 400
    assert "inválido" in torto.json()["detail"]


@requires_media
def test_rota_de_analise_em_clipe_de_texto_e_400(client, projeto_http):
    pid = projeto_http
    resposta = client.post(
        f"/api/editor/projects/{pid}/operations",
        json={"operation": "add_text", "params": {"track_id": "t1", "text": "oi", "duration": 2}},
    )
    assert resposta.status_code == 200, resposta.text
    cid = next(
        clipe["id"]
        for faixa in resposta.json()["project"]["tracks"]
        for clipe in faixa["clips"]
    )
    analise = client.post(f"/api/editor/projects/{pid}/analyze", json={"clip_id": cid})
    assert analise.status_code == 400
    assert "Só clipes de mídia" in analise.json()["detail"]
