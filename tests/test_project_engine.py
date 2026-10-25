"""
Testes do motor de timeline não destrutivo (editor_project).

Cobrem conversão de tempo, operações de corte (split/move/trim/slip/slide/roll),
validação de colisões, undo/redo, persistência em disco e versões.
"""

import shutil

import pytest

from conftest import MEDIA, requires_media
from editor_project import (
    ProjectError,
    ProjectStore,
    add_clip,
    add_marker,
    add_region,
    add_subtitle_clip,
    add_text_clip,
    add_track,
    apply_operation,
    clip_duration,
    clip_end,
    delete_clip,
    duplicate_clip,
    format_timecode,
    get_clip,
    has_errors,
    move_clip,
    new_project,
    normalize_color,
    parse_fps,
    parse_timecode,
    project_duration,
    remove_marker,
    roll_edit,
    set_clip_properties,
    slip_clip,
    slide_clip,
    split_clip,
    trim_clip,
    validate_project,
)


# --------------------------------------------------------------- conversões


@pytest.mark.parametrize(
    "valor,esperado",
    [
        (12.5, 12.5),
        ("12.5", 12.5),
        ("00:00:01", 1.0),
        ("00:01:30", 90.0),
        ("1:30", 90.0),
        ("00:00:01,500", 1.5),
        ("00:00:00.250", 0.25),
    ],
)
def test_parse_timecode_aceita_formatos(valor, esperado):
    assert parse_timecode(valor) == pytest.approx(esperado)


@pytest.mark.parametrize("valor", ["", "abc", "1:2:3:4", -3, True])
def test_parse_timecode_rejeita_invalidos(valor):
    with pytest.raises(ProjectError):
        parse_timecode(valor)


def test_format_timecode_roundtrip():
    assert format_timecode(90.0) == "00:01:30"
    assert format_timecode(1.5, precise=True) == "00:00:01.500"
    assert parse_timecode(format_timecode(3661.0)) == 3661.0


@pytest.mark.parametrize(
    "valor,esperado",
    [(30, 30.0), ("29.97", 29.97), ("30000/1001", 29.97), (60, 60.0)],
)
def test_parse_fps(valor, esperado):
    assert parse_fps(valor) == pytest.approx(esperado, abs=0.01)


@pytest.mark.parametrize("valor", [0, 500, "nada"])
def test_parse_fps_rejeita_invalidos(valor):
    with pytest.raises(ProjectError):
        parse_fps(valor)


# ---------------------------------------------------------------- estrutura


def test_projeto_novo_tem_faixas_padrao():
    projeto = new_project("Base", 1920, 1080, 30)
    ids = [t["id"] for t in projeto["tracks"]]
    assert ids == ["v1", "v2", "t1", "s1", "a1"]
    assert projeto["settings"]["width"] == 1920
    assert project_duration(projeto) == 0.0


def test_add_track_cria_id_unico():
    projeto = new_project("Base")
    nova = add_track(projeto, "audio", "Trilha")
    assert nova["id"] == "a2"
    assert nova["type"] == "audio"
    with pytest.raises(ProjectError):
        add_track(projeto, "invalida")


@pytest.mark.parametrize("nome", ["", "a" * 121])
def test_new_project_rejeita_nome_invalido(nome):
    with pytest.raises(ProjectError):
        new_project(nome)


@pytest.mark.parametrize("largura,altura", [(1921, 1080), (10, 10), (1920, 9000)])
def test_new_project_rejeita_resolucao_invalida(largura, altura):
    with pytest.raises(ProjectError):
        new_project("Ruim", largura, altura)


# ------------------------------------------------------------------ mídia


@requires_media
def test_add_clip_usa_duracao_real_da_midia(store):
    projeto = store.create("Midia")
    with store.edit(projeto["id"]) as vivo:
        clipe = add_clip(vivo, "v1", str(MEDIA / "timeline_teste.mp4"))
    assert clip_duration(clipe) == pytest.approx(6.0, abs=0.1)
    assert clipe["in"] == 0.0
    assert clipe["out"] == pytest.approx(6.0, abs=0.1)


@requires_media
def test_add_clip_fora_do_arquivo_e_rejeitada(store):
    projeto = store.create("Midia")
    with store.edit(projeto["id"]) as vivo:
        with pytest.raises(ProjectError, match="maior que a duração"):
            add_clip(vivo, "v1", str(MEDIA / "timeline_teste.mp4"), out_point=9999)


@requires_media
def test_add_audio_na_faixa_de_video_e_aceito_e_o_inverso_nao(store):
    projeto = store.create("Faixas")
    with store.edit(projeto["id"]) as vivo:
        add_clip(vivo, "v1", str(MEDIA / "timeline_teste.mp4"))
        add_clip(vivo, "a1", str(MEDIA / "musica.mp3"))
        with pytest.raises(ProjectError, match="não aceita clipes de mídia"):
            add_clip(vivo, "t1", str(MEDIA / "timeline_teste.mp4"))


@requires_media
def test_colisao_na_mesma_faixa_e_rejeitada(store):
    projeto = store.create("Colisao")
    with store.edit(projeto["id"]) as vivo:
        add_clip(vivo, "v1", str(MEDIA / "timeline_teste.mp4"), start=0)
        with pytest.raises(ProjectError, match="colidiria"):
            add_clip(vivo, "v1", str(MEDIA / "clipe_a.mp4"), start=1)
        # em outra faixa, a sobreposição é permitida
        add_clip(vivo, "v2", str(MEDIA / "clipe_a.mp4"), start=1)


# ------------------------------------------------------------ edições de corte


def _projeto_dois_clipes(store):
    """clipe_a (4 s) encostado em clipe_b (4 s) na faixa v1."""
    projeto = store.create("Cortes")
    with store.edit(projeto["id"]) as vivo:
        a = add_clip(vivo, "v1", str(MEDIA / "clipe_a.mp4"), start=0)
        b = add_clip(vivo, "v1", str(MEDIA / "clipe_b.mp4"), start=clip_end(a))
    return projeto["id"], a["id"], b["id"]


@requires_media
def test_split_mantem_cobertura_e_contiguidade(store):
    pid, aid, _ = _projeto_dois_clipes(store)
    with store.edit(pid, "split") as vivo:
        primeiro, segundo = split_clip(vivo, aid, 2.0)
        assert primeiro["start"] == 0.0
        assert clip_duration(primeiro) == pytest.approx(2.0)
        assert segundo["start"] == pytest.approx(2.0)
        assert primeiro["out"] == segundo["in"], "a divisão não pode duplicar nem pular quadros"
        assert clip_duration(primeiro) + clip_duration(segundo) == pytest.approx(4.0)


@requires_media
def test_split_fora_do_clipe_e_rejeitado(store):
    pid, aid, _ = _projeto_dois_clipes(store)
    with store.edit(pid, "split") as vivo:
        with pytest.raises(ProjectError, match="ponto de divisão"):
            split_clip(vivo, aid, 9.0)


@requires_media
def test_move_respeita_colisao(store):
    pid, aid, bid = _projeto_dois_clipes(store)
    with store.edit(pid, "mover") as vivo:
        dur_a = clip_duration(get_clip(vivo, aid)[1])
        with pytest.raises(ProjectError, match="colidiria"):
            move_clip(vivo, bid, 0.0)
        move_clip(vivo, bid, dur_a + 5.0)
        assert get_clip(vivo, bid)[1]["start"] == pytest.approx(dur_a + 5.0)


@requires_media
def test_trim_ripple_desloca_seguintes(store):
    pid, aid, bid = _projeto_dois_clipes(store)
    with store.edit(pid, "trim") as vivo:
        duracao_antes = clip_duration(get_clip(vivo, aid)[1])
        start_antes = get_clip(vivo, bid)[1]["start"]
        trim_clip(vivo, aid, out_point=1.0, ripple=True)
        novo_start = get_clip(vivo, bid)[1]["start"]
        assert clip_duration(get_clip(vivo, aid)[1]) == pytest.approx(1.0)
    # o buraco de (duracao_antes - 1) s fechou: o vizinho veio para trás
    assert novo_start == pytest.approx(start_antes - (duracao_antes - 1.0), abs=0.02)
    assert novo_start < start_antes


@requires_media
def test_trim_sem_ripple_mantem_vizinho_no_lugar(store):
    pid, aid, bid = _projeto_dois_clipes(store)
    with store.edit(pid, "trim") as vivo:
        antes = get_clip(vivo, bid)[1]["start"]
        trim_clip(vivo, aid, out_point=1.0)
        assert get_clip(vivo, bid)[1]["start"] == pytest.approx(antes)


@requires_media
def test_duplicate_insere_depois_e_empurra(store):
    pid, aid, bid = _projeto_dois_clipes(store)
    with store.edit(pid, "duplicar") as vivo:
        novo = duplicate_clip(vivo, aid, ripple=True)
        clipes = sorted(vivo["tracks"][0]["clips"], key=lambda c: c["start"])
        assert len(clipes) == 3
        assert clipes[1]["id"] == novo["id"]
        assert novo["start"] == pytest.approx(clip_duration(clipes[0]))
        assert clipes[2]["id"] == bid
        assert clipes[2]["start"] == pytest.approx(8.0)


@requires_media
def test_delete_ripple_fecha_buraco(store):
    pid, aid, bid = _projeto_dois_clipes(store)
    with store.edit(pid, "excluir") as vivo:
        delete_clip(vivo, aid, ripple=True)
        restante = get_clip(vivo, bid)[1]
    assert restante["start"] == 0.0


@requires_media
def test_delete_sem_ripple_abre_vazio(store):
    pid, aid, bid = _projeto_dois_clipes(store)
    with store.edit(pid, "excluir") as vivo:
        delete_clip(vivo, aid, ripple=False)
        restante = get_clip(vivo, bid)[1]
    assert restante["start"] == pytest.approx(4.0)


@requires_media
def test_slip_troca_trecho_sem_mover_timeline(store):
    projeto = store.create("Slip")
    with store.edit(projeto["id"], "slip") as vivo:
        a = add_clip(vivo, "v1", str(MEDIA / "clipe_a.mp4"), start=0, in_point=1.0, out_point=3.0)
        antes = dict(a)
        slip_clip(vivo, a["id"], 0.5)
        depois = get_clip(vivo, a["id"])[1]
        assert depois["start"] == antes["start"]
        assert clip_duration(depois) == clip_duration(antes)
        assert depois["in"] == pytest.approx(antes["in"] + 0.5)
        assert depois["out"] == pytest.approx(antes["out"] + 0.5)


@requires_media
def test_slip_fora_do_arquivo_e_rejeitado(store):
    projeto = store.create("Slip")
    with store.edit(projeto["id"], "slip") as vivo:
        a = add_clip(vivo, "v1", str(MEDIA / "clipe_a.mp4"), start=0, in_point=1.0, out_point=3.0)
        with pytest.raises(ProjectError, match="início do arquivo"):
            slip_clip(vivo, a["id"], -5.0)
        with pytest.raises(ProjectError, match="fim do arquivo"):
            slip_clip(vivo, a["id"], 5.0)


@requires_media
def test_slide_move_clipe_do_meio_ajustando_vizinhos(store):
    projeto = store.create("Slide")
    with store.edit(projeto["id"], "add") as vivo:
        a = add_clip(vivo, "v1", str(MEDIA / "clipe_a.mp4"), start=0, out_point=2)
        b = add_clip(vivo, "v1", str(MEDIA / "clipe_b.mp4"), start=2, in_point=1, out_point=3)
        c = add_clip(vivo, "v1", str(MEDIA / "clipe_b.mp4"), start=4, in_point=0, out_point=2)
        ids = (a["id"], b["id"], c["id"])
    with store.edit(projeto["id"], "slide") as vivo:
        slide_clip(vivo, ids[1], 0.5)
        assert get_clip(vivo, ids[0])[1]["out"] == pytest.approx(2.5)
        assert get_clip(vivo, ids[1])[1]["start"] == pytest.approx(2.5)
        assert get_clip(vivo, ids[2])[1]["start"] == pytest.approx(4.5)
        assert get_clip(vivo, ids[2])[1]["in"] == pytest.approx(0.5)
        # fronteira externa do primeiro não se move
        assert get_clip(vivo, ids[0])[1]["start"] == 0.0


@requires_media
def test_slide_exige_vizinhos_encostados(store):
    pid, aid, bid = _projeto_dois_clipes(store)
    with store.edit(pid, "slide") as vivo:
        with pytest.raises(ProjectError, match="Slide exige"):
            slide_clip(vivo, aid, 0.5)


@requires_media
def test_roll_move_fronteira_sem_criar_buraco(store):
    projeto = store.create("Roll")
    with store.edit(projeto["id"], "add") as vivo:
        a = add_clip(vivo, "v1", str(MEDIA / "clipe_a.mp4"), start=0, out_point=3)
        b = add_clip(vivo, "v1", str(MEDIA / "clipe_b.mp4"), start=3, in_point=1, out_point=4)
        ids = (a["id"], b["id"])
    with store.edit(projeto["id"], "roll") as vivo:
        roll_edit(vivo, ids[0], 0.5)
        clip_a = get_clip(vivo, ids[0])[1]
        clip_b = get_clip(vivo, ids[1])[1]
        assert clip_end(clip_a) == pytest.approx(clip_b["start"]), "roll não pode abrir buraco"
        assert clip_b["start"] == pytest.approx(3.5)
        assert clip_a["out"] == pytest.approx(3.5)
        assert clip_b["in"] == pytest.approx(1.5)
    # a duração total da timeline é preservada
    assert project_duration(store.view(projeto["id"])) == pytest.approx(6.0)


@requires_media
def test_roll_sem_clipe_seguinte_e_rejeitado(store):
    pid, _, bid = _projeto_dois_clipes(store)
    with store.edit(pid, "roll") as vivo:
        with pytest.raises(ProjectError, match="Roll exige"):
            roll_edit(vivo, bid, 0.5)


# ------------------------------------------------------------- propriedades


@requires_media
def test_set_properties_valida_limites(store):
    projeto = store.create("Props")
    with store.edit(projeto["id"], "props") as vivo:
        clipe = add_clip(vivo, "v1", str(MEDIA / "clipe_a.mp4"))
        with pytest.raises(ProjectError, match="velocidade"):
            set_clip_properties(vivo, clipe["id"], speed=20)
        set_clip_properties(vivo, clipe["id"], speed=2.0, volume=0.5)
        assert vivo["tracks"][0]["clips"][0]["speed"] == 2.0
        assert vivo["tracks"][0]["clips"][0]["volume"] == 0.5


@requires_media
def test_speed_reduz_duracao_na_timeline(store):
    projeto = store.create("Speed")
    with store.edit(projeto["id"], "add") as vivo:
        clipe = add_clip(vivo, "v1", str(MEDIA / "clipe_a.mp4"))
    with store.edit(projeto["id"], "speed") as vivo:
        set_clip_properties(vivo, clipe["id"], speed=2.0)
        assert clip_duration(get_clip(vivo, clipe["id"])[1]) == pytest.approx(2.0)


@requires_media
def test_transform_e_cor_validam_faixas(store):
    projeto = store.create("Look")
    with store.edit(projeto["id"], "add") as vivo:
        clipe = add_clip(vivo, "v1", str(MEDIA / "clipe_a.mp4"))
    with store.edit(projeto["id"], "look") as vivo:
        set_clip_properties(
            vivo, clipe["id"],
            transform_scale=1.5, transform_opacity=0.8, color_brightness=0.2,
        )
        alvo = get_clip(vivo, clipe["id"])[1]
        assert alvo["transform"]["scale"] == 1.5
        assert alvo["transform"]["opacity"] == 0.8
        assert alvo["color"]["brightness"] == 0.2
        # fora da faixa: o motor limita em vez de gravar um valor impossível
        set_clip_properties(vivo, clipe["id"], transform_opacity=12, color_contrast=-3)
        alvo = get_clip(vivo, clipe["id"])[1]
        assert alvo["transform"]["opacity"] == 1.0
        assert alvo["color"]["contrast"] == 0.0
        with pytest.raises(ProjectError, match="Transformação desconhecida"):
            set_clip_properties(vivo, clipe["id"], transform_warp=1)
        with pytest.raises(ProjectError, match="não suportada"):
            set_clip_properties(vivo, clipe["id"], scale=2)


@pytest.mark.parametrize(
    "valor,esperado",
    [
        ("white", "#FFFFFF"),
        ("branco", "#FFFFFF"),
        ("#ff0000", "#FF0000"),
        ("0x00ff00", "#00FF00"),
        ("  amarelo  ", "#FFFF00"),
    ],
)
def test_normaliza_cor_canoniciza_para_hex(valor, esperado):
    assert normalize_color(valor) == esperado


@pytest.mark.parametrize(
    "valor", ["", "cor-de-urubu", "#GGG", "#FFFF", "rgb(1,2,3)", "1,2,3", None, 3]
)
def test_normaliza_cor_rejeita_valores_sem_equivalente_no_render(valor):
    with pytest.raises(ProjectError, match="inválida"):
        normalize_color(valor, "cor da legenda")


@requires_media
def test_cor_e_validada_na_entrada_e_nao_silenciosa(store):
    projeto = store.create("Cores")
    with store.edit(projeto["id"], "cores") as vivo:
        titulo = add_text_clip(vivo, "t1", "Oi", color="amarelo")
        assert titulo["text"]["color"] == "#FFFF00"
        legenda = add_subtitle_clip(vivo, "s1", str(MEDIA / "legenda.srt"), color="#00FF00")
        assert legenda["subtitle"]["color"] == "#00FF00"
        set_clip_properties(vivo, titulo["id"], text_color="azul")
        assert get_clip(vivo, titulo["id"])[1]["text"]["color"] == "#0000FF"
        # cor que nem o drawtext nem o ASS entendem precisa virar erro, não branco
        with pytest.raises(ProjectError, match="cor do título inválida"):
            add_text_clip(vivo, "t1", "Ruim", color="cor-de-urubu", start=4)
        with pytest.raises(ProjectError, match="cor da legenda inválida"):
            set_clip_properties(vivo, legenda["id"], subtitle_color="cor-de-urubu")


@requires_media
def test_subtitle_position_aceita_so_posicoes_validas(store):
    projeto = store.create("Legendas")
    with store.edit(projeto["id"], "legenda") as vivo:
        clipe = add_subtitle_clip(vivo, "s1", str(MEDIA / "legenda.srt"))
        set_clip_properties(vivo, clipe["id"], subtitle_position="centro")
        assert get_clip(vivo, clipe["id"])[1]["subtitle"]["position"] == "centro"
        with pytest.raises(ProjectError, match="inválida"):
            set_clip_properties(vivo, clipe["id"], subtitle_position="canto")
        with pytest.raises(ProjectError, match="não suportada"):
            set_clip_properties(vivo, clipe["id"], cor_inexistente=1)
        with pytest.raises(ProjectError, match="só se aplica a legendas"):
            set_clip_properties(
                vivo, add_clip(vivo, "v1", str(MEDIA / "clipe_a.mp4"))["id"],
                subtitle_position="topo",
            )


@requires_media
def test_transicao_somente_fade_e_limitada(store):
    projeto = store.create("Transicao")
    with store.edit(projeto["id"], "add") as vivo:
        clipe = add_clip(vivo, "v1", str(MEDIA / "clipe_a.mp4"))
    with store.edit(projeto["id"], "transicao") as vivo:
        set_clip_properties(vivo, clipe["id"], transition={"type": "fade", "duration": 0.5})
        assert get_clip(vivo, clipe["id"])[1]["transition"]["type"] == "fade"
        with pytest.raises(ProjectError, match="Transição suportada"):
            set_clip_properties(vivo, clipe["id"], transition={"type": "wipe", "duration": 0.5})
        with pytest.raises(ProjectError, match="metade"):
            set_clip_properties(vivo, clipe["id"], transition={"type": "fade", "duration": 3.5})


@requires_media
def test_fades_maiores_que_o_clipe_sao_rejeitados(store):
    projeto = store.create("Fades")
    with store.edit(projeto["id"], "add") as vivo:
        clipe = add_clip(vivo, "v1", str(MEDIA / "clipe_a.mp4"), out_point=2)
    with store.edit(projeto["id"], "fades") as vivo:
        with pytest.raises(ProjectError, match="fades"):
            set_clip_properties(vivo, clipe["id"], fade_in=1.5, fade_out=1.5)


# ------------------------------------------------------------- marcadores


def test_marcador_e_regiao_guardam_rotulos(store):
    projeto = store.create("Notas")
    with store.edit(projeto["id"], "notas") as vivo:
        marcador = add_marker(vivo, 12.5, "capítulo")
        regiao = add_region(vivo, 0.0, 1.0, "abertura")
        assert marcador["label"] == "capítulo"
        assert regiao["label"] == "abertura"
        with pytest.raises(ProjectError, match="maior que o início"):
            add_region(vivo, 2.0, 1.0, "invertida")
    snapshot = store.view(projeto["id"])
    assert snapshot["markers"][0]["time"] == pytest.approx(12.5)
    with store.edit(projeto["id"], "remover") as vivo:
        remove_marker(vivo, marcador["id"])
        assert vivo["markers"] == []


# ------------------------------------------------------------- validação


@requires_media
def test_valid_detecta_arquivo_faltando(store):
    projeto = store.create("Quebrado")
    with store.edit(projeto["id"], "quebrar") as vivo:
        clipe = add_clip(vivo, "v1", str(MEDIA / "clipe_a.mp4"))
        clipe["source"] = str(MEDIA / "nao-existe.mp4")
        issues = validate_project(vivo)
    assert has_errors(issues)
    assert any(item["code"] == "missing_media" for item in issues)


def test_valid_detecta_posicao_negativa():
    projeto = new_project("Ruim")
    projeto["tracks"][0]["clips"].append({
        "id": "c_ruim", "type": "video", "source": None, "name": "x",
        "start": -1, "in": 0, "out": 2, "speed": 1, "volume": 1,
        "fade_in": 0, "fade_out": 0, "muted": False,
        "transition": {"type": "none", "duration": 0},
        "transform": {}, "color": {},
    })
    issues = validate_project(projeto, check_media=False)
    assert any(item["code"] == "clip_time" for item in issues)


def test_valid_detecta_sobreposicao_na_faixa():
    projeto = new_project("Colidindo")
    base = {
        "type": "text", "source": None, "name": "t", "in": 0, "speed": 1,
        "volume": 1, "fade_in": 0, "fade_out": 0, "muted": False,
        "transition": {"type": "none", "duration": 0},
    }
    trilha = projeto["tracks"][2]
    trilha["clips"].append({**base, "id": "c1", "start": 0, "out": 5, "text": {"content": "a"}})
    trilha["clips"].append({**base, "id": "c2", "start": 4, "out": 8, "text": {"content": "b"}})
    issues = validate_project(projeto, check_media=False)
    assert any(item["code"] == "overlap" for item in issues)


def test_valid_projeto_vazio_e_erro():
    issues = validate_project(new_project("Vazio"), check_media=False)
    assert any(item["code"] in {"empty_project", "zero_duration"} for item in issues)
    assert has_errors(issues)


# ------------------------------------- store: undo/redo/persistência/versões


@requires_media
def test_undo_redo_restaura_estado(store):
    projeto = store.create("Undo")
    pid = projeto["id"]
    with store.edit(pid, "adicionar") as vivo:
        clipe = add_clip(vivo, "v1", str(MEDIA / "clipe_a.mp4"))
    assert len(store.view(pid)["tracks"][0]["clips"]) == 1
    store.undo(pid)
    assert len(store.view(pid)["tracks"][0]["clips"]) == 0
    store.redo(pid)
    restaurado = store.view(pid)["tracks"][0]["clips"]
    assert len(restaurado) == 1
    assert restaurado[0]["id"] == clipe["id"]


@requires_media
def test_undo_nao_aparece_quando_edicao_falha(store):
    projeto = store.create("UndoFalho")
    pid = projeto["id"]
    with pytest.raises(ProjectError):
        with store.edit(pid, "inválida") as vivo:
            add_clip(vivo, "v1", str(MEDIA / "clipe_a.mp4"))
            raise ProjectError("estourou no meio")
    assert len(store.view(pid)["tracks"][0]["clips"]) == 0
    with pytest.raises(ProjectError, match="desfazer"):
        store.undo(pid)


@requires_media
def test_um_edit_contexto_e_um_passo_de_undo(store):
    projeto = store.create("Transacao")
    pid = projeto["id"]
    with store.edit(pid, "várias operações") as vivo:
        a = add_clip(vivo, "v1", str(MEDIA / "clipe_a.mp4"))
        split_clip(vivo, a["id"], 2.0)
    assert len(store.view(pid)["tracks"][0]["clips"]) == 2
    store.undo(pid)
    assert store.view(pid)["tracks"][0]["clips"] == []
    assert store.history(pid)["undo"] == []


@requires_media
def test_persistencia_sobrevive_a_releitura(tmp_path):
    raiz = tmp_path / "projetos"
    um = ProjectStore(root=raiz)
    projeto = um.create("Persistente")
    with um.edit(projeto["id"], "montar") as vivo:
        add_clip(vivo, "v1", str(MEDIA / "clipe_a.mp4"))
        add_marker(vivo, 1.0, "capítulo")
        add_region(vivo, 0.0, 1.0, "região")

    dois = ProjectStore(root=raiz)
    recuperado = dois.get(projeto["id"])
    assert recuperado["name"] == "Persistente"
    assert len(recuperado["tracks"][0]["clips"]) == 1
    assert recuperado["markers"][0]["label"] == "capítulo"
    assert recuperado["regions"][0]["label"] == "região"
    # undo é por sessão: não sobrevive à reabertura
    with pytest.raises(ProjectError, match="desfazer"):
        dois.undo(projeto["id"])


@requires_media
def test_versoes_permitem_restaurar(store):
    projeto = store.create("Versoes")
    pid = projeto["id"]
    with store.edit(pid, "adicionar") as vivo:
        clipe = add_clip(vivo, "v1", str(MEDIA / "clipe_a.mp4"))
    depois_de_adicionar = [v["name"] for v in store.versions(pid)]
    assert depois_de_adicionar, "cada salva gera um snapshot"
    with store.edit(pid, "mover") as vivo:
        move_clip(vivo, clipe["id"], 4.0)
    assert store.view(pid)["tracks"][0]["clips"][0]["start"] == pytest.approx(4.0)

    store.restore_version(pid, depois_de_adicionar[0])
    assert store.view(pid)["tracks"][0]["clips"][0]["start"] == pytest.approx(0.0)
    # restaurar também é desfazível
    store.undo(pid)
    assert store.view(pid)["tracks"][0]["clips"][0]["start"] == pytest.approx(4.0)


@requires_media
def test_restaurar_rejeita_versao_de_outro_projeto(store):
    a = store.create("A")
    b = store.create("B")
    nome = store.versions(a["id"])[0]["name"]
    # mesmo nome de arquivo em outro projeto não pode trocar o conteúdo
    destino = store.root / b["id"] / "versions" / nome
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(store.root / a["id"] / "versions" / nome, destino)
    with pytest.raises(ProjectError, match="não pertence"):
        store.restore_version(b["id"], nome)
    with pytest.raises(ProjectError, match="Nome de versão inválido"):
        store.restore_version(a["id"], "../project.json")


@requires_media
def test_apply_operation_usa_o_motor(store):
    projeto = store.create("Operacoes")
    pid = projeto["id"]
    resultado = store.apply(pid, "add_text", {"text": "Olá", "duration": 2})
    assert resultado["tracks"][2]["clips"][0]["text"]["content"] == "Olá"
    store.undo(pid)
    assert store.view(pid)["tracks"][2]["clips"] == []
    with pytest.raises(ProjectError, match="desconhecida"):
        store.apply(pid, "explode")
    with pytest.raises(ProjectError, match="Parâmetros inválidos"):
        store.apply(pid, "add_text", {"texto_errado": 1})


def test_exclusao_de_projeto_exige_confirmacao(store):
    projeto = store.create("Descartar")
    with pytest.raises(ProjectError, match="confirmação"):
        store.delete(projeto["id"])
    store.delete(projeto["id"], confirm=True)
    assert projeto["id"] not in [p["id"] for p in store.list_projects()]


@pytest.mark.parametrize("pid", ["", "../etc", "p_ZZZZZZZZZZ", "p_abc"])
def test_id_invalido_nao_toca_no_disco(store, pid):
    with pytest.raises(ProjectError):
        store.get(pid)
