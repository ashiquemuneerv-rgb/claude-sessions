#!/bin/bash
# Claude Code Sessions Dashboard — installer
# Usage: curl -fsSL https://raw.githubusercontent.com/ashiquemuneerv-rgb/claude-sessions/main/install.sh | bash

set -e

REPO="https://raw.githubusercontent.com/ashiquemuneerv-rgb/claude-sessions/main"
INSTALL_DIR="$HOME/Documents/claude-sessions"

echo ""
echo "╔══════════════════════════════════════╗"
echo "║   Claude Code Sessions Dashboard     ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ── Check Python 3 ────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
  echo "  ERROR: Python 3 is not installed."
  echo ""
  echo "  Install it from: https://www.python.org/downloads/"
  echo "  Then re-run this command."
  exit 1
fi

# ── Download files ────────────────────────────────────────────────────────────
echo "  Downloading to $INSTALL_DIR ..."
mkdir -p "$INSTALL_DIR"

curl -fsSL "$REPO/generate.py"   -o "$INSTALL_DIR/generate.py"
curl -fsSL "$REPO/run.command"   -o "$INSTALL_DIR/run.command"
chmod +x "$INSTALL_DIR/run.command"
echo "  ✓ Files downloaded"

# ── Run generate.py (installs hook + builds dashboard) ───────────────────────
echo ""
echo "  Setting up..."
python3 "$INSTALL_DIR/generate.py"

# ── Open dashboard ────────────────────────────────────────────────────────────
echo ""
echo "  Opening dashboard in your browser..."
open "$INSTALL_DIR/index.html"

echo ""
echo "  ✓ All done! Your dashboard will auto-update after every Claude session."
echo "  ✓ To refresh manually, double-click run.command in $INSTALL_DIR"
echo ""
