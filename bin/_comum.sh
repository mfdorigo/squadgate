# Shared by the squadgate scripts: code folder, state folder and Python.
# Python runs in UTF-8 mode so files and messages behave the same on Windows.
SG_CODE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SG_STATE="${SQUADGATE_STATE:-$HOME/.claude/squad-state}"
export PYTHONUTF8=1
# sg_python: fills SG_PY with the Python 3 command (only called when Python is really needed).
# On Windows, "python3" may be the Microsoft Store stub, so it is tested before use.
sg_python() {
  SG_PY=()
  case "$(uname -s 2>/dev/null)" in MINGW*|MSYS*|CYGWIN*) local testar=1 ;; *) local testar= ;; esac
  for c in python3 python "py -3"; do
    command -v ${c%% *} >/dev/null 2>&1 || continue
    if [ -n "$testar" ] || [ "$c" = python ]; then
      $c -c "import sys; sys.exit(sys.version_info[0] < 3)" >/dev/null 2>&1 || continue
    fi
    read -r -a SG_PY <<< "$c"; return 0
  done
  return 1
}
