"""
Medição do conteúdo dos clipes com FFmpeg.

Cenas, pausas e loudness saem dos filtros reais (`scdet`, `silencedetect`,
`ebur128`) rodados na janela exata que o clipe ocupa no arquivo. Nada aqui toca
no projeto: quem transforma medida em anotação é `editor_project.annotate`, e a
anotação é um candidato que o editor (humano ou IA) revisa antes de cortar.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Optional

from editor_project import (
    ProjectError,
    clip_duration,
    format_timecode,
    get_clip,
    probe_media,
)

FFMPEG = "ffmpeg"


def _round(value: float) -> float:
    """Mesma granularidade do motor: 3 decimais, para os tempos baterem com o projeto."""
    return round(float(value), 3)

KINDS = ("scenes", "silence", "loudness")

# Nome do grupo de anotação que cada análise grava na timeline. `loudness` mede,
# não marca nada, então o grupo é vazio e a interface esconde "Limpar".
GROUPS = {"scenes": "cenas", "silence": "pausas", "loudness": ""}

# Mais que isso na timeline vira ruído visual e o FFmpeg já está lendo o arquivo
# inteiro; a mensagem diz para estreitar a janela em vez de silenciar o resto.
MAX_CANDIDATOS = 200

_TIMEOUT = 900


def run_ffmpeg_log(args: list[str], timeout: int = _TIMEOUT) -> str:
    """
    Roda FFmpeg sem gerar arquivo e devolve o log de stderr.

    Os filtros de análise escrevem as medidas no stderr, então o que importa é o
    texto. `editor_render` também consome isto: uma única leitura de FFmpeg para
    medir e para conferir o render, sem duas implementações divergindo.
    """
    comando = [FFMPEG, "-hide_banner", "-nostats", *args]
    try:
        resultado = subprocess.run(
            comando,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError:
        raise ProjectError("FFmpeg não encontrado. Instale e adicione ao PATH.") from None
    except subprocess.TimeoutExpired:
        raise ProjectError(f"O FFmpeg demorou mais de {timeout}s para analisar o material") from None
    stderr = resultado.stderr or ""
    if resultado.returncode != 0:
        ultima = stderr.strip().splitlines()[-1] if stderr.strip() else f" FFmpeg saiu com código {resultado.returncode}"
        raise ProjectError("Falha na análise: " + ultima[:300])
    return stderr


# ---------------------------------------------------------------------------
# Leitura das medidas
# ---------------------------------------------------------------------------

_NUMERO = r"(-?\d+(?:\.\d+)?)"


def parse_scene_log(texto: str) -> list[dict]:
    """Extrai (tempo relativo ao início da leitura, score) do log do `scdet`."""
    pares = re.findall(
        rf"lavfi\.scd\.score:\s*{_NUMERO},\s*lavfi\.scd\.time:\s*{_NUMERO}",
        texto,
    )
    vistos: set[float] = set()
    cenas: list[dict] = []
    for nota, tempo in pares:
        valor = round(float(tempo), 2)
        if valor in vistos:
            continue
        vistos.add(valor)
        cenas.append({"time": valor, "score": round(float(nota), 1)})
    cenas.sort(key=lambda item: item["time"])
    return cenas


def parse_silence_log(texto: str, total: float) -> list[dict]:
    """Emparelha `silence_start`/`silence_end` do log do `silencedetect`."""
    inicios = [float(v) for v in re.findall(rf"silence_start:\s*{_NUMERO}", texto)]
    fins = [float(v) for v in re.findall(rf"silence_end:\s*{_NUMERO}", texto)]
    pausas: list[dict] = []
    for indice, inicio in enumerate(inicios):
        fim = fins[indice] if indice < len(fins) else total
        fim = min(fim, total) if total else fim
        if fim > inicio:
            pausas.append({
                "start": round(inicio, 3),
                "end": round(fim, 3),
                "duration": round(fim - inicio, 3),
            })
    return pausas


def parse_ebur128(texto: str) -> dict:
    """Lê loudness integrado, LRA e true peak do resumo do `ebur128`."""
    medidas: dict = {}
    integrados = re.findall(rf"I:\s*{_NUMERO}\s*LUFS", texto)
    lras = re.findall(rf"LRA:\s*{_NUMERO}\s*LU", texto)
    peaks = re.findall(rf"Peak:\s*{_NUMERO}\s*dBFS", texto)
    if integrados:
        medidas["integrated_lufs"] = float(integrados[-1])
    if lras:
        medidas["lra_lu"] = float(lras[-1])
    if peaks:
        medidas["true_peak_dbfs"] = float(peaks[-1])
    return medidas


def parse_black_log(texto: str) -> list[list[float]]:
    """Trechos `[início, fim]` com quadro preto lidos do `blackdetect`."""
    return [
        [round(float(match.group(1)), 3), round(float(match.group(2)), 3)]
        for match in re.finditer(rf"black_start:{_NUMERO}\s+black_end:{_NUMERO}", texto)
    ]


# ---------------------------------------------------------------------------
# Medição por arquivo (tempos na janela lida)
# ---------------------------------------------------------------------------

def _janela(source: str | Path, start: float, end: Optional[float]) -> tuple[Path, float, float, dict]:
    """Resolve (arquivo, início, fim, metadados) da janela a ler, validando o recorte."""
    arquivo = Path(source).expanduser()
    if not arquivo.is_file():
        raise ProjectError(f"Arquivo não encontrado: {source}")
    info = probe_media(arquivo)
    limite = float(end) if end is not None else float(info["duration"])
    inicio = max(0.0, float(start))
    if limite <= inicio:
        raise ProjectError("O fim da janela precisa ser maior que o início")
    if info["duration"] and limite > info["duration"] + 0.05:
        raise ProjectError(
            f"Janela até {format_timecode(limite)} passa do arquivo "
            f"({format_timecode(info['duration'])})"
        )
    return arquivo, inicio, limite, info


def _leitura_em_janela(inicio: float, fim: float) -> str:
    """
    Filtro que recorta o áudio já decodificado na janela lida.

    O recorte acontece depois de `-i`, dentro do `-af`, e não com `-ss` na
    entrada: seek de entrada descarta o quadrinho de priming do decodificador AAC
    e a medição sai falsa. No material de teste, o true peak do arquivo inteiro
    veio 0,1 dBFS com `-ss` na entrada e 3,9 dBFS com o recorte em `atrim` — o
    pico verdadeiro estava exatamente nesses 21 ms descartados. Áudio decodifica
    rápido, então ler do começo e recortar custa pouco e mede certo.

    O `asetpts` devolve a contagem para zero, então quem recebe os tempos continua
    trabalhando com tempo relativo ao início da janela, igual ao `-ss` das cenas.
    """
    return f"atrim=start={inicio:g}:end={fim:g},asetpts=PTS-STARTPTS"


def scene_cuts(
    source: str | Path,
    start: float = 0.0,
    end: Optional[float] = None,
    threshold: float = 15,
) -> list[dict]:
    """
    Pontos de troca de cena no recorte, com o score do `scdet`.

    Os tempos são relativos ao início da janela lida; quem chama converte para o
    arquivo (soma `start`) e para a timeline (divisão pela velocidade).
    """
    limite = float(threshold)
    if not 1 <= limite <= 100:
        raise ProjectError("O threshold das cenas deve estar entre 1 e 100")
    arquivo, inicio, fim, info = _janela(source, start, end)
    if not info["has_video"]:
        raise ProjectError(f"{arquivo.name} não tem vídeo para detectar cenas")
    texto = run_ffmpeg_log([
        "-ss", f"{inicio:g}", "-t", f"{max(0.0, fim - inicio):g}", "-i", str(arquivo),
        "-an", "-sn", "-vf", f"scdet=threshold={limite:g}", "-f", "null", "-",
    ])
    return parse_scene_log(texto)


def silence_ranges(
    source: str | Path,
    start: float = 0.0,
    end: Optional[float] = None,
    noise: float = -30.0,
    min_pause: float = 0.5,
) -> list[dict]:
    """Intervalos de silêncio do recorte, medidos pelo `silencedetect`."""
    minimo = float(min_pause)
    if not 0.05 <= minimo <= 60:
        raise ProjectError("A duração mínima da pausa deve estar entre 0,05 e 60 segundos")
    limiar = float(noise)
    if not -90 <= limiar <= 0:
        raise ProjectError("O limiar de ruído deve estar entre -90 e 0 dB")
    arquivo, inicio, fim, info = _janela(source, start, end)
    if not info["has_audio"]:
        raise ProjectError(f"{arquivo.name} não tem áudio para detectar pausas")
    duracao = max(0.0, fim - inicio)
    texto = run_ffmpeg_log([
        "-i", str(arquivo), "-vn", "-sn",
        "-af", f"{_leitura_em_janela(inicio, fim)},silencedetect=noise={limiar:g}dB:d={minimo:g}",
        "-f", "null", "-",
    ])
    return parse_silence_log(texto, duracao)


def loudness(
    source: str | Path,
    start: float = 0.0,
    end: Optional[float] = None,
) -> dict:
    """Loudness integrado, LRA e true peak do recorte, medidos pelo `ebur128`."""
    arquivo, inicio, fim, info = _janela(source, start, end)
    if not info["has_audio"]:
        raise ProjectError(f"{arquivo.name} não tem áudio para medir loudness")
    texto = run_ffmpeg_log([
        "-i", str(arquivo), "-vn", "-sn",
        "-af", f"{_leitura_em_janela(inicio, fim)},ebur128=peak=true", "-f", "null", "-",
    ])
    medidas = parse_ebur128(texto)
    if not medidas:
        raise ProjectError(f"O ebur128 não devolveu medida para {arquivo.name}")
    return medidas


# ---------------------------------------------------------------------------
# Medição por clipe do projeto
# ---------------------------------------------------------------------------

def _projecao(clip: dict, tempo_na_janela: float) -> tuple[float, float]:
    """Converte um tempo lido na janela em (tempo no arquivo, tempo na timeline)."""
    ini = float(clip.get("in", 0) or 0)
    velocidade = max(0.01, float(clip.get("speed", 1) or 1))
    no_arquivo = _round(ini + tempo_na_janela)
    na_timeline = _round(float(clip.get("start", 0)) + tempo_na_janela / velocidade)
    return no_arquivo, na_timeline


def analyze_clip(project: dict, clip_id: str, kind: str = "scenes", **opts: Any) -> dict:
    """
    Analisa um clipe de mídia e devolve candidatos em tempo de timeline.

    `kind` aceita `scenes` (cortes de cena), `silence` (pausas) e `loudness`
    (medida de áudio). A função não escreve nada no projeto — o retorno traz os
    candidatos prontos para `annotate`, e `loudness` não tem candidato nenhum: é
    só número, porque diagnosticar antes de processar é a regra.
    """
    tipo = (kind or "scenes").strip().lower()
    if tipo not in KINDS:
        raise ProjectError(
            f"Análise desconhecida: {kind}. Use 'scenes', 'silence' ou 'loudness'."
        )
    track, clip = get_clip(project, clip_id)
    if clip.get("type") not in {"video", "audio"}:
        raise ProjectError("Só clipes de mídia podem ser analisados (títulos e legendas não têm arquivo)")

    ini = float(clip.get("in", 0) or 0)
    duracao = clip_duration(clip) * max(0.01, float(clip.get("speed", 1) or 1))
    fim = _round(ini + duracao)
    origem = str(clip.get("source") or "")

    resultado: dict = {
        "kind": tipo,
        "group": GROUPS[tipo],
        "clip_id": clip_id,
        "track_id": track["id"],
        "name": clip.get("name", Path(origem).name),
        "window": {
            "file_start": _round(ini),
            "file_end": fim,
            "timeline_start": _round(float(clip.get("start", 0))),
            "timeline_end": _round(float(clip.get("start", 0)) + clip_duration(clip)),
            "speed": float(clip.get("speed", 1) or 1),
        },
        "candidates": [],
    }

    if tipo == "loudness":
        medidas = loudness(origem, ini, fim)
        resultado["measurements"] = medidas
        jan = resultado["window"]
        resultado["summary"] = (
            f"{medidas.get('integrated_lufs', '?')} LUFS integrado, "
            f"LRA {medidas.get('lra_lu', '?')} LU, "
            f"pico {medidas.get('true_peak_dbfs', '?')} dBFS em {resultado['name']} "
            f"({_round(jan['file_end'] - jan['file_start'])}s de arquivo, "
            f"{_round(jan['timeline_end'] - jan['timeline_start'])}s na timeline)"
        )
        return resultado

    truncado = False
    if tipo == "scenes":
        cortes = scene_cuts(origem, ini, fim, threshold=float(opts.get("threshold", 15)))
        if len(cortes) > MAX_CANDIDATOS:
            truncado = True
            cortes = cortes[:MAX_CANDIDATOS]
        candidatos = []
        for corte in cortes:
            no_arquivo, na_timeline = _projecao(clip, corte["time"])
            candidatos.append({
                "time": na_timeline,
                "source_time": no_arquivo,
                "score": corte["score"],
                "label": f"Cena {format_timecode(na_timeline)}",
            })
        resultado["threshold"] = float(opts.get("threshold", 15))
        achado = f"{len(candidatos)} troca(s) de cena"
    else:
        pausas = silence_ranges(
            origem,
            ini,
            fim,
            noise=float(opts.get("noise", -30.0)),
            min_pause=float(opts.get("min_pause", 0.5)),
        )
        if len(pausas) > MAX_CANDIDATOS:
            truncado = True
            pausas = pausas[:MAX_CANDIDATOS]
        candidatos = []
        for pausa in pausas:
            inicio_arq, inicio_tl = _projecao(clip, pausa["start"])
            fim_arq, fim_tl = _projecao(clip, pausa["end"])
            candidatos.append({
                "start": inicio_tl,
                "end": fim_tl,
                # O corte remove o tempo de timeline; o de arquivo é o que o FFmpeg viu.
                "duration": _round(fim_tl - inicio_tl),
                "source_start": inicio_arq,
                "source_end": fim_arq,
                "source_duration": _round(pausa["duration"]),
                "label": f"Pausa {_round(fim_tl - inicio_tl):.1f}s",
            })
        resultado["noise"] = float(opts.get("noise", -30.0))
        resultado["min_pause"] = float(opts.get("min_pause", 0.5))
        total = _round(sum(c["duration"] for c in candidatos))
        achado = f"{len(candidatos)} pausa(s) de silêncio, {total}s cortados na timeline"

    resultado["candidates"] = candidatos
    resultado["summary"] = f"{resultado['name']}: {achado} entre " \
        f"{format_timecode(resultado['window']['timeline_start'])} e " \
        f"{format_timecode(resultado['window']['timeline_end'])}"
    if truncado:
        resultado["summary"] += (
            f" (limitado a {MAX_CANDIDATOS}; estreite a janela ou aumente o limiar)"
        )
    if not candidatos:
        resultado["summary"] += "; nada encontrado com esses parâmetros"
    return resultado


def build_annotations(analysis: dict) -> dict:
    """
    Converte a análise nos parâmetros da operação `annotate`.

    Cena é marcador (um ponto); pausa é região (um intervalo) — a forma como a
    timeline já mostra cada coisa. O `group` permite limpar só uma análise sem
    apagar os marcadores que o editor fez à mão.

    Sempre devolve `markers` e `regions`, mesmo vazios: o resultado vai direto
    como parâmetro de `annotate`, e uma chave ausente estouraria a rota inteira.
    """
    kind = analysis["kind"]
    candidatos = analysis["candidates"]
    if kind == "scenes":
        return {
            "group": GROUPS["scenes"],
            "markers": [
                {"time": item["time"], "label": item["label"], "color": "#fbbf24"}
                for item in candidatos
            ],
            "regions": [],
        }
    if kind == "silence":
        return {
            "group": GROUPS["silence"],
            "markers": [],
            "regions": [
                {"start": item["start"], "end": item["end"], "label": item["label"], "color": "#4f8cff"}
                for item in candidatos
            ],
        }
    return {"group": GROUPS.get(kind, ""), "markers": [], "regions": []}
