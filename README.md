# Claude Code Sessions Dashboard

A single-file Python script that turns your local Claude Code session history into a beautiful, searchable HTML dashboard — with stats, heatmaps, and per-session details.

Run it once, open `index.html` in your browser. That's it.

![Dashboard overview: sidebar with Stats and Sessions tabs, pastel stat cards, activity heatmap](https://i.imgur.com/placeholder.png)

---

## Requirements

| Requirement | Notes |
|---|---|
| **Python 3.6+** | No third-party packages — standard library only |
| **Claude Code** | Sessions must exist in `~/.claude/projects/` |
| **Internet** | First run only — downloads the icon font (~3.8 MB) once |

---

## Quick Start

```bash
# 1. Download the script
curl -O https://raw.githubusercontent.com/VILWAS/claude-sessions/main/generate.py

# 2. Run it
python3 generate.py

# 3. Open the dashboard
open index.html          # macOS
xdg-open index.html      # Linux
start index.html         # Windows
```

The script creates two files next to itself:
- `index.html` — your dashboard (open this in a browser)
- `material-symbols.woff2` — icon font (downloaded once, cached forever)

---

## Auto-Run After Every Session

Add this to `~/.claude/settings.json` so the dashboard regenerates automatically every time a Claude Code session ends:

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/Documents/sessions/generate.py"
          }
        ]
      }
    ]
  }
}
```

> **Change the path** to wherever you saved `generate.py`.

---

## Features

### Stats Page
- **4 large stat cards** — Total Sessions, Messages, Tokens, Estimated Cost
- **8 secondary cards** — Input/Output tokens, This Week, Today, Avg Messages, Busiest Day, Top Project, Projects count
- **Activity heatmap** — GitHub-style, past 52 weeks
- **Per-project breakdown table** — sessions, messages, tokens, and cost per project

### Sessions Page
- **Horizontal sub-tabs** — Recent (last 7 days) | per-project folders | Archived
- **Search** — full-text across titles, first message, summaries
- **Filters** — by date range, category, starred status
- **14 auto-detected categories** with color-coded pills (supports multiple per session):
  `Figma` `VS Code` `Git` `Python` `JavaScript` `CSS` `Database` `Docker` `API` `Testing` `Shell` `Slack` `Setup` `General`
- **Sortable columns** — date, messages, tokens, cost, category, title
- **Per-row actions** — star, label (7 colors), notes, view chat, copy resume command, archive, delete
- **Bulk actions** — archive/delete/label multiple sessions at once
- **Export** — CSV export, per-session Markdown export, annotation import/export
- **Chat viewer** — WhatsApp-style message bubbles with timestamps
- **Summary popup** — auto-generated extractive summary per session
- **Dark / light mode** — follows system preference, toggle with `d` key

### Keyboard Shortcuts
| Key | Action |
|---|---|
| `/` | Focus search |
| `d` | Toggle dark / light mode |
| `?` | Show all shortcuts |
| `Esc` | Close modal / clear search |
| `Shift + click` | Bulk select rows |

---

## Sharing With Your Team

Just share the `generate.py` file. Each person runs it on their own machine against their own Claude Code sessions.

**For fully offline use** (no internet required on first run), also share `material-symbols.woff2` alongside `generate.py`.

```
your-team/
├── generate.py              ← share this (required)
└── material-symbols.woff2   ← share this too (optional, enables offline icons)
```

Each person generates their own `index.html` locally — no server or shared infrastructure needed.

---

## Configuration

### Adjust Token Pricing

Edit the two constants at the top of `generate.py` to match your Claude plan:

```python
# Claude Sonnet pricing — adjust if using a different model
INPUT_COST_PER_M  = 3.0   # $/M input tokens
OUTPUT_COST_PER_M = 15.0  # $/M output tokens
```

Current rates (as of 2025): [Anthropic pricing page](https://www.anthropic.com/pricing)

### Output Location

By default, `index.html` is saved next to `generate.py`. To change this, edit:

```python
OUT_DIR = Path(__file__).resolve().parent
```

---

## How It Works

```
~/.claude/projects/
└── -Users-yourname-Documents-my-project/
    ├── abc123...jsonl   ← one file per session
    └── def456...jsonl
```

1. **Scans** every `.jsonl` file in `~/.claude/projects/`
2. **Parses** messages, timestamps, token counts, and cost
3. **Infers categories** from message content (multi-category support)
4. **Generates** a single self-contained `index.html` with all data embedded
5. **Caches** summaries in `summaries.json` — unchanged sessions are never re-processed

All data stays local. Nothing is sent anywhere.

---

## Files Created

| File | Description |
|---|---|
| `index.html` | Your dashboard — open in any browser |
| `material-symbols.woff2` | Icon font, downloaded once |
| `summaries.json` | Summary cache — speeds up regeneration |
| `deleted.json` | Tracks sessions you've hidden in the UI |

---

## Troubleshooting

**"No sessions found"**
Make sure Claude Code has been used and `~/.claude/projects/` exists with `.jsonl` files inside.

**Icons show as text**
The icon font failed to download. Check your internet connection and re-run `generate.py`. Or manually download the `.woff2` file and place it next to the script.

**Costs look wrong**
Update `INPUT_COST_PER_M` and `OUTPUT_COST_PER_M` at the top of `generate.py` to match your actual Claude model pricing.

**Hook doesn't fire**
Make sure the path in `settings.json` points to where you actually saved `generate.py`. Test manually: `python3 /your/path/to/generate.py`.

---

## License

MIT — do whatever you want with it.
