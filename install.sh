#!/usr/bin/env bash
# CAD MCP telepítő macOS-re.
#   ./install.sh                  # telepítés + bekötés a Claude Code-ba (kek profil)
#   ./install.sh --modules mind   # más induló modulok/profil (kek, vztel, geodeta, kozvil, keva, rajz, minimal, mind)
#   ./install.sh --no-register    # csak telepítés, a bekötést kézzel végzed
#   ./install.sh --test           # a végén lefuttatja a teszteket
set -euo pipefail
cd "$(dirname "$0")"
DIR="$(pwd)"
MODULES="kek"
REGISTER=1
TEST=0
while [ $# -gt 0 ]; do
  case "$1" in
    --modules) MODULES="$2"; shift 2 ;;
    --no-register) REGISTER=0; shift ;;
    --test) TEST=1; shift ;;
    *) echo "Ismeretlen kapcsoló: $1"; exit 2 ;;
  esac
done

PY="${PYTHON:-python3}"
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
  echo "Python 3.10 vagy újabb kell (python.org vagy Homebrew: brew install python@3.12)."
  exit 1
fi

echo "== Virtuális környezet: $DIR/.venv"
"$PY" -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
if ! .venv/bin/python -m pip install --quiet -e ".[dev]"; then
  echo "== Újrapróbálás a rendszer tanúsítványaival"
  PIP_USE_DEPRECATED=legacy-certs .venv/bin/python -m pip install --quiet -e ".[dev]"
fi

WORK="${CAD_MCP_WORKDIR:-$HOME/Documents/CAD-MCP}"
mkdir -p "$WORK"

echo "== Ellenőrzés"
PYTHONPATH="$DIR/src" .venv/bin/python -c "import cad_mcp.server as s; s.build_server(); print('A szerver elindul, eszközök:', len(s.OPS))"

if [ "$TEST" = 1 ]; then
  .venv/bin/python -m pytest -q
fi

if [ "$REGISTER" = 1 ] && command -v claude >/dev/null 2>&1; then
  echo "== Bekötés a Claude Code-ba (minden munkamenetben elérhető)"
  claude mcp remove autocad -s user >/dev/null 2>&1 || true
  claude mcp add autocad -s user -e PYTHONPATH="$DIR/src" -e CAD_MCP_WORKDIR="$WORK" \
    -e CAD_MCP_MODULES="$MODULES" -- "$DIR/.venv/bin/python" -m cad_mcp
  claude mcp get autocad || true
else
  cat <<EOF

== Kézi bekötés
Claude Code:
  claude mcp add autocad -s user -e PYTHONPATH="$DIR/src" -e CAD_MCP_WORKDIR="$WORK" -e CAD_MCP_MODULES="$MODULES" -- "$DIR/.venv/bin/python" -m cad_mcp

Claude Desktop – a claude_desktop_config.json "mcpServers" részébe:
  "autocad": {
    "command": "$DIR/.venv/bin/python",
    "args": ["-m", "cad_mcp"],
    "env": {"PYTHONPATH": "$DIR/src", "CAD_MCP_WORKDIR": "$WORK", "CAD_MCP_MODULES": "$MODULES"}
  }
EOF
fi

echo
echo "Kész. A rajzok helye: $WORK"
echo "DWG-hez telepítsd az ingyenes ODA File Convertert: https://www.opendesign.com/guestfiles/oda_file_converter"
