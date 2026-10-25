"""
Agente de IA especializado na timeline do ClipMind.

Usa o mesmo SDK oficial do LM Studio do agente principal, mas com um conjunto
menor de ferramentas focadas em projeto, cortes, títulos, legendas, validação
e renderização. Cada ferramenta valida os parâmetros no motor da timeline; a
IA nunca executa FFmpeg diretamente.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import contextmanager
from typing import Optional

import lmstudio as lms
from lmstudio import AsyncClient, Chat

import editor_analysis
import editor_skills
from agent import (
    _client_kwargs,
    _forward,
    _is_masked_auth_failure,
    _resolve_llm,
)
from editor_project import (
    ProjectError,
    STORE,
    add_clip,
    add_marker,
    add_subtitle_clip,
    add_text_clip,
    annotate,
    apply_operation,
    clear_annotations,
    delete_clip,
    duplicate_clip,
    format_timecode,
    get_clip,
    has_errors,
    move_clip,
    project_duration,
    project_summary,
    project_view,
    roll_edit,
    set_clip_properties,
    slide_clip,
    slip_clip,
    split_clip,
    trim_clip,
    validate_project,
)
from editor_render import MANAGER, RenderError


class TimelineAgentError(RuntimeError):
    """Falha de comunicação ou de configuração do agente do editor."""


def _project(project_id: str = "") -> dict:
    pid = (project_id or "").strip() or STORE.get_active()
    if not pid:
        raise ProjectError(
            "Nenhum projeto ativo. Crie um projeto no editor ou informe project_id."
        )
    return STORE.get(pid)


@contextmanager
def _editing(project_id: str, label: str):
    """Entrega o projeto vivo para mutação e grava undo + autosave ao final."""
    pid = (project_id or "").strip() or STORE.get_active()
    if not pid:
        raise ProjectError(
            "Nenhum projeto ativo. Crie um projeto no editor ou informe project_id."
        )
    with STORE.edit(pid, label) as projeto:
        yield projeto


def _brief(project: dict) -> str:
    issues = validate_project(project, check_media=False)
    erros = [i for i in issues if i["severity"] == "error"]
    avisos = [i for i in issues if i["severity"] == "warning"]
    resumo = project_summary(project)
    if len(resumo) > 5000:
        resumo = resumo[:5000] + "\n[resumo truncado]"
    return json.dumps(
        {
            "ok": not erros,
            "project_id": project["id"],
            "duracao": format_timecode(project_duration(project)),
            "erros": erros[:8],
            "avisos": avisos[:8],
            "resumo": resumo,
        },
        ensure_ascii=False,
    )


def _fail(message: str) -> str:
    return json.dumps({"ok": False, "erro": message}, ensure_ascii=False)


def _ok(project: dict, message: str, **extra) -> str:
    dados = {
        "ok": True,
        "mensagem": message,
        "project_id": project["id"],
        "resumo": project_summary(project),
    }
    dados.update(extra)
    return json.dumps(dados, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Ferramentas de projeto
# ---------------------------------------------------------------------------

def create_edit_project(
    name: str,
    width: int = 1920,
    height: int = 1080,
    fps: float = 30,
) -> str:
    """
    Cria um projeto de edição vazio e o torna o projeto ativo.

    Args:
        name: nome do projeto.
        width: largura final, por exemplo 1920 (horizontal) ou 1080 (vertical).
        height: altura final, por exemplo 1080 (horizontal) ou 1920 (vertical).
        fps: taxa de quadros do projeto (30, 60, 24...).
    """
    try:
        projeto = STORE.create(name, width, height, fps)
        STORE.set_active(projeto["id"])
        return _ok(projeto, f"Projeto '{projeto['name']}' criado e ativado.")
    except (ProjectError, TypeError, ValueError) as e:
        return _fail(str(e))


def inspect_edit_project(project_id: str = "") -> str:
    """
    Mostra a timeline atual: faixas, clipes, ids, tempos, arquivos e problemas.

    Use esta ferramenta antes de qualquer edição e depois de cada etapa para
    confirmar os ids e a duração. project_id vazio usa o projeto ativo.
    """
    try:
        return _brief(_project(project_id))
    except ProjectError as e:
        return _fail(str(e))


def configure_edit_project(
    project_id: str = "",
    name: str = "",
    width: int = 0,
    height: int = 0,
    fps: float = 0,
) -> str:
    """
    Altera nome, resolução e fps do projeto. Use 0 para manter um campo.

    Mude a resolução apenas quando o destino exigir (por exemplo 1080x1920
    para Shorts); o renderizador reenquadra os clipes existentes.
    """
    try:
        props = {}
        if name:
            props["name"] = name
        if width:
            props["width"] = width
        if height:
            props["height"] = height
        if fps:
            props["fps"] = fps
        if not props:
            return _fail("Informe ao menos um campo para alterar")
        with _editing(project_id, "Alterar configurações") as projeto:
            apply_operation(projeto, "settings", props)
        return _ok(projeto, "Configurações do projeto atualizadas.")
    except ProjectError as e:
        return _fail(str(e))


# ---------------------------------------------------------------------------
# Mídia, títulos e legendas
# ---------------------------------------------------------------------------

def add_timeline_clip(
    project_id: str = "",
    source: str = "",
    track: str = "v1",
    start: Optional[float] = None,
    in_point: float = 0,
    out_point: Optional[float] = None,
    speed: float = 1,
    volume: float = 1,
) -> str:
    """
    Adiciona um arquivo de vídeo ou áudio à timeline, sem copiar o original.

    Args:
        source: caminho do arquivo de mídia.
        track: id da faixa (v1 vídeo, v2 sobreposição, a1 áudio).
        start: segundo na timeline; vazio coloca no fim da faixa.
        in_point: segundo inicial dentro do arquivo.
        out_point: segundo final dentro do arquivo; vazio usa até o fim.
        speed: 0.1 a 8 (1 = normal).
        volume: 0 a 4 (1 = original).
    """
    try:
        with _editing(project_id, "Adicionar clipe") as projeto:
            clip = add_clip(
                projeto, track_id=track, source=source, start=start,
                in_point=in_point, out_point=out_point, speed=speed, volume=volume,
            )
        return _ok(
            projeto,
            f"Clipe {clip['id']} adicionado em {track} "
            f"({format_timecode(clip['start'])}–{format_timecode(clip['start'] + (clip['out']-clip['in'])/max(0.1, clip['speed']))}).",
            clip_id=clip["id"],
        )
    except ProjectError as e:
        return _fail(str(e))


def add_timeline_text(
    project_id: str = "",
    text: str = "",
    start: float = 0,
    duration: float = 3,
    font_size: int = 56,
    position: str = "inferior",
    color: str = "white",
    background: bool = True,
) -> str:
    """
    Cria um título na faixa de títulos (t1).

    Args:
        text: conteúdo (uma ou duas linhas curtas funcionam melhor).
        start: segundo em que o título aparece.
        duration: quanto tempo fica na tela.
        font_size: tamanho em pixels relativo à resolução do projeto.
        position: inferior, topo, centro, inferior-esquerda, inferior-direita.
        color: branco, amarelo, preto ou #RRGGBB.
        background: caixa escura atrás do texto.
    """
    try:
        with _editing(project_id, "Adicionar título") as projeto:
            clip = add_text_clip(
                projeto, track_id="t1", text=text, start=start, duration=duration,
                font_size=font_size, color=color, position=position, background=background,
            )
        return _ok(projeto, f"Título {clip['id']} criado.", clip_id=clip["id"])
    except ProjectError as e:
        return _fail(str(e))


def add_timeline_subtitles(
    project_id: str = "",
    subtitle_path: str = "",
    start: float = 0,
    font_size: int = 22,
    position: str = "inferior",
    margin_v: int = 42,
) -> str:
    """
    Adiciona um arquivo .srt/.vtt/.ass como legenda queimada no vídeo final.

    Args:
        subtitle_path: caminho do arquivo de legendas.
        start: segundo da timeline em que a legenda começa.
        font_size: tamanho da fonte.
        position: inferior, centro ou topo.
        margin_v: margem vertical em pixels.
    """
    try:
        with _editing(project_id, "Adicionar legendas") as projeto:
            clip = add_subtitle_clip(
                projeto, track_id="s1", subtitle_path=subtitle_path, start=start,
                font_size=font_size, position=position, margin_v=margin_v,
            )
        return _ok(projeto, f"Legendas {clip['id']} adicionadas.", clip_id=clip["id"])
    except ProjectError as e:
        return _fail(str(e))


# ---------------------------------------------------------------------------
# Edição
# ---------------------------------------------------------------------------

def move_timeline_clip(project_id: str = "", clip_id: str = "", start: float = 0) -> str:
    """Move um clipe para outro segundo da timeline, sem alterar o conteúdo."""
    try:
        with _editing(project_id, "Mover clipe") as projeto:
            move_clip(projeto, clip_id, start)
        return _ok(projeto, f"Clipe {clip_id} movido para {format_timecode(start)}.", clip_id=clip_id)
    except ProjectError as e:
        return _fail(str(e))


def trim_timeline_clip(
    project_id: str = "",
    clip_id: str = "",
    in_point: Optional[float] = None,
    out_point: Optional[float] = None,
    duration: Optional[float] = None,
    ripple: bool = False,
) -> str:
    """
    Ajusta as bordas de um clipe.

    Em vídeo/áudio, in_point/out_point são segundos dentro do arquivo original.
    Em título/legenda, use duration. ripple aproxima os clipes seguintes.
    """
    try:
        with _editing(project_id, "Ajustar clipe") as projeto:
            trim_clip(
                projeto, clip_id, in_point=in_point, out_point=out_point,
                duration=duration, ripple=ripple,
            )
        return _ok(projeto, f"Clipe {clip_id} ajustado.", clip_id=clip_id)
    except ProjectError as e:
        return _fail(str(e))


def split_timeline_clip(project_id: str = "", clip_id: str = "", at: float = 0) -> str:
    """Divide um clipe no segundo indicado da timeline (não do arquivo)."""
    try:
        with _editing(project_id, "Dividir clipe") as projeto:
            primeiro, segundo = split_clip(projeto, clip_id, at)
        return _ok(
            projeto,
            f"Clipe dividido em {format_timecode(at)}: {primeiro['id']} e {segundo['id']}.",
            clip_ids=[primeiro["id"], segundo["id"]],
        )
    except ProjectError as e:
        return _fail(str(e))


def delete_timeline_clip(
    project_id: str = "",
    clip_id: str = "",
    ripple: bool = False,
    confirm: bool = False,
) -> str:
    """
    Remove um clipe. Exige confirm=True depois do aval explícito do usuário.

    Sem confirm, devolve requires_confirmation=True e não altera nada.
    ripple fecha o espaço deixado na faixa.
    """
    if not confirm:
        return json.dumps(
            {
                "ok": False,
                "requires_confirmation": True,
                "mensagem": "Exclusão não executada. Explique ao usuário qual clipe será removido "
                            "e só chame novamente com confirm=true após a autorização.",
                "clip_id": clip_id,
            },
            ensure_ascii=False,
        )
    try:
        with _editing(project_id, "Remover clipe") as projeto:
            delete_clip(projeto, clip_id, ripple=ripple)
        return _ok(projeto, f"Clipe {clip_id} removido.")
    except ProjectError as e:
        return _fail(str(e))


def duplicate_timeline_clip(project_id: str = "", clip_id: str = "", ripple: bool = True) -> str:
    """Duplica um clipe logo depois dele, empurrando os seguintes se preciso."""
    try:
        with _editing(project_id, "Duplicar clipe") as projeto:
            novo = duplicate_clip(projeto, clip_id, ripple=ripple)
        return _ok(projeto, f"Clipe duplicado como {novo['id']}.", clip_id=novo["id"])
    except ProjectError as e:
        return _fail(str(e))


def fine_timeline_edit(
    project_id: str = "",
    clip_id: str = "",
    operation: str = "slip",
    delta: float = 0,
) -> str:
    """
    Aplica slip, slide ou roll em um clipe ou fronteira.

    slip troca o trecho sem mover o clipe; slide move o clipe ajustando os
    vizinhos encostados; roll move a fronteira com o próximo clipe. delta em
    segundos; positivo avança, negativo recua.
    """
    if operation not in {"slip", "slide", "roll"}:
        return _fail("operation deve ser slip, slide ou roll")
    try:
        with _editing(project_id, f"{operation.title()} em clipe") as projeto:
            if operation == "slip":
                slip_clip(projeto, clip_id, delta)
            elif operation == "slide":
                slide_clip(projeto, clip_id, delta)
            else:
                roll_edit(projeto, clip_id, delta)
        return _ok(projeto, f"{operation} de {delta}s aplicado em {clip_id}.")
    except ProjectError as e:
        return _fail(str(e))


def set_timeline_clip(
    project_id: str = "",
    clip_id: str = "",
    volume: Optional[float] = None,
    speed: Optional[float] = None,
    fade_in: Optional[float] = None,
    fade_out: Optional[float] = None,
    transform_scale: Optional[float] = None,
    transform_x: Optional[float] = None,
    transform_y: Optional[float] = None,
    transform_rotation: Optional[float] = None,
    transform_opacity: Optional[float] = None,
    color_brightness: Optional[float] = None,
    color_contrast: Optional[float] = None,
    color_saturation: Optional[float] = None,
    color_gamma: Optional[float] = None,
    text: Optional[str] = None,
    font_size: Optional[int] = None,
    text_color: Optional[str] = None,
    position: Optional[str] = None,
    transition_type: Optional[str] = None,
    transition_duration: Optional[float] = None,
    subtitle_font_size: Optional[int] = None,
    subtitle_margin_v: Optional[int] = None,
    subtitle_color: Optional[str] = None,
    subtitle_position: Optional[str] = None,
) -> str:
    """
    Altera propriedades de um clipe de forma validada.

    volume 0–4; speed 0.1–8; fades em segundos; transform_scale 0.05–8;
    transform_x/y em pixels; rotation em graus; opacity 0–1; cor: brightness
    -1–1, contrast/saturation 0–4, gamma 0.1–10. Títulos aceitam text,
    font_size, text_color e position. Legendas aceitam subtitle_*.
    transition_type: none ou fade; transition_duration em segundos.
    """
    try:
        props = {
            chave: valor for chave, valor in {
                "volume": volume,
                "speed": speed,
                "fade_in": fade_in,
                "fade_out": fade_out,
                "transform_scale": transform_scale,
                "transform_x": transform_x,
                "transform_y": transform_y,
                "transform_rotation": transform_rotation,
                "transform_opacity": transform_opacity,
                "color_brightness": color_brightness,
                "color_contrast": color_contrast,
                "color_saturation": color_saturation,
                "color_gamma": color_gamma,
                "text": text,
                "font_size": font_size,
                "text_color": text_color,
                "position": position,
                "subtitle_font_size": subtitle_font_size,
                "subtitle_margin_v": subtitle_margin_v,
                "subtitle_color": subtitle_color,
                "subtitle_position": subtitle_position,
            }.items() if valor is not None
        }
        if transition_type is not None:
            props["transition"] = {
                "type": transition_type,
                "duration": transition_duration if transition_duration is not None else 0.5,
            }
        elif transition_duration is not None:
            props["transition"] = {"type": "fade", "duration": transition_duration}
        if not props:
            return _fail("Nenhuma propriedade informada")
        with _editing(project_id, "Alterar propriedades do clipe") as projeto:
            set_clip_properties(projeto, clip_id, **props)
        return _ok(projeto, f"Propriedades de {clip_id} atualizadas: {', '.join(props)}.")
    except ProjectError as e:
        return _fail(str(e))


def add_timeline_marker(project_id: str = "", time: float = 0, label: str = "") -> str:
    """Cria um marcador visível na régua da timeline."""
    try:
        with _editing(project_id, "Adicionar marcador") as projeto:
            marker = add_marker(projeto, time, label)
        return _ok(projeto, f"Marcador criado em {format_timecode(marker['time'])}.", marker_id=marker["id"])
    except ProjectError as e:
        return _fail(str(e))


# ---------------------------------------------------------------------------
# Análise de conteúdo
# ---------------------------------------------------------------------------

def analyze_timeline_clip(
    project_id: str = "",
    clip_id: str = "",
    kind: str = "scenes",
    threshold: float = 15,
    noise: float = -30,
    min_pause: float = 0.5,
    apply_candidates: bool = False,
) -> str:
    """
    Mede o conteúdo real de um clipe com FFmpeg e devolve candidatos em tempo de timeline.

    kind="scenes" acha trocas de cena (scdet, com score de 1 a 100; menor acha
    mais). kind="silence" acha pausas (silencedetect; noise em dB, min_pause em
    segundos). kind="loudness" mede LUFS integrado, LRA e true peak do clipe —
    use ANTES de mexer em volume, para diagnosticar em vez de chutar.

    A análise não corta nada. Sem apply_candidates, você só recebe os tempos. Com
    apply_candidates=True, cenas viram marcadores e pausas viram regiões na
    timeline, num único passo de undo, para revisão. Regiões e marcadores criados
    à mão não são tocados.
    """
    try:
        projeto = _project(project_id)
        analise = editor_analysis.analyze_clip(
            projeto,
            clip_id,
            kind,
            threshold=threshold,
            noise=noise,
            min_pause=min_pause,
        )
    except ProjectError as e:
        return _fail(str(e))

    dados: dict = {
        "ok": True,
        "kind": analise["kind"],
        "grupo": analise["group"],
        "clip_id": analise["clip_id"],
        "janela": analise["window"],
        "mensagem": analise["summary"],
        "candidatos": analise["candidates"][:40],
        "total_candidatos": len(analise["candidates"]),
    }
    if analise["kind"] == "loudness":
        dados["medicoes"] = analise["measurements"]
        dados["candidatos"] = []

    if apply_candidates:
        anotacao = editor_analysis.build_annotations(analise)
        if not (anotacao["markers"] or anotacao["regions"]):
            dados["anotacao"] = None
            dados["aviso"] = (
                "Nada para gravar: loudness é só medida, e as outras análises não "
                "trouxeram candidato."
            )
        else:
            try:
                with _editing(project_id, f"Anotar {anotacao['group']}") as vivo:
                    resultado = annotate(
                        vivo,
                        group=anotacao["group"],
                        markers=anotacao["markers"],
                        regions=anotacao["regions"],
                    )
                dados["anotacao"] = resultado
            except ProjectError as e:
                return _fail(str(e))
    return json.dumps(dados, ensure_ascii=False)


def clear_timeline_annotations(project_id: str = "", group: str = "") -> str:
    """
    Remove os candidatos que uma análise gravou (group "cenas" ou "pausas").

    Use antes de reanalisar com parâmetros diferentes ou quando o editor decidiu
    que a sugestão não serve. Marcadores e regiões criados à mão ficam na timeline.
    """
    try:
        with _editing(project_id, "Limpar anotações") as vivo:
            removido = clear_annotations(vivo, group)
        return _ok(vivo, f"Removidos {removido['markers']} marcadores e {removido['regions']} regiões de '{group}'.",
                   removido=removido)
    except ProjectError as e:
        return _fail(str(e))


# ---------------------------------------------------------------------------
# Validação e render
# ---------------------------------------------------------------------------

def validate_timeline(project_id: str = "") -> str:
    """Verifica integridade antes do render: mídia, sobreposição, tempos e áudio."""
    try:
        projeto = _project(project_id)
        issues = validate_project(projeto)
        return json.dumps(
            {
                "ok": not has_errors(issues),
                "issues": issues,
                "project_id": projeto["id"],
                "resumo": project_summary(projeto),
            },
            ensure_ascii=False,
        )
    except ProjectError as e:
        return _fail(str(e))


def render_timeline(
    project_id: str = "",
    preview: bool = True,
    filename: str = "",
    crf: int = 0,
    format: str = "mp4",
) -> str:
    """
    Inicia a renderização em segundo plano e devolve job_id.

    preview=True gera uma prévia leve (360p). Para exportar, use preview=False.
    Acompanhe com check_render_job(job_id); o arquivo só fica pronto quando o
    status for 'done'. Nunca sobrescreve um arquivo existente.
    """
    try:
        projeto = _project(project_id)
        options = {"preview": preview, "format": format}
        if filename:
            options["filename"] = filename
        if crf:
            options["crf"] = crf
        job = MANAGER.submit(projeto["id"], options)
        return json.dumps(
            {
                "ok": True,
                "job_id": job["id"],
                "status": job["status"],
                "output_name": job["output_name"],
                "mensagem": "Renderização iniciada em segundo plano. "
                            "Use check_render_job para acompanhar.",
            },
            ensure_ascii=False,
        )
    except (ProjectError, RenderError) as e:
        return _fail(str(e))


def check_render_job(job_id: str = "") -> str:
    """Consulta status, progresso, QC e caminho de uma renderização."""
    try:
        job = MANAGER.get(job_id)
        qc = job.get("qc") or {}
        return json.dumps(
            {
                "ok": job["status"] == "done" and bool(qc.get("ok")),
                "job_id": job["id"],
                "status": job["status"],
                "progress": job["progress"],
                "mensagem": job["message"],
                "arquivo": job.get("output_name"),
                "erro": job.get("error"),
                "qc": {
                    "ok": qc.get("ok"),
                    "issues": (qc.get("issues") or [])[:12],
                    "measurements": qc.get("measurements") or {},
                } if qc else None,
            },
            ensure_ascii=False,
        )
    except RenderError as e:
        return _fail(str(e))


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------

def list_editor_skills() -> str:
    """Lista as skills profissionais disponíveis para carregar sob demanda."""
    skills = editor_skills.list_skills()
    return json.dumps(
        {
            "skills": [
                {
                    "name": item["name"],
                    "title": item["title"],
                    "description": item["description"],
                    "complete": item["complete"],
                }
                for item in skills
            ]
        },
        ensure_ascii=False,
    )


def load_editor_skill(name: str) -> str:
    """
    Carrega o conteúdo completo de uma skill (procedimento e critérios).

    Use antes de tarefas de corte, podcast, shorts, cor, áudio, legendas,
    diagnóstico etc. Carregue apenas as skills relevantes ao pedido.
    """
    try:
        return json.dumps(editor_skills.load_skill(name), ensure_ascii=False)
    except ProjectError as e:
        return _fail(str(e))


# ---------------------------------------------------------------------------
# Agente
# ---------------------------------------------------------------------------

TOOLS = [
    create_edit_project,
    inspect_edit_project,
    configure_edit_project,
    add_timeline_clip,
    add_timeline_text,
    add_timeline_subtitles,
    move_timeline_clip,
    trim_timeline_clip,
    split_timeline_clip,
    delete_timeline_clip,
    duplicate_timeline_clip,
    fine_timeline_edit,
    set_timeline_clip,
    add_timeline_marker,
    analyze_timeline_clip,
    clear_timeline_annotations,
    validate_timeline,
    render_timeline,
    check_render_job,
    list_editor_skills,
    load_editor_skill,
]


def _system_prompt() -> str:
    catalogo = editor_skills.catalog_text()
    return f"""Você é o editor de vídeo profissional do ClipMind, com ferramentas reais que editam um projeto de timeline e renderizam com FFmpeg.

Fluxo obrigatório:
1. Antes de editar, chame inspect_edit_project uma vez para ver faixas, ids e tempos reais.
2. Se o pedido depender do conteúdo (pausas, cortes de cena, volume alto ou baixo),
   meça antes de propor qualquer corte: analyze_timeline_clip com kind="silence",
   "scenes" ou "loudness". Os números vêm da medição; nunca estime de cabeça.
   A medição não altera o projeto. Só grave candidatos (apply_candidates=true)
   depois de dizer o que encontrou, e avise que candidato não é corte.
3. Carregue uma skill com load_editor_skill quando o pedido envolver método (corte, ritmo,
   áudio, legendas, shorts, cor, exportação, diagnóstico). Para operação pontual simples,
   edite direto sem carregar skill.
4. Trabalhe em operações pequenas e confirme cada resultado pela resposta da ferramenta.
5. Use validate_timeline depois de mudanças estruturais (cortes, moves, splits, exclusões).
6. Antes de entregar uma edição concluída, renderize uma prévia com render_timeline(preview=true)
   e acompanhe com check_render_job. Não repita a prévia a cada ajuste pequeno.
7. Só exporte (preview=false) quando a prévia e o QC estiverem corretos.
8. Exclusões exigem aval explícito do usuário; chame delete_timeline_clip com confirm=true apenas depois disso.

Regras:
- Nunca invente clipes, ids, caminhos ou números. Use o resultado das ferramentas.
- Não diga que uma edição foi feita antes de a ferramenta confirmar.
- O render roda em segundo plano; nunca afirme que terminou sem consultar check_render_job.
- Não existe preview em tempo real da composição: a prévia é um render leve.
- Não prometa keyframes, rastreamento de rosto, transcrição ou multicam: ainda não estão implementados neste motor.
- Preserve o material original; todas as edições são não destrutivas.
- Responda em português brasileiro, curto e direto, citando ids e tempos relevantes.

Skills disponíveis (carregue só as relevantes):
{catalogo}
"""


_chats: dict[str, Chat] = {}

logger = logging.getLogger("clipmind.timeline_agent")

# Um turno completo pode ter várias rodadas de LLM em GPU local; o padrão é
# generoso e pode ser reduzido com CLIPMIND_TURN_TIMEOUT.
TURN_TIMEOUT = float(os.getenv("CLIPMIND_TURN_TIMEOUT", "900"))


def reset_chat(project_id: str = "") -> None:
    """Descarta o histórico do projeto para começar uma conversa nova."""
    if project_id:
        _chats.pop(project_id, None)
    else:
        _chats.clear()


async def run_timeline_turn(
    project_id: str,
    user_text: str,
    on_event,
) -> str:
    """Executa um turno do agente de timeline com tool calling real."""
    chat = _chats.get(project_id)
    if chat is None:
        chat = Chat(_system_prompt())
        _chats[project_id] = chat

    projeto = STORE.get(project_id)
    contexto = (
        f"(Projeto ativo: {projeto['id']} — {projeto['name']}; "
        f"{projeto['settings']['width']}x{projeto['settings']['height']} @ "
        f"{projeto['settings']['fps']} fps. project_id vazio usa este projeto.)\n\n"
    )
    chat.add_user_message(contexto + user_text)

    try:
        pendentes: list[asyncio.Future] = []
        resposta_final = ""
        inicio = time.monotonic()

        async def capturar(event: dict) -> None:
            nonlocal resposta_final
            if event.get("kind") == "text":
                resposta_final = event["text"]
            await on_event(event)

        try:
            async with AsyncClient(**_client_kwargs()) as client:
                llm = await _resolve_llm(client, capturar, pendentes)
                await asyncio.wait_for(
                    llm.act(
                        chat,
                        TOOLS,
                        on_message=lambda message: _forward(message, capturar, pendentes),
                    ),
                    timeout=TURN_TIMEOUT,
                )
                if pendentes:
                    await asyncio.gather(*pendentes)
        except asyncio.TimeoutError:
            if resposta_final:
                chat.add_assistant_response(resposta_final)
            raise TimelineAgentError(
                f"O turno foi interrompido após {TURN_TIMEOUT:.0f}s sem concluir. "
                "A IA pode ter parado de responder; tente de novo com um pedido menor."
            ) from None
        if not resposta_final:
            resposta_final = "A IA terminou sem texto de resposta."
        duracao = time.monotonic() - inicio
        logger.info("turno de %s concluído em %.1fs", project_id, duracao)
        await on_event({"kind": "answer", "text": resposta_final, "duration": round(duracao, 1)})
        return resposta_final
    except Exception as e:
        if _is_masked_auth_failure(e):
            from agent import AUTH_HINT
            raise TimelineAgentError(AUTH_HINT) from e
        texto = str(e).lower()
        sem_conexao = (
            isinstance(e, (ConnectionError, OSError, lms.LMStudioTimeoutError,
                           lms.LMStudioClientError, lms.LMStudioWebsocketError))
            or "not reachable" in texto
            or "is lm studio running" in texto
        )
        if sem_conexao:
            raise TimelineAgentError(
                "LM Studio não acessível. Abra o LM Studio e inicie o servidor "
                "(aba Developer). Detalhe: " + str(e)[:200]
            ) from e
        raise TimelineAgentError(str(e)) from e
