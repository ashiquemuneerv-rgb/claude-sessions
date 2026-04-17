#!/bin/bash
# Double-click this file on macOS to set up and open your Claude Code dashboard.
cd "$(dirname "$0")"

# Check generate.py is in the same folder
if [ ! -f "generate.py" ]; then
  echo "----------------------------------------------"
  echo "  ERROR: generate.py not found."
  echo ""
  echo "  Make sure generate.py and run.command are"
  echo "  in the same folder, then try again."
  echo "----------------------------------------------"
  read -rp "Press Enter to close..."
  exit 1
fi

# Check Python 3 is available
if ! command -v python3 &>/dev/null; then
  echo "----------------------------------------------"
  echo "  Python 3 is not installed on this Mac."
  echo ""
  echo "  Install it from: https://www.python.org/downloads/"
  echo "  Then double-click this file again."
  echo "----------------------------------------------"
  read -rp "Press Enter to close..."
  exit 1
fi

python3 generate.py

if [ $? -eq 0 ]; then
  echo ""
  echo "Opening dashboard in your browser..."
  open index.html
fi

read -rp "Press Enter to close this window..."
