"""Claude integration — shared by all three agents.

Every feature in this toolkit is LLM-driven, so a working ``ANTHROPIC_API_KEY``
is required. The key is read from the environment or from a ``.env`` file at the
repo root (never committed). Model + effort come from :mod:`config`.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from .config import REPO_ROOT, Config


def _load_dotenv() -> None:
    """Minimal .env loader (no dependency). Only sets keys not already set."""
    env = REPO_ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


@lru_cache(maxsize=1)
def _client():
    _load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit(
            "ANTHROPIC_API_KEY is not set. This toolkit is LLM-driven — add the "
            "key to your environment or to a .env file at the repo root.\n"
            "  echo 'ANTHROPIC_API_KEY=sk-ant-...' >> "
            f"{REPO_ROOT / '.env'}")
    try:
        import anthropic
    except ImportError as e:  # pragma: no cover
        raise SystemExit(
            "The 'anthropic' package is not installed. Run: pip install -e .") from e
    return anthropic.Anthropic()


def _classify_schema(folder_names: list[str]) -> dict:
    """Schema whose ``folder`` is an ENUM of the allowed folders — the model is
    structurally forced to pick one configured bucket, so folders never
    fragment and 'Miscellaneous' is always a valid landing spot."""
    return {
        "type": "object",
        "properties": {
            "folder": {
                "type": "string",
                "enum": folder_names,
                "description": "Destination folder — must be one of the allowed "
                               "values.",
            },
            "category": {
                "type": "string",
                "description": "One-word content category, e.g. document, image, "
                               "installer, archive, code, media, data.",
            },
            "reason": {
                "type": "string",
                "description": "Brief (<=12 words) justification for the choice.",
            },
        },
        "required": ["folder", "category", "reason"],
        "additionalProperties": False,
    }


def classify_download(cfg: Config, filename: str, size_h: str,
                      coarse_category: str, peek: str = "") -> dict:
    """Ask Claude which *fixed* folder a downloaded file belongs in. The folder
    set comes from ``cfg.folders``; the schema enum guarantees the answer is one
    of them ('Miscellaneous' is the guaranteed fallback)."""
    client = _client()

    names = [f["name"] for f in cfg.folders]
    if "Miscellaneous" not in names:
        names.append("Miscellaneous")
    taxonomy = "\n".join(f"  - {f['name']}: {f['description']}"
                         for f in cfg.folders)

    # Only the first page / peek_max_chars is ever included — bounds token spend.
    peek_block = (f"\n\nFirst page preview (truncated):\n{peek}" if peek
                  else "\n\n(No text preview available — classify from the "
                       "filename and type.)")
    prompt = (
        "You are the classifier for an automatic Downloads organizer on macOS. "
        "Choose exactly ONE destination folder for this file from the fixed list "
        "below. If it does not clearly fit any folder, choose 'Miscellaneous'.\n\n"
        f"Allowed folders:\n{taxonomy}\n"
        "  - Miscellaneous: fallback for anything unclear or unidentifiable\n\n"
        f"Filename: {filename}\n"
        f"Size: {size_h}\n"
        f"Extension-based guess: {coarse_category}"
        f"{peek_block}"
    )
    resp = client.messages.create(
        model=cfg.sort_model or cfg.model,
        max_tokens=512,
        output_config={
            "format": {"type": "json_schema", "schema": _classify_schema(names)},
        },
        messages=[{"role": "user", "content": prompt}],
    )
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


def author_report(cfg: Config, facts_markdown: str) -> str:
    """Ask Claude to turn a block of filesystem facts into a readable report
    with concrete improvement opportunities. Returns markdown body text."""
    client = _client()
    prompt = (
        "You are a meticulous systems analyst writing a report on the state of a "
        "user's macOS file system. Below are collected facts (sizes, stale files, "
        "download clutter, largest directories). Write a clear, well-structured "
        "markdown report with these sections:\n"
        "  1. Executive summary (3-4 sentences)\n"
        "  2. Key findings (bulleted, cite the numbers)\n"
        "  3. Opportunities for improvement (specific, actionable, prioritized)\n"
        "  4. Suggested next steps (map each to a workspaceManager command where "
        "relevant: `workspace-manager janitor`, `workspace-manager sort`)\n\n"
        "Be concrete and reference the actual figures. Do not invent data beyond "
        "what is given. Do not include a title heading — the caller adds it.\n\n"
        "=== FACTS ===\n"
        f"{facts_markdown}\n"
    )
    with client.messages.stream(
        model=cfg.model,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        output_config={"effort": cfg.effort},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        msg = stream.get_final_message()
    return "".join(b.text for b in msg.content if b.type == "text")
