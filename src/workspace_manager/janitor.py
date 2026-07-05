"""Feature 1 — Janitor: flag large + stale files/folders that *could* be deleted.

Selection is deliberately **deterministic** (size + staleness), not LLM-driven:
this agent flags candidates for *review*, and a predictable, auditable rule is
safer than a model deciding what looks disposable. The LLM contributes a written
summary at the top of the report (see :mod:`reporter` for full analysis). This
agent NEVER deletes — it only moves flagged items into a review folder, and
records a manifest so every move is reversible 1:1.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from .common import (categorize, human, iter_files, last_touched, notify,
                     safe_move, write_manifest)
from .config import Config


def scan(cfg: Config) -> list[dict]:
    now = time.time()
    stale_cutoff = now - cfg.stale_days * 86400
    candidates: list[dict] = []

    home = Path.home()
    for root in cfg.scan_roots:
        # Only prune the system/app top-level dirs when scanning HOME itself;
        # a narrower configured root was chosen deliberately, so honor it.
        prune = cfg.prune_top_level if root.resolve() == home else None
        for fpath in iter_files(root, cfg.protected_dir_names, prune):
            try:
                st = fpath.stat()
            except OSError:
                continue
            if st.st_size < cfg.min_size_bytes:
                continue
            touched = last_touched(fpath, st)
            if touched > stale_cutoff:
                continue  # still active
            candidates.append({
                "path": str(fpath),
                "size_bytes": st.st_size,
                "size_h": human(st.st_size),
                "last_touched": datetime.fromtimestamp(
                    touched, timezone.utc).strftime("%Y-%m-%d"),
                "days_stale": int((now - touched) / 86400),
                "category": categorize(fpath),
            })

    candidates.sort(key=lambda c: c["size_bytes"], reverse=True)
    return candidates


def write_report(cfg: Config, candidates: list[dict], dest: Path,
                 applied: bool) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    home = str(Path.home())
    total = sum(c["size_bytes"] for c in candidates)
    lines = [
        f"# Janitor report — {datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"- Mode: **{'APPLIED (files moved)' if applied else 'DRY RUN (nothing moved)'}**",
        f"- Candidates: **{len(candidates)}**",
        f"- Reclaimable if reviewed & removed: **{human(total)}**",
        f"- Filters: size >= {human(cfg.min_size_bytes)}, "
        f"not touched in >= {cfg.stale_days} days",
        "",
        "| Size | Category | Stale (days) | Last touched | Path |",
        "|------|----------|--------------|--------------|------|",
    ]
    for c in candidates:
        p = c["path"].replace(home, "~")
        lines.append(
            f"| {c['size_h']} | {c['category']} | {c['days_stale']} | "
            f"{c['last_touched']} | {p} |")
    (dest / "REPORT.md").write_text("\n".join(lines) + "\n")
    (dest / "candidates.json").write_text(json.dumps(candidates, indent=2))


def apply_moves(cfg: Config, candidates: list[dict], dest: Path) -> None:
    home = Path.home()
    moves = []
    for c in candidates:
        src = Path(c["path"])
        if not src.exists():
            continue
        try:
            rel = src.relative_to(home)
        except ValueError:
            rel = Path(src.name)
        final = safe_move(src, dest / "files" / rel)
        moves.append({"original": str(src), "moved_to": str(final),
                      "size_bytes": c["size_bytes"]})
    write_manifest(dest, moves)


def run(cfg: Config, apply: bool = False) -> int:
    print(f"[janitor] scanning {', '.join(str(r) for r in cfg.scan_roots)} ...")
    candidates = scan(cfg)
    dest = cfg.review_root / datetime.now().strftime("%Y-%m-%d_%H%M")
    total = sum(c["size_bytes"] for c in candidates)

    write_report(cfg, candidates, dest, applied=apply)
    if apply:
        apply_moves(cfg, candidates, dest)
        print(f"[janitor] moved {len(candidates)} items -> {dest}")
        print(f"[janitor] restore anytime: {dest / 'RESTORE_ALL.sh'}")
        notify(title="Janitor moved files to review",
               subtitle=f"{len(candidates)} items · {human(total)}",
               message=str(dest), open_path=dest, enabled=cfg.notifications)
    else:
        print(f"[janitor] DRY RUN: {len(candidates)} candidates, "
              f"{human(total)} reclaimable (nothing moved).")
        print(f"[janitor] report: {dest / 'REPORT.md'}")
        notify(title="Janitor scan complete",
               subtitle=f"{len(candidates)} candidates · {human(total)} reclaimable",
               message="Review report ready (nothing moved)",
               open_path=dest, enabled=cfg.notifications)
    return 0
