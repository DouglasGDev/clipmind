"""
Agente LM Studio do ClipMind.

Camada única de IA compartilhada pela interface web (server.py) e pelo CLI
(editor_agent.py). Usa o SDK oficial com AsyncClient + .act(), que executa o
loop de tool calling: o modelo escolhe a ferramenta, o SDK chama a função
Python correspondente, o resultado volta para o modelo, e assim até a resposta.

Configuração por variáveis de ambiente:
    CLIPMIND_MODEL     nome/chave do modelo no LM Studio
    CLIPMIND_LMS_HOST  host:porta da API local (padrão: descoberta automática)
    CLIPMIND_CONTEXT   contexto em tokens ao carregar o modelo (padrão: 16384)

O SDK 1.5.0 não expõe parâmetro de token no AsyncClient, então o servidor do LM
Studio precisa estar sem exigência de API token (veja AUTH_HINT abaixo).
"""

import asyncio
import os
from typing import Any, Awaitable, Callable, Optional

import lmstudio as lms
from lmstudio import AsyncClient, Chat

from youtube_editor_tools import (
    add_music,
    add_text,
    burn_subtitles,
    change_speed,
    compress_video,
    convert_video,
    create_contact_sheet,
    create_gif,
    create_thumbnail,
    crop_video,
    cut_multiple_segments,
    cut_video,
    detect_scenes,
    extract_audio,
    fade_video,
    inspect_video,
    join_videos,
    loop_video,
    normalize_audio,
    optimize_for_youtube,
    remove_silence,
    resize_for_shorts,
    rotate_video,
)


MODEL_NAME = os.getenv("CLIPMIND_MODEL", "")
LMS_HOST = os.getenv("CLIPMIND_LMS_HOST", "")

# As 23 definições de ferramentas ocupam ~5.700 tokens; com 8k de contexto sobra
# pouco histórico e resultados antigos saem da janela no meio de uma cadeia.
try:
    CONTEXT_LENGTH = int(os.getenv("CLIPMIND_CONTEXT", "16384"))
except ValueError:
    CONTEXT_LENGTH = 16384

TOOLS = [
    inspect_video,
    detect_scenes,
    cut_video,
    cut_multiple_segments,
    remove_silence,
    join_videos,
    optimize_for_youtube,
    resize_for_shorts,
    compress_video,
    convert_video,
    create_thumbnail,
    create_contact_sheet,
    create_gif,
    extract_audio,
    normalize_audio,
    add_music,
    change_speed,
    fade_video,
    rotate_video,
    crop_video,
    loop_video,
    add_text,
    burn_subtitles,
]

SYSTEM_PROMPT = """Você é o editor de vídeo do ClipMind. Você tem ferramentas reais que executam FFmpeg de verdade e geram arquivos em ./output.

Regras:
- Quando o usuário pedir uma edição, CHAME a ferramenta apropriada. Não descreva comandos, execute.
- Use o caminho de arquivo exatamente como o usuário informou.
- Se faltar um dado obrigatório (por exemplo o caminho do vídeo), pergunte antes de executar.
- Você pode encadear ferramentas: use a saída de uma como entrada da próxima (o resultado informa o caminho salvo).
- Antes de recortar ou aplicar efeitos, se não souber a duração/resolução, use inspect_video primeiro.
- Depois de executar, diga em uma frase o que foi feito e onde o arquivo foi salvo.
- Responda sempre em português brasileiro, de forma curta.

Ferramentas disponíveis:
- inspect_video: metadados do vídeo (duração, resolução, codecs, fps).
- detect_scenes: lista os cortes de cena com tempo e intensidade.
- cut_video: extrai um trecho (start + end ou duration).
- cut_multiple_segments: extrai vários trechos e junta em um só (formato "inicio-fim, inicio-fim").
- remove_silence: remove pausas/silêncios, mantendo áudio e vídeo sincronizados.
- join_videos: junta vários vídeos em sequência.
- optimize_for_youtube: H.264/AAC com faststart, escalando sem distorcer.
- resize_for_shorts: vertical 1080x1920, com fundo desfocado (blur) ou corte (crop).
- compress_video: reduz para um tamanho alvo em MB (2 passadas).
- convert_video: converte para mp4/mkv/webm/mov.
- create_thumbnail: extrai um frame como capa JPG.
- create_contact_sheet: grade de frames para pré-visualizar o vídeo.
- create_gif: GIF animado de um trecho.
- extract_audio: extrai o áudio em mp3/wav/m4a.
- normalize_audio: normaliza o volume para loudness de YouTube (-14 LUFS por padrão).
- add_music: adiciona música de fundo, podendo manter ou substituir o áudio original.
- change_speed: acelera ou desacelera (0.25x a 4x) com áudio sincronizado.
- fade_video: fade de entrada e/ou saída.
- rotate_video: gira 90/180/270 graus.
- crop_video: recorta uma área (largura, altura, x, y).
- loop_video: repete o vídeo N vezes.
- add_text: escreve um texto sobre o vídeo (posição, tamanho, cor, tempo).
- burn_subtitles: grava legendas .srt/.ass/.vtt dentro do vídeo.
"""


class AgentError(RuntimeError):
    """Falha de comunicação com o LM Studio, com mensagem acionável."""


AUTH_HINT = (
    "O LM Studio está com autenticação por API token ativada, e o SDK Python "
    "1.5.0 não tem como enviar token (o AsyncClient só aceita api_host). "
    "Desative o switch de autenticação em Developer → Server Settings e reinicie "
    "o servidor. Para não perder a proteção da rede, mantenha a Network "
    "Interface em 127.0.0.1 em vez de 0.0.0.0."
)

# O SDK 1.5.0 faz dict(details) ao montar LMStudioServerError; quando o servidor
# responde com a recusa de token, `details` é uma string e o dict() levanta
# ValueError, perdendo a mensagem original. Nada na exceção denuncia auth, então
# este marcador é a única pista disponível de que a falha é a recusa de token.
_SDK_AUTH_MASK_MARKERS = ("dictionary update sequence",)


def _is_masked_auth_failure(exc: BaseException) -> bool:
    """Reconhece a recusa de token, mesmo quando o SDK a deforma."""
    texto = str(exc).lower()
    if any(m in texto for m in _SDK_AUTH_MASK_MARKERS):
        return True
    return "token" in texto or "authentication" in texto


# Histórico compartilhado: criado no primeiro uso e mantido entre pedidos
_chat: Optional[Chat] = None

# Progresso bruto do SDK vem como dict/objeto variável; normalizamos para dict
def _as_dict(part: Any) -> dict:
    if isinstance(part, dict):
        return part
    to_dict = getattr(part, "to_dict", None)
    if callable(to_dict):
        try:
            return to_dict()
        except Exception:
            pass
    return {}


# Modelos de raciocínio no LM Studio emitem o pensamento interno dentro do
# próprio texto, separado da resposta por este marcador. Ele não é conteúdo.
_REASONING_MARKER = "__LM_STUDIO_INTERNAL_LSEP_SYNTHETIC_REASONING_END_"


def _clean_text(text: str) -> str:
    """Descarta o raciocínio sintético que antecede o marcador interno."""
    idx = text.find(_REASONING_MARKER)
    if idx == -1:
        return text.strip()
    fim = text.find("__", idx + len(_REASONING_MARKER))
    if fim == -1:
        return ""
    return text[fim + 2:].strip()


# O resultado de uma ferramenta chega em mensagem separada,identified only by
# toolCallId; guardamos o nome visto na requisição para exibir o resultado com
# contexto. Limite arbitrário: uma conversa raramente passa de dezenas de chamadas.
_TOOL_NAMES: dict[str, str] = {}
_TOOL_NAMES_MAX = 200


def _describe_message(message: Any) -> list[dict]:
    """
    Converte um evento do .act() em eventos simples para a interface.

    Retorna itens {'kind': 'tool_call'|'tool_result'|'text', ...}. Os nomes de
    campo seguem o wire format do SDK 1.5.0 (camelCase: toolCallRequest,
    toolCallResult, toolCallId) — não o snake_case das classes Python.
    """
    events: list[dict] = []
    data = _as_dict(message)
    content = data.get("content", [])

    if isinstance(content, str):
        text = _clean_text(content)
        if text:
            events.append({"kind": "text", "text": text})
        return events

    for part in content or []:
        pdata = _as_dict(part)
        ptype = str(pdata.get("type", ""))

        if ptype == "toolCallRequest":
            req = pdata.get("toolCallRequest") or {}
            name = str(req.get("name") or "ferramenta")
            call_id = req.get("id")
            if call_id:
                if len(_TOOL_NAMES) >= _TOOL_NAMES_MAX:
                    _TOOL_NAMES.clear()
                _TOOL_NAMES[str(call_id)] = name
            events.append({
                "kind": "tool_call",
                "name": name,
                "args": req.get("arguments") or {},
            })
        elif ptype == "toolCallResult":
            call_id = pdata.get("toolCallId")
            events.append({
                "kind": "tool_result",
                "name": _TOOL_NAMES.get(str(call_id), "") if call_id else "",
                "result": str(pdata.get("content", "")),
            })
        elif ptype == "text":
            text = _clean_text(str(pdata.get("text", "")))
            if text:
                events.append({"kind": "text", "text": text})

    return events


def _client_kwargs() -> dict:
    if LMS_HOST:
        return {"api_host": LMS_HOST}
    return {}


def _load_progress(
    on_event: Optional[Callable[[dict], Awaitable[None]]],
    pendentes: Optional[list[asyncio.Future]] = None,
) -> Optional[Callable[[float], None]]:
    """
    Constrói o callback de progresso do `llm.model()`.

    Um 27B leva minutos para carregar; sem isso a interface parece travada.
    O SDK chama a cada fração, então só emite quando o percentual inteiro muda.
    """
    if on_event is None:
        return None

    vistos: set[int] = set()

    def callback(progress: float) -> None:
        pct = int(round(progress * 100)) if progress <= 1 else int(round(progress))
        if pct not in vistos:
            vistos.add(pct)
            _emit(on_event, {"kind": "loading", "progress": pct}, pendentes)

    return callback


async def _resolve_llm(
    client: Any,
    on_event: Optional[Callable[[dict], Awaitable[None]]] = None,
    pendentes: Optional[list[asyncio.Future]] = None,
) -> Any:
    """
    Retorna o modelo pronto para uso.

    Sem CLIPMIND_MODEL definido, usa o modelo já carregado; se nenhum estiver
    carregado, usa o único LLM baixado. `llm.model()` carrega sob demanda.
    """
    progress = _load_progress(on_event, pendentes)
    config_carga = {"contextLength": CONTEXT_LENGTH}

    if not MODEL_NAME:
        loaded = await client.llm.list_loaded()
        if loaded:
            return loaded[0]

        downloaded = await client.llm.list_downloaded()
        llms_baixados = [m for m in downloaded if isinstance(m, lms.AsyncDownloadedLlm)]
        if not llms_baixados:
            raise AgentError(
                "Nenhum modelo de linguagem baixado no LM Studio. Baixe um na "
                "aba Discover (ex: um Qwen com suporte a tool calling)."
            )
        if len(llms_baixados) > 1:
            nomes = ", ".join(m.model_key for m in llms_baixados[:8])
            raise AgentError(
                "Há mais de um modelo baixado e nenhum está carregado agora. "
                "Carregue um no LM Studio ou defina CLIPMIND_MODEL. Opções: "
                + nomes
            )
        return await client.llm.model(
            llms_baixados[0].model_key,
            config=config_carga,
            on_load_progress=progress,
        )

    try:
        return await client.llm.model(
            MODEL_NAME, config=config_carga, on_load_progress=progress
        )
    except lms.LMStudioModelNotFoundError:
        downloaded = await client.llm.list_downloaded()
        nomes = sorted({m.model_key for m in downloaded})
        amostra = ", ".join(nomes[:12]) or "nenhum"
        raise AgentError(
            f"Modelo '{MODEL_NAME}' não existe no LM Studio. Baixe-o na aba "
            f"Discover ou aponte para um modelo instalado com CLIPMIND_MODEL. "
            f"Baixados: {amostra}"
        ) from None


def reset_chat() -> None:
    """Descarta o histórico para o próximo turno começar do zero."""
    global _chat
    _chat = None


async def run_agent_turn(
    user_text: str,
    on_event: Callable[[dict], Awaitable[None]],
) -> str:
    """
    Executa um turno do agente: manda o texto para o modelo, transmite cada
    ferramenta chamada via on_event e devolve a resposta final.
    """
    global _chat

    if _chat is None:
        _chat = Chat(SYSTEM_PROMPT)
    _chat.add_user_message(user_text)

    try:
        pendentes: list[asyncio.Future] = []
        resposta_final = ""

        async def capturar(event: dict) -> None:
            nonlocal resposta_final
            if event.get("kind") == "text":
                resposta_final = event["text"]
            await on_event(event)

        async with AsyncClient(**_client_kwargs()) as client:
            llm = await _resolve_llm(client, capturar, pendentes)

            # O SDK 1.5.0 expõe ActResult.rounds apenas como contagem; a
            # resposta final chega pelo callback, no último texto do assistente.
            await llm.act(
                _chat,
                TOOLS,
                on_message=lambda message: _forward(message, capturar, pendentes),
            )

            # Drena os eventos agendados para a resposta final não chegar na
            # frente das linhas de ferramenta na interface.
            if pendentes:
                await asyncio.gather(*pendentes)

            if not resposta_final:
                resposta_final = "A IA terminou sem texto de resposta."

            await on_event({"kind": "answer", "text": resposta_final})
            return resposta_final

    except AgentError:
        raise
    except Exception as e:
        if _is_masked_auth_failure(e):
            raise AgentError(AUTH_HINT) from e
        texto = str(e).lower()
        sem_conexao = (
            isinstance(
                e,
                (
                    ConnectionError,
                    OSError,
                    lms.LMStudioTimeoutError,
                    lms.LMStudioClientError,
                    lms.LMStudioWebsocketError,
                ),
            )
            or "not reachable" in texto
            or "is lm studio running" in texto
        )
        if sem_conexao:
            raise AgentError(
                "LM Studio não acessível. Abra o LM Studio e inicie o servidor "
                "(aba Developer). Detalhe: " + str(e)[:200]
            ) from e
        raise


def _emit(
    on_event: Callable[[dict], Awaitable[None]],
    event: dict,
    pendentes: Optional[list[asyncio.Future]] = None,
) -> None:
    """
    Encaminha um evento do callback síncrono do SDK para o handler assíncrono.

    O SDK chama on_message/on_load_progress de dentro do próprio event loop,
    então criamos a task aqui; o futuro fica registrado para o chamador poder
    aguardar a ordem correta antes de devolver a resposta.
    """
    task = asyncio.ensure_future(on_event(event))
    if pendentes is not None:
        pendentes.append(task)


def _forward(
    message: Any,
    on_event: Callable[[dict], Awaitable[None]],
    pendentes: Optional[list[asyncio.Future]] = None,
) -> None:
    for event in _describe_message(message):
        _emit(on_event, event, pendentes)


async def agent_status() -> dict:
    """Verifica se o LM Studio está acessível e qual modelo será usado."""
    try:
        async with AsyncClient(**_client_kwargs()) as client:
            loaded = [m.identifier for m in await client.llm.list_loaded()]
            downloaded = [m.model_key for m in await client.llm.list_downloaded()]
            alvo = MODEL_NAME or (loaded[0] if loaded else (downloaded[0] if downloaded else ""))
            matching = [k for k in downloaded if alvo and alvo.lower() in k.lower()]
            return {
                "connected": True,
                "model": alvo or "(nenhum)",
                "auto_selected": not bool(MODEL_NAME),
                "loaded_models": loaded,
                "has_matching_model": bool(loaded) or bool(matching),
                "downloaded_count": len(downloaded),
            }
    except Exception as e:
        if _is_masked_auth_failure(e):
            return {"connected": False, "model": MODEL_NAME, "error": AUTH_HINT}
        return {
            "connected": False,
            "model": MODEL_NAME or "(auto)",
            "error": "LM Studio inacessível na API local (porta 41343). "
                     "Abra o LM Studio e inicie o servidor. " + str(e)[:200],
        }
