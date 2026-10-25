"""
Carregador de skills do editor profissional.

Cada skill é uma pasta em ./skills com um SKILL.md contendo frontmatter e as
dez seções obrigatórias. O catálogo entra no prompt do agente; o conteúdo
completo só é carregado quando a IA pede, economizando contexto.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from editor_project import ProjectError

SKILLS_DIR = Path("./skills")
MAX_SKILL_CHARS = 16000
_LIMITE = 14000
_REQUIRED = [f"## {i}." for i in range(1, 11)]
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")


def _split_frontmatter(texto: str) -> tuple[dict, str]:
    if not texto.startswith("---"):
        return {}, texto
    partes = texto.split("---", 2)
    if len(partes) < 3:
        return {}, texto
    meta: dict[str, str] = {}
    for linha in partes[1].splitlines():
        if ":" not in linha:
            continue
        chave, valor = linha.split(":", 1)
        meta[chave.strip()] = valor.strip().strip('"').strip("'")
    return meta, partes[2].lstrip("\n")


def _skill_file(name: str) -> Path:
    if not _NAME_RE.match(str(name or "")):
        raise ProjectError(f"Nome de skill inválido: {name}")
    arquivo = SKILLS_DIR / name / "SKILL.md"
    if not arquivo.is_file():
        raise ProjectError(f"Skill não encontrada: {name}")
    return arquivo


def list_skills() -> list[dict]:
    """Lista as skills instaladas com metadados e seções obrigatórias."""
    if not SKILLS_DIR.is_dir():
        return []
    itens = []
    for pasta in sorted(SKILLS_DIR.iterdir(), key=lambda p: p.name):
        arquivo = pasta / "SKILL.md"
        if not pasta.is_dir() or not arquivo.is_file():
            continue
        try:
            texto = arquivo.read_text(encoding="utf-8")
        except OSError:
            continue
        meta, corpo = _split_frontmatter(texto)
        nome = meta.get("name") or pasta.name
        if not _NAME_RE.match(nome):
            continue
        faltando = [secao for secao in _REQUIRED if secao not in corpo]
        itens.append({
            "name": nome,
            "title": meta.get("title") or nome.replace("-", " ").title(),
            "description": meta.get("description") or "",
            "triggers": [t.strip() for t in meta.get("triggers", "").split(",") if t.strip()],
            "tools": [t.strip() for t in meta.get("tools", "").split(",") if t.strip()],
            "complete": not faltando,
            "missing_sections": faltando,
            "path": str(arquivo),
        })
    return itens


def load_skill(name: str) -> dict:
    """Carrega o conteúdo completo de uma skill para o contexto do agente."""
    arquivo = _skill_file(name)
    try:
        texto = arquivo.read_text(encoding="utf-8")
    except OSError as e:
        raise ProjectError(f"Falha ao ler a skill {name}: {e}") from None
    meta, corpo = _split_frontmatter(texto)
    cabecalho = texto[: len(texto) - len(corpo)]
    truncada = len(corpo) > _LIMITE
    if truncada:
        corpo = corpo[:_LIMITE].rstrip() + "\n\n[skill truncada por limite de contexto]"
    faltando = [secao for secao in _REQUIRED if secao not in texto]
    return {
        "name": meta.get("name") or name,
        "title": meta.get("title") or name,
        "content": cabecalho + corpo,
        "truncated": truncada,
        "sections": len(_REQUIRED) - len(faltando),
        "complete": not faltando,
        "missing_sections": faltando,
    }


def catalog_text(max_description: int = 140) -> str:
    """Catálogo compacto para o prompt de sistema."""
    linhas = []
    for item in list_skills():
        descricao = item["description"]
        if len(descricao) > max_description:
            descricao = descricao[: max_description - 1] + "…"
        linhas.append(f"- {item['name']}: {descricao}")
    return "\n".join(linhas)


def choose_skills(text: str, limit: int = 4) -> list[str]:
    """Sugere skills por palavra-chave; a IA continua livre para escolher."""
    texto = (text or "").lower()
    pontuacao: list[tuple[int, str]] = []
    for item in list_skills():
        pontos = 0
        if item["name"] in texto or item["title"].lower() in texto:
            pontos += 5
        for gatilho in item["triggers"]:
            if gatilho.lower() in texto:
                pontos += 1
        if pontos:
            pontuacao.append((pontos, item["name"]))
    pontuacao.sort(reverse=True)
    return [nome for _, nome in pontuacao[:limit]]
