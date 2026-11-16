#!/usr/bin/env bash
# Removes squadgate from ~/.claude: agents, skill, scripts and hooks. Your other settings stay.
#   ./uninstall.sh           keeps ~/.claude/squad-state (history, backups)
#   ./uninstall.sh --purge   also deletes ~/.claude/squad-state
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
CLAUDE="$HOME/.claude"
STATE="${SQUADGATE_STATE:-$CLAUDE/squad-state}"
BACKUP="$STATE/backup/$(date +%Y%m%d-%H%M%S)-uninstall"
. "$REPO/bin/_comum.sh"
sg_python || { echo "squadgate: Python 3 not found." >&2; exit 1; }

"${SG_PY[@]}" "$REPO/lib/settings_hooks.py" remove "$CLAUDE/settings.json" "$BACKUP/settings.json"
echo "Hooks removed from ~/.claude/settings.json (previous file saved in $BACKUP/settings.json)"

lista="$STATE/instalados.txt"
if [ -f "$lista" ]; then
  while IFS= read -r alvo; do
    case "$alvo" in "$CLAUDE"/*) ;; *) continue ;; esac   # never touches anything outside ~/.claude
    if [ -L "$alvo" ]; then rm "$alvo"; echo "  removed link $alvo"
    elif [ -e "$alvo" ]; then rm -r "$alvo"; echo "  removed $alvo"; fi
  done < "$lista"
  rm -f "$lista" "$STATE/instalacao.json"
else
  echo "No install list found in $STATE; nothing else to remove."
fi

if [ "${1:-}" = "--purge" ]; then
  rm -r "$STATE"
  echo "Removed $STATE"
else
  echo "Kept $STATE (history and backups). Use --purge to delete it."
fi
echo "squadgate uninstalled. Open a new Claude Code session for it to take effect."
