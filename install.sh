#!/bin/bash
# workspaceManager installer (macOS).
#
# 1. Creates a virtualenv and installs the package.
# 2. Renders the launchd agent plists with your real paths.
# 3. Loads the agents so the workflow runs automatically:
#      - download sorter: fires whenever ~/Downloads changes
#      - janitor:  weekly dry-run scan (Sun 09:00)
#      - reporter: weekly state report (Sun 09:15)
#
# Re-runnable (idempotent): it reloads agents in place.
# Uninstall: ./install.sh --uninstall
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV="$REPO_ROOT/.venv"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
LABELS=(com.workspacemanager.downloadsorter \
        com.workspacemanager.janitor \
        com.workspacemanager.reporter)

uninstall() {
  for label in "${LABELS[@]}"; do
    launchctl unload "$LAUNCH_AGENTS/$label.plist" 2>/dev/null || true
    rm -f "$LAUNCH_AGENTS/$label.plist"
    echo "removed $label"
  done
  echo "Agents removed. The package + venv are left in place; delete $VENV to remove."
  exit 0
}

[ "${1:-}" = "--uninstall" ] && uninstall

echo "==> Creating virtualenv at $VENV"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
echo "==> Installing workspace-manager"
"$VENV/bin/pip" install --quiet -e "$REPO_ROOT"

WM_BIN="$VENV/bin/workspace-manager"

# terminal-notifier gives reliable, clickable notification banners (macOS often
# suppresses the osascript fallback). Install it via Homebrew if available.
if ! command -v terminal-notifier >/dev/null 2>&1 \
   && [ ! -x /opt/homebrew/bin/terminal-notifier ] \
   && [ ! -x /usr/local/bin/terminal-notifier ]; then
  if command -v brew >/dev/null 2>&1; then
    echo "==> Installing terminal-notifier (for clickable notifications)"
    brew install terminal-notifier >/dev/null 2>&1 || \
      echo "   (brew install failed; notifications fall back to osascript)"
  else
    echo "!! terminal-notifier not found and Homebrew unavailable — notifications"
    echo "   will use the osascript fallback (which macOS may suppress). Install"
    echo "   Homebrew + 'brew install terminal-notifier' for reliable banners."
  fi
fi

# Read workspace_root / downloads_dir from config if present, else defaults.
WORKSPACE_ROOT="$HOME/workspaceManager"
DOWNLOADS="$HOME/Downloads"
if [ -f "$REPO_ROOT/config.yaml" ]; then
  WORKSPACE_ROOT="$("$VENV/bin/python" - <<PY
import yaml, os
d = yaml.safe_load(open("$REPO_ROOT/config.yaml")) or {}
print(os.path.expanduser(d.get("workspace_root", "$HOME/workspaceManager")))
PY
)"
  DOWNLOADS="$("$VENV/bin/python" - <<PY
import yaml, os
d = yaml.safe_load(open("$REPO_ROOT/config.yaml")) or {}
print(os.path.expanduser(d.get("downloads_dir", "$HOME/Downloads")))
PY
)"
fi

LOG_DIR="$WORKSPACE_ROOT/logs"
mkdir -p "$LOG_DIR" "$LAUNCH_AGENTS"

if [ ! -f "$REPO_ROOT/.env" ]; then
  echo "!! No .env found. The agents are LLM-driven and need an API key."
  echo "   Create it before the agents will work:"
  echo "     echo 'ANTHROPIC_API_KEY=sk-ant-...' > $REPO_ROOT/.env"
fi

echo "==> Installing launchd agents"
for label in "${LABELS[@]}"; do
  tpl="$REPO_ROOT/agents/$label.plist.template"
  out="$LAUNCH_AGENTS/$label.plist"
  sed -e "s|__WM_BIN__|$WM_BIN|g" \
      -e "s|__DOWNLOADS__|$DOWNLOADS|g" \
      -e "s|__LOG_DIR__|$LOG_DIR|g" \
      "$tpl" > "$out"
  launchctl unload "$out" 2>/dev/null || true
  launchctl load "$out"
  echo "   loaded $label"
done

echo
echo "Done. Try it now:"
echo "  $WM_BIN sort --dry-run     # preview download classification"
echo "  $WM_BIN janitor            # dry-run scan -> review report"
echo "  $WM_BIN report             # write a file-system state report"
echo
echo "Logs: $LOG_DIR"
