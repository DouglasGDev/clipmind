"""
Fixtures compartilhadas dos testes do ClipMind.

Isola o diretório de projetos antes de qualquer import do motor: PROJECTS_DIR é
lido no import de editor_project, então a variável de ambiente precisa ser
definida aqui, no primeiro módulo carregado pelo pytest.
"""

import os
import tempfile
from pathlib import Path

_TMP_ROOT = Path(tempfile.mkdtemp(prefix="clipmind-tests-"))
os.environ["CLIPMIND_PROJECTS"] = str(_TMP_ROOT / "projects")

import pytest  # noqa: E402

import editor_render  # noqa: E402
from editor_project import ProjectStore  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
MEDIA = RAIZ / "test_videos"


def _tem_media() -> bool:
    return all((MEDIA / nome).is_file() for nome in ("timeline_teste.mp4", "clipe_a.mp4", "legenda.srt"))


requires_media = pytest.mark.skipif(not _tem_media(), reason="mídia de teste ausente em ./test_videos")


@pytest.fixture
def store(tmp_path) -> ProjectStore:
    return ProjectStore(root=tmp_path / "projects")


@pytest.fixture
def render_dir(tmp_path, monkeypatch) -> Path:
    destino = tmp_path / "output"
    destino.mkdir()
    monkeypatch.setattr(editor_render, "OUTPUT_DIR", destino)
    return destino


@pytest.fixture
def projeto_media(store):
    """Projeto com um clipe de 6 s de timeline_teste.mp4 na faixa v1."""
    projeto = store.create("Teste Render", 1920, 1080, 30)
    with store.edit(projeto["id"], "adicionar clipe") as vivo:
        from editor_project import add_clip
        add_clip(vivo, track_id="v1", source=str(MEDIA / "timeline_teste.mp4"))
    return store.get(projeto["id"])
