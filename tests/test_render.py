"""
Testes do compositor FFmpeg, do QC e da fila de renderização (editor_render).

Os testes que invocam o FFmpeg usam a mídia real de ./test_videos e gravam em
diretório temporário; os de parsing/option são puros e rápidos.
"""

import threading
import time

import pytest

from conftest import MEDIA, requires_media
from editor_project import (
    ProjectError,
    add_clip,
    add_subtitle_clip,
    add_text_clip,
    new_project,
    project_duration,
)
from editor_render import (
    RenderError,
    RenderCancelled,
    RenderManager,
    _atempo_chain,
    _ass_color,
    _encoder_args,
    _ff_color,
    _fmt_ass_clock,
    _normalize_options,
    _parse_ass_clock,
    _parse_srt_clock,
    _subtitle_cues,
    _unique_output,
    _write_subtitle_ass,
    render_project,
    validate_render,
)


def _tem_ffmpeg() -> bool:
    import shutil
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


requires_ffmpeg = pytest.mark.skipif(not _tem_ffmpeg(), reason="FFmpeg ausente do PATH")


# ------------------------------------------------------------- opções/código


@pytest.mark.parametrize(
    "opcoes,esperado",
    [
        ({}, {"preview": False, "crf": 20, "max_height": 0, "format": "mp4"}),
        ({"preview": True}, {"preview": True, "crf": 28, "max_height": 360, "format": "mp4"}),
    ],
)
def test_normalize_options_aplica_padroes_de_preview_e_export(opcoes, esperado):
    resultado = _normalize_options(opcoes)
    for chave, valor in esperado.items():
        assert resultado[chave] == valor


def test_normalize_options_limita_crf_normaliza_extensao_e_nome():
    resultado = _normalize_options({"crf": 99, "format": ".MKV", "filename": "Meu Vídeo!!!"})
    assert resultado["crf"] == 51
    assert resultado["format"] == "mkv"
    assert resultado["filename"] == "Meu-V-deo"


@pytest.mark.parametrize("formato", ["avi", "gif", "mp4.exe", ""])
def test_normalize_options_rejeita_formato_insuportavel(formato):
    with pytest.raises(RenderError, match="Formato suportado"):
        _normalize_options({"format": formato})


def test_unique_output_nunca_sobrescreve(render_dir):
    projeto = {"name": "Saida Unica"}
    opcoes = _normalize_options({"format": "mp4", "preview": True})
    primeiro = _unique_output(projeto, opcoes)
    assert primeiro.parent == render_dir
    assert primeiro.name.startswith("Saida-Unica_preview")
    primeiro.write_bytes(b"x")
    segundo = _unique_output(projeto, opcoes)
    assert segundo != primeiro
    assert segundo.name.endswith("_2.mp4")


def test_encoder_args_usa_codec_real_e_faststart_apenas_para_container_h264():
    mp4 = _encoder_args({"video_codec": "libx264", "preset": "medium", "crf": 23}, ".mp4")
    assert "libx264" in mp4 and "medium" in mp4 and "yuv420p" in mp4
    assert "+faststart" in mp4
    mkv = _encoder_args({"video_codec": "libx264"}, ".mkv")
    assert "+faststart" not in mkv
    webm = _encoder_args({}, ".webm")
    assert "libvpx-vp9" in webm and "libopus" in webm
    # codec inventado (a IA pode pedir h264_qsv) cai no padrão em vez de quebrar
    fallback = _encoder_args({"video_codec": "h264_nao_existe"}, ".mp4")
    assert fallback[1] == "libx264"
    bitrate = _encoder_args({"audio_bitrate": "128k"}, ".mp4")
    assert bitrate[bitrate.index("-b:a") + 1] == "128k"
    assert _encoder_args({"preset": "ultrafast"}, ".mp4")[3] == "ultrafast"


@pytest.mark.parametrize("velocidade", [0.1, 0.5, 1.0, 1.5, 2.0, 4.0, 8.0])
def test_atempo_chain_fica_na_faixa_do_ffmpeg(velocidade):
    cadeia = _atempo_chain(velocidade)
    assert cadeia, "velocidade precisa de filtro de áudio"
    fatores = [float(item.split("=")[1]) for item in cadeia]
    produto = 1.0
    for fator in fatores:
        produto *= fator
    assert produto == pytest.approx(velocidade, rel=0.01)
    for fator in fatores:
        assert 0.5 <= fator <= 2.0, "o FFmpeg rejeita atempo fora de 0.5–2.0"


@pytest.mark.parametrize(
    "valor,esperado",
    [("white", "white"), ("#ff0000", "0xff0000"), ("#AABBCC", "0xAABBCC"), ("nao-cor", "white")],
)
def test_ff_color_normaliza_para_o_formato_do_drawtext(valor, esperado):
    assert _ff_color(valor) == esperado


@pytest.mark.parametrize(
    "valor,esperado",
    [
        ("white", "&H00FFFFFF"),
        ("#FF0000", "&H000000FF"),
        ("#00FF00", "&H0000FF00"),
        ("yellow", "&H0000FFFF"),
        ("lixo", "&H00FFFFFF"),
        (None, "&H00FFFFFF"),
    ],
)
def test_ass_color_converte_rgb_para_bgra(valor, esperado):
    assert _ass_color(valor) == esperado


# ------------------------------------------------------------------- tempos


@pytest.mark.parametrize(
    "texto,esperado",
    [("00:00:01,500", 1.5), ("00:01:30,000", 90.0), ("01:00:00.250", 3600.25)],
)
def test_parse_srt_clock(texto, esperado):
    assert _parse_srt_clock(texto) == pytest.approx(esperado)


@pytest.mark.parametrize(
    "texto,esperado",
    [("0:00:03.50", 3.5), ("0:01:00.00", 60.0), ("10:00:00.00", 36000.0)],
)
def test_parse_ass_clock(texto, esperado):
    assert _parse_ass_clock(texto) == pytest.approx(esperado)


def test_fmt_ass_clock_faz_roundtrip():
    for segundos in (0.0, 0.5, 3.47, 90.0, 3661.25):
        assert _parse_ass_clock(_fmt_ass_clock(segundos)) == pytest.approx(segundos, abs=0.01)


@requires_media
def test_subtitle_cues_le_srt_com_numeros_e_linhas_em_branco():
    cues = _subtitle_cues(MEDIA / "legenda.srt")
    assert cues == [
        (0.5, 3.0, "Primeira legenda do ClipMind"),
        (3.5, 6.0, "A IA chama ferramentas reais"),
    ]


@requires_media
def test_subtitle_cues_aceita_vtt_e_ass(tmp_path):
    vtt = tmp_path / "alice.vtt"
    vtt.write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.500\nsegunda faixa\n\n"
        "00:00:04.000 --> 00:00:06.000\nterceira <i>fala</i>\n",
        encoding="utf-8",
    )
    cues = _subtitle_cues(vtt)
    assert [c[0] for c in cues] == [1.0, 4.0]
    assert cues[0][2] == "segunda faixa"

    ass = tmp_path / "carol.ass"
    ass.write_text(
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:02.10,0:00:04.20,Default,,0,0,0,,linha {aninhada} de ASS\n",
        encoding="utf-8",
    )
    assert _subtitle_cues(ass) == [(2.1, 4.2, "linha {aninhada} de ASS")]


def test_subtitle_cues_em_arquivo_inexistente_gera_erro_lido(tmp_path):
    with pytest.raises((ProjectError, OSError)):
        _subtitle_cues(tmp_path / "nao-existe.srt")


# ------------------------------------------------------------------- ASS


def test_write_subtitle_ass_controla_posicao_e_margem(tmp_path):
    destino = tmp_path / "legenda.ass"
    mantidos = _write_subtitle_ass(
        destino,
        [(0.5, 3.0, "uma fala"), (3.5, 9.0, "fora do clipe")],
        inicio_clipe=1.0,
        duracao=3.0,
        estilo={"font_size": 22, "margin_v": 42, "position": "centro", "color": "#FF0000"},
        width=640,
        height=360,
        scale=1.0,
    )
    texto = destino.read_text(encoding="utf-8")
    assert mantidos == 1, "a fala que passa do fim do clipe não pode estourar para a próxima"
    assert "ScriptType: v4.00+" in texto
    assert "PlayResX: 640" in texto and "PlayResY: 360" in texto
    style = [linha for linha in texto.splitlines() if linha.startswith("Style: Default")][0]
    campos = style.split(",")
    assert campos[2] == "22", "tamanho de fonte segue o projeto, não o padrão do FFmpeg"
    assert campos[3] == "&H000000FF", "cor RGB vira BGRA no ASS"
    assert campos[18] == "5", "alinhamento 5 = centro no cabeçalho v4+"
    assert campos[21] == "42"
    assert campos[19] == campos[20] == "32", "margem lateral de 5% da largura"
    assert "Dialogue: 0,0:00:01.50,0:00:04.00,Default,,0,0,0,,uma fala" in texto


def test_write_subtitle_ass_mapeia_inferior_e_topo(tmp_path):
    for posicao, alinhamento in (("inferior", "2"), ("topo", "8")):
        destino = tmp_path / f"legenda-{posicao}.ass"
        _write_subtitle_ass(
            destino, [(0.0, 1.0, "x")], 0.0, 1.0,
            {"position": posicao}, 1280, 720, 1.0,
        )
        style = [l for l in destino.read_text(encoding="utf-8").splitlines() if l.startswith("Style:")][0]
        assert style.split(",")[18] == alinhamento


def test_write_subtitle_ass_sem_falas_nao_gera_arquivo(tmp_path):
    destino = tmp_path / "vazio.ass"
    assert _write_subtitle_ass(destino, [], 0.0, 5.0, {}, 640, 360, 1.0) == 0
    assert not destino.exists()


# ---------------------------------------------------------------- render


@requires_media
@requires_ffmpeg
def test_preview_renderiza_e_mediu_com_ffprobe(store, render_dir):
    projeto = store.create("Preview")
    with store.edit(projeto["id"], "add") as vivo:
        add_clip(vivo, "v1", str(MEDIA / "clipe_a.mp4"))
    destino = render_dir / "preview.mp4"
    resultado = render_project(store.get(projeto["id"]), destino, {"preview": True})

    assert destino.is_file() and destino.stat().st_size > 1000
    assert resultado["output"] == str(destino.resolve())
    assert resultado["duration"] == pytest.approx(4.0, abs=0.1)
    qc = resultado["qc"]
    assert qc["ok"], qc["issues"]
    medido = qc["measurements"]
    assert medido["height"] == 360 and medido["width"] == 640
    assert medido["duration"] == pytest.approx(4.0, abs=0.1)
    assert medido["fps"] == pytest.approx(30.0, abs=0.1)
    assert medido["has_audio"]
    assert medido["loudness_lufs"] < -5, "silêncio absoluto não é uma prévia útil"
    assert medido["true_peak_dbfs"] < 0.0
    assert not any(i["severity"] == "error" for i in qc["issues"])


@requires_media
@requires_ffmpeg
def test_export_e_preview_tem_mesma_duracao_e_proporcao(store, render_dir):
    projeto = store.create("Consistencia")
    with store.edit(projeto["id"], "add") as vivo:
        add_clip(vivo, "v1", str(MEDIA / "clipe_a.mp4"))
    vivo = store.get(projeto["id"])

    previa = render_project(vivo, render_dir / "a_prev.mp4", {"preview": True})
    final = render_project(vivo, render_dir / "a_export.mp4", {"preview": False, "crf": 28})

    assert previa["qc"]["measurements"]["duration"] == pytest.approx(
        final["qc"]["measurements"]["duration"], abs=0.1
    ), "a prévia não pode esconder um corte que aparece na exportação"
    for qc, altura in ((previa["qc"], 360), (final["qc"], 1080)):
        assert qc["ok"], qc["issues"]
        assert qc["measurements"]["height"] == altura
        proporcao = qc["measurements"]["width"] / qc["measurements"]["height"]
        assert abs(proporcao - 16 / 9) < 0.01
    # o arquivo bom para o YouTube é maior que a prévia barata
    assert final["qc"]["measurements"]["size"] > previa["qc"]["measurements"]["size"]


@requires_media
@requires_ffmpeg
def test_render_multicamadas_com_sobreposicao_titulo_legenda_e_trilha(store, render_dir, tmp_path):
    legenda = tmp_path / "curta.srt"
    legenda.write_text(
        "1\n00:00:00,500 --> 00:00:02,000\nprimeira fala\n\n"
        "2\n00:00:02,200 --> 00:00:03,800\nsegunda fala\n",
        encoding="utf-8",
    )
    projeto = store.create("Camadas", 1280, 720, 30)
    with store.edit(projeto["id"], "montar") as vivo:
        base = add_clip(vivo, "v1", str(MEDIA / "clipe_a.mp4"))
        assert base["start"] == 0.0
        add_clip(vivo, "v2", str(MEDIA / "clipe_b.mp4"), start=1.0, out_point=2.5)
        add_text_clip(vivo, "t1", "Título na faixa", start=0.5, duration=2.0, position="topo")
        add_subtitle_clip(vivo, "s1", str(legenda), start=0.0)
        add_clip(vivo, "a1", str(MEDIA / "musica.mp3"), start=0.0, out_point=4.0, volume=0.6)
        sobreposto = vivo["tracks"][1]["clips"][0]
        sobreposto["transform"] = {"x": 0, "y": 0, "scale": 0.4, "rotation": 0, "opacity": 0.85}
    vivo = store.get(projeto["id"])
    assert project_duration(vivo) == pytest.approx(4.0, abs=0.05)

    destino = render_dir / "camadas.mp4"
    resultado = render_project(vivo, destino, {"preview": True})
    qc = resultado["qc"]
    assert qc["ok"], qc["issues"]
    assert qc["measurements"]["duration"] == pytest.approx(4.0, abs=0.15)
    assert qc["measurements"]["has_audio"]
    assert qc["measurements"].get("av_start_delta", 0) <= 0.15
    assert not any(i["code"] == "black_frames" for i in qc["issues"]), "camadas não podem deixar buraco preto"


@requires_media
@requires_ffmpeg
def test_render_aplica_velocidade_e_corte_de_in_point(store, render_dir):
    projeto = store.create("Ritmo", 1280, 720, 30)
    with store.edit(projeto["id"], "montar") as vivo:
        clipe = add_clip(vivo, "v1", str(MEDIA / "timeline_teste.mp4"), in_point=1.0, out_point=3.0)
        clipe["speed"] = 2.0
    vivo = store.get(projeto["id"])
    assert project_duration(vivo) == pytest.approx(1.0, abs=0.02)

    destino = render_dir / "ritmo.mp4"
    resultado = render_project(vivo, destino, {"preview": True})
    assert resultado["qc"]["ok"], resultado["qc"]["issues"]
    assert resultado["qc"]["measurements"]["duration"] == pytest.approx(1.0, abs=0.15)


@requires_media
@requires_ffmpeg
def test_render_rejeita_timeline_invalida(store, render_dir):
    vazio = store.create("Vazio")
    with pytest.raises(RenderError, match="Timeline inválida"):
        render_project(store.get(vazio["id"]), render_dir / "nunca.mp4", {"preview": True})
    assert not (render_dir / "nunca.mp4").exists()


def test_render_rejeita_midia_ausente_antes_de_chamar_ffmpeg(tmp_path):
    projeto = new_project("Quebrado", 1280, 720, 30)
    projeto["tracks"][0]["clips"].append({
        "id": "c_quebrado", "type": "video", "source": str(tmp_path / "sumiu.mp4"),
        "name": "sumiu.mp4", "start": 0, "in": 0, "out": 4, "speed": 1, "volume": 1,
        "fade_in": 0, "fade_out": 0, "muted": False, "text": None, "subtitle": None,
        "transition": {"type": "none", "duration": 0},
        "transform": {"x": 0, "y": 0, "scale": 1, "rotation": 0, "opacity": 1},
        "color": {"brightness": 0, "contrast": 1, "saturation": 1, "gamma": 1},
    })
    with pytest.raises(RenderError, match="Timeline inválida"):
        render_project(projeto, tmp_path / "saida.mp4", {"preview": True})


def test_validate_render_de_arquivo_inexistente_nao_estoura(tmp_path):
    qc = validate_render(tmp_path / "nao-existe.mp4", new_project("X"))
    assert qc["ok"] is False
    assert qc["issues"][0]["code"] == "file"
    assert qc["measurements"] == {}


# ------------------------------------------------------------------- fila


@requires_media
@requires_ffmpeg
def test_manager_conclui_exporta_e_registra_qc(store, render_dir):
    projeto = store.create("Fila")
    with store.edit(projeto["id"], "add") as vivo:
        add_clip(vivo, "v1", str(MEDIA / "clipe_a.mp4"), out_point=2.0)

    eventos: list[dict] = []
    manager = RenderManager(store=store, on_update=eventos.append)
    job = manager.submit(projeto["id"], {"preview": True, "crf": 32})
    assert job["kind"] == "preview"
    assert job["status"] in {"queued", "running"}

    final = _aguardar(manager, job["id"], 120)
    assert final["status"] == "done", final.get("error")
    assert final["progress"] == 100
    assert final["output_name"].startswith("Fila_preview")
    assert (render_dir / final["output_name"]).is_file()
    assert final["qc"]["ok"], final["qc"]["issues"]
    # a interface recebe cada mudança de estado pelo sink
    assert [e["status"] for e in eventos][0] in {"queued", "running"}
    assert eventos[-1]["status"] == "done"
    assert manager.list(projeto["id"])[0]["id"] == job["id"]


@requires_media
@requires_ffmpeg
def test_manager_cancela_e_apaga_o_parcial(store, render_dir):
    projeto = store.create("Cancelamento")
    with store.edit(projeto["id"], "add") as vivo:
        add_clip(vivo, "v1", str(MEDIA / "video_teste.mp4"))

    manager = RenderManager(store=store)
    job = manager.submit(projeto["id"], {"preview": False, "preset": "medium", "crf": 20})
    cancelado = manager.cancel(job["id"])
    assert cancelado["message"] == "Cancelando"

    final = _aguardar(manager, job["id"], 120)
    assert final["status"] == "cancelled", final
    assert not (render_dir / job["output_name"]).exists(), "a parcial não pode ficar na pasta de saída"
    assert manager.get(job["id"])["id"] == job["id"]


def test_manager_rejeita_projeto_invalido_e_job_inexistente(store, render_dir):
    manager = RenderManager(store=store)
    vazio = store.create("Sem Clipe")
    with pytest.raises(RenderError, match="Timeline inválida|Adicione pelo menos"):
        manager.submit(vazio["id"], {"preview": True})
    with pytest.raises(RenderError, match="Tarefa não encontrada"):
        manager.get("job_inexistente")
    with pytest.raises(RenderError, match="Tarefa não encontrada"):
        manager.cancel("job_inexistente")


def test_submit_de_projeto_inexistente_da_erro_claro(store):
    manager = RenderManager(store=store)
    with pytest.raises(ProjectError):
        manager.submit("p_aaaaaaa000")


@requires_media
@requires_ffmpeg
def test_cancel_antes_de_iniciar_nao_renderiza_nada(store, render_dir):
    """Cancelamento por evento: mesmo com o processo já em execução o arquivo some."""
    projeto = store.create("Abort")
    with store.edit(projeto["id"], "add") as vivo:
        add_clip(vivo, "v1", str(MEDIA / "video_teste.mp4"))

    evento = threading.Event()
    destino = render_dir / "abort.mp4"

    def ao_iniciar(_):
        evento.set()

    def ao_progredir(pct, _):
        if pct >= 2:
            cancel.set()

    cancel = threading.Event()
    with pytest.raises(RenderCancelled):
        render_project(
            store.get(projeto["id"]), destino, {"preview": False, "preset": "medium"},
            on_progress=ao_progredir, cancel=cancel, on_process=ao_iniciar,
        )
    assert evento.is_set(), "o FFmpeg chegou a rodar"
    assert not destino.exists()


def _aguardar(manager: RenderManager, job_id: str, limite: float) -> dict:
    inicio = time.monotonic()
    while time.monotonic() - inicio < limite:
        snapshot = manager.get(job_id)
        if snapshot["status"] in {"done", "error", "cancelled"}:
            return snapshot
        time.sleep(0.25)
    raise AssertionError(f"job {job_id} não terminou em {limite}s: {snapshot['status']}")
