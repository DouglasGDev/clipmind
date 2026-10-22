"""
Ferramentas de edição de vídeo para YouTube usando FFmpeg.
Todas as funções executam comandos FFmpeg reais via subprocess.
"""

import subprocess
import json
from pathlib import Path
from typing import Optional


# Pasta de saída padrão (pode ser configurada)
OUTPUT_DIR = Path("./output")


def ensure_output_dir() -> Path:
    """Cria a pasta de saída se não existir."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


def get_output_path(video_path: str, suffix: str, extension: Optional[str] = None) -> Path:
    """
    Gera o caminho do arquivo de saída baseado no nome original + sufixo.

    Args:
        video_path: Caminho do vídeo original
        suffix: Sufixo a adicionar (ex: "_cortado", "_youtube")
        extension: Extensão do arquivo (se None, usa a mesma do original)

    Returns:
        Path: Caminho completo do arquivo de saída
    """
    ensure_output_dir()
    original = Path(video_path)
    ext = extension if extension else original.suffix
    output_name = f"{original.stem}{suffix}{ext}"
    return OUTPUT_DIR / output_name


def run_ffmpeg(args: list[str], error_message: str = "Erro ao executar FFmpeg") -> tuple[bool, str]:
    """
    Executa um comando FFmpeg e retorna o resultado.

    Args:
        args: Lista de argumentos para o FFmpeg
        error_message: Mensagem de erro personalizada

    Returns:
        tuple[bool, str]: (sucesso, mensagem)
    """
    try:
        result = subprocess.run(
            ["ffmpeg"] + args,
            capture_output=True,
            text=True,
            check=True
        )
        return True, "Comando executado com sucesso"
    except subprocess.CalledProcessError as e:
        return False, f"{error_message}: {e.stderr}"
    except FileNotFoundError:
        return False, "FFmpeg não encontrado. Certifique-se de que está instalado e no PATH"
    except Exception as e:
        return False, f"{error_message}: {str(e)}"


def inspect_video(video_path: str) -> str:
    """
    Analisa um vídeo e retorna informações detalhadas sobre ele.

    Esta ferramenta extrai metadados completos do vídeo incluindo:
    - Duração total
    - Resolução (largura x altura)
    - Codecs de vídeo e áudio
    - Taxa de quadros (FPS)
    - Bitrate
    - Formato do container

    Args:
        video_path: Caminho completo para o arquivo de vídeo a ser analisado

    Returns:
        str: JSON com todas as informações do vídeo ou mensagem de erro
    """
    path = Path(video_path)

    if not path.exists():
        return json.dumps({"erro": f"Arquivo não encontrado: {video_path}"}, ensure_ascii=False)

    try:
        # Usa ffprobe para extrair informações
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                str(path)
            ],
            capture_output=True,
            text=True,
            check=True
        )

        probe_data = json.loads(result.stdout)

        # Extrai informações relevantes
        info = {
            "arquivo": path.name,
            "caminho": str(path.absolute()),
            "formato": probe_data.get("format", {}).get("format_name", "desconhecido"),
            "duracao_segundos": float(probe_data.get("format", {}).get("duration", 0)),
            "tamanho_bytes": int(probe_data.get("format", {}).get("size", 0)),
            "bitrate_total": probe_data.get("format", {}).get("bit_rate", "desconhecido"),
            "streams": []
        }

        # Processa cada stream (vídeo, áudio, etc)
        for stream in probe_data.get("streams", []):
            stream_info = {
                "tipo": stream.get("codec_type", "desconhecido"),
                "codec": stream.get("codec_name", "desconhecido"),
            }

            if stream.get("codec_type") == "video":
                stream_info.update({
                    "largura": stream.get("width", 0),
                    "altura": stream.get("height", 0),
                    "resolucao": f"{stream.get('width', 0)}x{stream.get('height', 0)}",
                    "fps": stream.get("r_frame_rate", "desconhecido"),
                    "bitrate": stream.get("bit_rate", "desconhecido"),
                    "pix_fmt": stream.get("pix_fmt", "desconhecido")
                })
            elif stream.get("codec_type") == "audio":
                stream_info.update({
                    "sample_rate": stream.get("sample_rate", "desconhecido"),
                    "channels": stream.get("channels", 0),
                    "bitrate": stream.get("bit_rate", "desconhecido")
                })

            info["streams"].append(stream_info)

        # Converte duração para formato legível
        duracao = info["duracao_segundos"]
        horas = int(duracao // 3600)
        minutos = int((duracao % 3600) // 60)
        segundos = int(duracao % 60)
        info["duracao_formato"] = f"{horas:02d}:{minutos:02d}:{segundos:02d}"

        return json.dumps(info, indent=2, ensure_ascii=False)

    except subprocess.CalledProcessError as e:
        return json.dumps({"erro": f"Erro ao analisar vídeo: {e.stderr}"}, ensure_ascii=False)
    except FileNotFoundError:
        return json.dumps({"erro": "FFprobe não encontrado. Certifique-se de que FFmpeg está instalado"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"erro": f"Erro inesperado: {str(e)}"}, ensure_ascii=False)


def cut_video(video_path: str, start: str, end: Optional[str] = None, duration: Optional[str] = None) -> str:
    """
    Corta um vídeo extraindo um segmento específico.

    Você pode especificar o corte de duas formas:
    1. Usando start e end (ex: start="00:01:30", end="00:03:45")
    2. Usando start e duration (ex: start="00:01:30", duration="00:02:15")

    O corte é feito de forma rápida usando stream copy (sem re-codificação).

    Args:
        video_path: Caminho completo para o vídeo original
        start: Tempo de início no formato HH:MM:SS ou MM:SS ou segundos (ex: "00:01:30" ou "90")
        end: Tempo de fim no formato HH:MM:SS (opcional, use OU end OU duration, não ambos)
        duration: Duração do corte no formato HH:MM:SS (opcional, use OU end OU duration, não ambos)

    Returns:
        str: Mensagem de sucesso com o caminho do arquivo gerado, ou mensagem de erro
    """
    path = Path(video_path)

    if not path.exists():
        return f"Erro: Arquivo não encontrado: {video_path}"

    if not end and not duration:
        return "Erro: Você deve especificar 'end' ou 'duration'"

    if end and duration:
        return "Erro: Especifique apenas 'end' OU 'duration', não ambos"

    output_path = get_output_path(video_path, "_cortado")

    # Monta os argumentos do FFmpeg
    args = ["-y", "-i", str(path), "-ss", start]

    if end:
        args.extend(["-to", end])
    elif duration:
        args.extend(["-t", duration])

    # Usa stream copy para corte rápido
    args.extend(["-c", "copy", "-avoid_negative_ts", "make_zero", str(output_path)])

    success, message = run_ffmpeg(args, "Erro ao cortar vídeo")

    if success:
        return f"Vídeo cortado com sucesso! Arquivo salvo em: {output_path.absolute()}"
    else:
        return message


def create_thumbnail(video_path: str, time: str = "00:00:05") -> str:
    """
    Cria uma imagem thumbnail/capa a partir de um frame específico do vídeo.

    Extrai um frame no tempo especificado e salva como imagem JPG de alta qualidade.
    Ideal para criar capas/thumbnails para YouTube.

    Args:
        video_path: Caminho completo para o vídeo
        time: Tempo do frame no formato HH:MM:SS (padrão: "00:00:05" - 5 segundos)

    Returns:
        str: Mensagem de sucesso com o caminho da imagem gerada, ou mensagem de erro
    """
    path = Path(video_path)

    if not path.exists():
        return f"Erro: Arquivo não encontrado: {video_path}"

    output_path = get_output_path(video_path, "_capa", ".jpg")

    args = [
        "-y",
        "-i", str(path),
        "-ss", time,
        "-vframes", "1",
        "-q:v", "2",  # Alta qualidade (2-31, menor = melhor)
        str(output_path)
    ]

    success, message = run_ffmpeg(args, "Erro ao criar thumbnail")

    if success:
        return f"Thumbnail criada com sucesso! Imagem salva em: {output_path.absolute()}"
    else:
        return message


def optimize_for_youtube(video_path: str, resolution: str = "1920x1080") -> str:
    """
    Otimiza um vídeo para upload no YouTube com as configurações recomendadas.

    Configurações aplicadas:
    - Codec de vídeo: H.264 (libx264)
    - Codec de áudio: AAC
    - Bitrate de áudio: 192k
    - Preset: medium (bom equilíbrio entre velocidade e qualidade)
    - CRF: 23 (qualidade padrão do YouTube)
    - Movflags: +faststart (permite playback antes do download completo)
    - Resolução: conforme especificado (padrão: 1920x1080)

    Args:
        video_path: Caminho completo para o vídeo a ser otimizado
        resolution: Resolução de saída no formato LARGURAxALTURA (padrão: "1920x1080")

    Returns:
        str: Mensagem de sucesso com o caminho do arquivo otimizado, ou mensagem de erro
    """
    path = Path(video_path)

    if not path.exists():
        return f"Erro: Arquivo não encontrado: {video_path}"

    output_path = get_output_path(video_path, "_youtube")

    # Extrai largura e altura da resolução
    try:
        width, height = resolution.split("x")
    except ValueError:
        return f"Erro: Formato de resolução inválido. Use LARGURAxALTURA (ex: 1920x1080)"

    args = [
        "-y",
        "-i", str(path),
        "-vf", f"scale={width}:{height}",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(output_path)
    ]

    success, message = run_ffmpeg(args, "Erro ao otimizar vídeo para YouTube")

    if success:
        return f"Vídeo otimizado para YouTube com sucesso! Arquivo salvo em: {output_path.absolute()}"
    else:
        return message


def remove_silence(video_path: str, noise: str = "-30dB", duration: str = "0.5") -> str:
    """
    Remove silêncios longos do vídeo, mantendo apenas as partes com áudio.

    Usa o filtro silenceremove do FFmpeg para identificar e remover períodos
    de silêncio. O filtro atua tanto no início quanto no meio/fim do vídeo.

    Args:
        video_path: Caminho completo para o vídeo
        noise: Limiar de ruído em dB para considerar como silêncio (padrão: "-30dB")
               Valores mais negativos = silêncio mais rigoroso (ex: "-40dB" é mais stricto)
               Valores menos negativos = detecta mais silêncio (ex: "-20dB" é mais permissivo)
        duration: Duração mínima em segundos para considerar como silêncio (padrão: "0.5")
                  Silêncios menores que isso não serão removidos

    Returns:
        str: Mensagem de sucesso com o caminho do arquivo processado, ou mensagem de erro
    """
    path = Path(video_path)

    if not path.exists():
        return f"Erro: Arquivo não encontrado: {video_path}"

    output_path = get_output_path(video_path, "_sem_silencio")

    # Filtro silenceremove:
    # start_periods=1     → remove silêncio no início (1 período)
    # start_silence       → duração mínima do silêncio inicial para remover
    # start_threshold     → limiar de volume para considerar silêncio
    # stop_periods=-1     → remove silêncio durante todo o vídeo (-1 = todos os períodos)
    # stop_silence        → duração mínima do silêncio no meio/fim para remover
    # stop_threshold      → limiar de volume para silêncio no meio/fim
    # start_duration=0.1  → mantém uma pequena margem no início para não cortar o primeiro som
    # stop_duration=0.1   → mantém uma pequena margem entre falas
    filter_complex = (
        f"silenceremove="
        f"start_periods=1:start_silence={duration}:start_threshold={noise}:"
        f"stop_periods=-1:stop_silence={duration}:stop_threshold={noise}:"
        f"start_duration=0.1:stop_duration=0.1"
    )

    args = [
        "-y",
        "-i", str(path),
        "-af", filter_complex,
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        str(output_path)
    ]

    success, message = run_ffmpeg(args, "Erro ao remover silêncio")

    if success:
        return f"Silêncios removidos com sucesso! Arquivo salvo em: {output_path.absolute()}"
    else:
        return message


def extract_audio(video_path: str) -> str:
    """
    Extrai o áudio de um vídeo e salva como arquivo MP3 de alta qualidade.

    Converte o áudio para formato MP3 com bitrate de 192kbps,
    mantendo a melhor qualidade possível.

    Args:
        video_path: Caminho completo para o vídeo

    Returns:
        str: Mensagem de sucesso com o caminho do arquivo MP3 gerado, ou mensagem de erro
    """
    path = Path(video_path)

    if not path.exists():
        return f"Erro: Arquivo não encontrado: {video_path}"

    output_path = get_output_path(video_path, "_audio", ".mp3")

    args = [
        "-y",
        "-i", str(path),
        "-vn",  # Remove vídeo
        "-acodec", "libmp3lame",
        "-ab", "192k",
        "-ar", "44100",  # Sample rate padrão para MP3
        str(output_path)
    ]

    success, message = run_ffmpeg(args, "Erro ao extrair áudio")

    if success:
        return f"Áudio extraído com sucesso! Arquivo salvo em: {output_path.absolute()}"
    else:
        return message
