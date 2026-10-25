"""
API HTTP do editor profissional do ClipMind.

Mantém a interface antiga intacta e acrescenta o fluxo de projeto: timeline,
undo/redo, versões, validação, render em segundo plano e chat com ferramentas
de timeline. Todas as operações passam pelo modelo validado de editor_project.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Awaitable, Callable, Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

import editor_analysis
import editor_skills
import timeline_agent
from agent import agent_status
from editor_project import (
    ProjectError,
    STORE,
    has_errors,
    project_summary,
    project_view,
    validate_project,
)
from editor_render import MANAGER, RenderError, validate_render
from youtube_editor_tools import OUTPUT_DIR


router = APIRouter()
UPLOAD_DIR = Path("./uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
templates = Jinja2Templates(directory="templates")

_sink: Optional[Callable[[dict], Awaitable[None]]] = None

_MEDIA_TYPES = {
    ".mp4": "video/mp4", ".mkv": "video/x-matroska", ".webm": "video/webm",
    ".mov": "video/quicktime", ".avi": "video/x-msvideo",
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
    ".aac": "audio/aac", ".flac": "audio/flac", ".ogg": "audio/ogg",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
}


def configure(sink: Callable[[dict], Awaitable[None]]) -> None:
    """Registra o broadcast do WebSocket sem criar import circular."""
    global _sink
    _sink = sink


async def _emit(event: dict) -> None:
    if _sink is not None:
        await _sink(event)


def _payload(project_id: str) -> dict:
    projeto = STORE.get(project_id)
    return {
        "project": project_view(projeto),
        "issues": validate_project(projeto),
        "history": STORE.history(project_id),
        "summary": project_summary(projeto),
        "active": STORE.get_active(),
    }


def _jobs_of(project_id: str) -> list[dict]:
    """Lista as filas do projeto; id desconhecido cai em 404 como as rotas irmãs."""
    try:
        STORE.get(project_id)
    except ProjectError as e:
        raise _handle(e)
    return MANAGER.list(project_id)


def _handle(exc: Exception) -> HTTPException:
    if isinstance(exc, ProjectError):
        mensagem = str(exc)
        # "não encontrado/a" é recurso ausente; o resto é pedido malformado
        if "não encontrad" in mensagem or "não pertence" in mensagem:
            return HTTPException(status_code=404, detail=mensagem)
        return HTTPException(status_code=400, detail=mensagem)
    if isinstance(exc, RenderError):
        return HTTPException(status_code=409, detail=str(exc))
    raise exc


async def _corpo(request: Request) -> dict:
    """Lê o JSON do pedido como objeto; corpo inválido é erro do cliente."""
    try:
        texto = await request.body()
        dados = json.loads(texto.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="O corpo precisa ser JSON válido")
    if not isinstance(dados, dict):
        raise HTTPException(status_code=400, detail="O corpo precisa ser um objeto JSON")
    return dados


def _media_allowed(path: Path) -> bool:
    """Só serve mídia já usada por algum projeto ou enviada para ./uploads."""
    try:
        resolvido = path.resolve()
    except OSError:
        return False
    if not resolvido.is_file():
        return False
    try:
        if UPLOAD_DIR.resolve() in resolvido.parents or OUTPUT_DIR.resolve() in resolvido.parents:
            return True
    except OSError:
        pass
    for item in STORE.list_projects():
        try:
            projeto = STORE.get(item["id"])
        except ProjectError:
            continue
        for caminho in projeto.get("media", {}):
            try:
                if Path(caminho).resolve() == resolvido:
                    return True
            except OSError:
                continue
    return False


@router.get("/editor", response_class=HTMLResponse)
async def editor_page(request: Request):
    """Interface profissional com timeline multipista."""
    return templates.TemplateResponse(request, "editor.html")


@router.get("/api/editor/status")
async def editor_status():
    status = await agent_status()
    status["skills"] = len(editor_skills.list_skills())
    return status


@router.get("/api/editor/projects")
async def list_projects():
    projetos = STORE.list_projects()
    return {"projects": projetos, "active": STORE.get_active()}


@router.post("/api/editor/projects")
async def create_project(request: Request):
    body = await _corpo(request)
    inesperados = set(body) - {"name", "width", "height", "fps"}
    if inesperados:
        raise HTTPException(
            status_code=400,
            detail=f"Campo inesperado na criação do projeto: {sorted(inesperados)[0]}",
        )
    try:
        projeto = STORE.create(
            body.get("name", ""),
            int(body.get("width", 1920)),
            int(body.get("height", 1080)),
            body.get("fps", 30),
        )
        STORE.set_active(projeto["id"])
    except (ProjectError, TypeError, ValueError) as e:
        raise _handle(e if isinstance(e, ProjectError) else ProjectError(str(e)))
    await _emit({"type": "editor_projects"})
    return _payload(projeto["id"])


@router.post("/api/editor/projects/{project_id}/activate")
async def activate_project(project_id: str):
    try:
        STORE.set_active(project_id)
    except ProjectError as e:
        raise _handle(e)
    return _payload(project_id)


@router.get("/api/editor/projects/{project_id}")
async def get_project(project_id: str):
    try:
        payload = _payload(project_id)
        payload["versions"] = STORE.versions(project_id)
        payload["jobs"] = MANAGER.list(project_id)
        return payload
    except ProjectError as e:
        raise _handle(e)


@router.delete("/api/editor/projects/{project_id}")
async def delete_project(project_id: str, confirm: bool = False):
    try:
        STORE.delete(project_id, confirm=confirm)
    except ProjectError as e:
        raise _handle(e)
    await _emit({"type": "editor_projects"})
    return {"ok": True}


@router.post("/api/editor/projects/{project_id}/operations")
async def apply_operation(project_id: str, request: Request):
    body = await _corpo(request)
    operation = str(body.get("operation") or "")
    params = body.get("params") or {}
    if not isinstance(params, dict):
        raise HTTPException(status_code=400, detail="params precisa ser um objeto")
    try:
        STORE.apply(project_id, operation, params)
    except ProjectError as e:
        raise _handle(e)
    await _emit({"type": "editor_project_changed", "project_id": project_id, "operation": operation})
    return _payload(project_id)


@router.post("/api/editor/projects/{project_id}/undo")
async def undo(project_id: str):
    try:
        STORE.undo(project_id)
    except ProjectError as e:
        raise _handle(e)
    await _emit({"type": "editor_project_changed", "project_id": project_id, "operation": "undo"})
    return _payload(project_id)


@router.post("/api/editor/projects/{project_id}/redo")
async def redo(project_id: str):
    try:
        STORE.redo(project_id)
    except ProjectError as e:
        raise _handle(e)
    await _emit({"type": "editor_project_changed", "project_id": project_id, "operation": "redo"})
    return _payload(project_id)


@router.get("/api/editor/projects/{project_id}/versions")
async def versions(project_id: str):
    try:
        return {"versions": STORE.versions(project_id)}
    except ProjectError as e:
        raise _handle(e)


@router.post("/api/editor/projects/{project_id}/versions/{version_name}/restore")
async def restore_version(project_id: str, version_name: str):
    try:
        STORE.restore_version(project_id, version_name)
    except ProjectError as e:
        raise _handle(e)
    return _payload(project_id)


@router.get("/api/editor/projects/{project_id}/validate")
async def validate(project_id: str):
    try:
        projeto = STORE.get(project_id)
    except ProjectError as e:
        raise _handle(e)
    issues = validate_project(projeto)
    return {"issues": issues, "ok": not has_errors(issues)}


@router.post("/api/editor/projects/{project_id}/analyze")
async def analyze(project_id: str, request: Request):
    """
    Mede o conteúdo de um clipe com FFmpeg e devolve candidatos.

    A medição roda em thread: ler dez minutos de áudio com silencedetect é lento
    demais para deixar no event loop, que serve o WebSocket da interface. Com
    `apply=true` os candidatos viram marcadores/regiões num passo só de undo; o
    corte em si continua sendo decisão de quem edita.
    """
    body = await _corpo(request)
    try:
        projeto = STORE.get(project_id)
    except ProjectError as e:
        raise _handle(e)

    try:
        analise = await asyncio.to_thread(
            editor_analysis.analyze_clip,
            projeto,
            str(body.get("clip_id") or ""),
            str(body.get("kind") or "scenes"),
            threshold=float(body.get("threshold", 15)),
            noise=float(body.get("noise", -30)),
            min_pause=float(body.get("min_pause", 0.5)),
        )
    except (ProjectError, TypeError, ValueError) as e:
        raise _handle(e if isinstance(e, ProjectError) else ProjectError(str(e)))

    resposta: dict = {"analysis": analise, "project": project_view(projeto)}
    if not body.get("apply"):
        return resposta

    anotacao = editor_analysis.build_annotations(analise)
    if not (anotacao["markers"] or anotacao["regions"]):
        raise HTTPException(status_code=400, detail="Essa análise não tem candidato para gravar")
    try:
        atualizado = STORE.apply(project_id, "annotate", {
            "group": anotacao["group"],
            "markers": anotacao["markers"],
            "regions": anotacao["regions"],
        })
    except ProjectError as e:
        raise _handle(e)
    # O que se conta aqui é o projeto depois da escrita, não o que se pediu: se
    # o motor deduplicou um tempo, a interface mostra o que de fato está na timeline.
    resposta["annotations"] = {
        "group": anotacao["group"],
        "markers": sum(1 for m in atualizado.get("markers", []) if m.get("group") == anotacao["group"]),
        "regions": sum(1 for r in atualizado.get("regions", []) if r.get("group") == anotacao["group"]),
    }
    resposta["project"] = project_view(atualizado)
    await _emit({
        "type": "editor_project_changed",
        "project_id": project_id,
        "operation": "annotate",
    })
    return resposta


@router.post("/api/editor/projects/{project_id}/render")
async def render(project_id: str, request: Request):
    options = await _corpo(request)
    try:
        job = MANAGER.submit(project_id, options)
    except (RenderError, ProjectError) as e:
        raise _handle(e)
    return {"job": job}


@router.get("/api/editor/projects/{project_id}/jobs")
async def project_jobs(project_id: str):
    return {"jobs": _jobs_of(project_id)}


@router.get("/api/editor/jobs/{job_id}")
async def get_job(job_id: str):
    try:
        return {"job": MANAGER.get(job_id)}
    except RenderError as e:
        raise _handle(e)


@router.delete("/api/editor/jobs/{job_id}")
async def cancel_job(job_id: str):
    try:
        return {"job": MANAGER.cancel(job_id)}
    except RenderError as e:
        raise _handle(e)


@router.post("/api/editor/jobs/{job_id}/validate")
async def validate_job(job_id: str):
    try:
        job = MANAGER.get(job_id)
    except RenderError as e:
        raise _handle(e)
    if job["status"] != "done" or not job.get("output_path"):
        raise HTTPException(status_code=409, detail="A renderização ainda não terminou")
    try:
        projeto = STORE.get(job["project_id"])
        qc = validate_render(job["output_path"], projeto)
    except (ProjectError, RenderError) as e:
        raise _handle(e)
    return {"qc": qc}


@router.get("/api/editor/media")
async def serve_source(path: str):
    """Serve somente mídia pertencente a um projeto ou enviada pela interface."""
    arquivo = Path(path).expanduser()
    if not _media_allowed(arquivo):
        raise HTTPException(status_code=404, detail="Mídia não encontrada neste projeto")
    return FileResponse(
        arquivo,
        media_type=_MEDIA_TYPES.get(arquivo.suffix.lower(), "application/octet-stream"),
    )


@router.get("/api/editor/uploads")
async def list_uploads():
    """Lista os vídeos, áudios e imagens enviados pela interface."""
    itens = []
    for arquivo in sorted(UPLOAD_DIR.rglob("*")):
        if not arquivo.is_file() or arquivo.name.startswith("."):
            continue
        tipo = _MEDIA_TYPES.get(arquivo.suffix.lower())
        if tipo is None:
            continue
        try:
            stat = arquivo.stat()
        except OSError:
            continue
        itens.append({
            "name": arquivo.name,
            "path": str(arquivo.resolve()),
            "kind": tipo.split("/", 1)[0],
            "size": stat.st_size,
            "modified": int(stat.st_mtime),
        })
    itens.sort(key=lambda item: item["modified"], reverse=True)
    return {"uploads": itens[:80]}


@router.get("/api/editor/skills")
async def list_skills():
    return {"skills": editor_skills.list_skills()}


@router.get("/api/editor/skills/{name}")
async def get_skill(name: str):
    try:
        return editor_skills.load_skill(name)
    except ProjectError as e:
        raise _handle(e)


@router.post("/api/editor/projects/{project_id}/chat")
async def chat(project_id: str, request: Request):
    body = await _corpo(request)
    message = str(body.get("message") or "").strip()
    turn_id = str(body.get("turn_id") or "")
    if not message:
        raise HTTPException(status_code=400, detail="Mensagem vazia")
    try:
        STORE.get(project_id)
        if STORE.get_active() != project_id:
            STORE.set_active(project_id)
    except ProjectError as e:
        raise _handle(e)

    async def forward(event: dict) -> None:
        await _emit({
            "type": "editor_agent",
            "turn_id": turn_id,
            "project_id": project_id,
            **event,
        })
        if event.get("kind") == "tool_result":
            await _emit({"type": "editor_project_changed", "project_id": project_id, "operation": event.get("name")})

    try:
        answer = await timeline_agent.run_timeline_turn(project_id, message, forward)
        return {"answer": answer, "turn_id": turn_id, "project": project_view(STORE.get(project_id))}
    except timeline_agent.TimelineAgentError as e:
        return {"answer": str(e), "error": True, "turn_id": turn_id}
    except Exception as e:
        detail = f"Falha inesperada no agente do editor: {type(e).__name__}: {e}"
        await forward({"kind": "error", "text": detail})
        return {"answer": detail, "error": True, "turn_id": turn_id}


@router.post("/api/editor/projects/{project_id}/chat/reset")
async def reset_chat(project_id: str):
    timeline_agent.reset_chat(project_id)
    await _emit({"type": "editor_chat_reset", "project_id": project_id})
    return {"ok": True}


@router.get("/api/editor/projects/{project_id}/preview")
async def latest_preview(project_id: str):
    """Última prévia/export concluído do projeto, para reabrir o monitor."""
    jobs = _jobs_of(project_id)
    for job in jobs:
        if job["status"] == "done" and job.get("output_name"):
            return {
                "job": job,
                "url": f"/preview/{quote(job['output_name'])}",
                "download_url": f"/download/{quote(job['output_name'])}",
            }
    return {"job": None}
