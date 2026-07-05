"""Feature 2 — Download sorter: classify each new download and file it away.

Designed to be fired by a launchd ``WatchPaths`` watcher on ``~/Downloads``
(see ``agents/``), but also runnable by hand. Every eligible top-level item in
Downloads is classified by Claude and moved into ``_Sorted/<Folder>/``. Because
sorting *removes* the item from the top level, a re-run only ever sees genuinely
new arrivals — no state file needed. Every move is recorded in a manifest and is
reversible.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from . import llm
from .common import (categorize, first_page_text, human, is_bundle, notify,
                     safe_move, utc_now_stamp, write_manifest)
from .config import Config

# Files still being written by the browser — never touch these.
INCOMPLETE_SUFFIXES = {".crdownload", ".part", ".download", ".partial", ".tmp"}


def _created_ts(item: Path) -> float:
    """File creation time. macOS exposes st_birthtime; fall back to ctime."""
    st = item.stat()
    return getattr(st, "st_birthtime", st.st_ctime)


def _baseline(cfg: Config) -> float | None:
    f = cfg.sort_since_file
    if not f.exists():
        return None
    try:
        return float(f.read_text().strip())
    except ValueError:
        return None


def set_baseline(cfg: Config) -> int:
    """Record 'now' as the cutoff so only downloads created AFTER this moment
    are ever sorted. Used to ignore an existing backlog."""
    f = cfg.sort_since_file
    f.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    f.write_text(f"{now}\n")
    print(f"[sort] baseline set to {datetime.fromtimestamp(now):%Y-%m-%d %H:%M:%S}. "
          "Only downloads created after this will be sorted.")
    print(f"[sort] (existing files in {cfg.downloads_dir} are left untouched; "
          "sort them on demand with `workspace-manager sort --all-existing`.)")
    return 0


def _eligible(cfg: Config, item: Path) -> bool:
    if item.name.startswith("."):
        return False
    # Office lock/temp files (~$foo.docx) and editor backups — never sort these.
    if item.name.startswith("~$") or item.name.endswith("~"):
        return False
    if item.suffix.lower() in INCOMPLETE_SUFFIXES:
        return False
    # Skip the sorted destination itself and anything already inside it.
    if item.resolve() == cfg.sorted_root.resolve():
        return False
    return True


def _peek(cfg: Config, item: Path) -> str:
    # Only the first page / peek_max_chars of the file is ever read — the
    # token-cost guard. Bundles and unreadable binaries yield "".
    if is_bundle(item) or item.is_dir():
        return ""
    return first_page_text(item, cfg.peek_max_chars)


def run(cfg: Config, dry_run: bool = False, limit: int | None = None,
        all_existing: bool = False) -> int:
    downloads = cfg.downloads_dir
    if not downloads.exists():
        print(f"[sort] downloads dir not found: {downloads}")
        return 1

    # Top-level items only: files, plus macOS bundles treated as single units.
    items = [p for p in downloads.iterdir()
             if (p.is_file() or is_bundle(p)) and _eligible(cfg, p)]

    # Baseline: unless --all-existing, ignore anything created before the cutoff
    # so we only ever sort genuinely new downloads.
    baseline = None if all_existing else _baseline(cfg)
    if baseline is not None:
        items = [p for p in items if _created_ts(p) >= baseline]

    if not items:
        print("[sort] nothing new to sort.")
        return 0

    # Cost guard: never fire an unbounded number of LLM calls in one run.
    # `limit` (CLI --limit) overrides the config default; 0 means unlimited.
    cap = cfg.sort_batch_limit if limit is None else limit
    total_eligible = len(items)
    if cap and total_eligible > cap:
        items = items[:cap]
        print(f"[sort] {total_eligible} eligible items; processing {cap} this "
              f"run (batch limit). Re-run to continue, or use --limit 0 for all.")

    moves = []
    for item in items:
        size = item.stat().st_size if item.is_file() else _dir_size(item)
        coarse = categorize(item)
        try:
            verdict = llm.classify_download(
                cfg, item.name, human(size), coarse, _peek(cfg, item))
        except Exception as e:
            print(f"[sort] classify failed for {item.name}: {e} -> Miscellaneous")
            verdict = {"folder": "Miscellaneous", "category": coarse,
                       "reason": "fallback"}

        folder = _sanitize(verdict.get("folder") or "Miscellaneous")
        target = cfg.sorted_root / folder / item.name
        arrow = f"{item.name}  ->  _Sorted/{folder}/"
        if dry_run:
            print(f"[sort] (dry-run) {arrow}   ({verdict.get('reason','')})")
            continue
        final = safe_move(item, target)
        moves.append({"original": str(item), "moved_to": str(final),
                      "folder": folder, "category": verdict.get("category"),
                      "reason": verdict.get("reason")})
        print(f"[sort] {arrow}   ({verdict.get('reason','')})")

    if moves:
        dest = cfg.sort_manifests_dir / utc_now_stamp()
        write_manifest(dest, moves)
        print(f"[sort] sorted {len(moves)} item(s). "
              f"Undo: {dest / 'RESTORE_ALL.sh'}")
        _notify_moves(cfg, moves)
    return 0


def _notify_moves(cfg: Config, moves: list[dict]) -> None:
    """Small batch -> one banner per file showing its destination folder.
    Larger batch -> a single summary banner (avoid a notification storm)."""
    if len(moves) <= 5:
        for m in moves:
            notify(title="Sorted a download",
                   subtitle=f"→ {m['folder']}",
                   message=Path(m["moved_to"]).name,
                   open_path=Path(m["moved_to"]).parent,   # click -> that folder
                   enabled=cfg.notifications)
    else:
        folders = sorted({m["folder"] for m in moves})
        notify(title=f"Sorted {len(moves)} downloads",
               subtitle=f"into {len(folders)} folders",
               message=", ".join(folders),
               open_path=cfg.sorted_root,                  # click -> _Sorted
               enabled=cfg.notifications)


def _sanitize(name: str) -> str:
    return name.replace("/", "-").replace("\\", "-").strip() or "Miscellaneous"


def _dir_size(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total
