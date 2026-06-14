"""Safe dependency acquisition primitives (design/15 §12).

Never executes dependency code. Provides hash verification and archive-safe
extraction with the design's guards: size and file-count limits, path-traversal
protection, and rejection of unsafe symlinks. Network download is layered on top
of these primitives and is intentionally not performed here.
"""

from __future__ import annotations

import hashlib
import io
import tarfile
import zipfile
from pathlib import Path

from beagle.service.errors import ValidationError

DEFAULT_MAX_BYTES = 200 * 1024 * 1024
DEFAULT_MAX_FILES = 50_000


def verify_hash(data: bytes, expected: str) -> bool:
    """Verify ``data`` against an ``algo:hexdigest`` or ``algo-base64`` integrity string."""
    algorithm, separator, digest = expected.partition(":")
    if separator:
        actual = hashlib.new(algorithm, data).hexdigest()
        return actual == digest.strip()
    # npm-style "sha512-<base64>"
    algorithm, separator, b64 = expected.partition("-")
    if separator:
        import base64

        actual = base64.b64encode(hashlib.new(algorithm, data).digest()).decode()
        return actual == b64.strip()
    raise ValidationError(f"unrecognized integrity string: {expected}")


def safe_extract_tar(
    data: bytes, dest: Path, max_bytes: int = DEFAULT_MAX_BYTES,
    max_files: int = DEFAULT_MAX_FILES,
) -> int:
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        members = list(archive.getmembers())
        _enforce_limits(members, dest, max_bytes, max_files, lambda m: m.size,
                        lambda m: m.name, lambda m: m.issym() or m.islnk())
        safe = [m for m in members if m.isfile() or m.isdir()]
        archive.extractall(dest, members=safe)
        return len([m for m in safe if m.isfile()])


def safe_extract_zip(
    data: bytes, dest: Path, max_bytes: int = DEFAULT_MAX_BYTES,
    max_files: int = DEFAULT_MAX_FILES,
) -> int:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        _enforce_limits(infos, dest, max_bytes, max_files, lambda i: i.file_size,
                        lambda i: i.filename, lambda i: _zip_is_symlink(i))
        archive.extractall(dest)
        return len([i for i in infos if not i.is_dir()])


def _enforce_limits(members, dest, max_bytes, max_files, size_of, name_of, is_link) -> None:
    if len(members) > max_files:
        raise ValidationError(f"archive exceeds file-count limit ({len(members)})")
    total = 0
    base = dest.resolve()
    for member in members:
        if is_link(member):
            raise ValidationError(f"archive contains an unsafe link: {name_of(member)}")
        total += size_of(member)
        if total > max_bytes:
            raise ValidationError("archive exceeds size limit")
        target = (dest / name_of(member)).resolve()
        if base != target and base not in target.parents:
            raise ValidationError(f"archive path escapes destination: {name_of(member)}")


def _zip_is_symlink(info: zipfile.ZipInfo) -> bool:
    # Unix mode is stored in the high 16 bits of external_attr; 0xA000 == symlink.
    return (info.external_attr >> 16) & 0xF000 == 0xA000
