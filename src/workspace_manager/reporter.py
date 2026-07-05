"""Feature 3 — Reporter: document the file-system's state + improvement ideas.

Facts are gathered deterministically; Claude turns them into a readable report
with prioritized, actionable opportunities. The report is delivered through a
pluggable **sink** so the destination can grow without touching this logic. A
local markdown file is the default sink today; an Apple Notes or Gmail sink can
be dropped in by implementing :class:`Sink`.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Protocol

from . import janitor, llm
from .common import human, is_bundle, notify
from .config import Config


class Sink(Protocol):
    """A destination for a finished report. Implement one method."""

    def deliver(self, title: str, body_markdown: str, cfg: Config) -> str:
        """Persist/send the report; return a human-readable location string."""
        ...


class MarkdownFileSink:
    """Default sink: write a dated ``.md`` into ``<workspace>/reports/``."""

    def deliver(self, title: str, body_markdown: str, cfg: Config) -> str:
        cfg.reports_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        path = cfg.reports_dir / f"report_{stamp}.md"
        path.write_text(f"# {title}\n\n{body_markdown}\n")
        return str(path)


def _gather_facts(cfg: Config) -> str:
    """Collect deterministic facts and render them as a markdown block for the
    model. Reuses the janitor scan so we don't walk the tree twice."""
    candidates = janitor.scan(cfg)
    total_stale = sum(c["size_bytes"] for c in candidates)
    by_cat = Counter()
    size_by_cat: Counter = Counter()
    for c in candidates:
        by_cat[c["category"]] += 1
        size_by_cat[c["category"]] += c["size_bytes"]

    # Downloads clutter (top-level, unsorted).
    dl_items = []
    if cfg.downloads_dir.exists():
        for p in cfg.downloads_dir.iterdir():
            if p.name.startswith(".") or p.resolve() == cfg.sorted_root.resolve():
                continue
            if p.is_file() or is_bundle(p):
                try:
                    sz = p.stat().st_size if p.is_file() else 0
                except OSError:
                    sz = 0
                dl_items.append((p.name, sz))
    dl_total = sum(s for _, s in dl_items)

    lines = [
        f"Scan roots: {', '.join(str(r) for r in cfg.scan_roots)}",
        f"Thresholds: size >= {human(cfg.min_size_bytes)}, "
        f"stale >= {cfg.stale_days} days",
        "",
        "## Large + stale items (janitor candidates)",
        f"- Count: {len(candidates)}",
        f"- Total reclaimable: {human(total_stale)}",
        "- By category:",
    ]
    for cat, n in by_cat.most_common():
        lines.append(f"    - {cat}: {n} items, {human(size_by_cat[cat])}")

    lines += ["", "## Top 10 largest stale items"]
    for c in candidates[:10]:
        p = c["path"].replace(str(Path.home()), "~")
        lines.append(f"- {c['size_h']}  ({c['days_stale']}d stale)  {p}")

    lines += [
        "",
        "## Downloads clutter (top-level, unsorted)",
        f"- Items: {len(dl_items)}",
        f"- Total size: {human(dl_total)}",
    ]
    for name, sz in sorted(dl_items, key=lambda x: x[1], reverse=True)[:10]:
        lines.append(f"- {human(sz)}  {name}")

    return "\n".join(lines)


def run(cfg: Config, sink: Sink | None = None) -> int:
    sink = sink or MarkdownFileSink()
    print("[report] gathering facts ...")
    facts = _gather_facts(cfg)
    print("[report] asking Claude to write the report ...")
    body = llm.author_report(cfg, facts)
    title = f"File System State Report — {datetime.now():%Y-%m-%d}"
    location = sink.deliver(title, body, cfg)
    print(f"[report] written: {location}")
    notify(title="File-system report ready",
           subtitle=Path(location).name,
           message=str(Path(location).parent),
           open_path=location, enabled=cfg.notifications)
    return 0
