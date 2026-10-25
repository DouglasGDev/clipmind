"""
Motor de projeto não destrutivo do ClipMind.

Um projeto é um arquivo JSON com faixas, clipes e ajustes. Nenhuma operação
altera o arquivo original: a timeline guarda apenas referências, pontos de
entrada/saída e parâmetros. O renderizador (editor_render.py) lê este mesmo
modelo para compor o vídeo final.

Operações destrutivas de arquivo (apagar projeto) exigem confirmação explícita;
as operações da timeline são reversíveis por undo/redo e por versões salvas.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PROJECTS_DIR = Path(os.getenv("CLIPMIND_PROJECTS", "./projects"))
PROJECT_SCHEMA = 1
MAX_UNDO = 100
MAX_VERSIONS = 30

TRACK_TYPES = {"video", "audio", "text", "subtitle"}
POSITIONS = {
    "topo": ("(w-text_w)/2", "h*0.08"),
    "centro": ("(w-text_w)/2", "(h-text_h)/2"),
    "inferior": ("(w-text_w)/2", "h-text_h-h*0.08"),
    "inferior-esquerda": ("w*0.05", "h-text_h-h*0.10"),
    "inferior-direita": ("w-text_w-w*0.05", "h-text_h-h*0.10"),
}

_FPS_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")


class ProjectError(ValueError):
    """Erro de validação da timeline com mensagem em português."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _round(value: float) -> float:
    return round(float(value), 3)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", text).strip("-")[:48] or "versao"


# ---------------------------------------------------------------------------
# Tempo
# ---------------------------------------------------------------------------

def parse_timecode(value: Any, field: str = "tempo") -> float:
    """
    Converte segundos ou HH:MM:SS[.mmm] em segundos.

    Aceita também MM:SS. Valores negativos e texto inválido são rejeitados.
    """
    if isinstance(value, bool):
        raise ProjectError(f"{field} inválido: {value!r}")
    if isinstance(value, (int, float)):
        segundos = float(value)
    else:
        texto = str(value).strip().replace(",", ".")
        if not texto:
            raise ProjectError(f"{field} vazio")
        partes = texto.split(":")
        if len(partes) > 3:
            raise ProjectError(f"{field} inválido: {value}")
        try:
            segundos = 0.0
            for parte in partes:
                segundos = segundos * 60 + float(parte)
        except ValueError:
            raise ProjectError(f"{field} inválido: {value}") from None
    if segundos < 0:
        raise ProjectError(f"{field} não pode ser negativo")
    return _round(segundos)


def format_timecode(seconds: float, precise: bool = False) -> str:
    """Formata segundos como HH:MM:SS (ou HH:MM:SS.mmm)."""
    segundos = max(0.0, float(seconds))
    horas = int(segundos // 3600)
    minutos = int((segundos % 3600) // 60)
    resto = segundos % 60
    if precise:
        return f"{horas:02d}:{minutos:02d}:{resto:06.3f}"
    return f"{horas:02d}:{minutos:02d}:{int(resto):02d}"


def parse_fps(value: Any) -> float:
    """Aceita 30, 29.97 ou a fração 30000/1001 devolvida pelo ffprobe."""
    if isinstance(value, (int, float)):
        fps = float(value)
    else:
        texto = str(value or "").strip()
        match = _FPS_RE.match(texto)
        if match:
            num, den = float(match.group(1)), float(match.group(2))
            fps = num / den if den else 0.0
        else:
            try:
                fps = float(texto)
            except ValueError:
                raise ProjectError(f"FPS inválido: {value}") from None
    if not 1 <= fps <= 240:
        raise ProjectError("FPS deve estar entre 1 e 240")
    return round(fps, 3)


# ---------------------------------------------------------------------------
# Mídia
# ---------------------------------------------------------------------------

def probe_media(path: str | Path) -> dict:
    """
    Lê metadados reais do arquivo com ffprobe.

    Devolve duração, resolução, fps e presença de vídeo/áudio. Levanta
    ProjectError quando o arquivo não existe ou não é uma mídia válida.
    """
    arquivo = Path(path).expanduser()
    if not arquivo.is_file():
        raise ProjectError(f"Arquivo não encontrado: {path}")
    try:
        saida = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", str(arquivo.resolve()),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        ).stdout
        dados = json.loads(saida or "{}")
    except FileNotFoundError:
        raise ProjectError("ffprobe não encontrado. Instale o FFmpeg e adicione ao PATH.") from None
    except subprocess.TimeoutExpired:
        raise ProjectError(f"ffprobe demorou demais para ler {arquivo.name}") from None
    except subprocess.CalledProcessError as e:
        raise ProjectError(f"Arquivo de mídia inválido: {arquivo.name}: {(e.stderr or '')[-300:]}") from None

    info = {
        "path": str(arquivo.resolve()),
        "name": arquivo.name,
        "size": int(dados.get("format", {}).get("size", 0) or 0),
        "duration": 0.0,
        "has_video": False,
        "has_audio": False,
        "width": 0,
        "height": 0,
        "fps": 0.0,
        "video_codec": "",
        "audio_codec": "",
    }
    try:
        info["duration"] = round(float(dados.get("format", {}).get("duration", 0) or 0), 3)
    except (TypeError, ValueError):
        info["duration"] = 0.0

    for stream in dados.get("streams", []):
        if stream.get("disposition", {}).get("attached_pic") == 1:
            continue
        if stream.get("codec_type") == "video" and not info["has_video"]:
            info["has_video"] = True
            info["width"] = int(stream.get("width", 0) or 0)
            info["height"] = int(stream.get("height", 0) or 0)
            info["video_codec"] = str(stream.get("codec_name", ""))
            try:
                info["fps"] = parse_fps(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or 0)
            except ProjectError:
                info["fps"] = 0.0
            if not info["duration"]:
                try:
                    info["duration"] = round(float(stream.get("duration", 0) or 0), 3)
                except (TypeError, ValueError):
                    pass
        elif stream.get("codec_type") == "audio" and not info["has_audio"]:
            info["has_audio"] = True
            info["audio_codec"] = str(stream.get("codec_name", ""))
    return info


def is_supported_media(path: str | Path, kind: str) -> bool:
    """Aceita vídeo/áudio para as faixas correspondentes."""
    try:
        info = probe_media(path)
    except ProjectError:
        return False
    if kind == "video":
        return info["has_video"]
    if kind == "audio":
        return info["has_audio"]
    return False


# ---------------------------------------------------------------------------
# Criação
# ---------------------------------------------------------------------------

def new_track(track_id: str, tipo: str, name: str) -> dict:
    return {
        "id": track_id,
        "type": tipo,
        "name": name,
        "clips": [],
        "muted": False,
        "hidden": False,
        "locked": False,
    }


def new_project(
    name: str,
    width: int = 1920,
    height: int = 1080,
    fps: float = 30,
    project_id: Optional[str] = None,
) -> dict:
    """Cria um projeto vazio com faixas de vídeo, título, legenda e áudio."""
    nome = (name or "").strip()
    if not nome:
        raise ProjectError("Informe um nome para o projeto")
    if len(nome) > 120:
        raise ProjectError("O nome do projeto deve ter até 120 caracteres")
    if width < 16 or height < 16 or width > 7680 or height > 4320:
        raise ProjectError("Resolução inválida (use entre 16x16 e 7680x4320)")
    if width % 2 or height % 2:
        raise ProjectError("Largura e altura precisam ser pares para o H.264")
    agora = _now()
    return {
        "schema": PROJECT_SCHEMA,
        "id": project_id or _uid("p"),
        "name": nome,
        "created_at": agora,
        "updated_at": agora,
        "settings": {
            "width": int(width),
            "height": int(height),
            "fps": parse_fps(fps),
            "audio_rate": 48000,
        },
        "media": {},
        "tracks": [
            new_track("v1", "video", "Vídeo 1"),
            new_track("v2", "video", "Sobreposição"),
            new_track("t1", "text", "Títulos"),
            new_track("s1", "subtitle", "Legendas"),
            new_track("a1", "audio", "Áudio 1"),
        ],
        "markers": [],
        "regions": [],
        "recent_operations": [],
    }


def _add_media(project: dict, source: str | Path) -> dict:
    info = probe_media(source)
    project.setdefault("media", {})[info["path"]] = info
    return info


def _media_for(project: dict, source: str | Path) -> dict:
    caminho = str(Path(source).expanduser().resolve())
    info = project.get("media", {}).get(caminho)
    if not info:
        info = probe_media(caminho)
        project.setdefault("media", {})[caminho] = info
    return info


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------

def get_track(project: dict, track_id: str) -> dict:
    for track in project.get("tracks", []):
        if track["id"] == track_id or track["name"] == track_id:
            return track
    raise ProjectError(f"Faixa não encontrada: {track_id}")


def get_clip(project: dict, clip_id: str) -> tuple[dict, dict]:
    for track in project.get("tracks", []):
        for clip in track.get("clips", []):
            if clip["id"] == clip_id:
                return track, clip
    raise ProjectError(f"Clipe não encontrado: {clip_id}")


def clip_duration(clip: dict) -> float:
    """Duração ocupada na timeline, já considerando a velocidade."""
    if clip.get("type") in {"text", "subtitle"}:
        return _round(max(0.0, float(clip.get("out", 0)) - float(clip.get("in", 0))))
    speed = max(0.01, float(clip.get("speed", 1) or 1))
    return _round(max(0.0, (float(clip.get("out", 0)) - float(clip.get("in", 0))) / speed))


def clip_end(clip: dict) -> float:
    return _round(float(clip.get("start", 0)) + clip_duration(clip))


def project_duration(project: dict) -> float:
    fim = 0.0
    for track in project.get("tracks", []):
        for clip in track.get("clips", []):
            fim = max(fim, clip_end(clip))
    return _round(fim)


def timeline_end(track: dict) -> float:
    return _round(max([clip_end(c) for c in track.get("clips", [])] or [0.0]))


def _sorted_clips(track: dict) -> list[dict]:
    track["clips"].sort(key=lambda c: (float(c.get("start", 0)), c.get("id", "")))
    return track["clips"]


def _check_collision(track: dict, start: float, duration: float, ignore_id: Optional[str] = None) -> None:
    end = start + duration
    for outro in track.get("clips", []):
        if outro["id"] == ignore_id:
            continue
        outro_start = float(outro.get("start", 0))
        outro_end = clip_end(outro)
        if start < outro_end - 1e-4 and end > outro_start + 1e-4:
            raise ProjectError(
                f"O clipe colidiria com '{outro.get('name', outro['id'])}' "
                f"({format_timecode(outro_start)}–{format_timecode(outro_end)}) na faixa {track['name']}. "
                "Mova, corte ou use uma faixa livre."
            )


def _shift_following(track: dict, after: float, delta: float, ignore_id: Optional[str] = None) -> None:
    for clip in track.get("clips", []):
        if clip["id"] == ignore_id:
            continue
        if float(clip.get("start", 0)) >= after - 1e-4:
            clip["start"] = _round(max(0.0, float(clip["start"]) + delta))
    _sorted_clips(track)


def _base_clip(tipo: str, source: Optional[str], name: str, start: float, in_point: float, out_point: float) -> dict:
    return {
        "id": _uid("c"),
        "type": tipo,
        "source": source,
        "name": name,
        "start": _round(max(0.0, start)),
        "in": _round(max(0.0, in_point)),
        "out": _round(max(0.0, out_point)),
        "speed": 1.0,
        "volume": 1.0,
        "fade_in": 0.0,
        "fade_out": 0.0,
        "transform": {"x": 0, "y": 0, "scale": 1.0, "rotation": 0, "opacity": 1.0},
        "color": {"brightness": 0.0, "contrast": 1.0, "saturation": 1.0, "gamma": 1.0},
        "transition": {"type": "none", "duration": 0.0},
        "text": None,
        "subtitle": None,
    }


def _valida_volume(valor: Any) -> float:
    """
    Confina o volume à faixa que as ferramentas declaram (0 a 4).

    Passar disso não é ganho de loudness: estoura o headroom e o render volta
    clipado. O valor também precisa ser o mesmo nas duas portas — aceitar 9 na
    entrada e cortar em 4 no set faria a timeline mentir sobre o próprio áudio.
    """
    try:
        volume = float(valor)
    except (TypeError, ValueError):
        raise ProjectError(f"Volume inválido: {valor!r}") from None
    if not 0.0 <= volume <= 4.0:
        raise ProjectError("O volume deve estar entre 0 e 4")
    return volume


def add_clip(
    project: dict,
    track_id: str,
    source: str,
    start: Optional[float] = None,
    in_point: float = 0.0,
    out_point: Optional[float] = None,
    speed: float = 1.0,
    volume: float = 1.0,
    ripple: bool = False,
) -> dict:
    """Adiciona um clipe de mídia à timeline sem copiar o arquivo original."""
    track = get_track(project, track_id)
    if track["type"] not in {"video", "audio"}:
        raise ProjectError(f"A faixa '{track['name']}' não aceita clipes de mídia")
    info = _add_media(project, source)
    if track["type"] == "video" and not info["has_video"]:
        raise ProjectError(f"'{info['name']}' não tem stream de vídeo")
    if track["type"] == "audio" and not info["has_audio"]:
        raise ProjectError(f"'{info['name']}' não tem stream de áudio")

    ini = _round(parse_timecode(in_point, "entrada"))
    fim = _round(parse_timecode(out_point, "saída")) if out_point not in (None, "") else _round(info["duration"])
    if info["duration"] > 0 and fim > info["duration"] + 0.05:
        raise ProjectError(
            f"Saída {format_timecode(fim)} maior que a duração de {info['name']} "
            f"({format_timecode(info['duration'])})"
        )
    if fim <= ini:
        raise ProjectError("A saída precisa ser maior que a entrada")
    if not 0.1 <= float(speed) <= 8:
        raise ProjectError("A velocidade deve estar entre 0.1 e 8")

    inicio = _round(timeline_end(track) if start in (None, "") else parse_timecode(start, "início"))
    duracao = _round((fim - ini) / float(speed))
    if duracao < 0.05:
        raise ProjectError("O clipe ficaria curto demais")
    if ripple:
        _shift_following(track, inicio, duracao)
    _check_collision(track, inicio, duracao)

    clip = _base_clip(track["type"], info["path"], info["name"], inicio, ini, fim)
    clip["speed"] = float(speed)
    clip["volume"] = _valida_volume(volume)
    track["clips"].append(clip)
    _sorted_clips(track)
    _touch(project, f"Adicionar {info['name']} em {track['name']}")
    return clip


def add_text_clip(
    project: dict,
    track_id: str = "t1",
    text: str = "",
    start: float = 0,
    duration: float = 3,
    font_size: int = 56,
    color: str = "white",
    position: str = "inferior",
    background: bool = True,
) -> dict:
    """Cria um título editável; o texto é renderizado pelo FFmpeg na exportação."""
    track = get_track(project, track_id)
    if track["type"] != "text":
        raise ProjectError(f"A faixa '{track['name']}' não é uma faixa de títulos")
    conteudo = (text or "").strip()
    if not conteudo:
        raise ProjectError("Informe o texto do título")
    if len(conteudo) > 2000:
        raise ProjectError("O título deve ter até 2000 caracteres")
    if position not in POSITIONS and position != "personalizado":
        raise ProjectError("Posição inválida para o título")
    inicio = _round(parse_timecode(start, "início"))
    dur = max(0.2, _round(parse_timecode(duration, "duração")))
    _check_collision(track, inicio, dur)

    clip = _base_clip("text", None, conteudo[:48], inicio, 0, dur)
    clip["text"] = {
        "content": conteudo,
        "font_size": max(8, min(300, int(font_size))),
        "color": normalize_color(color or "white", "cor do título"),
        "position": position,
        "background": bool(background),
        "x": None,
        "y": None,
    }
    track["clips"].append(clip)
    _sorted_clips(track)
    _touch(project, f"Adicionar título em {track['name']}")
    return clip


_CORES: dict[str, str] = {
    "white": "#FFFFFF", "branco": "#FFFFFF",
    "black": "#000000", "preto": "#000000",
    "red": "#FF0000", "vermelho": "#FF0000",
    "green": "#00FF00", "verde": "#00FF00",
    "blue": "#0000FF", "azul": "#0000FF",
    "yellow": "#FFFF00", "amarelo": "#FFFF00",
    "cyan": "#00FFFF", "ciano": "#00FFFF",
    "magenta": "#FF00FF",
    "orange": "#FFA500", "laranja": "#FFA500",
    "pink": "#FFC0CB", "rosa": "#FFC0CB",
    "gold": "#FFD700", "dourado": "#FFD700",
    "gray": "#BFBFBF", "grey": "#BFBFBF", "cinza": "#BFBFBF",
    "purple": "#A020F0", "roxo": "#A020F0",
    "lime": "#BFFF00", "lima": "#BFFF00",
}

# Só os nomes em português na mensagem: a lista inteira, EN e PT misturadas em
# ordem alfabética, virava um texto ilegível de 30 itens.
_CORES_NOMES_PT = "branco, preto, vermelho, verde, azul, amarelo, ciano, magenta, laranja, rosa, dourado, cinza, roxo, lima"


def normalize_color(valor: Any, campo: str = "cor") -> str:
    """
    Canoniciza uma cor para #RRGGBB.

    Título e legenda usam o mesmo valor, mas só o formato hexadecimal chega
    igual aos dois filtros; nome solto faria o drawtext renderizar e a legenda
    cair em branco silenciosamente.
    """
    texto = str(valor if valor is not None else "").strip().lower()
    if re.fullmatch(r"#[0-9a-f]{6}", texto):
        return texto.upper()
    if re.fullmatch(r"0x[0-9a-f]{6}", texto):
        return ("#" + texto[2:]).upper()
    if texto in _CORES:
        return _CORES[texto]
    raise ProjectError(
        f"{campo} inválida: {valor!r}. Use #RRGGBB ou um nome conhecido "
        f"({_CORES_NOMES_PT})."
    )


def srt_duration(path: str | Path) -> float:
    """Duração do último subtítulo de um .srt (também aceita .vtt)."""
    arquivo = Path(path).expanduser()
    if not arquivo.is_file():
        raise ProjectError(f"Legenda não encontrada: {path}")
    if arquivo.suffix.lower() not in {".srt", ".vtt", ".ass"}:
        raise ProjectError("A legenda deve ser .srt, .vtt ou .ass")
    if arquivo.suffix.lower() == ".ass":
        return 0.0
    texto = arquivo.read_text(encoding="utf-8", errors="replace")
    padrao = re.compile(
        r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})"
    )
    fim = 0.0
    for m in padrao.finditer(texto):
        segundos = int(m.group(5)) * 3600 + int(m.group(6)) * 60 + int(m.group(7)) + int(m.group(8)) / 1000
        fim = max(fim, segundos)
    return _round(fim)


def add_subtitle_clip(
    project: dict,
    track_id: str = "s1",
    subtitle_path: str = "",
    start: float = 0,
    font_size: int = 22,
    color: str = "white",
    margin_v: int = 42,
    position: str = "inferior",
) -> dict:
    """Adiciona um arquivo de legendas a uma faixa, com estilo configurável."""
    track = get_track(project, track_id)
    if track["type"] != "subtitle":
        raise ProjectError(f"A faixa '{track['name']}' não é uma faixa de legendas")
    arquivo = Path(subtitle_path).expanduser()
    if not arquivo.is_file():
        raise ProjectError(f"Legenda não encontrada: {subtitle_path}")
    if arquivo.suffix.lower() not in {".srt", ".vtt", ".ass"}:
        raise ProjectError("A legenda deve ser .srt, .vtt ou .ass")
    dur = srt_duration(arquivo) or max(1.0, project_duration(project))
    inicio = _round(parse_timecode(start, "início"))
    if position not in {"inferior", "topo", "centro"}:
        raise ProjectError("Posição de legenda inválida")
    _check_collision(track, inicio, dur)

    clip = _base_clip("subtitle", str(arquivo.resolve()), arquivo.name, inicio, 0, dur)
    clip["subtitle"] = {
        "font_size": max(8, min(120, int(font_size))),
        "color": normalize_color(color or "white", "cor da legenda"),
        "margin_v": max(0, min(400, int(margin_v))),
        "position": position,
    }
    track["clips"].append(clip)
    _sorted_clips(track)
    _touch(project, f"Adicionar legendas em {track['name']}")
    return clip


def move_clip(project: dict, clip_id: str, start: float) -> dict:
    """Move um clipe no tempo sem alterar seu conteúdo."""
    track, clip = get_clip(project, clip_id)
    novo = _round(parse_timecode(start, "início"))
    _check_collision(track, novo, clip_duration(clip), ignore_id=clip_id)
    clip["start"] = novo
    _sorted_clips(track)
    _touch(project, f"Mover {clip.get('name', clip_id)}")
    return clip


def trim_clip(
    project: dict,
    clip_id: str,
    in_point: Optional[float] = None,
    out_point: Optional[float] = None,
    duration: Optional[float] = None,
    ripple: bool = False,
    shift_start: bool = False,
) -> dict:
    """
    Ajusta as bordas de um clipe.

    Em clipes de mídia, in_point/out_point operam no tempo do arquivo original.
    Em títulos e legendas, use duration. ripple desloca os clipes posteriores
    para manter a sequência sem buraco.
    """
    track, clip = get_clip(project, clip_id)
    antigo_start = float(clip["start"])
    antiga_dur = clip_duration(clip)

    if clip["type"] in {"text", "subtitle"}:
        if duration is not None:
            nova_dur = max(0.2, _round(parse_timecode(duration, "duração")))
        elif out_point is not None:
            nova_dur = max(0.2, _round(parse_timecode(out_point, "duração")))
        else:
            raise ProjectError("Informe a duração do clipe")
        delta = _round(nova_dur - antiga_dur)
        if ripple and abs(delta) > 1e-6:
            _shift_following(track, antigo_start + antiga_dur, delta, ignore_id=clip_id)
        _check_collision(track, antigo_start, nova_dur, ignore_id=clip_id)
        clip["out"] = _round(nova_dur)
        clip["in"] = 0
    else:
        info = _media_for(project, clip["source"])
        novo_in = _round(parse_timecode(in_point, "entrada")) if in_point is not None else float(clip["in"])
        novo_out = _round(parse_timecode(out_point, "saída")) if out_point is not None else float(clip["out"])
        if info["duration"] > 0 and novo_out > info["duration"] + 0.05:
            raise ProjectError("A saída passaria do fim do arquivo original")
        if novo_out <= novo_in:
            raise ProjectError("A saída precisa ser maior que a entrada")
        speed = max(0.01, float(clip.get("speed", 1)))
        nova_dur = _round((novo_out - novo_in) / speed)
        if nova_dur < 0.05:
            raise ProjectError("O clipe ficaria curto demais")
        novo_start = antigo_start
        if shift_start:
            novo_start = max(0.0, _round(antigo_start + (novo_in - float(clip["in"])) / speed))
            if novo_start <= 0 and novo_in > 0:
                novo_in = _round(float(clip["in"]) + (0.0 - antigo_start) * speed)
        delta = _round(nova_dur - antiga_dur)
        if ripple and abs(delta) > 1e-6:
            _shift_following(track, clip_end(clip), delta, ignore_id=clip_id)
        _check_collision(track, novo_start, nova_dur, ignore_id=clip_id)
        clip["in"], clip["out"] = novo_in, novo_out
        clip["start"] = novo_start

    _sorted_clips(track)
    _touch(project, f"Ajustar {clip.get('name', clip_id)}")
    return clip


def split_clip(project: dict, clip_id: str, at: float) -> tuple[dict, dict]:
    """Divide um clipe no tempo indicado, mantendo os dois lados editáveis."""
    track, clip = get_clip(project, clip_id)
    if clip["type"] not in {"video", "audio"}:
        raise ProjectError("Só é possível dividir clipes de mídia")
    ponto = _round(parse_timecode(at, "ponto de divisão"))
    inicio, fim = float(clip["start"]), clip_end(clip)
    if not (inicio + 0.05 < ponto < fim - 0.05):
        raise ProjectError(
            f"O ponto de divisão precisa ficar entre {format_timecode(inicio)} e "
            f"{format_timecode(fim)}"
        )
    speed = max(0.01, float(clip.get("speed", 1)))
    origem = _round(float(clip["in"]) + (ponto - inicio) * speed)

    segundo = copy.deepcopy(clip)
    segundo["id"] = _uid("c")
    segundo["start"] = ponto
    segundo["in"] = origem
    clip["out"] = origem

    track["clips"].append(segundo)
    _sorted_clips(track)
    _touch(project, f"Dividir {clip.get('name', clip_id)}")
    return clip, segundo


def delete_clip(project: dict, clip_id: str, ripple: bool = False) -> dict:
    """Remove um clipe. ripple fecha o buraco deixado na faixa."""
    track, clip = get_clip(project, clip_id)
    duracao = clip_duration(clip)
    track["clips"].remove(clip)
    if ripple:
        _shift_following(track, float(clip["start"]), -duracao)
    _touch(project, f"Excluir {clip.get('name', clip_id)}")
    return clip


def duplicate_clip(project: dict, clip_id: str, ripple: bool = True) -> dict:
    """Duplica o clipe logo após ele, empurrando o restante quando necessário."""
    track, clip = get_clip(project, clip_id)
    novo = copy.deepcopy(clip)
    novo["id"] = _uid("c")
    duracao = clip_duration(clip)
    novo["start"] = clip_end(clip)
    if ripple:
        _shift_following(track, float(novo["start"]), duracao)
    _check_collision(track, float(novo["start"]), duracao)
    track["clips"].append(novo)
    _sorted_clips(track)
    _touch(project, f"Duplicar {clip.get('name', clip_id)}")
    return novo


def slip_clip(project: dict, clip_id: str, delta: float) -> dict:
    """Slip: troca o trecho do arquivo sem mover o clipe na timeline."""
    _, clip = get_clip(project, clip_id)
    if clip["type"] not in {"video", "audio"}:
        raise ProjectError("Slip só se aplica a clipes de mídia")
    info = _media_for(project, clip["source"])
    deslocamento = float(delta)
    novo_in = _round(float(clip["in"]) + deslocamento)
    novo_out = _round(float(clip["out"]) + deslocamento)
    if novo_in < 0:
        raise ProjectError("O slip passaria do início do arquivo")
    if info["duration"] > 0 and novo_out > info["duration"] + 0.05:
        raise ProjectError("O slip passaria do fim do arquivo")
    clip["in"], clip["out"] = novo_in, novo_out
    _touch(project, f"Slip em {clip.get('name', clip_id)}")
    return clip


def slide_clip(project: dict, clip_id: str, delta: float) -> dict:
    """Slide: move o clipe ajustando os vizinhos imediatos."""
    track, clip = get_clip(project, clip_id)
    if clip["type"] not in {"video", "audio"}:
        raise ProjectError("Slide só se aplica a clipes de mídia")
    deslocamento = float(delta)
    clips = _sorted_clips(track)
    posicao = clips.index(clip)
    if posicao == 0 or posicao == len(clips) - 1:
        raise ProjectError("Slide exige um clipe antes e outro depois, encostados")
    anterior, proximo = clips[posicao - 1], clips[posicao + 1]
    if abs(clip_end(anterior) - float(clip["start"])) > 1e-3 or abs(clip_end(clip) - float(proximo["start"])) > 1e-3:
        raise ProjectError("Slide exige clipes encostados (sem espaços) dos dois lados")

    info_ant = _media_for(project, anterior["source"])
    info_prox = _media_for(project, proximo["source"])
    speed_ant = max(0.01, float(anterior.get("speed", 1)))
    speed_prox = max(0.01, float(proximo.get("speed", 1)))
    novo_out_ant = _round(float(anterior["out"]) + deslocamento * speed_ant)
    novo_in_prox = _round(float(proximo["in"]) + deslocamento * speed_prox)
    novo_out_prox = _round(float(proximo["out"]) + deslocamento * speed_prox)
    if novo_out_ant <= float(anterior["in"]) or (info_ant["duration"] and novo_out_ant > info_ant["duration"] + 0.05):
        raise ProjectError("O slide passaria dos limites do clipe anterior")
    if novo_in_prox < 0 or (info_prox["duration"] and novo_out_prox > info_prox["duration"] + 0.05):
        raise ProjectError("O slide passaria dos limites do próximo clipe")
    if deslocamento < 0 and float(clip["start"]) + deslocamento < 0:
        raise ProjectError("O slide deixaria o clipe antes do início da timeline")

    anterior["out"] = novo_out_ant
    clip["start"] = _round(float(clip["start"]) + deslocamento)
    proximo["start"] = _round(float(proximo["start"]) + deslocamento)
    proximo["in"], proximo["out"] = novo_in_prox, novo_out_prox
    _sorted_clips(track)
    _touch(project, f"Slide em {clip.get('name', clip_id)}")
    return clip


def roll_edit(project: dict, clip_id: str, delta: float) -> dict:
    """Roll: move a fronteira entre este clipe e o próximo, sem buraco."""
    track, clip = get_clip(project, clip_id)
    if clip["type"] not in {"video", "audio"}:
        raise ProjectError("Roll só se aplica a clipes de mídia")
    clips = _sorted_clips(track)
    posicao = clips.index(clip)
    if posicao == len(clips) - 1:
        raise ProjectError("Roll exige um clipe seguinte encostado")
    proximo = clips[posicao + 1]
    if abs(clip_end(clip) - float(proximo["start"])) > 1e-3:
        raise ProjectError("Roll exige clipes encostados (sem espaço entre eles)")

    info_ant = _media_for(project, clip["source"])
    info_prox = _media_for(project, proximo["source"])
    speed_ant = max(0.01, float(clip.get("speed", 1)))
    speed_prox = max(0.01, float(proximo.get("speed", 1)))
    novo_out = _round(float(clip["out"]) + delta * speed_ant)
    novo_in = _round(float(proximo["in"]) + delta * speed_prox)
    if novo_out <= float(clip["in"]) + 0.05:
        raise ProjectError("O roll deixaria o primeiro clipe curto demais")
    if (info_ant["duration"] and novo_out > info_ant["duration"] + 0.05) or novo_in < 0:
        raise ProjectError("O roll passaria dos limites do arquivo original")
    if novo_in >= float(proximo["out"]) - 0.05:
        raise ProjectError("O roll deixaria o segundo clipe curto demais")

    clip["out"] = novo_out
    proximo["start"] = _round(float(proximo["start"]) + delta)
    proximo["in"] = novo_in
    _sorted_clips(track)
    _touch(project, "Roll entre clipes")
    return clip


_ALLOWED_TRANSFORMS = {
    "x": (-20000, 20000),
    "y": (-20000, 20000),
    "scale": (0.05, 8),
    "rotation": (-3600, 3600),
    "opacity": (0, 1),
}
_ALLOWED_COLORS = {
    "brightness": (-1, 1),
    "contrast": (0, 4),
    "saturation": (0, 4),
    "gamma": (0.1, 10),
}


def set_clip_properties(project: dict, clip_id: str, ripple: bool = False, **props: Any) -> dict:
    """
    Altera propriedades de um clipe com validação por campo.

    Aceita volume, fade_in, fade_out, speed, transform*, color*, text*,
    transition* e muted. Campos desconhecidos são rejeitados para a IA não
    alterar o projeto por engano.
    """
    track, clip = get_clip(project, clip_id)
    if not props:
        raise ProjectError("Nenhuma propriedade informada")
    alterados: list[str] = []

    for chave, valor in props.items():
        if valor is None:
            continue
        if chave == "volume":
            clip["volume"] = _valida_volume(valor)
        elif chave in {"fade_in", "fade_out"}:
            clip[chave] = max(0.0, _round(parse_timecode(valor, chave)))
            if clip["fade_in"] + clip["fade_out"] > clip_duration(clip) + 1e-6:
                raise ProjectError("A soma dos fades não pode passar da duração do clipe")
        elif chave == "speed":
            if clip["type"] not in {"video", "audio"}:
                raise ProjectError("Velocidade só se aplica a clipes de mídia")
            nova = float(valor)
            if not 0.1 <= nova <= 8:
                raise ProjectError("A velocidade deve estar entre 0.1 e 8")
            nova_dur = _round((float(clip["out"]) - float(clip["in"])) / nova)
            if nova_dur < 0.05:
                raise ProjectError("Velocidade deixaria o clipe curto demais")
            delta = _round(nova_dur - clip_duration(clip))
            if ripple and abs(delta) > 1e-6:
                _shift_following(track, clip_end(clip), delta, ignore_id=clip_id)
            clip["speed"] = nova
            _check_collision(track, float(clip["start"]), clip_duration(clip), ignore_id=clip_id)
        elif chave == "muted":
            clip["muted"] = bool(valor)
        elif chave.startswith("transform_"):
            campo = chave.split("_", 1)[1]
            if campo not in _ALLOWED_TRANSFORMS:
                raise ProjectError(f"Transformação desconhecida: {campo}")
            minimo, maximo = _ALLOWED_TRANSFORMS[campo]
            clip.setdefault("transform", {})[campo] = max(minimo, min(maximo, float(valor)))
        elif chave.startswith("color_"):
            campo = chave.split("_", 1)[1]
            if campo not in _ALLOWED_COLORS:
                raise ProjectError(f"Ajuste de cor desconhecido: {campo}")
            minimo, maximo = _ALLOWED_COLORS[campo]
            clip.setdefault("color", {})[campo] = max(minimo, min(maximo, float(valor)))
        elif chave == "text":
            if clip["type"] != "text":
                raise ProjectError("Só clipes de título têm texto")
            conteudo = str(valor).strip()
            if not conteudo:
                raise ProjectError("O título não pode ficar vazio")
            clip["text"]["content"] = conteudo[:2000]
            clip["name"] = conteudo[:48]
        elif chave == "font_size":
            if clip["type"] != "text":
                raise ProjectError("font_size só se aplica a títulos")
            clip.setdefault("text", {})["font_size"] = max(8, min(300, int(float(valor))))
        elif chave == "text_color":
            if clip["type"] != "text":
                raise ProjectError("text_color só se aplica a títulos")
            clip.setdefault("text", {})["color"] = normalize_color(valor, "cor do título")
        elif chave == "position":
            if clip["type"] != "text" or str(valor) not in POSITIONS:
                raise ProjectError("Posição inválida")
            clip["text"]["position"] = str(valor)
        elif chave == "background":
            if clip["type"] != "text":
                raise ProjectError("background só se aplica a títulos")
            clip.setdefault("text", {})["background"] = bool(valor)
        elif chave == "subtitle_font_size":
            if clip["type"] != "subtitle":
                raise ProjectError("subtitle_font_size só se aplica a legendas")
            clip.setdefault("subtitle", {})["font_size"] = max(8, min(120, int(float(valor))))
        elif chave == "subtitle_color":
            if clip["type"] != "subtitle":
                raise ProjectError("subtitle_color só se aplica a legendas")
            clip.setdefault("subtitle", {})["color"] = normalize_color(valor, "cor da legenda")
        elif chave == "subtitle_margin_v":
            if clip["type"] != "subtitle":
                raise ProjectError("subtitle_margin_v só se aplica a legendas")
            clip.setdefault("subtitle", {})["margin_v"] = max(0, min(400, int(float(valor))))
        elif chave == "subtitle_position":
            if clip["type"] != "subtitle":
                raise ProjectError("subtitle_position só se aplica a legendas")
            if str(valor) not in {"inferior", "centro", "topo"}:
                raise ProjectError("Posição de legenda inválida (inferior, centro ou topo)")
            clip.setdefault("subtitle", {})["position"] = str(valor)
        elif chave == "transition":
            if not isinstance(valor, dict):
                raise ProjectError("transition precisa ser {type, duration}")
            tipo = str(valor.get("type", "none"))
            if tipo not in {"none", "fade"}:
                raise ProjectError("Transição suportada: fade")
            dur = max(0.0, _round(parse_timecode(valor.get("duration", 0), "duração")))
            if dur > clip_duration(clip) / 2 + 1e-6:
                raise ProjectError("A transição deve ocupar no máximo metade do clipe")
            clip["transition"] = {"type": tipo, "duration": dur}
        else:
            raise ProjectError(f"Propriedade não suportada: {chave}")
        alterados.append(chave)

    _sorted_clips(track)
    _touch(project, f"Editar {clip.get('name', clip_id)}: {', '.join(alterados)}")
    return clip


def add_track(project: dict, tipo: str, name: str = "") -> dict:
    tipo = (tipo or "").lower().strip()
    if tipo not in TRACK_TYPES:
        raise ProjectError("Tipo de faixa inválido (video, audio, text, subtitle)")
    existentes = [t["id"] for t in project["tracks"]]
    numero = 1
    while f"{'v' if tipo == 'video' else 'a' if tipo == 'audio' else 't' if tipo == 'text' else 's'}{numero}" in existentes:
        numero += 1
    prefixo = {"video": "v", "audio": "a", "text": "t", "subtitle": "s"}[tipo]
    track = new_track(f"{prefixo}{numero}", tipo, name.strip() or f"Faixa {tipo} {numero}")
    indice = len(project["tracks"])
    if tipo == "video":
        indice = max([i + 1 for i, t in enumerate(project["tracks"]) if t["type"] == "video"] or [0])
    elif tipo == "audio":
        indice = len(project["tracks"])
    project["tracks"].insert(indice, track)
    _touch(project, f"Adicionar faixa {track['name']}")
    return track


def remove_track(project: dict, track_id: str) -> dict:
    track = get_track(project, track_id)
    if track["clips"]:
        raise ProjectError("Esvazie a faixa antes de removê-la")
    if len([t for t in project["tracks"] if t["type"] == track["type"]]) <= 1 and track["type"] in {"video", "audio"}:
        raise ProjectError("O projeto precisa manter ao menos uma faixa de vídeo e uma de áudio")
    project["tracks"].remove(track)
    _touch(project, f"Remover faixa {track['name']}")
    return track


def set_track(project: dict, track_id: str, **props: Any) -> dict:
    track = get_track(project, track_id)
    for chave, valor in props.items():
        if chave == "name" and str(valor).strip():
            track["name"] = str(valor).strip()[:80]
        elif chave in {"muted", "hidden", "locked"}:
            track[chave] = bool(valor)
        elif valor is not None:
            raise ProjectError(f"Propriedade de faixa não suportada: {chave}")
    _touch(project, f"Editar faixa {track['name']}")
    return track


def add_marker(project: dict, time: float, label: str = "", color: str = "#fbbf24") -> dict:
    marker = {
        "id": _uid("m"),
        "time": _round(parse_timecode(time, "tempo do marcador")),
        "label": (label or "").strip()[:120],
        "color": color or "#fbbf24",
    }
    project.setdefault("markers", []).append(marker)
    project["markers"].sort(key=lambda m: m["time"])
    _touch(project, "Adicionar marcador")
    return marker


def remove_marker(project: dict, marker_id: str) -> dict:
    for marker in project.get("markers", []):
        if marker["id"] == marker_id:
            project["markers"].remove(marker)
            _touch(project, "Remover marcador")
            return marker
    raise ProjectError(f"Marcador não encontrado: {marker_id}")


def add_region(project: dict, start: float, end: float, label: str = "", color: str = "#4f8cff") -> dict:
    ini = _round(parse_timecode(start, "início da região"))
    fim = _round(parse_timecode(end, "fim da região"))
    if fim <= ini:
        raise ProjectError("O fim da região precisa ser maior que o início")
    region = {
        "id": _uid("r"),
        "start": ini,
        "end": fim,
        "label": (label or "").strip()[:120],
        "color": color or "#4f8cff",
    }
    project.setdefault("regions", []).append(region)
    project["regions"].sort(key=lambda r: r["start"])
    _touch(project, "Adicionar região")
    return region


def set_project_settings(project: dict, **props: Any) -> dict:
    settings = project.setdefault("settings", {})
    for chave, valor in props.items():
        if valor is None:
            continue
        if chave == "width":
            settings["width"] = int(valor)
        elif chave == "height":
            settings["height"] = int(valor)
        elif chave == "fps":
            settings["fps"] = parse_fps(valor)
        elif chave == "audio_rate":
            taxa = int(valor)
            if taxa not in {44100, 48000, 96000}:
                raise ProjectError("Taxa de áudio deve ser 44100, 48000 ou 96000")
            settings["audio_rate"] = taxa
        elif chave == "name":
            nome = str(valor).strip()
            if not nome:
                raise ProjectError("Nome do projeto vazio")
            project["name"] = nome[:120]
        else:
            raise ProjectError(f"Configuração não suportada: {chave}")
    if settings["width"] % 2 or settings["height"] % 2:
        raise ProjectError("Largura e altura precisam ser pares")
    if not 16 <= settings["width"] <= 7680 or not 16 <= settings["height"] <= 4320:
        raise ProjectError("Resolução fora do intervalo suportado")
    _touch(project, "Alterar configurações do projeto")
    return project


def _touch(project: dict, label: str) -> None:
    project["updated_at"] = _now()
    project.setdefault("recent_operations", []).append({"at": project["updated_at"], "label": label})
    project["recent_operations"] = project["recent_operations"][-50:]


def _assinatura(project: dict) -> str:
    """
    Estado do projeto sem os campos de auditoria.

    updated_at e recent_operations mudam em toda chamada, inclusive quando a
    operação não altera nada; ignorá-los é o que permite detectar o no-op.
    """
    limpo = {chave: valor for chave, valor in project.items() if chave not in {"updated_at", "recent_operations"}}
    return json.dumps(limpo, sort_keys=True, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Operações genéricas (API + IA)
# ---------------------------------------------------------------------------

def apply_operation(project: dict, operation: str, params: Optional[dict] = None) -> dict:
    """
    Executa uma operação nomeada com parâmetros validados.

    É a porta única usada pela API e pela IA; nenhuma operação aceita comando
    de shell ou caminho fora dos arquivos de mídia existentes.
    """
    params = params or {}
    op = (operation or "").strip()
    mapa = {
        "add_clip": lambda: add_clip(project, **params),
        "add_text": lambda: add_text_clip(project, **params),
        "add_subtitles": lambda: add_subtitle_clip(project, **params),
        "move": lambda: move_clip(project, **params),
        "trim": lambda: trim_clip(project, **params),
        "split": lambda: split_clip(project, **params),
        "delete": lambda: delete_clip(project, **params),
        "duplicate": lambda: duplicate_clip(project, **params),
        "slip": lambda: slip_clip(project, **params),
        "slide": lambda: slide_clip(project, **params),
        "roll": lambda: roll_edit(project, **params),
        "set": lambda: set_clip_properties(project, **params),
        "add_track": lambda: add_track(project, **params),
        "remove_track": lambda: remove_track(project, **params),
        "set_track": lambda: set_track(project, **params),
        "add_marker": lambda: add_marker(project, **params),
        "remove_marker": lambda: remove_marker(project, **params),
        "add_region": lambda: add_region(project, **params),
        "settings": lambda: set_project_settings(project, **params),
    }
    if op not in mapa:
        raise ProjectError(f"Operação desconhecida: {operation}")
    return mapa[op]()


# ---------------------------------------------------------------------------
# Validação e resumo
# ---------------------------------------------------------------------------

def _issue(severity: str, code: str, message: str, track_id: Optional[str] = None, clip_id: Optional[str] = None) -> dict:
    item = {"severity": severity, "code": code, "message": message}
    if track_id:
        item["track_id"] = track_id
    if clip_id:
        item["clip_id"] = clip_id
    return item


def validate_project(project: dict, check_media: bool = True) -> list[dict]:
    """
    Valida a integridade da timeline antes de renderizar.

    Erros impedem a exportação; avisos indicam riscos que merecem revisão.
    """
    issues: list[dict] = []
    settings = project.get("settings", {})
    for campo, minimo, maximo in (("width", 16, 7680), ("height", 16, 4320), ("fps", 1, 240)):
        valor = settings.get(campo)
        if not isinstance(valor, (int, float)) or not minimo <= float(valor) <= maximo:
            issues.append(_issue("error", "settings", f"Configuração inválida: {campo}={valor}"))
    if len(project.get("tracks", [])) == 0:
        issues.append(_issue("error", "no_tracks", "O projeto não tem faixas"))

    ids: set[str] = set()
    total_clips = 0
    com_audio = False
    for track in project.get("tracks", []):
        if track.get("type") not in TRACK_TYPES:
            issues.append(_issue("error", "track_type", f"Faixa com tipo inválido: {track.get('type')}", track.get("id")))
            continue
        anterior_fim = -1.0
        for clip in track.get("clips", []):
            total_clips += 1
            if clip.get("id") in ids:
                issues.append(_issue("error", "duplicate_clip", f"Clipe duplicado: {clip.get('id')}", track.get("id"), clip.get("id")))
            ids.add(clip.get("id"))
            try:
                inicio = float(clip["start"])
                dur = clip_duration(clip)
            except (KeyError, TypeError, ValueError):
                issues.append(_issue("error", "clip_shape", "Clipe com dados incompletos", track.get("id"), clip.get("id")))
                continue
            if inicio < 0 or dur <= 0:
                issues.append(_issue("error", "clip_time", f"Clipe '{clip.get('name')}' tem tempo inválido", track.get("id"), clip.get("id")))
            if inicio < anterior_fim - 1e-3:
                issues.append(_issue("error", "overlap", f"Clipe '{clip.get('name')}' se sobrepõe ao anterior", track.get("id"), clip.get("id")))
            anterior_fim = max(anterior_fim, clip_end(clip))

            if clip.get("type") in {"video", "audio"}:
                fonte = clip.get("source")
                if not fonte:
                    issues.append(_issue("error", "missing_source", f"Clipe sem arquivo: {clip.get('name')}", track.get("id"), clip.get("id")))
                    continue
                info = project.get("media", {}).get(str(Path(fonte).resolve()))
                if check_media and not Path(fonte).is_file():
                    issues.append(_issue("error", "missing_media", f"Arquivo ausente: {fonte}", track.get("id"), clip.get("id")))
                if info:
                    if float(clip.get("out", 0)) > float(info.get("duration", 0)) + 0.1:
                        issues.append(_issue("error", "out_of_bounds", f"'{clip.get('name')}' passa do fim do arquivo", track.get("id"), clip.get("id")))
                    if float(clip.get("in", 0)) < 0:
                        issues.append(_issue("error", "in_of_bounds", f"Entrada negativa em '{clip.get('name')}'", track.get("id"), clip.get("id")))
                    if track["type"] == "video" and info.get("has_audio"):
                        com_audio = True
                if clip.get("fade_in", 0) + clip.get("fade_out", 0) > dur + 1e-6:
                    issues.append(_issue("error", "fade", f"Fades maiores que o clipe '{clip.get('name')}'", track.get("id"), clip.get("id")))
                trans = clip.get("transition") or {}
                if trans.get("duration", 0) > dur / 2 + 1e-6:
                    issues.append(_issue("warning", "transition", f"Transição ocupa mais da metade de '{clip.get('name')}'", track.get("id"), clip.get("id")))
            elif clip.get("type") == "text":
                conteudo = ((clip.get("text") or {}).get("content") or "").strip()
                if not conteudo:
                    issues.append(_issue("error", "empty_text", "Título sem conteúdo", track.get("id"), clip.get("id")))
            elif clip.get("type") == "subtitle":
                fonte = clip.get("source")
                if check_media and (not fonte or not Path(fonte).is_file()):
                    issues.append(_issue("error", "missing_subtitles", "Arquivo de legendas ausente", track.get("id"), clip.get("id")))
    if total_clips == 0:
        issues.append(_issue("error", "empty_project", "Adicione pelo menos um clipe antes de renderizar"))
    if project_duration(project) <= 0:
        issues.append(_issue("error", "zero_duration", "A duração da timeline é zero"))
    if not any(t.get("type") == "video" and t.get("clips") for t in project.get("tracks", [])):
        issues.append(_issue("warning", "no_video", "O projeto não tem imagem em nenhuma faixa de vídeo"))
    if not com_audio and not any(t.get("type") == "audio" and t.get("clips") for t in project.get("tracks", [])):
        issues.append(_issue("warning", "no_audio", "O projeto não tem áudio; o vídeo sairá mudo"))
    return issues


def has_errors(issues: list[dict]) -> bool:
    return any(item.get("severity") == "error" for item in issues)


def project_summary(project: dict) -> str:
    """Resumo compacto para o modelo de IA entender o estado da timeline."""
    settings = project.get("settings", {})
    linhas = [
        f"Projeto {project.get('id')} — {project.get('name')}",
        f"Resolução {settings.get('width')}x{settings.get('height')} @ {settings.get('fps')} fps; "
        f"duração {format_timecode(project_duration(project))}.",
    ]
    for track in project.get("tracks", []):
        if not track.get("clips"):
            continue
        linhas.append(f"Faixa {track['id']} '{track['name']}' ({track['type']}):")
        for clip in track.get("clips", []):
            if track["type"] == "text":
                texto = (clip.get("text") or {}).get("content", "")
                linhas.append(
                    f"  - {clip['id']}: título \"{texto}\" "
                    f"{format_timecode(clip['start'])}–{format_timecode(clip_end(clip))}"
                )
            elif track["type"] == "subtitle":
                linhas.append(
                    f"  - {clip['id']}: legendas {clip.get('name')} "
                    f"{format_timecode(clip['start'])}–{format_timecode(clip_end(clip))}"
                )
            else:
                linhas.append(
                    f"  - {clip['id']}: {Path(str(clip.get('source'))).name} "
                    f"timeline {format_timecode(clip['start'])}–{format_timecode(clip_end(clip))}, "
                    f"fonte {clip['in']:.2f}–{clip['out']:.2f}s, "
                    f"speed {clip.get('speed', 1)}x, volume {clip.get('volume', 1)}"
                )
    if not project.get("tracks") or not any(t.get("clips") for t in project.get("tracks", [])):
        linhas.append("Timeline vazia.")
    markers = project.get("markers", [])
    if markers:
        linhas.append("Marcadores: " + ", ".join(f"{format_timecode(m['time'])} {m.get('label', '')}".strip() for m in markers[:20]))
    return "\n".join(linhas)


def project_view(project: dict) -> dict:
    """Cópia enriquecida para a interface, com durações e mídias ausentes."""
    view = copy.deepcopy(project)
    view["duration"] = project_duration(project)
    view["missing_media"] = [
        caminho for caminho in project.get("media", {}) if not Path(caminho).is_file()
    ]
    for track in view.get("tracks", []):
        track["end"] = timeline_end(track)
        for clip in track.get("clips", []):
            clip["duration"] = clip_duration(clip)
            clip["end"] = clip_end(clip)
            if clip.get("type") in {"video", "audio"}:
                info = project.get("media", {}).get(str(Path(str(clip.get("source"))).resolve()))
                clip["source_duration"] = (info or {}).get("duration", 0)
                clip["has_audio"] = (info or {}).get("has_audio", False)
                clip["has_video"] = (info or {}).get("has_video", False)
                clip["missing"] = bool(clip.get("source")) and not Path(str(clip["source"])).is_file()
    return view


# ---------------------------------------------------------------------------
# Persistência, undo/redo e versões
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporario = path.with_suffix(path.suffix + f".tmp{uuid.uuid4().hex[:6]}")
    temporario.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporario, path)


class ProjectStore:
    """
    Guarda projetos em disco, com autosave, undo/redo e histórico de versões.

    Uma instância é segura para uso concorrente; a API e o agente compartilham
    a mesma instância para que ambos vejam a timeline atualizada.
    """

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root else PROJECTS_DIR
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._cache: dict[str, dict] = {}
        self._undo: dict[str, list[dict]] = {}
        self._redo: dict[str, list[dict]] = {}
        self._active_file = self.root / "active.json"

    # -- arquivos ---------------------------------------------------------
    def _dir(self, project_id: str) -> Path:
        if not re.fullmatch(r"p_[a-f0-9]{10}", str(project_id or "")):
            raise ProjectError(f"ID de projeto inválido: {project_id}")
        return self.root / project_id

    def _file(self, project_id: str) -> Path:
        return self._dir(project_id) / "project.json"

    def _versions(self, project_id: str) -> Path:
        return self._dir(project_id) / "versions"

    def _save(self, project: dict, version: bool = True) -> None:
        pasta = self._dir(project["id"])
        pasta.mkdir(parents=True, exist_ok=True)
        _atomic_write(self._file(project["id"]), project)
        if version:
            snapshots = self._versions(project["id"])
            snapshots.mkdir(parents=True, exist_ok=True)
            rotulo = "estado"
            if project.get("recent_operations"):
                rotulo = project["recent_operations"][-1].get("label", "estado")
            nome = f"{datetime.now().strftime('%Y%m%d-%H%M%S-%f')[:-3]}_{_slug(rotulo)}.json"
            _atomic_write(snapshots / nome, project)
            arquivos = sorted(snapshots.glob("*.json"), key=lambda p: p.name)
            for antigo in arquivos[:-MAX_VERSIONS]:
                antigo.unlink(missing_ok=True)
        self._cache[project["id"]] = project

    def _load(self, project_id: str) -> dict:
        caminho = self._file(project_id)
        if not caminho.is_file():
            raise ProjectError(f"Projeto não encontrado: {project_id}")
        try:
            projeto = json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise ProjectError(f"Projeto corrompido ({project_id}): {e}") from None
        if projeto.get("schema") != PROJECT_SCHEMA:
            raise ProjectError(f"Versão de projeto não suportada: {projeto.get('schema')}")
        return projeto

    def _get(self, project_id: str) -> dict:
        if project_id not in self._cache:
            self._cache[project_id] = self._load(project_id)
        return self._cache[project_id]

    # -- projetos ---------------------------------------------------------
    def create(self, name: str, width: int = 1920, height: int = 1080, fps: float = 30) -> dict:
        with self._lock:
            projeto = new_project(name, width, height, fps)
            self._undo[projeto["id"]] = []
            self._redo[projeto["id"]] = []
            self._save(projeto)
            return projeto

    def list_projects(self) -> list[dict]:
        with self._lock:
            itens = []
            for pasta in self.root.iterdir():
                if not pasta.is_dir() or not (pasta / "project.json").is_file():
                    continue
                try:
                    projeto = self._load(pasta.name)
                except ProjectError:
                    continue
                itens.append({
                    "id": projeto["id"],
                    "name": projeto.get("name", pasta.name),
                    "updated_at": projeto.get("updated_at"),
                    "created_at": projeto.get("created_at"),
                    "duration": project_duration(projeto),
                    "clip_count": sum(len(t.get("clips", [])) for t in projeto.get("tracks", [])),
                    "width": projeto.get("settings", {}).get("width"),
                    "height": projeto.get("settings", {}).get("height"),
                    "fps": projeto.get("settings", {}).get("fps"),
                })
            itens.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
            return itens

    def get(self, project_id: str) -> dict:
        with self._lock:
            return copy.deepcopy(self._get(project_id))

    def view(self, project_id: str) -> dict:
        with self._lock:
            return project_view(self._get(project_id))

    def save(self, project_id: str) -> dict:
        with self._lock:
            projeto = self._get(project_id)
            self._save(projeto)
            return projeto

    def delete(self, project_id: str, confirm: bool = False) -> None:
        with self._lock:
            if not confirm:
                raise ProjectError("Exclusão exige confirmação explícita")
            pasta = self._dir(project_id)
            if not (pasta / "project.json").is_file():
                raise ProjectError(f"Projeto não encontrado: {project_id}")
            lixeira = self.root / ".trash"
            lixeira.mkdir(exist_ok=True)
            destino = lixeira / f"{project_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            shutil.move(str(pasta), str(destino))
            self._cache.pop(project_id, None)
            self._undo.pop(project_id, None)
            self._redo.pop(project_id, None)
            if self.get_active() == project_id:
                self.set_active(None)

    def set_active(self, project_id: Optional[str]) -> Optional[str]:
        with self._lock:
            if project_id:
                self._get(project_id)
            _atomic_write(self._active_file, {"project_id": project_id})
            return project_id

    def get_active(self) -> Optional[str]:
        with self._lock:
            if not self._active_file.is_file():
                return None
            try:
                pid = json.loads(self._active_file.read_text(encoding="utf-8")).get("project_id")
            except (OSError, json.JSONDecodeError):
                return None
            if pid and self._file(pid).is_file():
                return pid
            return None

    # -- edição -----------------------------------------------------------
    def _push_undo(self, project_id: str, antes: dict, label: str) -> None:
        pilha = self._undo.setdefault(project_id, [])
        pilha.append({"label": label, "project": antes})
        del pilha[:-MAX_UNDO]
        self._redo[project_id] = []

    def apply(self, project_id: str, operation: str, params: Optional[dict] = None) -> dict:
        """Aplica uma operação com validação, undo e autosave atômicos."""
        with self._lock:
            projeto = self._get(project_id)
            antes = copy.deepcopy(projeto)
            try:
                apply_operation(projeto, operation, params)
            except ProjectError:
                raise
            except (TypeError, ValueError) as e:
                raise ProjectError(f"Parâmetros inválidos para {operation}: {e}") from None
            if _assinatura(projeto) == _assinatura(antes):
                # Operação sem efeito não consome passo de undo nem versão.
                self._cache[project_id] = antes
                return copy.deepcopy(antes)
            self._push_undo(project_id, antes, (params or {}).get("label") or operation)
            self._save(projeto)
            return copy.deepcopy(projeto)

    @contextmanager
    def edit(self, project_id: str, label: str = "edição"):
        """
        Transação para mutações diretas no projeto, com undo e autosave.

        O agente precisa dos objetos retornados pelas funções do motor (ids de
        clipes, por exemplo); este contexto entrega o projeto vivo e registra
        a transação inteira como um único passo de undo.
        """
        with self._lock:
            projeto = self._get(project_id)
            antes = copy.deepcopy(projeto)
            try:
                yield projeto
                self._push_undo(project_id, antes, label)
                self._save(projeto)
            except BaseException:
                self._cache[project_id] = antes
                raise

    def undo(self, project_id: str) -> dict:
        with self._lock:
            atual = copy.deepcopy(self._get(project_id))
            pilha = self._undo.get(project_id) or []
            if not pilha:
                raise ProjectError("Nada para desfazer")
            item = pilha.pop()
            self._redo.setdefault(project_id, []).append({"label": item["label"], "project": atual})
            self._cache[project_id] = item["project"]
            item["project"]["updated_at"] = _now()
            self._save(item["project"], version=False)
            return copy.deepcopy(item["project"])

    def redo(self, project_id: str) -> dict:
        with self._lock:
            atual = copy.deepcopy(self._get(project_id))
            pilha = self._redo.get(project_id) or []
            if not pilha:
                raise ProjectError("Nada para refazer")
            item = pilha.pop()
            self._undo.setdefault(project_id, []).append({"label": item["label"], "project": atual})
            self._cache[project_id] = item["project"]
            item["project"]["updated_at"] = _now()
            self._save(item["project"], version=False)
            return copy.deepcopy(item["project"])

    def history(self, project_id: str) -> dict:
        with self._lock:
            self._get(project_id)
            return {
                "undo": [item["label"] for item in reversed(self._undo.get(project_id, []))],
                "redo": [item["label"] for item in reversed(self._redo.get(project_id, []))],
            }

    def versions(self, project_id: str) -> list[dict]:
        with self._lock:
            self._get(project_id)
            snapshots = self._versions(project_id)
            if not snapshots.is_dir():
                return []
            itens = []
            for arquivo in sorted(snapshots.glob("*.json"), reverse=True):
                try:
                    stat = arquivo.stat()
                except OSError:
                    continue
                rotulo = arquivo.stem.split("_", 1)[-1].replace("-", " ")
                itens.append({
                    "name": arquivo.name,
                    "label": rotulo,
                    "size": stat.st_size,
                    "modified": int(stat.st_mtime),
                })
            return itens[:MAX_VERSIONS]

    def restore_version(self, project_id: str, version_name: str) -> dict:
        with self._lock:
            if Path(version_name).name != version_name or not version_name.endswith(".json"):
                raise ProjectError("Nome de versão inválido")
            arquivo = self._versions(project_id) / version_name
            if not arquivo.is_file():
                raise ProjectError(f"Versão não encontrada: {version_name}")
            try:
                projeto = json.loads(arquivo.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                raise ProjectError(f"Versão corrompida: {e}") from None
            if projeto.get("id") != project_id:
                raise ProjectError("A versão não pertence a este projeto")
            atual = copy.deepcopy(self._get(project_id))
            self._push_undo(project_id, atual, f"Restaurar {version_name}")
            projeto["updated_at"] = _now()
            self._save(projeto)
            return copy.deepcopy(projeto)


STORE = ProjectStore()


# ---------------------------------------------------------------------------
# Utilitários para a IA
# ---------------------------------------------------------------------------

def operation_result(project: dict, message: str) -> str:
    """Resposta curta de uma operação para o agente."""
    return json.dumps(
        {
            "ok": True,
            "mensagem": message,
            "project_id": project.get("id"),
            "duration": format_timecode(project_duration(project)),
            "summary": project_summary(project),
        },
        ensure_ascii=False,
    )
