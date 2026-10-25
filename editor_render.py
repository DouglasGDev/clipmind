"""
Renderizador de timeline do ClipMind.

Lê o mesmo projeto JSON usado pela interface e compõe as faixas de vídeo,
áudio, títulos e legendas com FFmpeg. A exportação roda em segundo plano, com
progresso, cancelamento, log e validação técnica do arquivo final.

O render final e a prévia usam o mesmo grafo de filtros; a prévia apenas reduz
a resolução e a qualidade, então o enquadramento é idêntico.
"""

from __future__ import annotations

import copy
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

import editor_analysis
from editor_project import (
    ProjectError,
    ProjectStore,
    STORE,
    clip_duration,
    clip_end,
    format_timecode,
    has_errors,
    probe_media,
    project_duration,
    validate_project,
)
from youtube_editor_tools import OUTPUT_DIR, ensure_output_dir


FFMPEG = "ffmpeg"
MAX_JOBS = 50
POSITIONS = {
    "topo": ("(w-text_w)/2", "h*0.08"),
    "centro": ("(w-text_w)/2", "(h-text_h)/2"),
    "inferior": ("(w-text_w)/2", "h-text_h-h*0.08"),
    "inferior-esquerda": ("w*0.05", "h-text_h-h*0.10"),
    "inferior-direita": ("w-text_w-w*0.05", "h-text_h-h*0.10"),
}


class RenderError(RuntimeError):
    """Falha de renderização com mensagem acionável."""


class RenderCancelled(RuntimeError):
    """Renderização interrompida pelo usuário."""


def _round(value: float) -> float:
    return round(float(value), 3)


def _reapar_processo(processo: subprocess.Popen) -> None:
    """Espera o FFmpeg fechar de verdade antes de mexer nos arquivos abertos por ele."""
    try:
        if processo.poll() is not None:
            return
        processo.terminate()
        processo.wait(timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        pass
    if processo.poll() is None:
        try:
            processo.kill()
            processo.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _apagar_arquivo(caminho: Path) -> None:
    """
    Remove um arquivo parcial.

    No Windows o handle do FFmpeg pode sobreviver alguns instantes ao processo;
    sem repetir a tentativa o parcial fica na pasta de saída.
    """
    for tentativa in range(20):
        try:
            caminho.unlink(missing_ok=True)
            return
        except OSError:
            if tentativa == 19:
                return
            time.sleep(0.1)


def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", text).strip("-")[:60] or "timeline"


def _ff_color(value: str, default: str = "white") -> str:
    texto = str(value or default).strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", texto):
        return "0x" + texto[1:]
    if re.fullmatch(r"[a-zA-Z]{3,20}", texto):
        return texto
    return default


def _ass_color(value: str, default: str = "&H00FFFFFF") -> str:
    texto = str(value or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", texto):
        r, g, b = texto[1:3], texto[3:5], texto[5:7]
        return f"&H00{b}{g}{r}".upper()
    nomes = {
        "white": "&H00FFFFFF",
        "black": "&H00000000",
        "yellow": "&H0000FFFF",
        "red": "&H000000FF",
        "green": "&H0000FF00",
        "blue": "&H00FF0000",
    }
    return nomes.get(texto.lower(), default)


def _atempo_chain(speed: float) -> list[str]:
    """Divide velocidades extremas em fatores que o atempo aceita."""
    fatores: list[str] = []
    restante = max(0.01, float(speed))
    while restante > 2.0:
        fatores.append("atempo=2.0")
        restante /= 2.0
    while restante < 0.5:
        fatores.append("atempo=0.5")
        restante /= 0.5
    fatores.append(f"atempo={restante:.6g}")
    return fatores


def _find_font() -> Optional[Path]:
    candidatos = [
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeuib.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/calibrib.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ]
    for fonte in candidatos:
        if fonte.is_file():
            return fonte
    return None


@lru_cache(maxsize=1)
def _available_encoders() -> set[str]:
    try:
        saida = subprocess.run(
            [FFMPEG, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return set()
    nomes = set()
    for linha in saida.splitlines():
        match = re.match(r"\s*[VAS][A-Z.]{5,}\s+(\S+)", linha)
        if match:
            nomes.add(match.group(1))
    return nomes


# ---------------------------------------------------------------------------
# Legendas
# ---------------------------------------------------------------------------

def _parse_srt_clock(texto: str) -> float:
    match = re.match(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})", texto.strip())
    if not match:
        raise ValueError(texto)
    ms = int(match.group(4).ljust(3, "0"))
    return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + int(match.group(3)) + ms / 1000


def _parse_ass_clock(texto: str) -> float:
    match = re.match(r"(\d+):(\d{2}):(\d{2})[.:](\d{1,3})", texto.strip())
    if not match:
        raise ValueError(texto)
    fracao = match.group(4)
    return (
        int(match.group(1)) * 3600 + int(match.group(2)) * 60 + int(match.group(3))
        + int(fracao) / (10 ** len(fracao))
    )


def _fmt_ass_clock(seconds: float) -> str:
    cs = max(0, int(round(seconds * 100)))
    h, resto = divmod(cs, 360_000)
    m, resto = divmod(resto, 6000)
    s, cs = divmod(resto, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _subtitle_cues(origem: Path) -> list[tuple[float, float, str]]:
    """Lê SRT, VTT ou ASS e devolve as falas com tempos em segundos."""
    texto = origem.read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n")
    cues: list[tuple[float, float, str]] = []
    if origem.suffix.lower() == ".ass":
        for linha in texto.splitlines():
            if not linha.lower().startswith("dialogue:"):
                continue
            partes = linha.split(",", 9)
            if len(partes) < 10:
                continue
            try:
                inicio = _parse_ass_clock(partes[1])
                fim = _parse_ass_clock(partes[2])
            except ValueError:
                continue
            corpo = partes[9].replace("\\N", "\n").replace("\\n", "\n")
            cues.append((inicio, fim, corpo))
        return cues

    for bloco in re.split(r"\n\s*\n", texto):
        linhas = [linha for linha in bloco.splitlines() if linha.strip()]
        indice = next((i for i, linha in enumerate(linhas) if "-->" in linha), None)
        if indice is None:
            continue
        try:
            inicio_txt, fim_txt = [parte.strip() for parte in linhas[indice].split("-->", 1)]
            inicio = _parse_srt_clock(inicio_txt)
            fim = _parse_srt_clock(fim_txt)
        except (ValueError, IndexError):
            continue
        corpo = "\n".join(linhas[indice + 1:]) or " "
        cues.append((inicio, fim, corpo))
    return cues


def _write_subtitle_ass(
    destino: Path,
    cues: list[tuple[float, float, str]],
    inicio_clipe: float,
    duracao: float,
    estilo: dict,
    width: int,
    height: int,
    scale: float,
) -> int:
    """
    Gera um ASS v4+ próprio em vez de deixar o FFmpeg converter o SRT.

    O conversor interno usa alinhamento legado (5 = topo-esquerda); escrever o
    cabeçalho permite controlar posição, margem e tamanho de forma previsível.
    """
    tamanho = max(8, int(round(float(estilo.get("font_size", 22) or 22) * scale)))
    margem = max(0, int(round(float(estilo.get("margin_v", 42) or 42) * scale)))
    margem_h = max(12, int(round(width * 0.05)))
    contorno = max(1, int(round(2 * scale)))
    sombra = max(0, int(round(1 * scale)))
    alinhamento = {"inferior": 2, "centro": 5, "topo": 8}.get(str(estilo.get("position", "inferior")), 2)
    cor = _ass_color(estilo.get("color", "white"))
    limite = inicio_clipe + duracao

    eventos: list[str] = []
    for inicio, fim, corpo in cues:
        inicio = max(0.0, inicio + inicio_clipe)
        fim = min(limite, fim + inicio_clipe)
        if fim - inicio < 0.01:
            continue
        texto = corpo.replace("\n", "\\N").strip() or " "
        eventos.append(
            f"Dialogue: 0,{_fmt_ass_clock(inicio)},{_fmt_ass_clock(fim)},"
            f"Default,,0,0,0,,{texto}"
        )
    if not eventos:
        return 0

    cabecalho = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {width}\n"
        f"PlayResY: {height}\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        "YCbCr Matrix: TV.709\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,Arial,{tamanho},{cor},&H000000FF,&H00000000,&H00000000,"
        f"0,0,0,0,100,100,0,0,1,{contorno},{sombra},{alinhamento},"
        f"{margem_h},{margem_h},{margem},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    destino.write_text(cabecalho + "\n".join(eventos) + "\n", encoding="utf-8")
    return len(eventos)


# ---------------------------------------------------------------------------
# Grafo de filtros
# ---------------------------------------------------------------------------

class _TimelineGraph:
    def __init__(
        self,
        project: dict,
        workdir: Path,
        width: int,
        height: int,
        fps: float,
    ) -> None:
        self.project = project
        self.workdir = workdir
        self.width = width
        self.height = height
        self.fps = fps
        self.duration = project_duration(project)
        self.inputs: list[str] = []
        self.input_index: dict[str, int] = {}
        self.chains: list[str] = []
        self.audio_labels: list[str] = []
        self.warnings: list[str] = []
        self.font: Optional[Path] = _find_font()
        self._font_name: Optional[str] = None
        self._text_files: list[Path] = []

    # -- mídia ------------------------------------------------------------
    def _info(self, clip: dict) -> dict:
        caminho = str(Path(str(clip.get("source"))).expanduser().resolve())
        info = self.project.get("media", {}).get(caminho)
        if not info:
            info = probe_media(caminho)
            self.project.setdefault("media", {})[caminho] = info
        return info

    def _add_input(self, clip: dict) -> int:
        caminho = str(Path(str(clip["source"])).expanduser().resolve())
        indice = len(self.inputs)
        self.inputs.append(caminho)
        self.input_index[clip["id"]] = indice
        return indice

    # -- vídeo ------------------------------------------------------------
    def _video_chain(self, clip: dict, indice: int, rotulo: str) -> str:
        velocidade = max(0.01, float(clip.get("speed", 1) or 1))
        duracao = clip_duration(clip)
        filtros = [
            f"trim=start={float(clip['in']):.3f}:end={float(clip['out']):.3f}",
            f"setpts=(PTS-STARTPTS)/{velocidade:.6g}",
            f"scale=w={self.width}:h={self.height}:force_original_aspect_ratio=decrease",
            f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2:color=black@0",
            "format=rgba",
        ]
        cor = clip.get("color") or {}
        brilho = float(cor.get("brightness", 0) or 0)
        contraste = float(cor.get("contrast", 1) or 1)
        saturacao = float(cor.get("saturation", 1) or 1)
        gamma = float(cor.get("gamma", 1) or 1)
        if (brilho, contraste, saturacao, gamma) != (0.0, 1.0, 1.0, 1.0):
            filtros.append(
                f"eq=brightness={brilho:.4g}:contrast={contraste:.4g}:"
                f"saturation={saturacao:.4g}:gamma={gamma:.4g}"
            )

        transicao = clip.get("transition") or {}
        fade_in = max(0.0, float(clip.get("fade_in", 0) or 0))
        fade_out = max(0.0, float(clip.get("fade_out", 0) or 0))
        if str(transicao.get("type", "none")) == "fade" and float(transicao.get("duration", 0) or 0) > 0:
            fade_in = max(fade_in, float(transicao["duration"]))
            fade_out = max(fade_out, float(transicao["duration"]))
        if fade_in + fade_out > duracao:
            excesso = fade_in + fade_out - duracao
            fade_out = max(0.0, fade_out - excesso)
        if fade_in > 0:
            filtros.append(f"fade=t=in:st=0:d={fade_in:.3f}:alpha=1")
        if fade_out > 0:
            filtros.append(f"fade=t=out:st={max(0.0, duracao - fade_out):.3f}:d={fade_out:.3f}:alpha=1")

        transform = clip.get("transform") or {}
        opacidade = max(0.0, min(1.0, float(transform.get("opacity", 1) or 1)))
        if opacidade < 0.999:
            filtros.append(f"colorchannelmixer=aa={opacidade:.4g}")
        escala = max(0.05, min(8.0, float(transform.get("scale", 1) or 1)))
        if abs(escala - 1) > 1e-3:
            filtros.append(f"scale=trunc(iw*{escala:.6g}/2)*2:trunc(ih*{escala:.6g}/2)*2")
        rotacao = float(transform.get("rotation", 0) or 0)
        if abs(rotacao) > 1e-3:
            rad = rotacao * math.pi / 180
            filtros.append(f"rotate={rad:.6g}:fillcolor=none:ow=rotw({rad:.6g}):oh=roth({rad:.6g})")

        filtros.append(f"setpts=PTS+{float(clip['start']):.3f}/TB")
        self.chains.append(f"[{indice}:v]{','.join(filtros)}[{rotulo}]")
        return rotulo

    def _video(self) -> None:
        self.chains.append(
            f"color=c=black:s={self.width}x{self.height}:r={self.fps:.6g}:d={self.duration:.3f},format=yuv420p[base0]"
        )
        atual = "base0"
        numero = 0
        for track in self.project.get("tracks", []):
            if track.get("type") != "video" or track.get("hidden"):
                continue
            for clip in track.get("clips", []):
                indice = self._add_input(clip)
                rotulo = self._video_chain(clip, indice, f"v{numero}")
                destino = f"base{numero + 1}"
                transform = clip.get("transform") or {}
                x = float(transform.get("x", 0) or 0) * self._scale_factor
                y = float(transform.get("y", 0) or 0) * self._scale_factor
                inicio, fim = float(clip["start"]), clip_end(clip)
                self.chains.append(
                    f"[{atual}][{rotulo}]overlay=x=(main_w-overlay_w)/2+{x:.6g}:"
                    f"y=(main_h-overlay_h)/2+{y:.6g}:eof_action=pass:shortest=0:"
                    f"enable='between(t\\,{inicio:.3f}\\,{fim:.3f})'[{destino}]"
                )
                atual = destino
                numero += 1

        for track in self.project.get("tracks", []):
            if track.get("type") != "text" or track.get("hidden"):
                continue
            for clip in track.get("clips", []):
                atual = self._draw_text(clip, atual)

        for track in self.project.get("tracks", []):
            if track.get("type") != "subtitle" or track.get("hidden"):
                continue
            for clip in track.get("clips", []):
                atual = self._subtitle(clip, atual)

        self.chains.append(f"[{atual}]format=yuv420p[vout]")

    # -- títulos ----------------------------------------------------------
    def _draw_text(self, clip: dict, atual: str) -> str:
        if self.font is None:
            raise RenderError(
                "Nenhuma fonte TrueType encontrada para desenhar o título. "
                "Instale Arial ou DejaVu Sans."
            )
        if self._font_name is None:
            self._font_name = "clipmind-font.ttf"
            (self.workdir / self._font_name).write_bytes(self.font.read_bytes())
        texto = (clip.get("text") or {}).get("content", "")
        if not texto.strip():
            return atual
        nome_texto = f"texto-{re.sub(r'[^a-zA-Z0-9]', '', clip['id'])}.txt"
        (self.workdir / nome_texto).write_text(texto, encoding="utf-8")

        style = clip.get("text") or {}
        tamanho = max(8, int(round(float(style.get("font_size", 56) or 56) * self._scale_factor)))
        posicao = style.get("position", "inferior")
        if posicao == "personalizado" and style.get("x") is not None and style.get("y") is not None:
            x = f"{int(style['x']) * self._scale_factor:g}"
            y = f"{int(style['y']) * self._scale_factor:g}"
        else:
            x, y = POSITIONS.get(posicao, POSITIONS["inferior"])
        inicio = float(clip["start"])
        fim = clip_end(clip)
        duracao = max(0.01, clip_duration(clip))
        fade_in = min(max(0.0, float(clip.get("fade_in", 0) or 0)), duracao / 2)
        fade_out = min(max(0.0, float(clip.get("fade_out", 0) or 0)), duracao / 2)

        filtro = (
            f"drawtext=fontfile='{self._font_name}':textfile='{nome_texto}':"
            f"fontcolor={_ff_color(style.get('color', 'white'))}:fontsize={tamanho}:"
            f"x={x}:y={y}:fix_bounds=true:"
            f"shadowcolor=black@0.65:shadowx=2:shadowy=2:"
            f"enable='between(t\\,{inicio:.3f}\\,{fim:.3f})'"
        )
        if style.get("background", True):
            filtro += ":box=1:boxcolor=black@0.45:boxborderw=14"
        if fade_in > 0 or fade_out > 0:
            trechos = []
            if fade_in > 0:
                trechos.append(f"min(1\\,(t-{inicio:.3f})/{fade_in:.3f})")
            else:
                trechos.append("1")
            if fade_out > 0:
                trechos.append(f"max(0\\,({fim:.3f}-t)/{fade_out:.3f})")
            if len(trechos) == 1:
                alpha = trechos[0] if fade_in > 0 else f"if(lt(t\\,{fim - fade_out:.3f})\\,1\\,{trechos[0]})"
            else:
                alpha = (
                    f"if(lt(t\\,{inicio + fade_in:.3f})\\,{trechos[0]}\\,"
                    f"if(lt(t\\,{fim - fade_out:.3f})\\,1\\,{trechos[1]}))"
                )
            filtro += f":alpha='{alpha}'"

        destino = f"txt{len([c for c in self.chains if '[txt' in c])}"
        self.chains.append(f"[{atual}]{filtro}[{destino}]")
        return destino

    # -- legendas ---------------------------------------------------------
    def _subtitle(self, clip: dict, atual: str) -> str:
        origem = Path(str(clip.get("source", ""))).expanduser()
        if not origem.is_file():
            self.warnings.append(f"Legenda ausente ignorada: {origem}")
            return atual
        duracao = clip_duration(clip)
        estilo = clip.get("subtitle") or {}
        destino_arquivo = self.workdir / f"legenda-{re.sub(r'[^a-zA-Z0-9]', '', clip['id'])}.ass"
        try:
            cues = _subtitle_cues(origem)
            mantidos = _write_subtitle_ass(
                destino_arquivo,
                cues,
                float(clip["start"]),
                duracao,
                estilo,
                self.width,
                self.height,
                self._scale_factor,
            )
        except OSError as e:
            self.warnings.append(f"Falha ao ler legenda {origem.name}: {e}")
            return atual
        if not mantidos:
            self.warnings.append(f"A legenda {origem.name} não tem falas dentro do clipe")
            return atual

        destino = f"sub{len([c for c in self.chains if '[sub' in c])}"
        self.chains.append(
            f"[{atual}]subtitles=filename={destino_arquivo.name}[{destino}]"
        )
        return destino

    # -- áudio ------------------------------------------------------------
    def _audio_chain(self, clip: dict, indice: int, rotulo: str, info: dict) -> None:
        if not info.get("has_audio"):
            return
        velocidade = max(0.01, float(clip.get("speed", 1) or 1))
        duracao = clip_duration(clip)
        filtros = [
            f"atrim=start={float(clip['in']):.3f}:end={float(clip['out']):.3f}",
            "asetpts=PTS-STARTPTS",
            *_atempo_chain(velocidade),
            f"volume={max(0.0, float(clip.get('volume', 1) or 1)):.4g}",
        ]
        if float(clip.get("fade_in", 0) or 0) > 0:
            filtros.append(f"afade=t=in:st=0:d={float(clip['fade_in']):.3f}")
        if float(clip.get("fade_out", 0) or 0) > 0:
            filtros.append(
                f"afade=t=out:st={max(0.0, duracao - float(clip['fade_out'])):.3f}:d={float(clip['fade_out']):.3f}"
            )
        filtros.append(f"aresample={int(self.project.get('settings', {}).get('audio_rate', 48000))}")
        atraso = int(round(float(clip["start"]) * 1000))
        if atraso > 0:
            filtros.append(f"adelay=delays={atraso}:all=1")
        self.chains.append(f"[{indice}:a]{','.join(filtros)}[{rotulo}]")
        self.audio_labels.append(rotulo)

    def _audio(self) -> None:
        numero = 0
        for track in self.project.get("tracks", []):
            if track.get("type") not in {"video", "audio"} or track.get("muted"):
                continue
            for clip in track.get("clips", []):
                if clip.get("muted"):
                    continue
                if track["type"] == "video":
                    indice = self.input_index.get(clip["id"])
                    if indice is None:
                        indice = self._add_input(clip)
                else:
                    indice = self._add_input(clip)
                info = self._info(clip)
                if not info.get("has_audio"):
                    continue
                self._audio_chain(clip, indice, f"a{numero}", info)
                numero += 1

        taxa = int(self.project.get("settings", {}).get("audio_rate", 48000))
        if not self.audio_labels:
            self.chains.append(f"anullsrc=r={taxa}:cl=stereo,atrim=duration={self.duration:.3f}[aout]")
            return
        if len(self.audio_labels) == 1:
            self.chains.append(f"[{self.audio_labels[0]}]alimiter=limit=0.95,apad,atrim=duration={self.duration:.3f}[aout]")
            return
        entradas = "".join(f"[{rotulo}]" for rotulo in self.audio_labels)
        self.chains.append(
            f"{entradas}amix=inputs={len(self.audio_labels)}:duration=longest:"
            f"dropout_transition=0:normalize=0,alimiter=limit=0.95,apad,"
            f"atrim=duration={self.duration:.3f}[aout]"
        )

    def build(self) -> tuple[list[str], str]:
        if self.duration <= 0:
            raise RenderError("A timeline está vazia; adicione um clipe antes de renderizar")
        self._scale_factor = self.width / max(1, int(self.project["settings"]["width"]))
        self._video()
        self._audio()
        return self.inputs, ";\n".join(self.chains) + ";"


# ---------------------------------------------------------------------------
# Renderização
# ---------------------------------------------------------------------------

def _encoder_args(options: dict, ext: str) -> list[str]:
    crf = max(0, min(51, int(options.get("crf", 23))))
    preset = str(options.get("preset", "veryfast"))
    if preset not in {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower"}:
        preset = "veryfast"
    audio_bitrate = re.sub(r"[^0-9kK]", "", str(options.get("audio_bitrate", "192k"))) or "192k"

    if ext == ".webm":
        return [
            "-c:v", "libvpx-vp9", "-crf", str(crf + 8), "-b:v", "0",
            "-row-mt", "1", "-c:a", "libopus", "-b:a", "160k",
        ]

    pedido = str(options.get("video_codec", "libx264"))
    disponiveis = _available_encoders()
    codec = pedido if pedido in disponiveis else "libx264"
    args: list[str] = []
    if codec in {"h264_nvenc", "hevc_nvenc"}:
        args += ["-c:v", codec, "-preset", "p5", "-cq", str(crf), "-b:v", "0"]
    elif codec in {"libx265", "hevc"}:
        args += ["-c:v", "libx265", "-preset", preset, "-crf", str(crf), "-tag:v", "hvc1"]
    else:
        args += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf)]
    args += ["-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", audio_bitrate]
    if ext in {".mp4", ".mov"}:
        args += ["-movflags", "+faststart"]
    return args


def _normalize_options(options: Optional[dict]) -> dict:
    opcoes = dict(options or {})
    opcoes["preview"] = bool(opcoes.get("preview", False))
    opcoes["crf"] = max(0, min(51, int(opcoes.get("crf", 28 if opcoes["preview"] else 20))))
    opcoes["preset"] = str(opcoes.get("preset", "veryfast"))
    formato = str(opcoes.get("format", "mp4")).lower().lstrip(".")
    if formato not in {"mp4", "mov", "mkv", "webm"}:
        raise RenderError("Formato suportado: mp4, mov, mkv ou webm")
    opcoes["format"] = formato
    altura = opcoes.get("max_height")
    opcoes["max_height"] = max(144, min(4320, int(altura))) if altura else (360 if opcoes["preview"] else 0)
    nome = opcoes.get("filename")
    if nome:
        nome = _slug(Path(str(nome)).stem)
        opcoes["filename"] = nome
    return opcoes


def _unique_output(project: dict, options: dict) -> Path:
    ensure_output_dir()
    ext = "." + options["format"]
    sufixo = "_preview" if options["preview"] else "_timeline"
    base = options.get("filename") or f"{_slug(project.get('name', 'projeto'))}{sufixo}"
    destino = OUTPUT_DIR / f"{base}{ext}"
    if not destino.exists():
        return destino
    for indice in range(2, 1000):
        alternativa = OUTPUT_DIR / f"{base}_{indice}{ext}"
        if not alternativa.exists():
            return alternativa
    return OUTPUT_DIR / f"{base}_{uuid.uuid4().hex[:6]}{ext}"


def _render_resolution(project: dict, options: dict) -> tuple[int, int, float]:
    largura = int(project.get("settings", {}).get("width", 1920))
    altura = int(project.get("settings", {}).get("height", 1080))
    max_height = int(options.get("max_height") or 0)
    fator = min(1.0, max_height / altura) if max_height and altura > 0 else 1.0
    largura_saida = max(2, int(round(largura * fator / 2)) * 2)
    altura_saida = max(2, int(round(altura * fator / 2)) * 2)
    return largura_saida, altura_saida, fator


def render_project(
    project: dict,
    output_path: str | Path,
    options: Optional[dict] = None,
    on_progress: Optional[Callable[[int, str], None]] = None,
    cancel: Optional[threading.Event] = None,
    on_process: Optional[Callable[[subprocess.Popen], None]] = None,
) -> dict:
    """
    Renderiza o projeto para o arquivo indicado.

    Retorna {'output', 'qc', 'log', 'duration'}. Levanta RenderError quando a
    timeline é inválida ou o FFmpeg falha; RenderCancelled quando cancelada.
    """
    opcoes = _normalize_options(options)
    issues = validate_project(project)
    erros = [item for item in issues if item.get("severity") == "error"]
    if erros:
        mensagem = "Timeline inválida: " + "; ".join(item["message"] for item in erros[:5])
        raise RenderError(mensagem)

    projeto = copy.deepcopy(project)
    duracao = project_duration(projeto)
    largura, altura, _ = _render_resolution(projeto, opcoes)
    fps = float(projeto.get("settings", {}).get("fps", 30) or 30)
    destino = Path(output_path).expanduser().resolve()
    destino.parent.mkdir(parents=True, exist_ok=True)

    workdir = Path(tempfile.mkdtemp(prefix="clipmind-render-"))
    try:
        grafo = _TimelineGraph(projeto, workdir, largura, altura, fps)
        inputs, script = grafo.build()
        script_path = workdir / "filtros.txt"
        script_path.write_text(script, encoding="utf-8")
        log_path = workdir / "ffmpeg.log"

        comando = [FFMPEG, "-hide_banner", "-y", "-loglevel", "error", "-nostats"]
        comando += ["-progress", "pipe:1", "-stats_period", "0.5"]
        for entrada in inputs:
            comando += ["-i", entrada]
        # O FFmpeg 9 removeu -filter_complex_script; -/option lê o valor de um
        # arquivo e evita estourar o limite de linha de comando do Windows.
        comando += [
            "-/filter_complex", script_path.name,
            "-map", "[vout]", "-map", "[aout]",
            "-t", f"{duracao:.3f}", "-r", f"{fps:.6g}",
            *_encoder_args(opcoes, opcoes["format"]),
            str(destino),
        ]

        if on_progress:
            on_progress(2, "Preparando FFmpeg")
        log_handle = open(log_path, "w", encoding="utf-8", errors="replace")
        processo = subprocess.Popen(
            comando,
            cwd=str(workdir),
            stdout=subprocess.PIPE,
            stderr=log_handle,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if on_process:
            on_process(processo)
        cancelado = False
        codigo = 0
        try:
            assert processo.stdout is not None
            for linha in processo.stdout:
                if cancel is not None and cancel.is_set():
                    cancelado = True
                    break
                linha = linha.strip()
                if linha.startswith("out_time_us=") or linha.startswith("out_time_ms="):
                    try:
                        # O campo out_time_ms do FFmpeg é, historicamente, em microssegundos.
                        micros = int(linha.split("=", 1)[1])
                    except ValueError:
                        continue
                    segundos = micros / 1_000_000
                    pct = min(95, max(2, int(segundos / max(0.001, duracao) * 93)))
                    if on_progress:
                        on_progress(pct, f"Renderizando {format_timecode(segundos)} de {format_timecode(duracao)}")
            if not cancelado:
                codigo = processo.wait()
        finally:
            # Reaproveitar o processo aqui é o que libera o arquivo de saída:
            # apagar o parcial antes devolve PermissionError no Windows.
            _reapar_processo(processo)
            log_handle.close()
            if processo.stdout:
                processo.stdout.close()

        log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
        if cancelado or (cancel is not None and cancel.is_set()):
            _apagar_arquivo(destino)
            raise RenderCancelled("Renderização cancelada")
        if codigo != 0:
            _apagar_arquivo(destino)
            detalhe = log.strip()[-1600:] or "FFmpeg não explicou a falha"
            raise RenderError(f"FFmpeg falhou (código {codigo}): {detalhe}")
        if not destino.is_file() or destino.stat().st_size == 0:
            raise RenderError("O FFmpeg terminou sem gerar um arquivo válido")

        if on_progress:
            on_progress(96, "Validando o arquivo final")
        qc = validate_render(destino, projeto, esperado=duracao)
        if grafo.warnings:
            for aviso in grafo.warnings:
                qc["issues"].append({"severity": "warning", "code": "graph", "message": aviso})
        if on_progress:
            on_progress(100, "Concluído")
        return {
            "output": str(destino),
            "qc": qc,
            "log": log[-4000:],
            "duration": duracao,
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Controle de qualidade
# ---------------------------------------------------------------------------

def _run_analysis(args: list[str], timeout: int = 900) -> tuple[str, bool]:
    try:
        resultado = subprocess.run(
            [FFMPEG, "-hide_banner", "-nostats", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return (resultado.stderr or ""), True
    except FileNotFoundError:
        return "FFmpeg não encontrado", False
    except subprocess.TimeoutExpired:
        return "Análise demorou demais", False


def validate_render(path: str | Path, project: dict, esperado: Optional[float] = None) -> dict:
    """
    Confere o arquivo renderizado e devolve problemas classificados.

    Separa validação técnica (duração, resolução, áudio, quadros pretos,
    loudness) de avaliação estética, que não é feita aqui.
    """
    arquivo = Path(path)
    issues: list[dict] = []
    measurements: dict = {}
    try:
        info = probe_media(arquivo)
    except ProjectError as e:
        return {
            "ok": False,
            "issues": [{"severity": "error", "code": "file", "message": str(e)}],
            "measurements": {},
            "probe": {},
        }

    settings = project.get("settings", {})
    esperado = esperado if esperado is not None else project_duration(project)
    measurements["duration"] = info["duration"]
    measurements["size"] = info["size"]
    measurements["width"] = info["width"]
    measurements["height"] = info["height"]
    measurements["fps"] = info["fps"]
    measurements["has_audio"] = info["has_audio"]

    if info["duration"] <= 0:
        issues.append({"severity": "error", "code": "duration", "message": "O arquivo final tem duração zero"})
    elif esperado and abs(info["duration"] - esperado) > max(0.5, 1.0 / max(1, settings.get("fps", 30))):
        issues.append({
            "severity": "warning",
            "code": "duration_mismatch",
            "message": f"Duração final {format_timecode(info['duration'])} difere da timeline "
                       f"({format_timecode(esperado)})",
        })
    if (info["width"], info["height"]) != (int(settings.get("width", 0)), int(settings.get("height", 0))):
        esperado_res = f"{settings.get('width')}x{settings.get('height')}"
        atual = f"{info['width']}x{info['height']}"
        # A prévia é intencionalmente menor; só avisa quando não for múltipla exata.
        if info["width"] > 0:
            proporcao_ok = abs((info["width"] / max(1, info["height"])) - (settings.get("width", 1) / max(1, settings.get("height", 1)))) < 0.01
            if not proporcao_ok:
                issues.append({
                    "severity": "error",
                    "code": "resolution",
                    "message": f"Resolução {atual} não corresponde à proporção do projeto ({esperado_res})",
                })
    if abs(info["fps"] - float(settings.get("fps", info["fps"] or 30))) > 0.05:
        issues.append({
            "severity": "warning",
            "code": "fps",
            "message": f"FPS final {info['fps']} difere do projeto ({settings.get('fps')})",
        })

    tem_audio_esperado = any(
        track.get("type") == "audio" and track.get("clips") and not track.get("muted")
        for track in project.get("tracks", [])
    ) or any(
        track.get("type") == "video" and not track.get("muted")
        and any((project.get("media", {}).get(str(Path(str(c.get("source"))).resolve()), {}) or {}).get("has_audio") for c in track.get("clips", []))
        for track in project.get("tracks", [])
    )
    if tem_audio_esperado and not info["has_audio"]:
        issues.append({"severity": "error", "code": "audio_missing", "message": "O vídeo final saiu sem faixa de áudio"})
    if not tem_audio_esperado and info["has_audio"]:
        issues.append({"severity": "info", "code": "audio_silent", "message": "O projeto não tinha áudio; foi gerada uma faixa silenciosa"})

    if info["has_video"]:
        saida, ok = _run_analysis(["-i", str(arquivo), "-vf", "blackdetect=d=0.5:pix_th=0.10", "-an", "-f", "null", "-"])
        if ok:
            pretos = editor_analysis.parse_black_log(saida)
            measurements["black_ranges"] = pretos[:20]
            if pretos:
                amostra = ", ".join(f"{format_timecode(a)}–{format_timecode(b)}" for a, b in pretos[:4])
                issues.append({
                    "severity": "warning",
                    "code": "black_frames",
                    "message": f"{len(pretos)} trecho(s) de quadro preto ≥ 0,5 s: {amostra}",
                })
        else:
            issues.append({"severity": "warning", "code": "black_qc_skipped", "message": "Não foi possível verificar quadros pretos"})

    if info["has_audio"]:
        saida, ok = _run_analysis(["-i", str(arquivo), "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"])
        if ok:
            medidas = editor_analysis.parse_ebur128(saida)
            if "integrated_lufs" in medidas:
                measurements["loudness_lufs"] = medidas["integrated_lufs"]
            if "lra_lu" in medidas:
                measurements["lra_lu"] = medidas["lra_lu"]
            if "true_peak_dbfs" in medidas:
                measurements["true_peak_dbfs"] = medidas["true_peak_dbfs"]
            if measurements.get("loudness_lufs") is not None and measurements["loudness_lufs"] < -60:
                issues.append({"severity": "warning", "code": "audio_silence", "message": "O áudio final está praticamente silencioso"})
            if measurements.get("true_peak_dbfs") is not None and measurements["true_peak_dbfs"] > -0.1:
                issues.append({"severity": "warning", "code": "audio_peak", "message": "Pico de áudio próximo de 0 dBFS; risco de clipping"})
        else:
            issues.append({"severity": "warning", "code": "loudness_qc_skipped", "message": "Não foi possível medir o loudness do arquivo"})

    # Sincronia: diferença entre o início dos streams de vídeo e áudio.
    try:
        bruto = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(arquivo)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        ).stdout
        import json as _json
        streams = _json.loads(bruto or "{}").get("streams", [])
        inicios = {}
        for stream in streams:
            if stream.get("codec_type") in {"video", "audio"}:
                try:
                    inicios[stream["codec_type"]] = float(stream.get("start_time", 0) or 0)
                except (TypeError, ValueError):
                    pass
        if len(inicios) == 2:
            delta = abs(inicios["video"] - inicios["audio"])
            measurements["av_start_delta"] = round(delta, 3)
            if delta > 0.15:
                issues.append({"severity": "warning", "code": "av_sync", "message": f"Vídeo e áudio começam com {delta:.2f}s de diferença"})
    except Exception:
        pass

    return {
        "ok": not any(item["severity"] == "error" for item in issues),
        "issues": issues,
        "measurements": measurements,
        "probe": info,
    }


# ---------------------------------------------------------------------------
# Fila de renderização em segundo plano
# ---------------------------------------------------------------------------

@dataclass
class RenderJob:
    id: str
    project_id: str
    kind: str
    status: str = "queued"
    progress: int = 0
    message: str = "Na fila"
    output_path: Optional[str] = None
    output_name: Optional[str] = None
    error: Optional[str] = None
    qc: Optional[dict] = None
    log: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    options: dict = field(default_factory=dict)
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    _process: Optional[subprocess.Popen] = field(default=None, repr=False)

    def snapshot(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "kind": self.kind,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "output_path": self.output_path,
            "output_name": self.output_name,
            "error": self.error,
            "qc": self.qc,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "options": self.options,
        }


class RenderManager:
    """Executa renderizações em threads separadas, sem travar a interface."""

    def __init__(self, store: ProjectStore | None = None, on_update: Optional[Callable[[dict], None]] = None) -> None:
        self.store = store or STORE
        self.on_update = on_update
        self._jobs: dict[str, RenderJob] = {}
        self._lock = threading.RLock()

    def submit(self, project_id: str, options: Optional[dict] = None) -> dict:
        project = self.store.get(project_id)
        issues = validate_project(project)
        erros = [item for item in issues if item.get("severity") == "error"]
        if erros:
            raise RenderError("; ".join(item["message"] for item in erros[:5]))
        opcoes = _normalize_options(options)
        destino = _unique_output(project, opcoes)
        job = RenderJob(
            id=f"job_{uuid.uuid4().hex[:10]}",
            project_id=project_id,
            kind="preview" if opcoes["preview"] else "export",
            options=opcoes,
            output_path=str(destino),
            output_name=destino.name,
        )
        with self._lock:
            self._jobs[job.id] = job
            self._prune()
            thread = threading.Thread(target=self._run, args=(job, project, destino), daemon=True, name=f"render-{job.id}")
            thread.start()
        self._notify(job)
        return job.snapshot()

    def _notify(self, job: RenderJob) -> None:
        if self.on_update:
            try:
                self.on_update(job.snapshot())
            except Exception:
                pass

    def _run(self, job: RenderJob, project: dict, destino: Path) -> None:
        job.status = "running"
        job.started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        job.message = "Iniciando"
        self._notify(job)

        def progresso(pct: int, mensagem: str) -> None:
            job.progress = max(0, min(100, int(pct)))
            job.message = mensagem
            self._notify(job)

        def registrar_processo(processo: subprocess.Popen) -> None:
            job._process = processo

        try:
            resultado = render_project(
                project, destino, job.options, progresso, job._cancel, registrar_processo
            )
            job.status = "done"
            job.progress = 100
            job.message = "Concluído"
            job.qc = resultado["qc"]
            job.log = resultado["log"]
            job.output_path = resultado["output"]
            job.output_name = Path(resultado["output"]).name
        except RenderCancelled:
            job.status = "cancelled"
            job.message = "Cancelado"
            job.error = "Renderização cancelada pelo usuário"
            _apagar_arquivo(destino)
        except Exception as e:  # noqa: BLE001 - a mensagem vai para a interface
            job.status = "error"
            job.message = "Falhou"
            job.error = str(e)
            _apagar_arquivo(destino)
        finally:
            job._process = None
            job.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self._notify(job)

    def get(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise RenderError(f"Tarefa não encontrada: {job_id}")
            return job.snapshot()

    def list(self, project_id: Optional[str] = None) -> list[dict]:
        with self._lock:
            jobs = [j for j in self._jobs.values() if not project_id or j.project_id == project_id]
            jobs.sort(key=lambda j: j.created_at, reverse=True)
            return [j.snapshot() for j in jobs[:20]]

    def cancel(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise RenderError(f"Tarefa não encontrada: {job_id}")
            if job.status in {"done", "error", "cancelled"}:
                return job.snapshot()
            job._cancel.set()
            job.message = "Cancelando"
            processo = job._process
            if processo is not None and processo.poll() is None:
                processo.terminate()
            return job.snapshot()

    def _prune(self) -> None:
        if len(self._jobs) <= MAX_JOBS:
            return
        concluídos = [j for j in self._jobs.values() if j.status in {"done", "error", "cancelled"}]
        concluídos.sort(key=lambda j: j.created_at)
        for job in concluídos[: max(0, len(self._jobs) - MAX_JOBS)]:
            self._jobs.pop(job.id, None)


MANAGER = RenderManager()
