"""Configuration loading — resolves everything relative to the current machine.

No paths are hardcoded to a specific user. On first run the tool reads
``config.yaml`` from the repo root (or ``$WORKSPACE_MANAGER_CONFIG``); if that
file is absent, the built-in defaults below are used. This is what makes the
workflow reproducible on any Mac once the repo is cloned.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

HOME = Path.home()

# Repo root = two levels up from this file (src/workspace_manager/config.py).
REPO_ROOT = Path(__file__).resolve().parents[2]

# Directory NAMES pruned from every walk — dependencies, build output, VCS,
# app internals. These are never scanned, flagged, or moved.
DEFAULT_PROTECTED_DIR_NAMES = {
    # dependencies
    "node_modules", ".venv", "venv", "env", ".env", "site-packages",
    "Pods", "Carthage", "vendor", "bower_components", ".cargo", ".rustup",
    ".npm", ".pnpm-store", ".yarn", ".gradle", ".m2", ".terraform",
    # build output / caches
    "dist", "build", ".next", ".nuxt", "__pycache__", "target",
    ".build", "DerivedData", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".cache", ".turbo", "out",
    # vcs / tooling
    ".git", ".svn", ".hg", ".idea", ".vscode",
}

# Top-level home dirs skipped entirely (system-managed / app-managed / risky).
DEFAULT_PRUNE_TOP_LEVEL = {
    "Library", "Applications", ".Trash", "Public", ".ssh", ".gnupg",
    "go", "Movies", "Music", "Pictures", "workspaceManager",
}

# Fixed destination taxonomy for the download sorter. The classifier MUST pick
# one of these `name`s (enforced via an enum in the JSON schema), so folders
# never fragment (no "Resume" vs "Resumes" vs "CVs"). "Miscellaneous" is the
# guaranteed fallback for anything it can't confidently place. Edit freely in
# config.yaml — the `description` is what the model reads to decide.
DEFAULT_FOLDERS = [
    {"name": "Resume", "description": "resumes, CVs, cover letters, job "
        "applications, references"},
    {"name": "Schoolwork", "description": "assignments, homework, problem sets, "
        "lecture notes, syllabi, exams, essays, study guides, academic papers"},
    {"name": "Invoices", "description": "invoices, receipts, bills, statements, "
        "purchase orders, tax documents"},
    {"name": "Documents", "description": "general documents, contracts, forms, "
        "letters, PDFs and text that don't fit another folder"},
    {"name": "Screenshots", "description": "screenshots and screen captures"},
    {"name": "Images", "description": "photos, graphics, design assets, icons, "
        "logos (not screenshots)"},
    {"name": "Installers", "description": "app installers and disk images: "
        ".dmg, .pkg, .exe, .msi"},
    {"name": "Archives", "description": "compressed archives: .zip, .tar, .gz, "
        ".7z, .rar"},
    {"name": "Media", "description": "video and audio files"},
    {"name": "Code", "description": "source code, scripts, notebooks, "
        "config files, project archives"},
    {"name": "Data", "description": "datasets and structured data: .csv, .json, "
        ".xlsx, .parquet"},
    {"name": "Miscellaneous", "description": "anything that doesn't clearly "
        "belong in another folder, or can't be identified"},
]


@dataclass
class Config:
    """Runtime configuration. Every path is absolute and machine-local."""

    # Where the whole workflow keeps its state (reports, review folder, logs).
    workspace_root: Path = HOME / "workspaceManager"

    # --- Janitor (feature 1) ---
    scan_roots: list[Path] = field(default_factory=lambda: [HOME])
    min_size_bytes: int = 25 * 1024 * 1024   # 25 MB
    stale_days: int = 60
    protected_dir_names: set[str] = field(
        default_factory=lambda: set(DEFAULT_PROTECTED_DIR_NAMES))
    prune_top_level: set[str] = field(
        default_factory=lambda: set(DEFAULT_PRUNE_TOP_LEVEL))

    # --- Download sorter (feature 2) ---
    downloads_dir: Path = HOME / "Downloads"
    sorted_root: Path = HOME / "Downloads" / "_Sorted"
    # Max items classified per `sort` run — a cost guard against firing hundreds
    # of LLM calls at once (e.g. a large backlog). 0 = unlimited. Per-download
    # watcher runs are tiny; this only matters for backlog cleanup.
    sort_batch_limit: int = 50

    # --- LLM (required for all three features) ---
    # `model` authors the report (feature 3) and is the default classifier.
    # `sort_model` optionally overrides the classifier only — Haiku 4.5 is a
    # cheap, capable fit for "which folder does this file belong in".
    model: str = "claude-opus-4-8"          # report authoring; default classifier
    sort_model: str | None = None            # classifier override (e.g. claude-haiku-4-5)
    effort: str = "medium"                   # low | medium | high | max (report only)

    # Fixed destination folders for the sorter (see DEFAULT_FOLDERS).
    folders: list[dict] = field(default_factory=lambda: list(DEFAULT_FOLDERS))
    # Content peek budget: only the first page / this many characters of a file
    # are ever sent to the classifier — bounds tokens and cost, hard.
    peek_max_chars: int = 2000

    @property
    def review_root(self) -> Path:
        return self.workspace_root / "FlaggedForReview"

    @property
    def reports_dir(self) -> Path:
        return self.workspace_root / "reports"

    @property
    def sort_manifests_dir(self) -> Path:
        return self.workspace_root / "sort-manifests"

    @property
    def sort_since_file(self) -> Path:
        """Baseline cutoff: when set, the sorter only touches files created
        after this timestamp (i.e. genuinely new downloads)."""
        return self.workspace_root / "state" / "sort_since.txt"


def _coerce(cfg: Config, data: dict) -> Config:
    """Overlay a parsed YAML dict onto the defaults, expanding ``~``."""
    def as_path(v: str) -> Path:
        return Path(os.path.expanduser(v)).resolve()

    if "workspace_root" in data:
        cfg.workspace_root = as_path(data["workspace_root"])
    if data.get("scan_roots"):
        # Skip null entries (a bare `~` in YAML parses as null — quote it).
        cfg.scan_roots = [as_path(p) for p in data["scan_roots"] if p]
    if "min_size_mb" in data:
        cfg.min_size_bytes = int(data["min_size_mb"]) * 1024 * 1024
    if "stale_days" in data:
        cfg.stale_days = int(data["stale_days"])
    if "protected_dir_names" in data:
        cfg.protected_dir_names |= set(data["protected_dir_names"])
    if "prune_top_level" in data:
        cfg.prune_top_level |= set(data["prune_top_level"])
    if "downloads_dir" in data:
        cfg.downloads_dir = as_path(data["downloads_dir"])
    if "sorted_root" in data:
        cfg.sorted_root = as_path(data["sorted_root"])
    if "sort_batch_limit" in data:
        cfg.sort_batch_limit = int(data["sort_batch_limit"])
    if "model" in data:
        cfg.model = str(data["model"])
    if "sort_model" in data and data["sort_model"]:
        cfg.sort_model = str(data["sort_model"])
    if "effort" in data:
        cfg.effort = str(data["effort"])
    if data.get("folders"):
        cfg.folders = list(data["folders"])
    if "peek_max_chars" in data:
        cfg.peek_max_chars = int(data["peek_max_chars"])
    return cfg


def load(path: Path | None = None) -> Config:
    """Load config from YAML if present, else return defaults.

    Resolution order: explicit ``path`` arg -> ``$WORKSPACE_MANAGER_CONFIG``
    -> ``<repo>/config.yaml`` -> built-in defaults.
    """
    cfg = Config()
    candidate = (
        path
        or (Path(os.environ["WORKSPACE_MANAGER_CONFIG"])
            if os.environ.get("WORKSPACE_MANAGER_CONFIG") else None)
        or (REPO_ROOT / "config.yaml")
    )
    if candidate and candidate.exists():
        import yaml  # local import so the tool runs even if PyYAML is missing
        data = yaml.safe_load(candidate.read_text()) or {}
        cfg = _coerce(cfg, data)
    return cfg
