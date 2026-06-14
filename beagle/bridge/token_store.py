"""Local JWT storage for the bridge (design/15 §3).

The token is never stored in the repository. Resolution order: the
``BEAGLE_TOKEN`` environment variable, then a user-local file with 0600
permissions, then the OS keyring if the optional ``keyring`` package is present.
"""

from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_PATH = Path.home() / ".config" / "beagle" / "token"


class TokenStore:
    """Reads and writes the developer's service token."""

    def __init__(self, path: Path | None = None, keyring_name: str = "beagle"):
        self._path = path or _DEFAULT_PATH
        self._keyring_name = keyring_name

    def get(self) -> str | None:
        from_env = os.environ.get("BEAGLE_TOKEN")
        if from_env:
            return from_env.strip()
        if self._path.exists():
            return self._path.read_text(encoding="utf-8").strip() or None
        return self._from_keyring()

    def set(self, token: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(token, encoding="utf-8")
        self._path.chmod(0o600)

    def _from_keyring(self) -> str | None:
        try:
            import keyring  # optional dependency
        except ImportError:
            return None
        return keyring.get_password(self._keyring_name, "token")
