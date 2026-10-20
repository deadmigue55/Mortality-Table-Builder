"""Shared download machinery.

Every source file goes through :func:`fetch`, which saves it unchanged under
``data/raw/<source>/`` and records where it came from in ``data/raw/MANIFEST.csv``
(source, file, URL, download time, size and SHA-256), so any result can be traced back
to its exact input.
"""

from __future__ import annotations

import csv
import hashlib
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import requests

from mortality.config import Paths, get_paths

MANIFEST_FIELDS = ["source", "file", "url", "downloaded_at", "bytes", "sha256"]
USER_AGENT = "mortality-table-builder/0.1 (research project; contact via GitHub deadmigue55)"
CHUNK = 1024 * 256
TIMEOUT = (15, 120)  # connect, read (seconds)


class NotAFileError(RuntimeError):
    """The server answered, but not with the file we asked for (e.g. an HTML 'not found' page)."""


@dataclass(frozen=True)
class Download:
    """Result of a fetch."""

    path: Path
    url: str
    sha256: str
    bytes: int
    skipped: bool  # True when the file already existed and was reused


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_name(name: str) -> str:
    """Make a string safe to use as a file or folder name."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    if not cleaned:
        raise ValueError(f"Cannot build a safe file name from {name!r}")
    return cleaned


def read_manifest(paths: Paths | None = None) -> list[dict[str, str]]:
    paths = paths or get_paths()
    if not paths.manifest.exists():
        return []
    with paths.manifest.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def record(
    source: str,
    file: Path,
    url: str,
    sha256: str,
    size: int,
    paths: Paths | None = None,
) -> None:
    """Add (or replace) this file's row in the manifest."""
    paths = paths or get_paths()
    rel = file.relative_to(paths.raw).as_posix()
    rows = [r for r in read_manifest(paths) if r["file"] != rel]
    rows.append(
        {
            "source": source,
            "file": rel,
            "url": url,
            "downloaded_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "bytes": str(size),
            "sha256": sha256,
        }
    )
    rows.sort(key=lambda r: (r["source"], r["file"]))
    paths.manifest.parent.mkdir(parents=True, exist_ok=True)
    with paths.manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def fetch(
    url: str,
    *,
    source: str,
    filename: str | None = None,
    force: bool = False,
    session: requests.Session | None = None,
    paths: Paths | None = None,
    validate: Callable[[Path], None] | None = None,
) -> Download:
    """Download ``url`` into ``data/raw/<source>/`` and log it in the manifest.

    An existing file is reused unless ``force`` is set. The file is written to a temporary
    name first, so an interrupted download never leaves a half-written file behind.
    ``validate`` may inspect the downloaded file and raise :class:`NotAFileError` to reject it.
    """
    paths = (paths or get_paths()).ensure()
    folder = paths.raw / safe_name(source)
    folder.mkdir(parents=True, exist_ok=True)
    name = safe_name(filename or url.rstrip("/").rsplit("/", 1)[-1] or "download")
    target = folder / name

    if target.exists() and not force:
        digest = sha256_file(target)
        size = target.stat().st_size
        known = {r["file"]: r for r in read_manifest(paths)}.get(
            target.relative_to(paths.raw).as_posix()
        )
        if known is None or known["sha256"] != digest:
            record(source, target, url, digest, size, paths)
        return Download(target, url, digest, size, skipped=True)

    http = session or requests.Session()
    partial = target.with_suffix(target.suffix + ".part")
    digest = hashlib.sha256()
    size = 0
    try:
        with http.get(
            url, stream=True, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}
        ) as resp:
            resp.raise_for_status()
            with partial.open("wb") as handle:
                for block in resp.iter_content(CHUNK):
                    handle.write(block)
                    digest.update(block)
                    size += len(block)
        # Some servers (INEGI) answer 200 with an HTML "page not found" for bad URLs
        if target.suffix.lower() == ".zip" and not zipfile.is_zipfile(partial):
            raise NotAFileError(f"{url} did not return a ZIP file (wrong or retired URL?)")
        if validate is not None:
            validate(partial)
        partial.replace(target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise

    record(source, target, url, digest.hexdigest(), size, paths)
    return Download(target, url, digest.hexdigest(), size, skipped=False)


def register_local(
    path: Path,
    *,
    source: str,
    url: str,
    paths: Paths | None = None,
) -> Download:
    """Log a file that was produced locally (e.g. extracted from a zip) in the manifest."""
    paths = paths or get_paths()
    digest = sha256_file(path)
    size = path.stat().st_size
    record(source, path, url, digest, size, paths)
    return Download(path, url, digest, size, skipped=False)
