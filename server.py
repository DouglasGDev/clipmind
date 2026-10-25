"""
Servidor web do ClipMind - interface visual para edição de vídeo com IA local.

FastAPI + WebSocket para feedback em tempo real. A IA (agent.py) usa tool
calling real e cada ferramenta executa FFmpeg de verdade.
"""

import asyncio
import inspect
import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from youtube_editor_tools import (
    TOOL_SPECS,
    OUTPUT_DIR,
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
from agent import AgentError, agent_status, reset_chat, run_agent_turn
import editor_api


app = FastAPI(title="ClipMind - Editor de Vídeo com IA")
app.include_router(editor_api.router)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

UPLOAD_DIR = Path("./uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

active_connections: list[WebSocket] = []

# Whitelist explícita: o endpoint genérico só executa funções registradas aqui.
FERRAMENTAS = {
    f.__name__: f
    for f in (
        inspect_video, detect_scenes, cut_video, cut_multiple_segments,
        remove_silence, join_videos, optimize_for_youtube, resize_for_shorts,
        compress_video, convert_video, create_thumbnail, create_contact_sheet,
        create_gif, extract_audio, normalize_audio, add_music, change_speed,
        fade_video, rotate_video, crop_video, loop_video, add_text,
        burn_subtitles,
    )
}

_SPECS = {spec["name"]: spec for spec in TOOL_SPECS}

_SAIDA_RE = re.compile(r"salv[oa] em:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)

# Extensões por categoria para a galeria
_CATEGORIA = {
    **dict.fromkeys([".mp4", ".mkv", ".webm", ".mov", ".avi"], "video"),
    **dict.fromkeys([".jpg", ".jpeg", ".png", ".webp"], "image"),
    **dict.fromkeys([".mp3", ".wav", ".m4a", ".aac", ".flac"], "audio"),
    **dict.fromkeys([".gif"], "gif"),
}

_MEDIA_TYPES = {
    ".mp4": "video/mp4",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
}


async def send_to_all(message: dict):
    """Envia mensagem para todos os clientes WebSocket conectados."""
    for connection in list(active_connections):
        try:
            await connection.send_json(message)
        except Exception:
            if connection in active_connections:
                active_connections.remove(connection)


editor_api.configure(send_to_all)


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Página principal."""
    return templates.TemplateResponse(request, "index.html")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket para feedback em tempo real."""
    await websocket.accept()
    active_connections.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in active_connections:
            active_connections.remove(websocket)


@app.get("/agent-status")
async def get_agent_status():
    """Informa se a IA (LM Studio) está acessível."""
    return await agent_status()


@app.get("/tools")
async def list_tools():
    """Catálogo das ferramentas manuais, usado para montar a interface."""
    return [
        {**spec, "available": spec["name"] in FERRAMENTAS}
        for spec in TOOL_SPECS
    ]


@app.post("/tool/{name}")
async def run_tool(name: str, payload: Optional[dict] = None):
    """
    Executa uma ferramenta manualmente a partir do painel.

    Os campos vêm do formulário como texto; parâmetros ausentes usam o padrão
    da função. Só nomes registrados em FERRAMENTAS são aceitos.
    """
    func = FERRAMENTAS.get(name)
    if func is None:
        raise HTTPException(status_code=404, detail=f"Ferramenta desconhecida: {name}")

    payload = payload or {}
    assinatura = inspect.signature(func)
    argumentos: dict[str, str] = {}
    for param in assinatura.parameters.values():
        valor = payload.get(param.name)
        if valor is None or str(valor).strip() == "":
            if param.default is inspect.Parameter.empty:
                raise HTTPException(
                    status_code=400,
                    detail=f"O campo '{param.name}' é obrigatório para {name}.",
                )
            continue
        argumentos[param.name] = str(valor).strip()

    rotulo = _SPECS.get(name, {}).get("label", name)
    await send_to_all({"type": "processing", "action": f"{rotulo}..."})
    try:
        resultado = await asyncio.to_thread(func, **argumentos)
    finally:
        await send_to_all({"type": "complete", "action": rotulo})

    texto = str(resultado)
    saida = _extrair_saida(texto)
    dados = None
    if texto.lstrip().startswith("{"):
        try:
            dados = json.loads(texto)
        except json.JSONDecodeError:
            pass

    return {
        "ok": not texto.startswith("Erro"),
        "result": texto,
        "output_path": str(saida) if saida else None,
        "output_name": saida.name if saida else None,
        "data": dados,
    }


def _extrair_saida(texto: str) -> Optional[Path]:
    """
    Localiza o arquivo gerado na mensagem da ferramenta.

    Só aceita caminhos que estejam dentro de ./output, para nunca expor outro
    arquivo do disco pela galeria ou pelo download.
    """
    match = _SAIDA_RE.search(texto)
    if not match:
        return None
    caminho = Path(match.group(1).strip().strip('"'))
    try:
        resolvido = caminho.resolve()
        raiz = OUTPUT_DIR.resolve()
        if resolvido.is_file() and raiz in resolvido.parents:
            return resolvido
    except OSError:
        pass
    return None


@app.post("/chat")
async def chat(
    message: str = Form(...),
    file_path: str = Form(""),
    turn_id: str = Form(""),
):
    """
    Turno do agente: a IA escolhe e executa ferramentas de verdade.

    Cada chamada de ferramenta é transmitida em tempo real pelo WebSocket,
    então a interface mostra a IA trabalhando enquanto o FFmpeg roda.
    O turn_id permite que a aba que fez o pedido reconheça os próprios eventos.
    """
    async def forward(event: dict):
        await send_to_all({"type": "agent", "turn_id": turn_id, **event})

    texto = message.strip()
    if file_path.strip():
        texto = f"{texto}\n\n(Arquivo em edição nesta sessão: {file_path.strip()})"

    try:
        answer = await run_agent_turn(texto, forward)
        return {"answer": answer, "turn_id": turn_id}
    except AgentError as e:
        await send_to_all(
            {"type": "agent", "turn_id": turn_id, "kind": "error", "text": str(e)}
        )
        return {"answer": str(e), "error": True, "turn_id": turn_id}
    except Exception as e:
        detail = f"Falha inesperada no agente: {type(e).__name__}: {e}"
        await send_to_all(
            {"type": "agent", "turn_id": turn_id, "kind": "error", "text": detail}
        )
        return {"answer": detail, "error": True, "turn_id": turn_id}


@app.post("/chat/reset")
async def chat_reset():
    """Descarta o histórico para começar uma conversa nova."""
    reset_chat()
    await send_to_all({"type": "chat_reset"})
    return {"ok": True}


@app.get("/media-info")
async def media_info(path: str):
    """Metadados do vídeo em edição, sem poluir o feed de eventos."""
    if not Path(path).is_file():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    resultado = await asyncio.to_thread(inspect_video, path)
    try:
        return json.loads(resultado)
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail=resultado) from None


@app.post("/upload")
async def upload_video(file: UploadFile = File(...)):
    """Recebe um vídeo e devolve o caminho local para as ferramentas."""
    original = Path(file.filename or "video.mp4").name.strip() or "video.mp4"
    pasta = UPLOAD_DIR / uuid.uuid4().hex[:8]
    pasta.mkdir(parents=True, exist_ok=True)
    file_path = pasta / original

    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    return {"file_path": str(file_path.resolve()), "file_id": pasta.name, "name": original}


def _arquivo_seguro(nome: str) -> Optional[Path]:
    """Resolve um nome dentro de ./output, rejeitando travessia de diretório."""
    if not nome or Path(nome).name != nome:
        return None
    caminho = (OUTPUT_DIR / nome).resolve()
    raiz = OUTPUT_DIR.resolve()
    if caminho.parent != raiz or not caminho.is_file():
        return None
    return caminho


@app.get("/outputs")
async def list_outputs():
    """Lista os arquivos já gerados, do mais recente para o mais antigo."""
    itens = []
    for caminho in OUTPUT_DIR.iterdir():
        if not caminho.is_file() or caminho.name.startswith("."):
            continue
        try:
            stat = caminho.stat()
        except OSError:
            continue
        itens.append({
            "name": caminho.name,
            "path": str(caminho.resolve()),
            "url": f"/preview/{quote(caminho.name)}",
            "download_url": f"/download/{quote(caminho.name)}",
            "kind": _CATEGORIA.get(caminho.suffix.lower(), "other"),
            "size": stat.st_size,
            "modified": int(stat.st_mtime),
        })
    itens.sort(key=lambda item: item["modified"], reverse=True)
    return itens[:60]


@app.get("/preview/{filename}")
async def preview_file(filename: str):
    """Serve um arquivo de ./output para pré-visualização na galeria."""
    caminho = _arquivo_seguro(filename)
    if caminho is None:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    return FileResponse(
        caminho,
        media_type=_MEDIA_TYPES.get(caminho.suffix.lower(), "application/octet-stream"),
    )


@app.get("/download/{filename}")
async def download_file(filename: str):
    """Download de um arquivo gerado em ./output."""
    caminho = _arquivo_seguro(filename)
    if caminho is None:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    return FileResponse(caminho, filename=caminho.name)


if __name__ == "__main__":
    import uvicorn
    print("\n" + "=" * 60)
    print("  CLIPMIND - Interface Web")
    print("  Acesse: http://localhost:8000")
    print("=" * 60 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)
