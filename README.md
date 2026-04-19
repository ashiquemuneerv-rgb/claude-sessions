# Claude Code Sessions Dashboard

A dashboard that turns your Claude Code session history into a visual, searchable webpage — showing stats, costs, activity heatmap, and every conversation you've had.

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

## How to use

### Stats Page

The Stats page is your usage overview — open it by clicking **Stats** in the left sidebar.

**What you see:**
- **Total sessions, messages, tokens, and estimated cost** across all time
- **Activity heatmap** — GitHub-style grid showing which days you used Claude Code most (hover a cell to see the date and session count)
- **Sparkline** — a bar chart of the last 12 weeks of activity
- **Project breakdown table** — which folders you work in most, with message and token counts per project

> **Tip:** Collapse the heatmap by clicking the toggle button at the top-right of the card to save screen space.

---

### Sessions Page

Click **Sessions** in the sidebar to see your full session history.

**Sub-tabs across the top:**
- **Recent** — sessions from the last 7 days across all projects
- **Project folders** — one tab per project directory (e.g. `ViewTogether-Demo`, `friday-game`)
- **Archived** — sessions you've archived

The dashboard remembers which tab you had open — reloading brings you back to the same place.

---

### Search & Filter

**Search** — click the search bar (or press `/`) and type anything. The table filters in real time across session titles, notes, labels, and categories.

**Filter button** — click the **Filter** icon to open the filter panel:
- Filter by **date range** (pick start and end dates)
- Filter by **category** (Python, Git, JavaScript, Docker, etc.)
- Filter by **starred** sessions only

Active filters appear as removable chips below the search bar.

---

### Session columns — show, hide, and reorder

Click the **Cols** button (top-right of the sessions toolbar) to open the column menu:

- **Toggle any column on/off** using the checkboxes
- **Drag columns** up/down in the menu to reorder them in the table

Available columns: Title · Stars · Labels · Notes · Summary · Category · Date · Size · Messages · Tokens · Cost

Your column preferences are saved automatically and persist across reloads.

---

### Working with sessions

Each row in the table is one session. Here's what you can do:

| Action | How |
|--------|-----|
| **Edit title** | Click the title text in any row — type and press Enter |
| **Star a session** | Click the star icon in the Star column |
| **Set a colour label** | Click the dot in the Label column — pick a colour |
| **Add notes** | Click the `+` in the Notes column — type and press Enter |
| **Copy resume command** | Hover the row → click **Copy resume cmd** under the title — paste in Terminal to continue the session |
| **View full chat** | Click ··· → **View Chat** |
| **Get AI summary** | Click the **Summary** button in the Summary column |
| **Archive** | Click ··· → **Archive** |

---

### View full chat

Click **··· → View Chat** on any row to open the full conversation in a modal:

- Scroll through all messages with timestamps
- Search within the chat using the search bar in the modal header
- Click the expand icon to go full-screen
- Copy any individual message with the copy button that appears on hover

---

### AI Summary

Click the **Summary** button on any session to see an AI-generated summary of what was discussed. Useful for quickly recalling what a session was about without reading the full chat.

---

### Bulk actions

Select multiple sessions using the checkboxes (or the checkbox in the header to select all visible rows):

- **Archive** all selected
- **Set label** for all selected at once
- **Export** selected sessions to CSV or Markdown

---

### Dark / Light mode

Press `d` anywhere (or click the sun/moon icon in the sidebar bottom) to toggle between dark and light mode.

Your preference is saved automatically.

---

### Keyboard shortcuts

Press `?` to open the shortcuts panel.

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

## Changelog

### v1.1.0 — 2026-04-18

**Recent & Archived tabs — consistent with main table**
- Both tabs now show the full column set: checkbox, #, star, label, title, notes, summary, category, date, size, messages, tokens, cost, actions
- Column visibility toggles and drag-to-reorder now work across all tabs

**Copy resume cmd button**
- Icon changed to a copy icon (was arrow)

**Page & tab state persists on reload**
- The dashboard now remembers which page (Stats / Sessions) and which folder tab was open
- Reloading brings you back to exactly where you were

**Dark / light theme fixes**
- Star buttons now show the correct colour in dark mode
- Date filter picker renders correctly in both themes
- Heatmap card shadow is now theme-aware
- Search highlight works correctly in dark mode
- Message copy button uses theme colours instead of hardcoded black/white
- Label swatch hover border is now theme-aware
- Empty state text ("No archived sessions" etc.) is readable in dark mode
- All remaining hardcoded shadow colours replaced with CSS variables

---

## License

MIT
