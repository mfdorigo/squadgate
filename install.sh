#!/usr/bin/env bash
# Installs squadgate for the current user (Claude Code, ~/.claude).
#   ./install.sh          links on macOS/Linux, copies on Windows (Git Bash)
#   ./install.sh --copy   always copy (then run it again after each update)
# Safe to run again: it replaces the previous squadgate install and keeps your other settings.
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
CLAUDE="$HOME/.claude"
STATE="${SQUADGATE_STATE:-$CLAUDE/squad-state}"
BACKUP="$STATE/backup/$(date +%Y%m%d-%H%M%S)"
. "$REPO/bin/_comum.sh"

falha() { echo "squadgate: $*" >&2; exit 1; }
[ -z "${CLAUDE_CONFIG_DIR:-}" ] || [ "$CLAUDE_CONFIG_DIR" = "$CLAUDE" ] || \
  falha "CLAUDE_CONFIG_DIR points to $CLAUDE_CONFIG_DIR; squadgate supports only ~/.claude for now."
sg_python || falha "Python 3 not found. Install Python 3 and run again."
command -v git >/dev/null 2>&1 || falha "git not found."

MODO=link
case "$(uname -s 2>/dev/null)" in MINGW*|MSYS*|CYGWIN*) MODO=copy ;; esac
[ "${1:-}" = "--copy" ] && MODO=copy

mkdir -p "$CLAUDE/agents" "$CLAUDE/skills" "$STATE"
: > "$STATE/instalados.txt.tmp"

# Moves anything already at the target (a previous install, or a file of yours) into the backup folder.
guardar() {
  local alvo="$1"
  [ -e "$alvo" ] || [ -L "$alvo" ] || return 0
  if [ -L "$alvo" ]; then rm "$alvo"; return 0; fi
  local rel="${alvo#"$CLAUDE"/}"
  mkdir -p "$BACKUP/$(dirname "$rel")"
  mv "$alvo" "$BACKUP/$rel"
  echo "  backup: ~/.claude/$rel -> $BACKUP/$rel"
}

instalar() {
  local origem="$1" alvo="$2"
  guardar "$alvo"
  if [ "$MODO" = link ]; then ln -s "$origem" "$alvo"; else cp -R "$origem" "$alvo"; fi
  echo "$alvo" >> "$STATE/instalados.txt.tmp"
}

# Earlier layout (~/.claude/squad with its own estado/): keep the state, then back the folder up.
if [ -f "$CLAUDE/squad/lib/squad.py" ] && [ ! -L "$CLAUDE/squad" ]; then
  if [ -d "$CLAUDE/squad/estado" ]; then
    cp -R "$CLAUDE/squad/estado/." "$STATE/"
    echo "  state migrated from ~/.claude/squad/estado"
  fi
  guardar "$CLAUDE/squad"
fi

echo "Installing squadgate ($MODO) from $REPO"
for f in "$REPO"/agents/squad-*.md; do instalar "$f" "$CLAUDE/agents/$(basename "$f")"; done
instalar "$REPO/skills/squad" "$CLAUDE/skills/squad"
if [ "$MODO" = link ]; then
  instalar "$REPO" "$CLAUDE/squadgate"
else
  guardar "$CLAUDE/squadgate"
  mkdir -p "$CLAUDE/squadgate"
  for d in bin lib painel; do cp -R "$REPO/$d" "$CLAUDE/squadgate/"; done
  echo "$CLAUDE/squadgate" >> "$STATE/instalados.txt.tmp"
fi
chmod +x "$REPO"/bin/squad-* 2>/dev/null || true
mv "$STATE/instalados.txt.tmp" "$STATE/instalados.txt"
printf '{"modo": "%s", "repo": "%s"}\n' "$MODO" "$REPO" > "$STATE/instalacao.json"

"${SG_PY[@]}" "$REPO/lib/settings_hooks.py" add "$CLAUDE/settings.json" "$REPO/hooks.json" \
  "bash \"$CLAUDE/squadgate/bin/squad-hook\"" "$BACKUP/settings.json"
echo "  hooks added to ~/.claude/settings.json (previous file saved in $BACKUP/settings.json)"

echo
echo "Done. Open a new Claude Code session and type /squad to see the commands."
[ "$MODO" = copy ] && echo "Copy mode: run ./install.sh again after updating the repository."
exit 0
