"""
Medição do conteúdo dos clipes com FFmpeg.

Cenas, pausas, loudness e a curva de pico por instante saem dos filtros reais
(`scdet`, `silencedetect`, `ebur128`, `astats`) rodados na janela exata que o
clipe ocupa no arquivo. Nada aqui toca no projeto: quem transforma medida em
anotação é `editor_project.annotate`, e a anotação é um candidato que o editor
(humano ou IA) revisa antes de cortar.
"""

from __future__ import annotations

import math
import re
import statistics
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

KINDS = ("scenes", "silence", "loudness", "peaks")

# Nome do grupo de anotação que cada análise grava na timeline. `loudness` mede,
# não marca nada, então o grupo é vazio e a interface esconde "Limpar".
GROUPS = {"scenes": "cenas", "silence": "pausas", "loudness": "", "peaks": "picos"}

# Mais que isso na timeline vira ruído visual e o FFmpeg já está lendo o arquivo
# inteiro; a mensagem diz para estreitar a janela em vez de silenciar o resto.
MAX_CANDIDATOS = 200

# Teto da curva devolvida à interface: 10 minutos a 0,1 s dariam 6000 pontos no
# JSON; acima disso o passo cresce e a leitura continua fiel no que importa (o
# pico de cada trecho), só menos fina no tempo.
MAX_CURVA_PONTOS = 600

# Abaixo disto o quadro é silêncio para efeito de mediana. Sem esse piso, um
# arquivo com muito silêncio puxaria a mediana para -inf e qualquer som viraria
# "pico". O valor é um piso de audibilidade declarado, não uma medida.
AUDIBLE_DBFS = -60.0

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


_PTS_QUADRO = re.compile(r"pts_time:(\S+)")
_NIVEL_QUADRO = re.compile(r"lavfi\.astats\.Overall\.Peak_level=(\S+)")


def parse_peak_log(texto: str, interval: float = 0.1, total: Optional[float] = None) -> list[dict]:
    """
    Curva de pico por instante a partir do `astats` com `ametadata=print`.

    O astats é reiniciado a cada quadro de áudio (1024 amostras, ~21 ms) e imprime
    um bloco `frame:… pts_time:…` seguido de `lavfi.astats.Overall.Peak_level`.
    Cada quadro vale o maior pico absoluto entre os canais, em dBFS; `-inf` é
    silêncio digital e vira `None`, para ninguém ler `-inf` como número.

    O passo agrupa vários quadros e fica com o maior pico do intervalo — a curva
    mostra onde o nível está alto, não a média do trecho.
    """
    passo = float(interval)
    blocos = re.split(r"frame:\d+", texto)[1:]
    bins: dict[int, Optional[float]] = {}
    ultimo = -1
    for bloco in blocos:
        tempo = _PTS_QUADRO.search(bloco)
        nivel = _NIVEL_QUADRO.search(bloco)
        if not tempo or not nivel:
            continue
        try:
            instante = float(tempo.group(1))
            valor: Optional[float] = float(nivel.group(1))
        except ValueError:
            continue
        if not math.isfinite(valor):
            valor = None
        if instante < 0 or (total is not None and instante >= float(total) + 1e-6):
            continue
        indice = int(instante / passo + 1e-6)
        atual = bins.get(indice)
        if valor is not None and (atual is None or valor > atual):
            bins[indice] = valor
        else:
            bins.setdefault(indice, None)
        ultimo = max(ultimo, indice)

    total_bins = int(math.ceil(float(total) / passo - 1e-9)) if total is not None else ultimo + 1
    total_bins = max(total_bins, ultimo + 1)
    return [
        {
            "time": round(indice * passo, 3),
            "peak_dbfs": None if bins.get(indice) is None else round(bins[indice], 2),
        }
        for indice in range(total_bins)
    ]


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


def _intervalo_da_curva(duracao: float, interval: float) -> float:
    """Passo efetivo da curva: respeita o pedido e o teto de pontos do JSON."""
    passo = float(interval)
    if not 0.05 <= passo <= 5:
        raise ProjectError("O intervalo da curva de pico deve estar entre 0,05 e 5 segundos")
    if duracao > 0 and duracao / passo > MAX_CURVA_PONTOS:
        passo = math.ceil(duracao / MAX_CURVA_PONTOS * 100) / 100
    return passo


def peak_curve(
    source: str | Path,
    start: float = 0.0,
    end: Optional[float] = None,
    interval: float = 0.1,
) -> dict:
    """
    Curva de pico por instante do recorte, medida quadro a quadro pelo `astats`.

    Devolve `{"interval": passo, "curve": [{"time", "peak_dbfs"}, …]}` com tempo
    relativo ao início da janela. Silêncio digital vem como `peak_dbfs: None`;
    acima de 0 dBFS o valor é positivo e real (o material de teste tem +3,9).

    A medição lê do começo do arquivo e recorta com `atrim`, pelo mesmo motivo do
    loudness: seek de entrada descarta o priming do AAC e mentiria no primeiro
    quadro.
    """
    arquivo, inicio, fim, info = _janela(source, start, end)
    if not info["has_audio"]:
        raise ProjectError(f"{arquivo.name} não tem áudio para medir picos")
    passo = _intervalo_da_curva(fim - inicio, interval)
    texto = run_ffmpeg_log([
        "-i", str(arquivo), "-vn", "-sn",
        "-af", (
            f"{_leitura_em_janela(inicio, fim)},"
            "astats=metadata=1:reset=1:measure_perchannel=none:"
            "measure_overall=Peak_level,ametadata=mode=print"
        ),
        "-f", "null", "-",
    ])
    curva = parse_peak_log(texto, passo, fim - inicio)
    if not curva:
        raise ProjectError(f"O astats não devolveu medida para {arquivo.name}")
    return {"interval": passo, "curve": curva}


def find_peaks(
    curve: list[dict],
    interval: float,
    rise: float = 6.0,
    min_gap: float = 1.0,
    floor: float = AUDIBLE_DBFS,
) -> dict:
    """
    Momentos da curva que passam de `rise` dB acima da mediana do trecho audível.

    A mediana é calculada só nos pontos acima do piso: silêncio não é nível
    típico. Trechos contíguos acima do limite viram um candidato só, no ponto
    mais alto; `min_gap` junta picos vizinhos pelo mais alto. Nada aqui corta
    nem altera o projeto — é a lista de onde o áudio sobe mais.
    """
    aumento = float(rise)
    if not 0 <= aumento <= 40:
        raise ProjectError("O aumento sobre a mediana deve estar entre 0 e 40 dB")
    distancia = float(min_gap)
    if not 0.1 <= distancia <= 60:
        raise ProjectError("A distância mínima entre picos deve estar entre 0,1 e 60 segundos")
    passo = float(interval)

    audiveis = [
        item["peak_dbfs"] for item in curve
        if item.get("peak_dbfs") is not None and item["peak_dbfs"] > floor
    ]
    if not audiveis:
        return {"peaks": [], "median_dbfs": None, "level_dbfs": None, "audible_points": 0}

    mediana = round(statistics.median(audiveis), 2)
    limite = round(mediana + aumento, 2)

    trechos: list[list[int]] = []
    atual: list[int] = []
    for indice, item in enumerate(curve):
        nivel = item.get("peak_dbfs")
        if nivel is not None and nivel > floor and nivel >= limite:
            atual.append(indice)
        elif atual:
            trechos.append(atual)
            atual = []
    if atual:
        trechos.append(atual)

    picos: list[dict] = []
    for indices in trechos:
        indice = max(indices, key=lambda posicao: curve[posicao]["peak_dbfs"])
        nivel = float(curve[indice]["peak_dbfs"])
        picos.append({
            "time": _round(curve[indice]["time"]),
            "peak_dbfs": round(nivel, 2),
            "over_median_db": round(nivel - mediana, 2),
            "duration": round(len(indices) * passo, 2),
        })

    escolhidos: list[dict] = []
    for pico in sorted(picos, key=lambda item: item["peak_dbfs"], reverse=True):
        if all(abs(pico["time"] - outro["time"]) >= distancia for outro in escolhidos):
            escolhidos.append(pico)
    escolhidos.sort(key=lambda item: item["time"])
    return {
        "peaks": escolhidos,
        "median_dbfs": mediana,
        "level_dbfs": limite,
        "audible_points": len(audiveis),
    }


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

    `kind` aceita `scenes` (cortes de cena), `silence` (pausas), `loudness`
    (medida de áudio) e `peaks` (curva de pico por instante e momentos acima do
    nível típico). A função não escreve nada no projeto — o retorno traz os
    candidatos prontos para `annotate`, e `loudness` não tem candidato nenhum: é
    só número, porque diagnosticar antes de processar é a regra.
    """
    tipo = (kind or "scenes").strip().lower()
    if tipo not in KINDS:
        raise ProjectError(
            f"Análise desconhecida: {kind}. Use 'scenes', 'silence', 'loudness' ou 'peaks'."
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
    sem_audivel = False
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
    elif tipo == "peaks":
        curva = peak_curve(origem, ini, fim, interval=float(opts.get("interval", 0.1)))
        deteccao = find_peaks(
            curva["curve"],
            curva["interval"],
            rise=float(opts.get("rise", 6.0)),
            min_gap=float(opts.get("min_gap", 1.0)),
        )
        velocidade = max(0.01, float(clip.get("speed", 1) or 1))
        resultado["interval"] = curva["interval"]
        resultado["curve"] = curva["curve"]
        resultado["median_dbfs"] = deteccao["median_dbfs"]
        resultado["level_dbfs"] = deteccao["level_dbfs"]
        resultado["rise"] = float(opts.get("rise", 6.0))
        resultado["min_gap"] = float(opts.get("min_gap", 1.0))
        if len(deteccao["peaks"]) > MAX_CANDIDATOS:
            truncado = True
        candidatos = []
        for pico in deteccao["peaks"][:MAX_CANDIDATOS]:
            no_arquivo, na_timeline = _projecao(clip, pico["time"])
            candidatos.append({
                "time": na_timeline,
                "source_time": no_arquivo,
                "peak_dbfs": pico["peak_dbfs"],
                "over_median_db": pico["over_median_db"],
                # Trecho alto em segundos, na timeline e no arquivo.
                "duration": _round(pico["duration"] / velocidade),
                "source_duration": pico["duration"],
                "label": f"Pico {pico['peak_dbfs']:.1f} dBFS",
            })
        if deteccao["median_dbfs"] is None:
            sem_audivel = True
            achado = (
                f"nenhum trecho acima de {AUDIBLE_DBFS:g} dBFS "
                "(silêncio ou nível muito baixo)"
            )
        else:
            achado = (
                f"{len(candidatos)} pico(s) acima de {deteccao['level_dbfs']:.1f} dBFS "
                f"(mediana {deteccao['median_dbfs']:.1f} dBFS, "
                f"curva de {len(curva['curve'])} pontos a cada {curva['interval']:g}s)"
            )
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
    if not candidatos and not sem_audivel:
        resultado["summary"] += "; nada encontrado com esses parâmetros"
    return resultado


def build_annotations(analysis: dict) -> dict:
    """
    Converte a análise nos parâmetros da operação `annotate`.

    Cena e pico são marcadores (um ponto); pausa é região (um intervalo) — a
    forma como a timeline já mostra cada coisa. O `group` permite limpar só uma
    análise sem apagar os marcadores que o editor fez à mão.

    Sempre devolve `markers` e `regions`, mesmo vazios: o resultado vai direto
    como parâmetro de `annotate`, e uma chave ausente estouraria a rota inteira.
    """
    kind = analysis["kind"]
    candidatos = analysis["candidates"]
    if kind in ("scenes", "peaks"):
        cor = "#fbbf24" if kind == "scenes" else "#f97316"
        return {
            "group": GROUPS[kind],
            "markers": [
                {"time": item["time"], "label": item["label"], "color": cor}
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
