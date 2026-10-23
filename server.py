"""
Servidor web do ClipMind - Interface visual para edição de vídeo com IA.
FastAPI + WebSocket para feedback em tempo real.
"""

import asyncio
import json
import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect, Form
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from youtube_editor_tools import (
    inspect_video,
    cut_video,
    create_thumbnail,
    optimize_for_youtube,
    remove_silence,
    extract_audio,
    OUTPUT_DIR,
)
from agent import AgentError, agent_status, run_agent_turn


app = FastAPI(title="ClipMind - Editor de Vídeo com IA")

# Monta arquivos estáticos
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Pasta de uploads
UPLOAD_DIR = Path("./uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# WebSocket connections
active_connections: list[WebSocket] = []


async def send_to_all(message: dict):
    """Envia mensagem para todos os clientes WebSocket conectados."""
    for connection in active_connections:
        try:
            await connection.send_json(message)
        except:
            pass


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
            # Mantém conexão viva
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        active_connections.remove(websocket)


@app.get("/agent-status")
async def get_agent_status():
    """Informa se a IA (LM Studio) está acessível."""
    return await agent_status()


@app.post("/chat")
async def chat(message: str = Form(...)):
    """
    Turno do agente: a IA escolhe e executa ferramentas de verdade.

    Cada chamada de ferramenta é transmitida em tempo real pelo WebSocket,
    então a interface mostra a IA trabalhando enquanto o FFmpeg roda.
    """
    async def forward(event: dict):
        await send_to_all({"type": "agent", **event})

    try:
        answer = await run_agent_turn(message, forward)
        return {"answer": answer}
    except AgentError as e:
        await send_to_all({"type": "agent", "kind": "error", "text": str(e)})
        return {"answer": str(e), "error": True}
    except Exception as e:
        detail = f"Falha inesperada no agente: {type(e).__name__}: {e}"
        await send_to_all({"type": "agent", "kind": "error", "text": detail})
        return {"answer": detail, "error": True}


@app.post("/upload")
async def upload_video(file: UploadFile = File(...)):
    """Upload de vídeo."""
    # Gera nome único para evitar conflitos
    file_id = str(uuid.uuid4())[:8]
    file_ext = Path(file.filename).suffix
    file_path = UPLOAD_DIR / f"{file_id}{file_ext}"
    
    # Salva o arquivo
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    
    return {"file_path": str(file_path), "file_id": file_id}


@app.post("/analyze")
async def analyze_video(file_path: str = Form(...)):
    """Analisa o vídeo e retorna informações."""
    await send_to_all({"type": "processing", "action": "Analisando vídeo..."})
    
    result = await asyncio.to_thread(inspect_video, file_path)
    
    await send_to_all({"type": "complete", "action": "Análise completa"})
    return {"result": json.loads(result)}


@app.post("/cut")
async def cut_video_endpoint(
    file_path: str = Form(...),
    start: str = Form(...),
    end: Optional[str] = Form(None),
    duration: Optional[str] = Form(None)
):
    """Corta o vídeo."""
    await send_to_all({"type": "processing", "action": "Cortando vídeo..."})
    
    result = await asyncio.to_thread(cut_video, file_path, start, end, duration)
    
    await send_to_all({"type": "complete", "action": "Corte completo"})
    return {"result": result, "output_path": result.split(": ")[-1] if "salvo em:" in result else None}


@app.post("/thumbnail")
async def create_thumbnail_endpoint(
    file_path: str = Form(...),
    time: str = Form("00:00:05")
):
    """Cria thumbnail do vídeo."""
    await send_to_all({"type": "processing", "action": "Criando thumbnail..."})
    
    result = await asyncio.to_thread(create_thumbnail, file_path, time)
    
    await send_to_all({"type": "complete", "action": "Thumbnail criada"})
    return {"result": result, "output_path": result.split(": ")[-1] if "salva em:" in result else None}


@app.post("/optimize")
async def optimize_video_endpoint(
    file_path: str = Form(...),
    resolution: str = Form("1920x1080")
):
    """Otimiza vídeo para YouTube."""
    await send_to_all({"type": "processing", "action": "Otimizando para YouTube..."})
    
    result = await asyncio.to_thread(optimize_for_youtube, file_path, resolution)
    
    await send_to_all({"type": "complete", "action": "Otimização completa"})
    return {"result": result, "output_path": result.split(": ")[-1] if "salvo em:" in result else None}


@app.post("/remove-silence")
async def remove_silence_endpoint(
    file_path: str = Form(...),
    noise: str = Form("-30dB"),
    duration: str = Form("0.5")
):
    """Remove silêncio do vídeo."""
    await send_to_all({"type": "processing", "action": "Removendo silêncio..."})
    
    result = await asyncio.to_thread(remove_silence, file_path, noise, duration)
    
    await send_to_all({"type": "complete", "action": "Silêncio removido"})
    return {"result": result, "output_path": result.split(": ")[-1] if "salvo em:" in result else None}


@app.post("/extract-audio")
async def extract_audio_endpoint(file_path: str = Form(...)):
    """Extrai áudio do vídeo."""
    await send_to_all({"type": "processing", "action": "Extraindo áudio..."})
    
    result = await asyncio.to_thread(extract_audio, file_path)
    
    await send_to_all({"type": "complete", "action": "Áudio extraído"})
    return {"result": result, "output_path": result.split(": ")[-1] if "salvo em:" in result else None}


@app.get("/download/{filename}")
async def download_file(filename: str):
    """Download de arquivo processado."""
    file_path = OUTPUT_DIR / filename
    if file_path.exists():
        return FileResponse(file_path, filename=filename)
    return {"error": "Arquivo não encontrado"}


@app.get("/video/{path:path}")
async def serve_video(path: str):
    """Serve arquivo de vídeo para preview."""
    file_path = Path(path)
    if file_path.exists():
        return FileResponse(file_path, media_type="video/mp4")
    return {"error": "Vídeo não encontrado"}


if __name__ == "__main__":
    import uvicorn
    print("\n" + "=" * 60)
    print("  CLIPMIND - Interface Web")
    print("  Acesse: http://localhost:8000")
    print("=" * 60 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)
