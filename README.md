# workspaceManager

An open-source, **macOS** file-organization toolkitx. Clone it onto
any Mac, add an Anthropic API key, run one installer, and utilize three LLM-driven agents to help keep your file system organized.


| Agent | What it does | Safety |
|-------|--------------|--------|
| **janitor** | Flags large **and** stale files/folders that *could* be deleted and moves them to a review folder. | **Never deletes.** Deterministic selection; every move is logged and reversible. |
| **download sorter** | Fires on every new download, asks Claude to classify it, and files it into the right `_Sorted/<Folder>/`. | Skips in-progress downloads; every move logged and reversible. |
| **reporter** | Writes a documentation-style report on the overall state of your file system, with prioritized improvement opportunities. | Read-only. Delivered via a pluggable sink (local markdown today; Notes/Gmail pluggable). |

Everything the toolkit produces lives under `~/workspaceManager/` (reports,
review folder, sort manifests, logs) — nothing is scattered across your disk.


from `config.yaml` (or built-in defaults), and the installer renders the launchd
agents with your real paths. Clone → configure → `./install.sh` on any Mac.

> **Scope:** macOS-first by design — it leans on native tooling (`mdls` for
> last-opened dates, `launchd` for scheduling/watching, and macOS *bundle*
> semantics so `.app`/`.photoslibrary` packages are treated as single units).
> The code is structured so other platforms can be added later.

## Requirements

- macOS, Python 3.10+
- An `ANTHROPIC_API_KEY` (all three agents call Claude)
- `terminal-notifier` (optional, recommended) for reliable, click-to-open
  notification banners — `install.sh` installs it via Homebrew if missing;
  otherwise notifications fall back to `osascript` (which macOS may suppress).

## Install

```bash
git clone <your-fork-url> workspaceManager && cd workspaceManager
cp config.example.yaml config.yaml        # optional — edit thresholds/paths
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env
./install.sh
```

The installer creates a venv, installs the `workspace-manager` command, and
loads the three launchd agents. Uninstall with `./install.sh --uninstall`.

## Use it by hand

```bash
workspace-manager sort --dry-run    # preview how new downloads would be filed
workspace-manager sort              # classify & file new downloads now
workspace-manager janitor           # dry-run scan -> review report (moves nothing)
workspace-manager janitor --apply   # move flagged items into the review folder
workspace-manager report            # write a file-system state report
```

Undo anything: each `--apply`/sort run drops a `RESTORE_ALL.sh` next to its
`MANIFEST.json`.

## Configuration

See `config.example.yaml`. Common knobs: `model` (defaults to `claude-opus-4-8`;
set `claude-haiku-4-5` for cheaper high-volume sorting), `effort`, `min_size_mb`,
`stale_days`, `scan_roots`, `downloads_dir`, `sorted_root`.

## Layout

```
src/workspace_manager/
  config.py          machine-local configuration (no hardcoded paths)
  common.py          safe walker (prunes deps, treats bundles as opaque), manifests
  llm.py             Claude integration (classification + report authoring)
  janitor.py         feature 1
  download_sorter.py feature 2
  reporter.py        feature 3 (pluggable Sink)
  cli.py             `workspace-manager` entry point
agents/              launchd .plist templates (rendered by install.sh)
```

## License

MIT — see `LICENSE`.
