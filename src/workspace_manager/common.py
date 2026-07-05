"""Shared filesystem utilities used by all three features.

The important safety primitive here is :func:`iter_files`, which walks a tree
while (a) pruning dependency/build/VCS directories and (b) treating macOS
*bundles* (``.app``, ``.photoslibrary``, ``.rtfd`` …) as opaque single units.
Without bundle-opacity a walk descends into an app's guts and would happily
flag or move files from *inside* it — silently corrupting the bundle. Every
consumer of this module therefore sees a bundle as one path, never its parts.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

# macOS packages: directories the Finder presents as a single opaque item.
# The walk must not descend into these.
BUNDLE_SUFFIXES = {
    ".app", ".bundle", ".framework", ".plugin", ".kext", ".xpc",
    ".photoslibrary", ".tvlibrary", ".theater", ".imovielibrary",
    ".rtfd", ".pages", ".numbers", ".key", ".sketch", ".playground",
    ".xcodeproj", ".xcworkspace", ".appex", ".prefPane", ".qlgenerator",
}

INSTALLER_EXTS = {".dmg", ".pkg", ".iso", ".exe", ".msi", ".deb", ".rpm"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".heic",
              ".webp", ".psd", ".svg"}
ARCHIVE_EXTS = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar"}
VIDEO_EXTS = {".mov", ".mp4", ".avi", ".mkv", ".m4v", ".webm"}
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg"}
DOC_EXTS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
            ".txt", ".md", ".rtf", ".csv", ".epub"}
MODEL_EXTS = {".bin", ".safetensors", ".ckpt", ".pt", ".pth", ".gguf",
              ".onnx", ".h5"}
CODE_EXTS = {".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp",
             ".rb", ".sh", ".swift", ".kt"}


TEXT_PEEK_EXTS = {".txt", ".md", ".csv", ".json", ".log", ".html", ".xml",
                  ".rtf", ".tsv", ".yaml", ".yml", ".ini", ".py", ".js", ".ts"}


def first_page_text(path: Path, max_chars: int = 2000) -> str:
    """Return only the *first page* of a file's text, capped at ``max_chars``.

    This is the token-cost guard for classification: PDFs contribute page 1
    only, docx the opening paragraphs, plain text the leading characters. Binary
    or unsupported types return "" (the classifier then relies on the filename).
    Missing optional extractors (pypdf / python-docx) degrade to "" too — the
    tool never hard-fails on a file it can't read.
    """
    ext = path.suffix.lower()
    try:
        if ext == ".pdf":
            return _pdf_first_page(path, max_chars)
        if ext == ".docx":
            return _docx_first_page(path, max_chars)
        if ext in TEXT_PEEK_EXTS:
            return path.read_text(errors="replace")[:max_chars]
    except Exception:
        return ""
    return ""


def _pdf_first_page(path: Path, max_chars: int) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    reader = PdfReader(str(path))
    if not reader.pages:
        return ""
    return (reader.pages[0].extract_text() or "")[:max_chars]


def _docx_first_page(path: Path, max_chars: int) -> str:
    try:
        import docx  # python-docx
    except ImportError:
        return ""
    doc = docx.Document(str(path))
    parts: list[str] = []
    total = 0
    for para in doc.paragraphs:
        parts.append(para.text)
        total += len(para.text)
        if total >= max_chars:
            break
    return "\n".join(parts)[:max_chars]


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


def categorize(path: Path) -> str:
    """Coarse, deterministic category by extension. The LLM layer refines this;
    this is the free/offline fallback and the label used in reports."""
    ext = path.suffix.lower()
    if ext in INSTALLER_EXTS:
        return "installer"
    if ext in IMAGE_EXTS:
        return "image"
    if ext in ARCHIVE_EXTS:
        return "archive"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in DOC_EXTS:
        return "document"
    if ext in MODEL_EXTS:
        return "model/weights"
    if ext in CODE_EXTS:
        return "code"
    return "other"


def is_bundle(path: Path) -> bool:
    return path.suffix.lower() in BUNDLE_SUFFIXES


def spotlight_last_used(path: Path) -> float | None:
    """``kMDItemLastUsedDate`` = when the user last *opened* the file. This is
    a far better staleness signal than mtime, and is macOS-specific."""
    try:
        out = subprocess.run(
            ["mdls", "-raw", "-name", "kMDItemLastUsedDate", str(path)],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        if not out or out == "(null)":
            return None
        return datetime.strptime(out, "%Y-%m-%d %H:%M:%S %z").timestamp()
    except Exception:
        return None


def last_touched(path: Path, st: os.stat_result) -> float:
    """Most recent of Spotlight-last-opened, atime, and mtime. Conservative:
    if *any* signal is recent, the item counts as active (not stale)."""
    candidates = [st.st_atime, st.st_mtime]
    lu = spotlight_last_used(path)
    if lu is not None:
        candidates.append(lu)
    return max(candidates)


def iter_files(
    root: Path,
    protected_dir_names: set[str],
    prune_top_level: set[str] | None = None,
) -> Iterator[Path]:
    """Yield files under ``root``, pruning protected dirs and treating macOS
    bundles as opaque (a bundle is yielded as one path; its contents are not).

    ``prune_top_level`` only applies to the immediate children of ``root``.
    """
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        here = Path(dirpath)

        # Bundle-opacity: if any dir child is a bundle, yield it as a single
        # item and prune it from further descent.
        bundle_children = [d for d in dirnames if is_bundle(here / d)]
        for d in bundle_children:
            yield here / d
        dirnames[:] = [d for d in dirnames if d not in bundle_children]

        if here == root and prune_top_level is not None:
            dirnames[:] = [d for d in dirnames
                           if d not in prune_top_level
                           and d not in protected_dir_names
                           and not d.startswith(".")]
        else:
            dirnames[:] = [d for d in dirnames if d not in protected_dir_names]

        for name in filenames:
            fpath = here / name
            if fpath.is_symlink():
                continue
            yield fpath


def write_manifest(dest: Path, moves: list[dict]) -> None:
    """Record every move as new->original and drop a 1:1 reversal script.
    NOTHING is ever deleted; a manifest makes every action undoable."""
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "MANIFEST.json").write_text(json.dumps(moves, indent=2))
    (dest / "RESTORE_ALL.sh").write_text(
        "#!/bin/bash\n# Move everything back to where it came from.\n"
        "set -e\ncd \"$(dirname \"$0\")\"\n"
        "python3 -c \"import json,shutil,os;[ ("
        "os.makedirs(os.path.dirname(m['original']),exist_ok=True), "
        "shutil.move(m['moved_to'],m['original'])) "
        "for m in json.load(open('MANIFEST.json')) "
        "if os.path.exists(m['moved_to']) ]\"\n"
        "echo 'Restored all files to their original locations.'\n")
    os.chmod(dest / "RESTORE_ALL.sh", 0o755)


def safe_move(src: Path, target: Path) -> Path:
    """Move ``src`` to ``target``, avoiding collisions by suffixing ``-1`` etc.
    Never overwrites an existing file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    final = target
    i = 1
    while final.exists():
        final = target.with_name(f"{target.stem}-{i}{target.suffix}")
        i += 1
    shutil.move(str(src), str(final))
    return final


def utc_now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
