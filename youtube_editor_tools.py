"""
Ferramentas de edição de vídeo do ClipMind.

Todas as funções executam FFmpeg de verdade, via subprocess. O agente de IA lê a
docstring de cada uma para saber quando chamá-la, então cada docstring diz o que
a ferramenta faz e o que cada parâmetro significa.

Convenção de retorno: string em português. Sucesso começa com o resultado e o
caminho do arquivo gerado; falha começa com "Erro:".
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Optional


OUTPUT_DIR = Path("./output")
FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


# ---------------------------------------------------------------------------
# Infraestrutura
# ---------------------------------------------------------------------------

def ensure_output_dir() -> Path:
    """Cria a pasta de saída se não existir."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


def get_output_path(video_path: str, suffix: str, extension: Optional[str] = None) -> Path:
    """
    Monta o caminho de saída: nome original + sufixo, dentro de OUTPUT_DIR.

    Se já existir, adiciona um contador (_2, _3, ...) para não sobrescrever uma
    edição anterior do mesmo vídeo.
    """
    ensure_output_dir()
    original = Path(video_path)
    ext = extension if extension else original.suffix
    caminho = OUTPUT_DIR / f"{original.stem}{suffix}{ext}"
    if not caminho.exists():
        return caminho
    for indice in range(2, 1000):
        alternativa = OUTPUT_DIR / f"{original.stem}{suffix}_{indice}{ext}"
        if not alternativa.exists():
            return alternativa
    return OUTPUT_DIR / f"{original.stem}{suffix}_{uuid.uuid4().hex[:6]}{ext}"


def run_ffmpeg(
    args: list[str],
    error_message: str = "Erro ao executar FFmpeg",
    cwd: Optional[Path] = None,
) -> tuple[bool, str]:
    """
    Executa o FFmpeg e devolve (sucesso, mensagem).

    O stderr é truncado no final porque o FFmpeg costuma despejar centenas de
    linhas e o agente não precisa delas.
    """
    try:
        subprocess.run(
            [FFMPEG, "-hide_banner", "-loglevel", "error", *args],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(cwd) if cwd else None,
        )
        return True, "Comando executado com sucesso"
    except subprocess.CalledProcessError as e:
        detalhe = (e.stderr or "").strip()
        return False, f"{error_message}: {detalhe[-800:]}"
    except FileNotFoundError:
        return False, "FFmpeg não encontrado. Instale e adicione ao PATH."
    except Exception as e:  # noqa: BLE001 - a mensagem vai para o usuário
        return False, f"{error_message}: {e}"


def _probe(path: Path) -> dict:
    """Roda ffprobe e devolve o JSON bruto (ou {} em caso de falha)."""
    try:
        saida = subprocess.run(
            [
                FFPROBE, "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return json.loads(saida or "{}")
    except Exception:
        return {}


def _media(path: Path) -> dict:
    """Resumo técnico do arquivo: duração, stream de vídeo e de áudio."""
    dados = _probe(path)
    info: dict = {
        "duration": 0.0,
        "video": None,
        "audio": None,
        "size": int(dados.get("format", {}).get("size", 0) or 0),
    }
    try:
        info["duration"] = float(dados.get("format", {}).get("duration", 0) or 0)
    except (TypeError, ValueError):
        info["duration"] = 0.0

    for stream in dados.get("streams", []):
        tipo = stream.get("codec_type")
        if tipo == "video" and stream.get("disposition", {}).get("attached_pic") != 1:
            if info["video"] is None:
                info["video"] = stream
        elif tipo == "audio" and info["audio"] is None:
            info["audio"] = stream
    return info


def _duration(path: Path) -> float:
    """Duração em segundos."""
    return _media(path)["duration"]


def _has_audio(path: Path) -> bool:
    """True se o arquivo tem stream de áudio."""
    return _media(path)["audio"] is not None


def _cut_output_ok(path: Path, esperado: float) -> bool:
    """Confere se o corte gerou vídeo e uma duração próxima da pedida."""
    info = _media(path)
    if info["video"] is None or info["duration"] <= 0:
        return False
    if esperado > 0 and abs(info["duration"] - esperado) > 1.5:
        return False
    return True


def _parse_time(valor: str | float) -> float:
    """Converte '90', '01:30' ou '00:01:30.500' em segundos."""
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip().replace(",", ".")
    if not texto:
        raise ValueError("tempo vazio")
    partes = texto.split(":")
    if len(partes) > 3:
        raise ValueError(f"tempo inválido: {valor}")
    total = 0.0
    for parte in partes:
        total = total * 60 + float(parte)
    return total


def _fmt_time(segundos: float) -> str:
    """Formata segundos como HH:MM:SS."""
    total = max(0, int(segundos))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def _num(valor: str | float, campo: str) -> float:
    """Converte um parâmetro numérico vindo do modelo/usuário."""
    try:
        return float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        raise ValueError(f"'{campo}' precisa ser um número") from None


def _check_file(caminho: str, rotulo: str = "Arquivo") -> Optional[str]:
    """Devolve mensagem de erro se o arquivo não existir, senão None."""
    if not Path(caminho).exists():
        return f"Erro: {rotulo} não encontrado: {caminho}"
    return None


def _concat_quote(caminho: Path) -> str:
    """Formata um caminho para o arquivo de lista do concat demuxer."""
    return "file '" + caminho.as_posix().replace("'", "'\\''") + "'"


def _font_path() -> Optional[Path]:
    """Primeira fonte TrueType disponível no Windows."""
    candidatos = [
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeuib.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/calibrib.ttf"),
    ]
    for fonte in candidatos:
        if fonte.exists():
            return fonte
    return None


def _build_trim_concat(
    faixas: list[tuple[float, float]],
    has_audio: bool,
) -> str:
    """
    Monta um filter_complex que mantém só as faixas dadas e as emenda.

    Usado por cut_multiple_segments e remove_silence; re-codifica para que
    vídeo e áudio fiquem exatamente do mesmo tamanho (sem dessincronizar).
    """
    partes: list[str] = []
    rotulos: list[str] = []
    for indice, (inicio, fim) in enumerate(faixas):
        partes.append(
            f"[0:v]trim=start={inicio:.3f}:end={fim:.3f},setpts=PTS-STARTPTS[v{indice}]"
        )
        if has_audio:
            partes.append(
                f"[0:a]atrim=start={inicio:.3f}:end={fim:.3f},"
                f"asetpts=PTS-STARTPTS[a{indice}]"
            )
            rotulos.append(f"[v{indice}][a{indice}]")
        else:
            rotulos.append(f"[v{indice}]")

    saida = "[outv][outa]" if has_audio else "[outv]"
    partes.append(
        "".join(rotulos) + f"concat=n={len(faixas)}:v=1:a={1 if has_audio else 0}{saida}"
    )
    return ";".join(partes)


def _encode_args(
    video_codec: str = "libx264",
    crf: str = "20",
    preset: str = "veryfast",
    audio_bitrate: str = "192k",
) -> list[str]:
    """Argumentos de codificação padrão (H.264 + AAC, compatível com YouTube)."""
    return [
        "-c:v", video_codec, "-preset", preset, "-crf", crf,
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", audio_bitrate,
        "-movflags", "+faststart",
    ]


# ---------------------------------------------------------------------------
# Análise
# ---------------------------------------------------------------------------

def inspect_video(video_path: str) -> str:
    """
    Analisa um vídeo e retorna metadados completos em JSON.

    Inclui duração, resolução, codecs de vídeo/áudio, FPS, bitrate, tamanho e
    formato. Use esta ferramenta antes de qualquer edição quando o usuário não
    souber as características do arquivo.

    Args:
        video_path: caminho do vídeo a analisar.

    Returns:
        JSON com as informações ou mensagem de erro.
    """
    path = Path(video_path)
    if not path.exists():
        return json.dumps({"erro": f"Arquivo não encontrado: {video_path}"}, ensure_ascii=False)

    dados = _probe(path)
    if not dados:
        return json.dumps({"erro": "Não foi possível ler o vídeo com ffprobe"}, ensure_ascii=False)

    try:
        info = {
            "arquivo": path.name,
            "caminho": str(path.absolute()),
            "formato": dados.get("format", {}).get("format_name", "desconhecido"),
            "duracao_segundos": float(dados.get("format", {}).get("duration", 0) or 0),
            "tamanho_bytes": int(dados.get("format", {}).get("size", 0) or 0),
            "bitrate_total": dados.get("format", {}).get("bit_rate", "desconhecido"),
            "streams": [],
        }

        for stream in dados.get("streams", []):
            item = {
                "tipo": stream.get("codec_type", "desconhecido"),
                "codec": stream.get("codec_name", "desconhecido"),
            }
            if stream.get("codec_type") == "video":
                item.update({
                    "largura": stream.get("width", 0),
                    "altura": stream.get("height", 0),
                    "resolucao": f"{stream.get('width', 0)}x{stream.get('height', 0)}",
                    "fps": stream.get("r_frame_rate", "desconhecido"),
                    "bitrate": stream.get("bit_rate", "desconhecido"),
                    "pix_fmt": stream.get("pix_fmt", "desconhecido"),
                })
            elif stream.get("codec_type") == "audio":
                item.update({
                    "sample_rate": stream.get("sample_rate", "desconhecido"),
                    "channels": stream.get("channels", 0),
                    "bitrate": stream.get("bit_rate", "desconhecido"),
                })
            elif stream.get("codec_type") == "subtitle":
                item["idioma"] = stream.get("tags", {}).get("language", "?")
            info["streams"].append(item)

        info["duracao_formato"] = _fmt_time(info["duracao_segundos"])
        info["tem_video"] = any(s["tipo"] == "video" for s in info["streams"])
        info["tem_audio"] = any(s["tipo"] == "audio" for s in info["streams"])
        return json.dumps(info, indent=2, ensure_ascii=False)

    except Exception as e:  # noqa: BLE001
        return json.dumps({"erro": f"Erro inesperado: {e}"}, ensure_ascii=False)


def detect_scenes(video_path: str, threshold: str = "15") -> str:
    """
    Detecta trocas de cena (cortes) no vídeo e devolve os tempos em JSON.

    Útil para sugerir capítulos, achar pontos de corte naturais ou dividir um
    vídeo longo. Não altera o arquivo.

    Args:
        video_path: caminho do vídeo.
        threshold: sensibilidade de 1 a 100 (padrão 15). Menor = detecta mais.

    Returns:
        JSON com a lista de tempos de corte e a pontuação de cada mudança.
    """
    erro = _check_file(video_path)
    if erro:
        return erro
    try:
        limite = _num(threshold, "threshold")
        if not 1 <= limite <= 100:
            return "Erro: threshold deve estar entre 1 e 100"
    except ValueError as e:
        return f"Erro: {e}"

    comando = [
        FFMPEG, "-hide_banner", "-nostats", "-i", video_path, "-an", "-sn",
        "-vf", f"scdet=threshold={limite:g}",
        "-f", "null", "-",
    ]
    try:
        processo = subprocess.run(comando, capture_output=True, text=True)
    except FileNotFoundError:
        return "Erro: FFmpeg não encontrado. Instale e adicione ao PATH."

    texto = processo.stderr or ""
    pares = re.findall(
        r"lavfi\.scd\.score:\s*([0-9]+(?:\.[0-9]+)?),\s*"
        r"lavfi\.scd\.time:\s*([0-9]+(?:\.[0-9]+)?)",
        texto,
    )
    vistos: set[float] = set()
    cenas: list[dict] = []
    for nota, tempo_txt in pares:
        tempo = round(float(tempo_txt), 2)
        if tempo in vistos:
            continue
        vistos.add(tempo)
        cenas.append({"tempo": tempo, "formato": _fmt_time(tempo), "score": round(float(nota), 1)})
    cenas.sort(key=lambda c: c["tempo"])
    return json.dumps(
        {"total_cenas": len(cenas), "cenas": cenas[:200]},
        ensure_ascii=False,
        indent=2,
    )


# ---------------------------------------------------------------------------
# Corte
# ---------------------------------------------------------------------------

def cut_video(video_path: str, start: str, end: Optional[str] = None, duration: Optional[str] = None) -> str:
    """
    Corta um trecho do vídeo, do início informado até o fim ou até uma duração.

    Use 'end' OU 'duration', nunca os dois. O corte usa stream copy (rápido,
    sem re-codificação).

    Args:
        video_path: caminho do vídeo original.
        start: início (ex: "00:01:30", "01:30" ou "90").
        end: fim (ex: "00:03:45").
        duration: quanto tempo manter a partir do início (ex: "00:02:15").

    Returns:
        Caminho do arquivo gerado ou mensagem de erro.
    """
    erro = _check_file(video_path)
    if erro:
        return erro
    if not end and not duration:
        return "Erro: informe 'end' ou 'duration'"
    if end and duration:
        return "Erro: informe apenas 'end' OU 'duration', não os dois"

    saida = get_output_path(video_path, "_cortado")
    args = ["-y", "-i", video_path, "-ss", start]
    if end:
        args.extend(["-to", end])
    else:
        args.extend(["-t", duration])
    args.extend(["-c", "copy", "-avoid_negative_ts", "make_zero", str(saida)])

    # Stream copy só funciona se houver keyframe dentro do trecho. Em vídeos
    # com GOP longo o FFmpeg descarta todo o vídeo e sobra só o áudio; nesse
    # caso refazemos o corte re-codificando com precisão.
    try:
        esperado = _parse_time(end) - _parse_time(start) if end else _parse_time(duration or "")
    except ValueError:
        esperado = 0.0

    ok, msg = run_ffmpeg(args, "Erro ao cortar vídeo")
    if ok and _cut_output_ok(saida, esperado):
        return f"Vídeo cortado! Arquivo salvo em: {saida.absolute()}"

    precisos = ["-y", "-ss", start, "-i", video_path]
    if end:
        precisos.extend(["-t", f"{esperado:.3f}"])
    else:
        precisos.extend(["-t", duration])
    precisos.extend(_encode_args_visual())
    precisos.append(str(saida))

    ok, msg = run_ffmpeg(precisos, "Erro ao cortar vídeo")
    if not ok:
        return msg
    if not _cut_output_ok(saida, esperado):
        return "Erro: o corte saiu vazio. Verifique se o início/fim existem no vídeo."
    return f"Vídeo cortado! Arquivo salvo em: {saida.absolute()}"


def cut_multiple_segments(video_path: str, segments: str) -> str:
    """
    Mantém vários trechos do vídeo e descarta o resto, emendando os trechos.

    Ideal para "deixe só as melhores partes" ou para tirar várias pausas.
    Re-codifica para emendar com precisão.

    Args:
        video_path: caminho do vídeo original.
        segments: trechos separados por vírgula, cada um "início-fim"
                  (ex: "00:00:05-00:00:12, 00:02:00-00:02:40").

    Returns:
        Caminho do arquivo gerado ou mensagem de erro.
    """
    erro = _check_file(video_path)
    if erro:
        return erro

    path = Path(video_path)
    faixas: list[tuple[float, float]] = []
    for pedaco in re.split(r"[,;]", segments or ""):
        pedaco = pedaco.strip()
        if not pedaco:
            continue
        if "-" not in pedaco:
            return f"Erro: trecho inválido '{pedaco}'. Use início-fim (ex: 00:00:05-00:00:12)"
        inicio_txt, fim_txt = pedaco.rsplit("-", 1)
        try:
            inicio, fim = _parse_time(inicio_txt), _parse_time(fim_txt)
        except ValueError:
            return f"Erro: tempo inválido no trecho '{pedaco}'"
        if fim <= inicio:
            return f"Erro: o fim deve ser maior que o início no trecho '{pedaco}'"
        faixas.append((inicio, fim))

    if not faixas:
        return "Erro: informe ao menos um trecho no formato início-fim"

    tem_audio = _has_audio(path)
    filtro = _build_trim_concat(faixas, tem_audio)
    saida = get_output_path(video_path, "_cortes")

    args = ["-y", "-i", video_path, "-filter_complex", filtro, "-map", "[outv]"]
    if tem_audio:
        args.extend(["-map", "[outa]"])
    args.extend(_encode_args())
    args.append(str(saida))

    ok, msg = run_ffmpeg(args, "Erro ao cortar trechos")
    if not ok:
        return msg
    total = _duration(saida)
    return (
        f"{len(faixas)} trecho(s) emendados ({_fmt_time(total)})! "
        f"Arquivo salvo em: {saida.absolute()}"
    )


def remove_silence(video_path: str, noise: str = "-30dB", duration: str = "0.5") -> str:
    """
    Remove pausas/silêncios do vídeo cortando o trecho, como um editor faria.

    Detecta os silêncios e emenda apenas as partes com som, mantendo vídeo e
    áudio sincronizados. Bom para aulas e lives.

    Args:
        video_path: caminho do vídeo.
        noise: limiar em dB (padrão "-30dB"). Mais negativo = só silêncio real.
        duration: duração mínima do silêncio em segundos (padrão 0.5).

    Returns:
        Caminho do arquivo gerado ou mensagem de erro.
    """
    erro = _check_file(video_path)
    if erro:
        return erro

    path = Path(video_path)
    if not _has_audio(path):
        return "Erro: o vídeo não tem faixa de áudio para analisar"

    try:
        minimo = _num(duration, "duration")
    except ValueError as e:
        return f"Erro: {e}"

    comando = [
        FFMPEG, "-hide_banner", "-nostats", "-i", str(path),
        "-af", f"silencedetect=noise={noise}:d={minimo}",
        "-f", "null", "-",
    ]
    try:
        processo = subprocess.run(comando, capture_output=True, text=True)
    except FileNotFoundError:
        return "Erro: FFmpeg não encontrado. Instale e adicione ao PATH."

    texto = processo.stderr or ""
    inicios = [float(v) for v in re.findall(r"silence_start:\s*([0-9.]+)", texto)]
    fins = [float(v) for v in re.findall(r"silence_end:\s*([0-9.]+)", texto)]
    if not inicios:
        return "Nenhum silêncio encontrado com esses parâmetros; o vídeo ficou igual."

    total = _duration(path) or max(fins or [0])
    silencios: list[tuple[float, float]] = []
    for indice, inicio in enumerate(inicios):
        fim = fins[indice] if indice < len(fins) else total
        if fim > inicio:
            silencios.append((inicio, fim))

    # Constrói as faixas que sobram (o inverso dos silêncios).
    faixas: list[tuple[float, float]] = []
    cursor = 0.0
    for inicio, fim in silencios:
        if inicio - cursor > 0.15:
            faixas.append((cursor, inicio))
        cursor = max(cursor, fim)
    if total - cursor > 0.15:
        faixas.append((cursor, total))

    if not faixas:
        return "Erro: o vídeo é praticamente todo silêncio; nada sobraria após o corte."
    if len(faixas) > 300:
        return (
            "Erro: mais de 300 cortes necessários. Aumente o valor de 'duration' "
            "(ex: 1.0) para ignorar pausas curtas."
        )

    filtro = _build_trim_concat(faixas, True)
    saida = get_output_path(video_path, "_sem_silencio")
    args = [
        "-y", "-i", str(path), "-filter_complex", filtro,
        "-map", "[outv]", "-map", "[outa]", *_encode_args(),
        str(saida),
    ]
    ok, msg = run_ffmpeg(args, "Erro ao remover silêncios")
    if not ok:
        return msg

    novo = _duration(saida)
    return (
        f"{len(silencios)} silêncio(s) removido(s): {_fmt_time(total)} → "
        f"{_fmt_time(novo)}. Arquivo salvo em: {saida.absolute()}"
    )


def join_videos(video_paths: str) -> str:
    """
    Junta vários vídeos em um só, na ordem informada.

    Se todos tiverem o mesmo codec/resolução/FPS, emenda sem re-codificar
    (rápido). Caso contrário, normaliza e re-codifica para emendar direito.
    Serve para montar intro + conteúdo, ou unir partes gravadas separadamente.

    Args:
        video_paths: caminhos separados por vírgula (ex: "intro.mp4, aula.mp4").

    Returns:
        Caminho do arquivo gerado ou mensagem de erro.
    """
    caminhos = [Path(p.strip()) for p in re.split(r"[,;]", video_paths or "") if p.strip()]
    if len(caminhos) < 2:
        return "Erro: informe ao menos dois vídeos separados por vírgula"
    for caminho in caminhos:
        if not caminho.exists():
            return f"Erro: arquivo não encontrado: {caminho}"

    ensure_output_dir()
    saida = OUTPUT_DIR / f"{caminhos[0].stem}_junto.mp4"

    def assinatura(path: Path) -> tuple:
        info = _media(path)
        video = info["video"] or {}
        audio = info["audio"] or {}
        return (
            video.get("codec_name"), video.get("width"), video.get("height"),
            video.get("r_frame_rate"), video.get("pix_fmt"),
            audio.get("codec_name") if audio else None,
            audio.get("sample_rate") if audio else None,
            audio.get("channels") if audio else None,
        )

    iguais = len({assinatura(p) for p in caminhos}) == 1
    if iguais:
        lista = OUTPUT_DIR / f".concat_{uuid.uuid4().hex[:8]}.txt"
        try:
            lista.write_text(
                "\n".join(_concat_quote(p.resolve()) for p in caminhos),
                encoding="utf-8",
            )
            ok, msg = run_ffmpeg(
                ["-y", "-f", "concat", "-safe", "0", "-i", str(lista),
                 "-c", "copy", "-avoid_negative_ts", "make_zero", str(saida)],
                "Erro ao juntar vídeos",
            )
        finally:
            lista.unlink(missing_ok=True)
        if not ok:
            return msg
    else:
        base = _media(caminhos[0])
        video = base["video"] or {}
        largura = int(video.get("width") or 1280)
        altura = int(video.get("height") or 720)
        fps = video.get("r_frame_rate") or "30"
        if "/" not in str(fps):
            fps = "30"

        partes: list[str] = []
        rotulos: list[str] = []
        entradas: list[str] = []
        for caminho in caminhos:
            entradas.extend(["-i", str(caminho)])
        for indice, caminho in enumerate(caminhos):
            info = _media(caminho)
            duracao = info["duration"] or 0.1
            partes.append(
                f"[{indice}:v]scale={largura}:{altura}:force_original_aspect_ratio=decrease,"
                f"pad={largura}:{altura}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}[v{indice}]"
            )
            if info["audio"]:
                partes.append(
                    f"[{indice}:a]aresample=48000,aformat=sample_fmts=fltp:"
                    f"channel_layouts=stereo[a{indice}]"
                )
            else:
                partes.append(
                    f"anullsrc=r=48000:cl=stereo,atrim=0:{duracao:.3f},"
                    f"asetpts=PTS-STARTPTS[a{indice}]"
                )
            rotulos.append(f"[v{indice}][a{indice}]")

        n = len(caminhos)
        partes.append("".join(rotulos) + f"concat=n={n}:v=1:a=1[outv][outa]")
        filtro = ";".join(partes)

        ok, msg = run_ffmpeg(
            ["-y", *entradas, "-filter_complex", filtro, "-map", "[outv]",
             "-map", "[outa]", *_encode_args(preset="medium"), str(saida)],
            "Erro ao juntar vídeos",
        )
        if not ok:
            return msg

    total = _duration(saida)
    return (
        f"{len(caminhos)} vídeos unidos ({_fmt_time(total)})! "
        f"Arquivo salvo em: {saida.absolute()}"
    )


# ---------------------------------------------------------------------------
# Formato / entrega
# ---------------------------------------------------------------------------

def optimize_for_youtube(video_path: str, resolution: str = "1920x1080") -> str:
    """
    Exporta o vídeo no padrão recomendado pelo YouTube.

    H.264, CRF 23, preset medium, AAC 192k, faststart e a resolução pedida
    (sem distorcer: mantém proporção e adiciona tarjas se necessário).

    Args:
        video_path: caminho do vídeo.
        resolution: largura x altura de saída (padrão "1920x1080").

    Returns:
        Caminho do arquivo gerado ou mensagem de erro.
    """
    erro = _check_file(video_path)
    if erro:
        return erro
    try:
        largura, altura = resolution.lower().split("x")
        int(largura), int(altura)
    except (ValueError, AttributeError):
        return "Erro: resolução inválida. Use LARGURAxALTURA (ex: 1920x1080)"

    saida = get_output_path(video_path, "_youtube")
    filtro = (
        f"scale={largura}:{altura}:force_original_aspect_ratio=decrease,"
        f"pad={largura}:{altura}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    )
    args = [
        "-y", "-i", video_path, "-vf", filtro,
        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", str(saida),
    ]
    ok, msg = run_ffmpeg(args, "Erro ao otimizar para YouTube")
    if not ok:
        return msg
    return f"Vídeo otimizado para YouTube! Arquivo salvo em: {saida.absolute()}"


def resize_for_shorts(video_path: str, mode: str = "blur", resolution: str = "1080x1920") -> str:
    """
    Converte o vídeo para o formato vertical de Shorts/Reels (9:16).

    Args:
        video_path: caminho do vídeo.
        mode: "blur" (fundo desfocado, mantém o vídeo inteiro) ou
              "crop" (preenche a tela cortando as laterais).
        resolution: tamanho final (padrão "1080x1920").

    Returns:
        Caminho do arquivo gerado ou mensagem de erro.
    """
    erro = _check_file(video_path)
    if erro:
        return erro
    try:
        largura, altura = resolution.lower().split("x")
        int(largura), int(altura)
    except (ValueError, AttributeError):
        return "Erro: resolução inválida. Use LARGURAxALTURA (ex: 1080x1920)"

    modo = (mode or "blur").strip().lower()
    saida = get_output_path(video_path, f"_shorts_{modo}")

    if modo == "crop":
        args = [
            "-y", "-i", video_path,
            "-vf",
            f"scale={largura}:{altura}:force_original_aspect_ratio=increase,"
            f"crop={largura}:{altura},setsar=1",
        ]
    elif modo == "blur":
        filtro = (
            f"[0:v]scale={largura}:{altura}:force_original_aspect_ratio=increase,"
            f"crop={largura}:{altura},boxblur=24:4[bg];"
            f"[0:v]scale={largura}:-2:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[outv]"
        )
        args = ["-y", "-i", video_path, "-filter_complex", filtro, "-map", "[outv]"]
    else:
        return "Erro: mode deve ser 'blur' ou 'crop'"

    if _has_audio(Path(video_path)):
        args.extend(["-map", "0:v", "-map", "0:a", "-c:a", "aac", "-b:a", "192k"])
    else:
        args.extend(["-map", "0:v"])
    args.extend(["-c:v", "libx264", "-preset", "medium", "-crf", "21",
                 "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(saida)])

    ok, msg = run_ffmpeg(args, "Erro ao converter para vertical")
    if not ok:
        return msg
    return f"Vídeo vertical ({modo}) criado! Arquivo salvo em: {saida.absolute()}"


def compress_video(video_path: str, target_size_mb: str = "25") -> str:
    """
    Comprime o vídeo para caber aproximadamente em um tamanho alvo em MB.

    Calcula o bitrate a partir da duração e faz codificação em duas passadas,
    buscando a melhor qualidade possível dentro do tamanho pedido.

    Args:
        video_path: caminho do vídeo.
        target_size_mb: tamanho desejado em MB (ex: "25").

    Returns:
        Caminho do arquivo gerado ou mensagem de erro.
    """
    erro = _check_file(video_path)
    if erro:
        return erro
    try:
        alvo = _num(target_size_mb, "target_size_mb")
    except ValueError as e:
        return f"Erro: {e}"
    if alvo <= 0:
        return "Erro: target_size_mb deve ser maior que zero"

    path = Path(video_path)
    duracao = _duration(path)
    if duracao <= 0:
        return "Erro: não foi possível ler a duração do vídeo"

    tem_audio = _has_audio(path)
    audio_kbps = 128 if tem_audio else 0
    total_kbps = (alvo * 8 * 1024) / duracao
    video_kbps = int(max(100, total_kbps - audio_kbps))

    saida = get_output_path(video_path, "_comprimido")
    log = Path(tempfile.gettempdir()) / f"clipmind_pass_{uuid.uuid4().hex[:8]}"
    base = [
        "-b:v", f"{video_kbps}k",
        "-maxrate", f"{int(video_kbps * 1.5)}k",
        "-bufsize", f"{video_kbps * 2}k",
        "-preset", "medium",
    ]

    try:
        ok, msg = run_ffmpeg(
            ["-y", "-i", str(path), "-c:v", "libx264", *base,
             "-pass", "1", "-passlogfile", str(log), "-an", "-f", "null", "-"],
            "Erro na 1ª passada da compressão",
        )
        if not ok:
            return msg

        args = ["-y", "-i", str(path), "-c:v", "libx264", *base,
                "-pass", "2", "-passlogfile", str(log), "-pix_fmt", "yuv420p"]
        if tem_audio:
            args.extend(["-c:a", "aac", "-b:a", f"{audio_kbps}k"])
        args.extend(["-movflags", "+faststart", str(saida)])

        ok, msg = run_ffmpeg(args, "Erro na compressão")
        if not ok:
            return msg
    finally:
        for resto in Path(tempfile.gettempdir()).glob(f"{log.name}*"):
            resto.unlink(missing_ok=True)

    tamanho = saida.stat().st_size / (1024 * 1024) if saida.exists() else 0
    return (
        f"Vídeo comprimido para {tamanho:.1f} MB (alvo {alvo:g} MB) a "
        f"{video_kbps} kbps! Arquivo salvo em: {saida.absolute()}"
    )


def convert_video(video_path: str, format: str = "mp4") -> str:
    """
    Converte o vídeo para outro formato de arquivo.

    Args:
        video_path: caminho do vídeo.
        format: "mp4", "mkv", "webm" ou "mov" (padrão "mp4").

    Returns:
        Caminho do arquivo gerado ou mensagem de erro.
    """
    erro = _check_file(video_path)
    if erro:
        return erro
    formato = (format or "mp4").strip().lower().lstrip(".")
    if formato not in {"mp4", "mkv", "webm", "mov"}:
        return "Erro: formato deve ser mp4, mkv, webm ou mov"

    saida = get_output_path(video_path, f"_{formato}", f".{formato}")
    if formato == "webm":
        args = [
            "-y", "-i", video_path,
            "-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0",
            "-row-mt", "1", "-deadline", "good", "-cpu-used", "4",
            "-c:a", "libopus", "-b:a", "128k", str(saida),
        ]
    elif formato == "mkv":
        args = [
            "-y", "-i", video_path,
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(saida),
        ]
    elif formato == "mov":
        args = [
            "-y", "-i", video_path,
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(saida),
        ]
    else:
        args = ["-y", "-i", video_path, *_encode_args(), str(saida)]

    ok, msg = run_ffmpeg(args, f"Erro ao converter para {formato}")
    if not ok:
        return msg
    return f"Vídeo convertido para {formato}! Arquivo salvo em: {saida.absolute()}"


def create_thumbnail(video_path: str, time: str = "00:00:05") -> str:
    """
    Cria uma capa (thumbnail) a partir de um frame do vídeo, em JPG.

    Args:
        video_path: caminho do vídeo.
        time: momento do frame (padrão "00:00:05").

    Returns:
        Caminho da imagem gerada ou mensagem de erro.
    """
    erro = _check_file(video_path)
    if erro:
        return erro

    saida = get_output_path(video_path, "_capa", ".jpg")
    args = [
        "-y", "-i", video_path, "-ss", time, "-vframes", "1",
        "-q:v", "2", str(saida),
    ]
    ok, msg = run_ffmpeg(args, "Erro ao criar thumbnail")
    if not ok:
        return msg
    return f"Thumbnail criada! Imagem salva em: {saida.absolute()}"


def create_contact_sheet(video_path: str, cols: str = "4", rows: str = "3") -> str:
    """
    Cria uma folha de contatos: grade de frames do vídeo inteiro em uma imagem.

    Serve para escolher a melhor capa ou ter uma visão geral rápida do conteúdo.

    Args:
        video_path: caminho do vídeo.
        cols: colunas na grade (padrão 4).
        rows: linhas na grade (padrão 3).

    Returns:
        Caminho da imagem gerada ou mensagem de erro.
    """
    erro = _check_file(video_path)
    if erro:
        return erro
    try:
        colunas = max(1, int(_num(cols, "cols")))
        linhas = max(1, int(_num(rows, "rows")))
    except ValueError as e:
        return f"Erro: {e}"

    duracao = _duration(Path(video_path))
    if duracao <= 0:
        return "Erro: não foi possível ler a duração do vídeo"
    intervalo = duracao / (colunas * linhas)

    saida = get_output_path(video_path, "_contatos", ".jpg")
    filtro = f"fps=1/{intervalo:.3f},scale=480:-2,tile={colunas}x{linhas}"
    ok, msg = run_ffmpeg(
        ["-y", "-i", video_path, "-vf", filtro, "-frames:v", "1", "-q:v", "3", str(saida)],
        "Erro ao criar folha de contatos",
    )
    if not ok:
        return msg
    return (
        f"Folha de contatos com {colunas * linhas} frames criada! "
        f"Imagem salva em: {saida.absolute()}"
    )


def create_gif(video_path: str, start: str = "00:00:00", duration: str = "3", fps: str = "12", width: str = "480") -> str:
    """
    Cria um GIF animado a partir de um trecho do vídeo.

    Args:
        video_path: caminho do vídeo.
        start: início do trecho (padrão "00:00:00").
        duration: duração em segundos (padrão "3").
        fps: quadros por segundo do GIF (padrão 12).
        width: largura em pixels (padrão 480).

    Returns:
        Caminho do GIF gerado ou mensagem de erro.
    """
    erro = _check_file(video_path)
    if erro:
        return erro
    try:
        taxa = max(1, int(_num(fps, "fps")))
        largura = max(64, int(_num(width, "width")))
    except ValueError as e:
        return f"Erro: {e}"

    saida = get_output_path(video_path, "_animacao", ".gif")
    filtro = (
        f"fps={taxa},scale={largura}:-1:flags=lanczos,"
        f"split[a][b];[a]palettegen[p];[b][p]paletteuse"
    )
    ok, msg = run_ffmpeg(
        ["-y", "-ss", start, "-t", duration, "-i", video_path,
         "-filter_complex", filtro, str(saida)],
        "Erro ao criar GIF",
    )
    if not ok:
        return msg
    return f"GIF criado! Arquivo salvo em: {saida.absolute()}"


# ---------------------------------------------------------------------------
# Áudio
# ---------------------------------------------------------------------------

def extract_audio(video_path: str, format: str = "mp3") -> str:
    """
    Extrai o áudio do vídeo como arquivo separado.

    Args:
        video_path: caminho do vídeo.
        format: "mp3" (padrão), "wav" ou "m4a".

    Returns:
        Caminho do áudio gerado ou mensagem de erro.
    """
    erro = _check_file(video_path)
    if erro:
        return erro
    formato = (format or "mp3").strip().lower().lstrip(".")
    if formato not in {"mp3", "wav", "m4a"}:
        return "Erro: formato de áudio deve ser mp3, wav ou m4a"
    if not _has_audio(Path(video_path)):
        return "Erro: o vídeo não tem faixa de áudio"

    saida = get_output_path(video_path, "_audio", f".{formato}")
    if formato == "mp3":
        codec = ["-acodec", "libmp3lame", "-ab", "192k", "-ar", "44100"]
    elif formato == "wav":
        codec = ["-acodec", "pcm_s16le", "-ar", "48000"]
    else:
        codec = ["-acodec", "aac", "-b:a", "192k"]

    ok, msg = run_ffmpeg(["-y", "-i", video_path, "-vn", *codec, str(saida)],
                         "Erro ao extrair áudio")
    if not ok:
        return msg
    return f"Áudio extraído! Arquivo salvo em: {saida.absolute()}"


def normalize_audio(video_path: str, target_lufs: str = "-14") -> str:
    """
    Normaliza o volume do áudio no padrão de loudness do YouTube (-14 LUFS).

    Corrige vídeos muito baixos ou muito altos, deixando o som competitivo
    com o resto da plataforma. O vídeo não é re-codificado.

    Args:
        video_path: caminho do vídeo.
        target_lufs: loudness alvo em LUFS (padrão "-14", padrão do YouTube).

    Returns:
        Caminho do arquivo gerado ou mensagem de erro.
    """
    erro = _check_file(video_path)
    if erro:
        return erro
    if not _has_audio(Path(video_path)):
        return "Erro: o vídeo não tem faixa de áudio"

    try:
        alvo = _num(target_lufs, "target_lufs")
    except ValueError as e:
        return f"Erro: {e}"

    saida = get_output_path(video_path, "_audio_normalizado")
    ok, msg = run_ffmpeg(
        ["-y", "-i", video_path, "-c:v", "copy",
         "-af", f"loudnorm=I={alvo:g}:TP=-1.5:LRA=11",
         "-c:a", "aac", "-b:a", "192k", str(saida)],
        "Erro ao normalizar áudio",
    )
    if not ok:
        return msg
    return f"Áudio normalizado para {alvo:g} LUFS! Arquivo salvo em: {saida.absolute()}"


def add_music(video_path: str, music_path: str, volume: str = "0.25", keep_original: str = "true") -> str:
    """
    Adiciona música de fundo ao vídeo.

    Args:
        video_path: caminho do vídeo.
        music_path: caminho do arquivo de música (mp3/wav/m4a).
        volume: volume da música de 0 a 1 (padrão "0.25").
        keep_original: "true" mistura com o áudio original; "false" substitui.

    Returns:
        Caminho do arquivo gerado ou mensagem de erro.
    """
    erro = _check_file(video_path) or _check_file(music_path, "Arquivo de música")
    if erro:
        return erro
    try:
        vol = min(1.0, max(0.0, _num(volume, "volume")))
    except ValueError as e:
        return f"Erro: {e}"
    manter = str(keep_original).strip().lower() not in {"false", "0", "nao", "não"}
    tem_audio = _has_audio(Path(video_path))

    saida = get_output_path(video_path, "_com_musica")
    entradas = ["-y", "-i", video_path, "-stream_loop", "-1", "-i", music_path]

    if manter and tem_audio:
        filtro = (
            f"[1:a]volume={vol:g}[m];"
            f"[0:a][m]amix=inputs=2:duration=first:dropout_transition=2[a]"
        )
        args = [*entradas, "-filter_complex", filtro,
                "-map", "0:v", "-map", "[a]"]
    else:
        filtro = f"[1:a]volume={vol:g}[a]"
        args = [*entradas, "-filter_complex", filtro,
                "-map", "0:v", "-map", "[a]"]

    args.extend(["-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                 "-shortest", "-movflags", "+faststart", str(saida)])
    ok, msg = run_ffmpeg(args, "Erro ao adicionar música")
    if not ok:
        return msg
    return f"Música adicionada! Arquivo salvo em: {saida.absolute()}"


# ---------------------------------------------------------------------------
# Visual
# ---------------------------------------------------------------------------

def change_speed(video_path: str, factor: str = "2") -> str:
    """
    Acelera ou desacelera o vídeo (e o áudio junto, sem mudar o tom).

    Args:
        video_path: caminho do vídeo.
        factor: 2 = duas vezes mais rápido, 0.5 = metade da velocidade
                (aceita de 0.25 a 4).

    Returns:
        Caminho do arquivo gerado ou mensagem de erro.
    """
    erro = _check_file(video_path)
    if erro:
        return erro
    try:
        fator = _num(factor, "factor")
    except ValueError as e:
        return f"Erro: {e}"
    if not 0.25 <= fator <= 4:
        return "Erro: factor deve estar entre 0.25 e 4"

    path = Path(video_path)
    tem_audio = _has_audio(path)
    saida = get_output_path(video_path, f"_x{fator:g}".replace(".", "_"))
    filtro_v = f"setpts=PTS/{fator:g}"

    args = ["-y", "-i", video_path, "-vf", filtro_v]
    if tem_audio:
        restante = fator
        etapas: list[str] = []
        while restante > 2.0:
            etapas.append("atempo=2.0")
            restante /= 2.0
        while restante < 0.5:
            etapas.append("atempo=0.5")
            restante /= 0.5
        etapas.append(f"atempo={restante:.4f}")
        args.extend(["-af", ",".join(etapas)])

    args.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                 "-pix_fmt", "yuv420p"])
    if tem_audio:
        args.extend(["-c:a", "aac", "-b:a", "192k"])
    args.extend(["-movflags", "+faststart", str(saida)])

    ok, msg = run_ffmpeg(args, "Erro ao alterar velocidade")
    if not ok:
        return msg
    return f"Velocidade alterada para {fator:g}x! Arquivo salvo em: {saida.absolute()}"


def fade_video(video_path: str, fade_in: str = "1", fade_out: str = "1") -> str:
    """
    Adiciona fade de entrada e de saída no vídeo (e no áudio).

    Args:
        video_path: caminho do vídeo.
        fade_in: segundos de fade no início (padrão "1").
        fade_out: segundos de fade no fim (padrão "1").

    Returns:
        Caminho do arquivo gerado ou mensagem de erro.
    """
    erro = _check_file(video_path)
    if erro:
        return erro
    try:
        entrada = max(0.0, _num(fade_in, "fade_in"))
        saida_fade = max(0.0, _num(fade_out, "fade_out"))
    except ValueError as e:
        return f"Erro: {e}"

    path = Path(video_path)
    duracao = _duration(path)
    if duracao <= 0:
        return "Erro: não foi possível ler a duração do vídeo"
    if entrada + saida_fade >= duracao:
        return "Erro: a soma dos fades é maior que a duração do vídeo"

    filtros: list[str] = []
    if entrada > 0:
        filtros.append(f"fade=t=in:st=0:d={entrada:g}")
    if saida_fade > 0:
        filtros.append(f"fade=t=out:st={duracao - saida_fade:.3f}:d={saida_fade:g}")

    saida = get_output_path(video_path, "_fade")
    args = ["-y", "-i", video_path, "-vf", ",".join(filtros)]
    if _has_audio(path):
        audio_filtros: list[str] = []
        if entrada > 0:
            audio_filtros.append(f"afade=t=in:st=0:d={entrada:g}")
        if saida_fade > 0:
            audio_filtros.append(
                f"afade=t=out:st={duracao - saida_fade:.3f}:d={saida_fade:g}"
            )
        args.extend(["-af", ",".join(audio_filtros)])
    args.extend(_encode_args_visual())
    args.append(str(saida))

    ok, msg = run_ffmpeg(args, "Erro ao aplicar fade")
    if not ok:
        return msg
    return f"Fade aplicado! Arquivo salvo em: {saida.absolute()}"


def _encode_args_visual() -> list[str]:
    """Codificação conservadora para ferramentas visuais."""
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart"]


def rotate_video(video_path: str, rotation: str = "90") -> str:
    """
    Gira o vídeo em 90, 180 ou 270 graus.

    Args:
        video_path: caminho do vídeo.
        rotation: "90" (horário), "180" ou "270" (anti-horário).

    Returns:
        Caminho do arquivo gerado ou mensagem de erro.
    """
    erro = _check_file(video_path)
    if erro:
        return erro
    try:
        graus = int(_num(rotation, "rotation")) % 360
    except ValueError as e:
        return f"Erro: {e}"
    mapa = {90: "transpose=1", 180: "hflip,vflip", 270: "transpose=2"}
    if graus not in mapa:
        return "Erro: rotation deve ser 90, 180 ou 270"

    saida = get_output_path(video_path, f"_girado{graus}")
    ok, msg = run_ffmpeg(
        ["-y", "-i", video_path, "-vf", mapa[graus],
         *_encode_args_visual(), str(saida)],
        "Erro ao girar vídeo",
    )
    if not ok:
        return msg
    return f"Vídeo girado {graus}°! Arquivo salvo em: {saida.absolute()}"


def crop_video(video_path: str, width: str, height: str, x: str = "0", y: str = "0") -> str:
    """
    Recorta uma área retangular do vídeo (crop).

    Args:
        video_path: caminho do vídeo.
        width: largura da área em pixels.
        height: altura da área em pixels.
        x: posição horizontal do canto superior esquerdo (padrão "0").
        y: posição vertical (padrão "0").

    Returns:
        Caminho do arquivo gerado ou mensagem de erro.
    """
    erro = _check_file(video_path)
    if erro:
        return erro
    try:
        largura = int(_num(width, "width"))
        altura = int(_num(height, "height"))
        pos_x = int(_num(x, "x"))
        pos_y = int(_num(y, "y"))
    except ValueError as e:
        return f"Erro: {e}"
    if largura <= 0 or altura <= 0:
        return "Erro: largura e altura devem ser maiores que zero"

    info = _media(Path(video_path))
    video = info["video"] or {}
    if largura > int(video.get("width") or 0) or altura > int(video.get("height") or 0):
        return "Erro: a área de recorte é maior que o vídeo"

    saida = get_output_path(video_path, "_recortado")
    ok, msg = run_ffmpeg(
        ["-y", "-i", video_path,
         "-vf", f"crop={largura}:{altura}:{pos_x}:{pos_y}",
         *_encode_args_visual(), str(saida)],
        "Erro ao recortar vídeo",
    )
    if not ok:
        return msg
    return f"Vídeo recortado para {largura}x{altura}! Arquivo salvo em: {saida.absolute()}"


def loop_video(video_path: str, times: str = "2") -> str:
    """
    Repete o vídeo várias vezes, gerando um arquivo mais longo.

    Args:
        video_path: caminho do vídeo.
        times: quantidade total de repetições (2 = vídeo duas vezes).

    Returns:
        Caminho do arquivo gerado ou mensagem de erro.
    """
    erro = _check_file(video_path)
    if erro:
        return erro
    try:
        vezes = int(_num(times, "times"))
    except ValueError as e:
        return f"Erro: {e}"
    if vezes < 2:
        return "Erro: times deve ser 2 ou mais"

    saida = get_output_path(video_path, f"_repetido{vezes}")
    ok, msg = run_ffmpeg(
        ["-y", "-stream_loop", str(vezes - 1), "-i", video_path,
         "-c", "copy", "-movflags", "+faststart", str(saida)],
        "Erro ao repetir vídeo",
    )
    if not ok:
        return msg
    return f"Vídeo repetido {vezes}x! Arquivo salvo em: {saida.absolute()}"


def add_text(
    video_path: str,
    text: str,
    position: str = "inferior",
    size: str = "48",
    color: str = "white",
    start: str = "",
    end: str = "",
) -> str:
    """
    Escreve um texto sobre o vídeo (título, aviso, legenda fixa).

    Args:
        video_path: caminho do vídeo.
        text: texto a exibir.
        position: "inferior" (padrão), "topo", "centro", "esquerda", "direita".
        size: tamanho da fonte em pixels (padrão "48").
        color: cor do texto (padrão "white"; aceita "yellow", "#ff0000" etc).
        start: segundo em que o texto aparece (vazio = desde o início).
        end: segundo em que o texto some (vazio = até o fim).

    Returns:
        Caminho do arquivo gerado ou mensagem de erro.
    """
    erro = _check_file(video_path)
    if erro:
        return erro
    if not (text or "").strip():
        return "Erro: informe o texto a exibir"

    try:
        tamanho = max(8, int(_num(size, "size")))
    except ValueError as e:
        return f"Erro: {e}"

    fonte = _font_path()
    if fonte is None:
        return "Erro: nenhuma fonte TrueType encontrada em C:/Windows/Fonts"

    posicoes = {
        "topo": ("(w-text_w)/2", "60"),
        "centro": ("(w-text_w)/2", "(h-text_h)/2"),
        "inferior": ("(w-text_w)/2", "h-text_h-80"),
        "esquerda": ("60", "(h-text_h)/2"),
        "direita": ("w-text_w-60", "(h-text_h)/2"),
    }
    chave = (position or "inferior").strip().lower()
    if chave not in posicoes:
        return "Erro: position deve ser inferior, topo, centro, esquerda ou direita"
    pos_x, pos_y = posicoes[chave]

    ensure_output_dir()
    arquivo_texto = OUTPUT_DIR / f".texto_{uuid.uuid4().hex[:8]}.txt"
    arquivo_texto.write_text(text, encoding="utf-8")
    fonte_local = OUTPUT_DIR / f".fonte_{uuid.uuid4().hex[:8]}{fonte.suffix}"
    fonte_local.write_bytes(fonte.read_bytes())

    filtro = (
        f"drawtext=fontfile='{fonte_local.name}':"
        f"textfile='{arquivo_texto.name}':"
        f"fontcolor={color}:fontsize={tamanho}:"
        f"box=1:boxcolor=black@0.45:boxborderw=14:"
        f"x={pos_x}:y={pos_y}"
    )
    if start or end:
        try:
            inicio = _parse_time(start) if start else 0.0
            fim = _parse_time(end) if end else None
        except ValueError:
            arquivo_texto.unlink(missing_ok=True)
            fonte_local.unlink(missing_ok=True)
            return "Erro: start/end inválidos"
        if fim is not None:
            filtro += f":enable='between(t\\,{inicio:g}\\,{fim:g})'"
        else:
            filtro += f":enable='gte(t\\,{inicio:g})'"

    saida = get_output_path(video_path, "_com_texto")
    try:
        ok, msg = run_ffmpeg(
            ["-y", "-i", str(Path(video_path).resolve()), "-vf", filtro,
             *_encode_args_visual(), str(saida.resolve())],
            "Erro ao adicionar texto",
            cwd=OUTPUT_DIR,
        )
    finally:
        arquivo_texto.unlink(missing_ok=True)
        fonte_local.unlink(missing_ok=True)

    if not ok:
        return msg
    return f"Texto adicionado! Arquivo salvo em: {saida.absolute()}"


def burn_subtitles(video_path: str, subtitle_path: str) -> str:
    """
    Grava as legendas de um arquivo .srt permanentemente sobre o vídeo.

    Args:
        video_path: caminho do vídeo.
        subtitle_path: caminho do arquivo .srt (ou .ass).

    Returns:
        Caminho do arquivo gerado ou mensagem de erro.
    """
    erro = _check_file(video_path) or _check_file(subtitle_path, "Arquivo de legenda")
    if erro:
        return erro

    legenda = Path(subtitle_path)
    if legenda.suffix.lower() not in {".srt", ".ass", ".vtt"}:
        return "Erro: a legenda deve ser .srt, .ass ou .vtt"

    ensure_output_dir()
    copia = OUTPUT_DIR / f".legenda_{uuid.uuid4().hex[:8]}{legenda.suffix.lower()}"
    copia.write_bytes(legenda.read_bytes())

    estilo = (
        "FontName=Arial,FontSize=18,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,MarginV=40"
    )
    filtro = f"subtitles={copia.name}:force_style='{estilo}'"
    saida = get_output_path(video_path, "_legendado")

    try:
        ok, msg = run_ffmpeg(
            ["-y", "-i", str(Path(video_path).resolve()), "-vf", filtro,
             *_encode_args(preset="medium"), str(saida.resolve())],
            "Erro ao gravar legendas",
            cwd=OUTPUT_DIR,
        )
    finally:
        copia.unlink(missing_ok=True)

    if not ok:
        return msg
    return f"Legendas gravadas no vídeo! Arquivo salvo em: {saida.absolute()}"


# ---------------------------------------------------------------------------
# Metadados da interface
# ---------------------------------------------------------------------------

TOOL_SPECS: list[dict] = [
    {
        "name": "inspect_video", "label": "Analisar", "icon": "🔍", "group": "Análise",
        "fields": [{"name": "video_path", "type": "video", "label": "Vídeo"}],
    },
    {
        "name": "detect_scenes", "label": "Detectar cenas", "icon": "🎬", "group": "Análise",
        "fields": [
            {"name": "video_path", "type": "video", "label": "Vídeo"},
            {"name": "threshold", "label": "Sensibilidade (1-100)", "default": "15",
             "placeholder": "0.3"},
        ],
    },
    {
        "name": "cut_video", "label": "Cortar", "icon": "✂️", "group": "Corte",
        "fields": [
            {"name": "video_path", "type": "video", "label": "Vídeo"},
            {"name": "start", "label": "Início", "default": "00:00:00"},
            {"name": "end", "label": "Fim", "placeholder": "00:01:00"},
        ],
    },
    {
        "name": "cut_multiple_segments", "label": "Cortes múltiplos", "icon": "🧩", "group": "Corte",
        "fields": [
            {"name": "video_path", "type": "video", "label": "Vídeo"},
            {"name": "segments", "label": "Trechos",
             "placeholder": "00:00:05-00:00:12, 00:02:00-00:02:40"},
        ],
    },
    {
        "name": "remove_silence", "label": "Remover silêncios", "icon": "🔇", "group": "Corte",
        "fields": [
            {"name": "video_path", "type": "video", "label": "Vídeo"},
            {"name": "noise", "label": "Limiar", "default": "-30dB"},
            {"name": "duration", "label": "Pausa mínima (s)", "default": "0.5"},
        ],
    },
    {
        "name": "join_videos", "label": "Juntar vídeos", "icon": "🔗", "group": "Corte",
        "fields": [{"name": "video_paths", "label": "Vídeos (separados por vírgula)",
                    "placeholder": "intro.mp4, aula.mp4"}],
    },
    {
        "name": "optimize_for_youtube", "label": "Otimizar YouTube", "icon": "⚡", "group": "Formato",
        "fields": [
            {"name": "video_path", "type": "video", "label": "Vídeo"},
            {"name": "resolution", "label": "Resolução", "default": "1920x1080"},
        ],
    },
    {
        "name": "resize_for_shorts", "label": "Vertical (Shorts)", "icon": "📱", "group": "Formato",
        "fields": [
            {"name": "video_path", "type": "video", "label": "Vídeo"},
            {"name": "mode", "label": "Modo", "type": "select", "default": "blur",
             "options": ["blur", "crop"]},
            {"name": "resolution", "label": "Resolução", "default": "1080x1920"},
        ],
    },
    {
        "name": "compress_video", "label": "Comprimir", "icon": "🗜️", "group": "Formato",
        "fields": [
            {"name": "video_path", "type": "video", "label": "Vídeo"},
            {"name": "target_size_mb", "label": "Tamanho alvo (MB)", "default": "25"},
        ],
    },
    {
        "name": "convert_video", "label": "Converter", "icon": "🔄", "group": "Formato",
        "fields": [
            {"name": "video_path", "type": "video", "label": "Vídeo"},
            {"name": "format", "label": "Formato", "type": "select", "default": "mp4",
             "options": ["mp4", "mkv", "webm", "mov"]},
        ],
    },
    {
        "name": "create_thumbnail", "label": "Thumbnail", "icon": "🖼️", "group": "Entrega",
        "fields": [
            {"name": "video_path", "type": "video", "label": "Vídeo"},
            {"name": "time", "label": "Momento", "default": "00:00:05"},
        ],
    },
    {
        "name": "create_contact_sheet", "label": "Folha de contatos", "icon": "🧭", "group": "Entrega",
        "fields": [
            {"name": "video_path", "type": "video", "label": "Vídeo"},
            {"name": "cols", "label": "Colunas", "default": "4"},
            {"name": "rows", "label": "Linhas", "default": "3"},
        ],
    },
    {
        "name": "create_gif", "label": "GIF", "icon": "🎞️", "group": "Entrega",
        "fields": [
            {"name": "video_path", "type": "video", "label": "Vídeo"},
            {"name": "start", "label": "Início", "default": "00:00:00"},
            {"name": "duration", "label": "Duração (s)", "default": "3"},
            {"name": "fps", "label": "FPS", "default": "12"},
            {"name": "width", "label": "Largura", "default": "480"},
        ],
    },
    {
        "name": "extract_audio", "label": "Extrair áudio", "icon": "🎵", "group": "Áudio",
        "fields": [
            {"name": "video_path", "type": "video", "label": "Vídeo"},
            {"name": "format", "label": "Formato", "type": "select", "default": "mp3",
             "options": ["mp3", "wav", "m4a"]},
        ],
    },
    {
        "name": "normalize_audio", "label": "Normalizar volume", "icon": "🔊", "group": "Áudio",
        "fields": [
            {"name": "video_path", "type": "video", "label": "Vídeo"},
            {"name": "target_lufs", "label": "Loudness (LUFS)", "default": "-14"},
        ],
    },
    {
        "name": "add_music", "label": "Música de fundo", "icon": "🎶", "group": "Áudio",
        "fields": [
            {"name": "video_path", "type": "video", "label": "Vídeo"},
            {"name": "music_path", "label": "Música", "placeholder": "C:/music/tema.mp3"},
            {"name": "volume", "label": "Volume (0-1)", "default": "0.25"},
            {"name": "keep_original", "label": "Manter áudio original", "type": "select",
             "default": "true", "options": ["true", "false"]},
        ],
    },
    {
        "name": "change_speed", "label": "Velocidade", "icon": "⏩", "group": "Visual",
        "fields": [
            {"name": "video_path", "type": "video", "label": "Vídeo"},
            {"name": "factor", "label": "Fator", "default": "2",
             "placeholder": "2 = dobro, 0.5 = metade"},
        ],
    },
    {
        "name": "fade_video", "label": "Fade", "icon": "🌗", "group": "Visual",
        "fields": [
            {"name": "video_path", "type": "video", "label": "Vídeo"},
            {"name": "fade_in", "label": "Entrada (s)", "default": "1"},
            {"name": "fade_out", "label": "Saída (s)", "default": "1"},
        ],
    },
    {
        "name": "rotate_video", "label": "Girar", "icon": "🔃", "group": "Visual",
        "fields": [
            {"name": "video_path", "type": "video", "label": "Vídeo"},
            {"name": "rotation", "label": "Graus", "type": "select", "default": "90",
             "options": ["90", "180", "270"]},
        ],
    },
    {
        "name": "crop_video", "label": "Recortar área", "icon": "🔲", "group": "Visual",
        "fields": [
            {"name": "video_path", "type": "video", "label": "Vídeo"},
            {"name": "width", "label": "Largura", "placeholder": "1280"},
            {"name": "height", "label": "Altura", "placeholder": "720"},
            {"name": "x", "label": "X", "default": "0"},
            {"name": "y", "label": "Y", "default": "0"},
        ],
    },
    {
        "name": "loop_video", "label": "Repetir", "icon": "🔁", "group": "Visual",
        "fields": [
            {"name": "video_path", "type": "video", "label": "Vídeo"},
            {"name": "times", "label": "Vezes", "default": "2"},
        ],
    },
    {
        "name": "add_text", "label": "Escrever texto", "icon": "🅣", "group": "Visual",
        "fields": [
            {"name": "video_path", "type": "video", "label": "Vídeo"},
            {"name": "text", "label": "Texto"},
            {"name": "position", "label": "Posição", "type": "select", "default": "inferior",
             "options": ["inferior", "topo", "centro", "esquerda", "direita"]},
            {"name": "size", "label": "Tamanho", "default": "48"},
            {"name": "color", "label": "Cor", "default": "white"},
            {"name": "start", "label": "Aparece em (s)", "placeholder": "opcional"},
            {"name": "end", "label": "Some em (s)", "placeholder": "opcional"},
        ],
    },
    {
        "name": "burn_subtitles", "label": "Gravar legendas", "icon": "💬", "group": "Visual",
        "fields": [
            {"name": "video_path", "type": "video", "label": "Vídeo"},
            {"name": "subtitle_path", "label": "Arquivo .srt",
             "placeholder": "C:/legendas/video.srt"},
        ],
    },
]
