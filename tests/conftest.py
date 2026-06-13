from __future__ import annotations

from pathlib import Path

import pytest

from beagle.workspace import Workspace


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "site.py").write_text(
        "class Site:\n"
        "    def deploy(self):\n"
        "        return run_deployment()\n"
        "\n"
        "def run_deployment():\n"
        "    return True\n"
    )
    (tmp_path / ".gitignore").write_text("ignored/\n")
    (tmp_path / "ignored").mkdir()
    (tmp_path / "ignored" / "skip.py").write_text("x = 1\n")
    return tmp_path


@pytest.fixture
def workspace(repo: Path) -> Workspace:
    ws = Workspace(repo)
    yield ws
    ws.close()
