# Claude Code Sessions Dashboard

A dashboard that turns your Claude Code session history into a visual, searchable webpage — showing stats, costs, activity heatmap, and every conversation you've had.

---

## Why use it?

- See exactly how much Claude Code you're using and what it costs
- Search and revisit past sessions
- Track which projects you spend the most time on
- GitHub-style activity heatmap across all sessions

---

## Setup — 3 steps, takes 30 seconds

**Step 1** — Open Terminal
Press `Cmd + Space`, type **Terminal**, hit Enter

**Step 2** — Paste this and hit Enter:

```bash
curl -fsSL https://raw.githubusercontent.com/ashiquemuneerv-rgb/claude-sessions/main/install.sh | bash
```

Your dashboard will open in the browser automatically.

**Step 3** — Bookmark it
Once the dashboard opens, press `Cmd + D` to bookmark it so you can come back anytime.

**Where are the files saved?**
Everything is stored in one folder: `~/Documents/claude-sessions/`
Open Finder → Documents → **claude-sessions**

**What happens behind the scenes:**
- Creates `~/Documents/claude-sessions/` folder
- Downloads `generate.py` and `run.command` into it
- Installs a hook in Claude Code so the dashboard auto-updates after every session
- Generates and opens `index.html`

---

## After setup

| Task | How |
|------|-----|
| View dashboard | Open your bookmark or `~/Documents/claude-sessions/index.html` |
| Auto-update | Happens automatically after every Claude Code session — nothing to do |
| Manual refresh | Double-click `run.command` in the `claude-sessions` folder |
| Get latest tool updates | Double-click `run.command` — it always pulls the latest version |

---

## Features

**Stats page**
- Total sessions, messages, tokens, and estimated cost
- Activity heatmap (GitHub-style, past 52 weeks)
- Per-project breakdown table

**Sessions page**
- Search across all sessions by title, content, or summary
- Filter by date, project, category, or starred status
- 14 auto-detected categories: `Figma` `Git` `Python` `JavaScript` `Docker` `API` `Testing` and more
- Star, label, and add notes to sessions
- View full chat history per session
- Export to CSV or Markdown
- Bulk archive / delete

**Keyboard shortcuts**
| Key | Action |
|-----|--------|
| `/` | Focus search |
| `d` | Toggle dark / light mode |
| `?` | Show all shortcuts |
| `Esc` | Close modal / clear search |

---

## Configuration

### Adjust token pricing

Edit the two lines at the top of `generate.py` to match your Claude plan:

```python
INPUT_COST_PER_M  = 3.0   # $/M input tokens
OUTPUT_COST_PER_M = 15.0  # $/M output tokens
```

Current rates: [anthropic.com/pricing](https://www.anthropic.com/pricing)

---

## Troubleshooting

**"No sessions found"**
Make sure Claude Code has been used at least once. Sessions are stored in `~/.claude/projects/`.

**Dashboard not auto-updating**
Run the install command again — it will re-install the hook without affecting your existing data.

**Costs look wrong**
Update `INPUT_COST_PER_M` and `OUTPUT_COST_PER_M` at the top of `generate.py`.

---

## Requirements

- macOS
- Python 3 — [python.org/downloads](https://www.python.org/downloads/)
- Claude Code — [claude.ai/code](https://claude.ai/code)

---

## License

MIT
