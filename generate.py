#!/usr/bin/env python3
"""
Auto-generates index.html from ~/.claude/projects/ session files.
Run manually or double-click run.command (macOS).

Setup is automatic — on first run this script installs itself as a Claude Code
Stop hook so the dashboard regenerates after every session.
"""

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

# Claude Sonnet pricing — adjust if using a different model
INPUT_COST_PER_M  = 3.0   # $/M input tokens
OUTPUT_COST_PER_M = 15.0  # $/M output tokens

# ── Paths (all derived from home dir — works on any machine) ──────────────────

HOME           = Path.home()
PROJECTS_DIR   = HOME / ".claude" / "projects"

# Output directory: same folder as this script
OUT_DIR        = Path(__file__).resolve().parent
OUTPUT_FILE    = OUT_DIR / "index.html"
SUMMARIES_FILE = OUT_DIR / "summaries.json"

# Claude Code stores project dirs as the filesystem path with "/" replaced by "-"
# e.g. /Users/alice -> -Users-alice,  /home/bob -> -home-bob
HOME_DIR_NAME  = str(HOME).lstrip("/").replace("/", "-")   # e.g. "Users-alice"
HOME_KEY       = "-" + HOME_DIR_NAME                        # e.g. "-Users-alice"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _dir_to_path(dir_name: str) -> str:
    """Convert Claude project dir name back to a readable path."""
    # Strip leading dash, replace remaining dashes-that-were-slashes with /
    # We do this by matching against the known home prefix
    if dir_name == HOME_KEY:
        return "~"
    stripped = dir_name[len(HOME_KEY) + 1:]   # remove "-Users-alice-"
    return "~/" + stripped.replace("-", "/", stripped.count("-"))

def project_label(dir_name: str) -> str:
    """Full readable path label, e.g. ~/Documents/my-project"""
    if dir_name == HOME_KEY:
        return "~ (home)"
    # Remove home prefix to get the relative part
    rel = dir_name[len(HOME_KEY) + 1:]         # e.g. "Documents-friday-game"
    # Find first segment (top-level dir under home)
    first_sep = rel.find("-")
    if first_sep == -1:
        return "~/" + rel
    top   = rel[:first_sep]                    # e.g. "Documents"
    rest  = rel[first_sep + 1:]               # e.g. "friday-game"
    return f"~/{top}/{rest}"

def project_short(dir_name: str) -> str:
    """Short tab label — just the leaf folder name."""
    if dir_name == HOME_KEY:
        return "~"
    rel = dir_name[len(HOME_KEY) + 1:]
    # Leaf is everything after the first segment (top-level dir)
    first_sep = rel.find("-")
    return rel[first_sep + 1:] if first_sep != -1 else rel

def project_resume_prefix(dir_name: str) -> str:
    """cd prefix for non-home projects."""
    if dir_name == HOME_KEY:
        return ""
    return f"cd {project_label(dir_name)} && "

def extract_text(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return block.get("text", "").strip()
    return ""

NOISE = ("<local-command-caveat>", "<local-command-stdout>", "<local-command-stderr>",
         "<ide_opened_file>", "<command-name>",
         "<system-reminder>", "<user-prompt-submit-hook>")

def is_noise(text: str) -> bool:
    return any(text.startswith(n) for n in NOISE) or not text.strip()

_CAT_RULES = [
    ("Figma",      ("figma", "mcp figma", "figma component", "figma design")),
    ("VS Code",    ("vs code", "vscode", ".vscode", "settings.json", "launch.json")),
    ("Git",        ("github", "git commit", "git push", "git pull", "git clone",
                    "pull request", "merge request", "git branch", "upload to git")),
    ("Slack",      ("slack", "slack channel", "slack message")),
    ("Docker",     ("docker", "dockerfile", "docker-compose", "kubernetes", "k8s",
                    "container image", "podman")),
    ("Python",     ("python", "django", "flask", "fastapi", "pandas", "numpy",
                    ".py", "pip install", "virtualenv", "poetry", "pyproject")),
    ("JavaScript", ("javascript", "typescript", "react", "next.js", "nextjs",
                    "vue.js", "angular", "node.js", "npm install", "yarn add",
                    "webpack", "vite", "bun ", "svelte")),
    ("CSS",        ("tailwind", ".scss", ".sass", "styled-components", "css module",
                    "css-in-js", "postcss")),
    ("Database",   ("postgres", "mysql", "sqlite", "mongodb", "redis", "prisma",
                    "database migration", "sql query", "orm ", "supabase", "drizzle")),
    ("API",        ("rest api", "graphql", "api endpoint", "webhook", "swagger",
                    "openapi", "api key", "http request", "axios")),
    ("Testing",    ("unit test", "integration test", " jest ", "pytest", "test coverage",
                    "e2e test", "vitest", "playwright", "cypress")),
    ("Shell",      ("#!/bin", "bash script", "zsh script", "shell script",
                    "cron job", "makefile", "#!/usr")),
    ("Setup",      ("setup guide", "install guide", "uninstall", "getting started",
                    "initial setup", "configuration guide")),
]

def infer_category(messages: list) -> list:
    combined = " ".join(t.lower() for _, t, *_ in messages[:10])
    cats = [cat for cat, kws in _CAT_RULES if any(k in combined for k in kws)]
    return cats if cats else ["General"]

def read_session(path: Path):
    messages = []
    input_tokens = output_tokens = 0
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg   = data.get("message", {})
                role  = msg.get("role", "")
                usage = msg.get("usage", {})
                input_tokens  += usage.get("input_tokens", 0)
                output_tokens += usage.get("output_tokens", 0)
                if role not in ("user", "assistant"):
                    continue
                text = extract_text(msg.get("content", ""))
                if text and not is_noise(text):
                    ts = data.get("timestamp", "")
                    messages.append((role, text, ts))
    except OSError:
        pass
    return messages, input_tokens, output_tokens

def get_first_user(messages):
    for role, text, *_ in messages:
        if role == "user":
            return text[:160]
    return "(empty session)"

def get_all_messages(messages, max_chars=800):
    return [[role, text[:max_chars], ts] for role, text, ts in messages]

_STRIP_PREFIXES = (
    "can you ", "could you ", "please ", "i want to ", "i need to ",
    "help me ", "how do i ", "how to ", "what is ", "what are ",
    "i would like to ", "is there a way to ", "can i ", "i am trying to ",
    "i'm trying to ", "i want ", "i need ", "would you ", "i have a ",
    "let's ", "lets ", "i'd like to ", "show me how to ", "explain ",
)

def _clean_text(text: str) -> str:
    """Strip tags, ANSI, brackets, paths, URLs from a candidate title string."""
    text = re.sub(r"<[^>]+>",        " ", text)
    text = re.sub(r"\x1b\[[0-9;]*m", "",  text)
    text = re.sub(r"\[[0-9]+m\]",    "",  text)
    text = re.sub(r"^\[[^\]]+\]\s*", "",  text)
    path_m = re.match(r"^[~/][^\s]+\s+(.*)", text, re.DOTALL)
    if path_m:
        text = path_m.group(1)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"www\.\S+",     "", text)
    return text.strip()

def _extract_words(text: str, max_words: int = 5) -> str:
    """Strip low-info prefix, take first sentence, return ≤max_words words."""
    lower = text.lower()
    for prefix in _STRIP_PREFIXES:
        if lower.startswith(prefix):
            text  = text[len(prefix):].lstrip()
            lower = text.lower()
            break
    for sep in ("\n", ". ", "? ", "! "):
        idx = text.find(sep)
        if 0 < idx < 120:
            text = text[:idx]
            break
    words = [w.rstrip(".,;:!?") for w in text.split() if w.rstrip(".,;:!?")]
    return " ".join(words[:max_words]).strip()

def generate_short_title(first_msg: str, summary: str = "") -> str:
    """Extract a 4–5 word title from the summary or first message."""

    # Candidate 1 — quoted goal from summary: The user asked: "..."
    cand1 = ""
    if summary:
        m = re.search(r'The user asked: "(.+?)"', summary)
        if m:
            cand1 = _extract_words(_clean_text(m.group(1)))

    # Candidate 2 — Claude's response verb phrase: "Claude responded by: ..."
    cand2 = ""
    if summary and len(cand1.split()) < 3:
        m2 = re.search(r'Claude responded by: (.+?)\.', summary)
        if m2:
            cand2 = _extract_words(_clean_text(m2.group(1)))

    # Candidate 3 — raw first message
    cand3 = _extract_words(_clean_text(first_msg))

    # Pick the longest candidate that has ≥ 3 words; otherwise longest overall
    candidates = [c for c in (cand1, cand2, cand3) if c]
    rich = [c for c in candidates if len(c.split()) >= 3]
    title = max(rich or candidates, key=lambda c: len(c.split()), default="")

    if not title:
        return "Session"
    return title[0].upper() + title[1:]

# ── Summary cache ─────────────────────────────────────────────────────────────

def load_summaries() -> dict:
    if SUMMARIES_FILE.exists():
        try:
            return json.loads(SUMMARIES_FILE.read_text())
        except Exception:
            pass
    return {}

def save_summaries(cache: dict):
    SUMMARIES_FILE.write_text(json.dumps(cache, indent=2, ensure_ascii=False))

def generate_summary(messages: list, category) -> str:
    """Build a ~100-word extractive summary from session messages."""
    user_msgs = [t for role, t, *_ in messages if role == "user"]
    asst_msgs = [t for role, t, *_ in messages if role == "assistant"]

    if not user_msgs:
        return "Session contained only system or automated messages with no user interaction."

    def first_sentence(text: str, limit: int = 120) -> str:
        for sep in (".\n", "\n\n", ".\n", ". ", "\n"):
            idx = text.find(sep)
            if 20 < idx < limit:
                return text[:idx + 1].strip()
        return text[:limit].strip()

    # What the user wanted
    goals = []
    for t in user_msgs[:4]:
        s = first_sentence(t)
        if s and len(s) > 8:
            goals.append(s)

    # What Claude did / key outcomes
    outcomes = []
    for t in asst_msgs[:3]:
        lines = [l.strip() for l in t.split("\n") if l.strip() and not l.strip().startswith("```") and len(l.strip()) > 25]
        if lines:
            outcomes.append(first_sentence(lines[0], 140))

    parts = []

    if goals:
        parts.append(f"The user asked: \"{goals[0]}\"")
    if len(goals) > 1:
        parts.append(f"Follow-up questions included: {'; '.join(goals[1:3])}.")

    if outcomes:
        parts.append(f"Claude responded by: {outcomes[0].rstrip('.')}.")
    if len(outcomes) > 1:
        parts.append(outcomes[1].rstrip(".") + ".")

    n = len(messages)
    cat_str = ", ".join(category) if isinstance(category, list) else category
    parts.append(f"The session had {n} message{'s' if n != 1 else ''} covering {cat_str.lower()} topics.")

    summary = " ".join(parts)
    words = summary.split()
    if len(words) > 105:
        summary = " ".join(words[:100]) + "..."
    return summary

def human_size(path: Path) -> str:
    b = path.stat().st_size
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.0f} {unit}" if unit == "B" else f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} GB"

# ── Scan ─────────────────────────────────────────────────────────────────────

def scan():
    projects        = {}
    summary_cache   = load_summaries()
    cache_dirty     = False

    if not PROJECTS_DIR.exists():
        return projects

    for proj_dir in sorted(PROJECTS_DIR.iterdir()):
        if not proj_dir.is_dir():
            continue
        dir_name = proj_dir.name
        sessions = []
        for jl in sorted(proj_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
            sid = jl.stem
            messages, inp_tok, out_tok = read_session(jl)
            mtime    = datetime.fromtimestamp(jl.stat().st_mtime)
            mtime_ts = int(jl.stat().st_mtime)
            first    = get_first_user(messages)
            category = infer_category(messages)
            cost_usd = (inp_tok * INPUT_COST_PER_M + out_tok * OUTPUT_COST_PER_M) / 1_000_000

            # Use cached summary if file hasn't changed, else regenerate
            cached = summary_cache.get(sid, {})
            if cached.get("mtime") == mtime_ts:
                summary = cached["summary"]
            else:
                summary = generate_summary(messages, category)
                summary_cache[sid] = {"mtime": mtime_ts, "summary": summary}
                cache_dirty = True

            short_title = generate_short_title(first, summary)
            cat_str = " ".join(category) if isinstance(category, list) else category
            search_corpus = (sid + " " + first + " " + cat_str + " " + summary + " "
                             + " ".join(t[:200] for _, t, *_ in messages[:20])).lower()
            sessions.append({
                "id":            sid,
                "short_id":      sid[:8],
                "tail_id":       sid[8:],
                "date":          mtime.strftime("%Y-%m-%d %H:%M"),
                "date_iso":      mtime.isoformat(),
                "size":          human_size(jl),
                "msg_count":     len(messages),
                "first_msg":     first,
                "short_title":   short_title,
                "category":      category,
                "summary":       summary,
                "all_messages":  get_all_messages(messages),
                "search_corpus": search_corpus,
                "resume_prefix": project_resume_prefix(dir_name),
                "file_path":     str(jl),
                "input_tokens":  inp_tok,
                "output_tokens": out_tok,
                "total_tokens":  inp_tok + out_tok,
                "cost_usd":      cost_usd,
            })
        if sessions:
            projects[dir_name] = sessions

    if cache_dirty:
        save_summaries(summary_cache)

    return projects

# ── Font ─────────────────────────────────────────────────────────────────────

# Subset CDN link — only the icons actually used (~15 KB vs 3.8 MB full font)
_FONT_ICONS = ",".join(sorted([
    "arrow_forward", "bar_chart", "chat_bubble", "check", "close",
    "close_fullscreen", "content_copy", "dark_mode", "download",
    "drag_indicator", "expand_less", "expand_more", "folder_open", "history",
    "inventory_2", "keyboard", "light_mode", "more_vert", "open_in_full",
    "restore", "search", "star", "summarize", "terminal", "tune", "unfold_more",
    "upload", "view_column",
]))
FONT_LINK = (
    '<link rel="preconnect" href="https://fonts.googleapis.com"/>'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2'
    f'?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200'
    f'&display=swap&icon_names={_FONT_ICONS}"/>'
)

# ── HTML generation ───────────────────────────────────────────────────────────

TAG_CLASSES = {
    "Figma":      "tag-figma",
    "VS Code":    "tag-vscode",
    "Git":        "tag-git",
    "Slack":      "tag-slack",
    "Setup":      "tag-setup",
    "General":    "tag-general",
    "System":     "tag-system",
    "Python":     "tag-python",
    "JavaScript": "tag-js",
    "CSS":        "tag-css",
    "Database":   "tag-db",
    "Docker":     "tag-docker",
    "API":        "tag-api",
    "Testing":    "tag-testing",
    "Shell":      "tag-shell",
}

def fmt_tokens(n: int) -> str:
    if not n:           return "—"
    if n >= 1_000_000:  return f"{n/1_000_000:.1f}M"
    if n >= 1_000:      return f"{n/1_000:.1f}K"
    return str(n)

def fmt_cost(c: float) -> str:
    if c == 0:    return "—"
    if c < 0.001: return "<$0.001"
    return f"${c:.3f}"

def esc(s: str) -> str:
    return (str(s).replace("&", "&amp;")
                  .replace("<", "&lt;")
                  .replace(">", "&gt;")
                  .replace('"', "&quot;"))

def render_table(sessions: list, proj_dir: str) -> str:
    rows = []
    for i, s in enumerate(sessions, 1):
        resume_cmd = f"{s['resume_prefix']}claude --resume {s['id']}"
        cats       = s["category"] if isinstance(s["category"], list) else [s["category"]]
        data_cat   = esc(",".join(cats))
        cat_pills  = '<div class="cat-pills">' + " ".join(
            f'<span class="cat-pill cp-{c.lower().replace(" ","").replace(".","")}">{esc(c)}</span>'
            for c in cats
        ) + '</div>'
        corpus_esc = esc(s["search_corpus"].replace('"', ""))
        first_sub  = esc(s['first_msg'][:80])
        rows.append(f"""
          <tr data-id="{s['id']}" data-search="{corpus_esc}" data-date="{s['date_iso']}" data-msgs="{s['msg_count']}" data-tokens="{s['total_tokens']}" data-cost="{s['cost_usd']:.6f}" data-cat="{data_cat}">
            <td class="col-check"><input type="checkbox" class="row-check" id="chk-{s['id']}" onchange="toggleRowCheck('{s['id']}')"></td>
            <td class="num col-num">{i}</td>
            <td class="col-star"><button class="star-btn" id="star-{s['id']}" onclick="toggleStar('{s['id']}')"><span class="mi">star</span></button></td>
            <td class="col-label"><span class="label-dot" id="ldot-{s['id']}" onclick="openLabelPicker('{s['id']}', this)" title="Set label"></span></td>
            <td class="title-cell col-title" data-id="{s['id']}">
              <div class="title-main"><span class="title-display" onclick="editTitle('{s['id']}', this)">Add title...</span></div>
              <div class="title-sub col-topic">{first_sub}</div>
              <div class="title-id">{esc(s['short_id'])}</div>
              <button id="copybtn-{s['id']}" class="copy-resume-btn" onclick="copyResume('{s['id']}')" title="{esc(resume_cmd)}"><span class="mi mi-xs">arrow_forward</span> Copy resume cmd</button>
            </td>
            <td class="col-notes"><span class="notes-disp" id="notes-{s['id']}" onclick="editNotes('{s['id']}', this)">+</span></td>
            <td class="col-summary"><button class="sum-btn" onclick="openSummary('{s['id']}')"><span class="mi mi-sm">summarize</span> Summary</button></td>
            <td class="col-cat">{cat_pills}</td>
            <td class="date col-date" title="{esc(s['date'])}" data-iso="{esc(s['date_iso'])}"></td>
            <td class="size col-size">{esc(s['size'])}</td>
            <td class="msgs col-msgs">{s['msg_count']}</td>
            <td class="tok col-tok" title="Input: {s['input_tokens']:,}&#10;Output: {s['output_tokens']:,}">{fmt_tokens(s['total_tokens'])}</td>
            <td class="cost-cell col-cost">{fmt_cost(s['cost_usd'])}</td>
            <td class="col-menu">
              <div class="row-menu-wrap">
                <button class="row-menu-btn" onclick="toggleRowMenu(this)"><span class="mi" style="font-size:20px">more_vert</span></button>
                <div class="row-menu-dropdown">
                  <button onclick="openModal('{s['id']}');closeRowMenus()"><span class="mi mi-sm">chat_bubble</span> View Chat</button>
                  <button onclick="archiveSession('{s['id']}');closeRowMenus()"><span class="mi mi-sm">inventory_2</span> Archive</button>
                </div>
              </div>
            </td>
          </tr>""")

    return f"""
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th class="col-check"><input type="checkbox" id="select-all" onclick="toggleSelectAll()" title="Select all"></th>
            <th class="col-num sortable" onclick="sortBy('num',this)" title="Sort by row number"># <span class="sort-icon">unfold_more</span></th>
            <th class="col-star sortable" onclick="sortBy('star',this)" title="Sort by starred"><span class="mi mi-sm">star</span><span class="sort-icon">unfold_more</span></th>
            <th class="col-label">Label</th>
            <th class="col-title sortable" onclick="sortBy('title',this)">Title <span class="sort-icon">unfold_more</span></th>
            <th class="col-notes">Notes</th>
            <th class="col-summary">Summary</th>
            <th class="col-cat sortable" onclick="sortBy('cat',this)">Cat <span class="sort-icon">unfold_more</span></th>
            <th class="col-date sortable" onclick="sortBy('date',this)">Date <span class="sort-icon">unfold_more</span></th>
            <th class="col-size">Size</th>
            <th class="col-msgs sortable" onclick="sortBy('msgs',this)">Msgs <span class="sort-icon">unfold_more</span></th>
            <th class="col-tok sortable" onclick="sortBy('tokens',this)" title="Hover rows for breakdown">Tokens <span class="sort-icon">unfold_more</span></th>
            <th class="col-cost sortable" onclick="sortBy('cost',this)">Cost <span class="sort-icon">unfold_more</span></th>
            <th class="col-menu">Actions</th>
          </tr>
        </thead>
        <tbody>{''.join(rows)}
        </tbody>
      </table>
    </div>"""

def render_session_data(projects: dict) -> str:
    entries = []
    for sessions in projects.values():
        for s in sessions:
            resume_cmd = f"{s['resume_prefix']}claude --resume {s['id']}"
            entries.append(
                f"'{esc(s['id'])}': {{"
                f"title: {json.dumps(s['first_msg'][:120])},"
                f"short_title: {json.dumps(s['short_title'])},"
                f"meta: {json.dumps(s['id'] + ' · ' + s['date'] + ' · ' + str(s['msg_count']) + ' msgs · ' + fmt_tokens(s['total_tokens']) + ' tokens · ' + fmt_cost(s['cost_usd']))},"
                f"resume: {json.dumps(resume_cmd)},"
                f"summary: {json.dumps(s['summary'])},"
                f"category: {json.dumps(','.join(s['category']) if isinstance(s['category'], list) else s['category'])},"
                f"messages: {json.dumps(s['all_messages'])},"
                f"date_iso: {json.dumps(s['date_iso'])},"
                f"input_tokens: {s['input_tokens']},"
                f"output_tokens: {s['output_tokens']},"
                f"total_tokens: {s['total_tokens']},"
                f"cost_usd: {s['cost_usd']:.6f}"
                f"}}"
            )
    return "{\n" + ",\n".join(entries) + "\n}"

def build_html(projects: dict) -> str:
    total     = sum(len(v) for v in projects.values())
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ── Stats ─────────────────────────────────────────────────────────────────
    all_s         = [s for slist in projects.values() for s in slist]
    total_msgs    = sum(s["msg_count"]     for s in all_s)
    total_inp_tok = sum(s["input_tokens"]  for s in all_s)
    total_out_tok = sum(s["output_tokens"] for s in all_s)
    total_tokens  = total_inp_tok + total_out_tok
    total_cost    = sum(s["cost_usd"]      for s in all_s)
    week_ago      = datetime.now() - timedelta(days=7)
    this_week     = sum(1 for s in all_s
                        if datetime.strptime(s["date"], "%Y-%m-%d %H:%M") > week_ago)
    most_active   = max(projects.items(), key=lambda x: len(x[1]))[0] if projects else ""
    top_proj      = project_short(most_active) if most_active else "—"
    avg_msgs      = round(total_msgs / total) if total else 0
    dow_counts    = [0] * 7
    for s in all_s:
        try:
            dow_counts[datetime.strptime(s["date"], "%Y-%m-%d %H:%M").weekday()] += 1
        except Exception:
            pass
    day_names   = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    busiest_day = day_names[dow_counts.index(max(dow_counts))] if any(dow_counts) else "—"

    # ── Heatmap & sparkline data ──────────────────────────────────────────────
    day_counts: dict = {}
    for s in all_s:
        try:
            d   = datetime.strptime(s["date"], "%Y-%m-%d %H:%M").date()
            key = d.isoformat()
            day_counts[key] = day_counts.get(key, 0) + 1
        except Exception:
            pass
    today_d = datetime.now().date()
    sparkline = []
    for w in range(11, -1, -1):
        wstart = today_d - timedelta(days=today_d.weekday() + 7 * w)
        wend   = wstart + timedelta(days=6)
        cnt    = sum(1 for s in all_s
                     if wstart <= datetime.strptime(s["date"], "%Y-%m-%d %H:%M").date() <= wend)
        sparkline.append(cnt)
    heatmap_data_json = json.dumps(day_counts)
    sparkline_json    = json.dumps(sparkline)

    today_count    = sum(1 for s in all_s if s["date"][:10] == datetime.now().strftime("%Y-%m-%d"))
    total_projects = len(projects)

    # ── Per-project breakdown ─────────────────────────────────────────────────
    proj_rows_html = []
    for dir_name, slist in projects.items():
        short_p = project_short(dir_name)
        plabel  = project_label(dir_name)
        pcount  = len(slist)
        pmsgs   = sum(s["msg_count"]    for s in slist)
        ptok    = sum(s["total_tokens"] for s in slist)
        pcost   = sum(s["cost_usd"]     for s in slist)
        proj_rows_html.append(
            f'<tr><td class="proj-b-name" title="{esc(plabel)}">{esc(short_p)}</td>'
            f'<td class="proj-b-num">{pcount}</td>'
            f'<td class="proj-b-num">{pmsgs:,}</td>'
            f'<td class="proj-b-num">{fmt_tokens(ptok)}</td>'
            f'<td class="proj-b-num">{fmt_cost(pcost)}</td></tr>'
        )
    proj_breakdown_html = '\n'.join(proj_rows_html)

    sub_tabs = [
        '<div class="sub-tab active" data-tab="recent" onclick="showTab(\'recent\')">'
        '<span class="mi mi-sm">history</span> Recent'
        '<span class="sub-tab-badge" id="nb-recent">0</span></div>'
    ]
    pages = ['<div class="page active" id="page-recent"></div>']

    for idx, (dir_name, sessions) in enumerate(projects.items()):
        tab_id = re.sub(r"[^a-z0-9]", "", dir_name.lower())
        short  = project_short(dir_name)
        sub_tabs.append(
            f'<div class="sub-tab" data-tab="{tab_id}" onclick="showTab(\'{tab_id}\')">'
            f'<span class="mi mi-sm">folder_open</span> {esc(short)}'
            f'<span class="sub-tab-badge" id="nb-{tab_id}">{len(sessions)}</span></div>'
        )
        pages.append(f"""
  <div class="page" id="page-{tab_id}">
    <div class="project-path">~/.claude/projects/{esc(dir_name)}/</div>
    {render_table(sessions, dir_name)}
  </div>""")

    sub_tabs.append(
        '<div class="sub-tab" data-tab="archived" onclick="showTab(\'archived\')">'
        '<span class="mi mi-sm">inventory_2</span> Archived'
        '<span class="sub-tab-badge" id="nb-archived">0</span></div>'
    )
    pages.append('<div class="page" id="page-archived"></div>')

    session_data = render_session_data(projects).replace("</", "<\\/")  # prevent premature </script> closing

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Claude Code Sessions</title>
  {FONT_LINK}
  <style>
    /* ── Design Tokens ──────────────────────────────────────────────────── */
    :root {{
      /* New aesthetic */
      --sidebar-bg:#ffffff; --main-bg:#f0f2f6; --card-bg:#ffffff;
      --teal:#0d9488; --teal-dim:#e6f7f5; --teal-text:#0f766e;
      --text:#1a1a2e; --text-2:#6b7280; --text-3:#9ca3af;
      --border:#e5e7eb; --border-2:#d1d5db;
      --shadow:0 2px 12px rgba(0,0,0,.06);
      --card-peach:#fff7ed; --card-peach-b:#fed7aa; --card-peach-text:#c2410c;
      --card-mint:#f0fdf4;  --card-mint-b:#bbf7d0;  --card-mint-text:#065f46;
      --card-lavender:#f5f3ff; --card-lavender-b:#ddd6fe; --card-lavender-text:#6d28d9;
      --card-sky:#eff6ff;   --card-sky-b:#bfdbfe;   --card-sky-text:#1d4ed8;
      /* Legacy aliases — keep existing CSS rules working */
      --bg:var(--main-bg); --surface:var(--card-bg); --surface-2:#f9fafb; --surface-3:#f3f4f6;
      --primary:var(--teal); --primary-dim:var(--teal-dim);
      --success:#059669; --success-dim:#d1fae5;
      --warning:#d97706; --danger:#dc2626; --danger-dim:#fee2e2;
      --radius:12px; --radius-sm:8px;
    }}
    body.dark {{
      --sidebar-bg:#111827; --main-bg:#0f1117; --card-bg:#1f2937;
      --teal:#2dd4bf; --teal-dim:#0d2926; --teal-text:#2dd4bf;
      --text:#f9fafb; --text-2:#9ca3af; --text-3:#4b5563;
      --border:#374151; --border-2:#4b5563;
      --shadow:0 2px 12px rgba(0,0,0,.35);
      --card-peach:#2d1f0e; --card-peach-b:#92400e; --card-peach-text:#fb923c;
      --card-mint:#0d2016;  --card-mint-b:#065f46;  --card-mint-text:#34d399;
      --card-lavender:#1e1b3a; --card-lavender-b:#4c1d95; --card-lavender-text:#a78bfa;
      --card-sky:#0c1a2e;   --card-sky-b:#1e40af;   --card-sky-text:#60a5fa;
      --bg:var(--main-bg); --surface:var(--card-bg); --surface-2:#374151; --surface-3:#1f2937;
      --primary:var(--teal); --primary-dim:var(--teal-dim);
      --success:#34d399; --success-dim:#064e3b;
      --danger:#f87171; --danger-dim:#2a0e0e;
    }}

    /* ── Reset & Base ───────────────────────────────────────────────────── */
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:var(--main-bg);color:var(--text);min-height:100vh;display:flex;overflow:hidden}}

    /* ── Sidebar ────────────────────────────────────────────────────────── */
    .sidebar{{width:220px;flex-shrink:0;height:100vh;position:sticky;top:0;overflow-y:auto;background:var(--sidebar-bg);border-right:1px solid var(--border);display:flex;flex-direction:column}}
    .sidebar-logo{{padding:22px 20px 18px;display:flex;align-items:center;gap:9px;border-bottom:1px solid var(--border)}}
    .sidebar-logo-icon{{width:30px;height:30px;background:var(--teal);border-radius:8px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:14px;flex-shrink:0}}
    .sidebar-logo-text{{font-size:15px;font-weight:800;color:var(--text);letter-spacing:-.3px}}
    .sidebar-nav{{padding:12px 10px;flex:1}}
    .nav-section-label{{font-size:10px;color:var(--text-3);text-transform:uppercase;letter-spacing:.8px;font-weight:600;padding:12px 10px 6px}}
    .nav-item{{display:flex;align-items:center;gap:9px;padding:9px 10px;border-radius:10px;cursor:pointer;color:var(--text-2);font-size:13px;font-weight:500;transition:all .15s;user-select:none;position:relative}}
    .nav-item:hover{{background:var(--teal-dim);color:var(--teal-text)}}
    .nav-item.active{{background:var(--teal-dim);color:var(--teal);font-weight:600}}
    .nav-icon{{font-size:15px;flex-shrink:0;width:18px;text-align:center}}
    .nav-badge{{background:var(--teal);color:#fff;font-size:10px;font-weight:700;padding:1px 7px;border-radius:99px;margin-left:auto;line-height:1.5}}
    .nav-item.active .nav-badge{{background:var(--teal)}}
    .nav-item.nav-dim{{opacity:.35}}
    .sidebar-bottom{{padding:14px 10px;border-top:1px solid var(--border);display:flex;flex-direction:column;gap:4px}}

    /* ── Main Area ──────────────────────────────────────────────────────── */
    .main-area{{flex:1;min-width:0;height:100vh;overflow-y:auto;display:flex;flex-direction:column}}

    /* ── Welcome Header ─────────────────────────────────────────────────── */
    .welcome-header{{padding:28px 28px 20px;display:flex;align-items:flex-start;justify-content:space-between;flex-wrap:wrap;gap:12px;flex-shrink:0}}
    .welcome-h1{{font-size:26px;font-weight:800;color:var(--text);letter-spacing:-.5px;line-height:1.2}}
    .welcome-sub{{font-size:13px;color:var(--text-2);margin-top:4px}}
    .welcome-actions{{display:flex;align-items:center;gap:8px;flex-wrap:wrap}}
    .search-wrap{{position:relative;display:flex;align-items:center}}
    .search-wrap .search-icon{{position:absolute;left:11px;color:var(--text-3);font-size:14px;pointer-events:none}}
    .search-input{{width:240px;background:var(--card-bg);border:1px solid var(--border);border-radius:var(--radius-sm);padding:8px 72px 8px 32px;color:var(--text);font-size:13px;outline:none;transition:border-color .15s;box-shadow:var(--shadow)}}
    .search-input:focus{{border-color:var(--teal)}}
    .search-input::placeholder{{color:var(--text-3)}}
    .search-clear{{position:absolute;right:46px;background:none;border:none;color:var(--text-3);cursor:pointer;font-size:13px;line-height:1;padding:2px 5px;border-radius:4px;display:none;transition:color .15s}}
    .search-clear:hover{{color:var(--text)}}
    .search-clear.visible{{display:block}}
    .search-count{{position:absolute;right:10px;font-size:11px;color:var(--text-3);white-space:nowrap}}
    .icon-btn{{background:var(--card-bg);border:1px solid var(--border);color:var(--text-2);font-size:12px;padding:7px 13px;border-radius:var(--radius-sm);cursor:pointer;transition:all .15s;white-space:nowrap;box-shadow:var(--shadow)}}
    .icon-btn:hover{{border-color:var(--teal);color:var(--teal)}}

    /* ── Stats Bar ──────────────────────────────────────────────────────── */
    .stats-bar{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;padding:0 28px 20px;flex-shrink:0}}
    .stats-bar-secondary{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;padding:0 28px 20px;flex-shrink:0}}
    .stat-card{{border-radius:16px;padding:20px 22px;box-shadow:var(--shadow);border:1px solid var(--border);background:var(--card-bg);transition:transform .15s,box-shadow .15s}}
    .stat-card:hover{{transform:translateY(-2px);box-shadow:0 6px 20px rgba(0,0,0,.1)}}
    .stat-card.card-peach{{background:var(--card-peach);border-color:var(--card-peach-b)}}
    .stat-card.card-mint{{background:var(--card-mint);border-color:var(--card-mint-b)}}
    .stat-card.card-lavender{{background:var(--card-lavender);border-color:var(--card-lavender-b)}}
    .stat-card.card-sky{{background:var(--card-sky);border-color:var(--card-sky-b)}}
    .stat-card.card-sm{{border-radius:12px;padding:14px 16px}}
    .stat-value{{font-size:28px;font-weight:800;color:var(--text);line-height:1.1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
    .stat-card.card-peach .stat-value{{color:var(--card-peach-text)}}
    .stat-card.card-mint .stat-value{{color:var(--card-mint-text)}}
    .stat-card.card-lavender .stat-value{{color:var(--card-lavender-text)}}
    .stat-card.card-sky .stat-value{{color:var(--card-sky-text)}}
    .stat-card.card-sm .stat-value{{font-size:18px;font-weight:700}}
    .stat-label{{font-size:11px;color:var(--text-2);margin-top:6px;text-transform:uppercase;letter-spacing:.5px;font-weight:500}}

    /* ── Heatmap Hero Card ──────────────────────────────────────────────── */
    .heatmap-card{{background:var(--teal);border-radius:16px;padding:22px 26px;margin:0 28px 20px;box-shadow:0 4px 24px rgba(13,148,136,.3);flex-shrink:0;transition:padding .2s;position:relative;overflow:hidden}}
    .heatmap-card::before{{content:'';position:absolute;inset:0;background:linear-gradient(135deg,rgba(255,255,255,.08) 0%,transparent 60%);pointer-events:none}}
    body.dark .heatmap-card{{background:var(--card-bg);border:1px solid var(--teal);box-shadow:none}}
    .heatmap-section{{position:relative;z-index:1}}
    .heatmap-section.collapsed .heatmap-body{{display:none}}
    .heatmap-toggle{{background:rgba(255,255,255,.2);border:none;color:#fff;cursor:pointer;font-size:11px;padding:3px 8px;border-radius:6px;transition:background .15s;line-height:1}}
    .heatmap-toggle:hover{{background:rgba(255,255,255,.3)}}
    body.dark .heatmap-toggle{{background:var(--surface-2);color:var(--text-3)}}
    body.dark .heatmap-toggle:hover{{color:var(--text)}}
    .heatmap-top{{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;flex-wrap:wrap;gap:8px}}
    .heatmap-heading{{font-size:12px;color:rgba(255,255,255,.8);text-transform:uppercase;letter-spacing:.5px;font-weight:600}}
    body.dark .heatmap-heading{{color:var(--text-2)}}
    .sparkline-wrap{{display:flex;align-items:flex-end;gap:2px;height:28px}}
    .sparkline-bar{{width:10px;border-radius:2px 2px 0 0;background:rgba(255,255,255,.3);min-height:2px;cursor:default;transition:background .12s}}
    .sparkline-bar:hover{{background:rgba(255,255,255,.85)}}
    body.dark .sparkline-bar{{background:var(--teal-dim)}}
    body.dark .sparkline-bar:hover{{background:var(--teal)}}
    .heatmap-months{{display:flex;gap:2px;margin-bottom:3px}}
    .heatmap-month-label{{font-size:9px;color:rgba(255,255,255,.6);white-space:nowrap;overflow:hidden;width:13px}}
    body.dark .heatmap-month-label{{color:var(--text-3)}}
    .heatmap-grid{{display:flex;gap:2px}}
    .heatmap-col{{display:flex;flex-direction:column;gap:2px}}
    .heatmap-day{{width:11px;height:11px;border-radius:2px;cursor:default;flex-shrink:0}}
    .heatmap-day.lv-0{{background:rgba(255,255,255,.12)}}
    .heatmap-day.lv-1{{background:rgba(255,255,255,.3)}}
    .heatmap-day.lv-2{{background:rgba(255,255,255,.5)}}
    .heatmap-day.lv-3{{background:rgba(255,255,255,.72)}}
    .heatmap-day.lv-4{{background:rgba(255,255,255,.92)}}
    .heatmap-day.future{{background:rgba(255,255,255,.06)}}
    body.dark .heatmap-day.lv-0{{background:rgba(45,212,191,.08)}}
    body.dark .heatmap-day.lv-1{{background:rgba(45,212,191,.25)}}
    body.dark .heatmap-day.lv-2{{background:rgba(45,212,191,.45)}}
    body.dark .heatmap-day.lv-3{{background:rgba(45,212,191,.68)}}
    body.dark .heatmap-day.lv-4{{background:var(--teal)}}
    body.dark .heatmap-day.future{{background:rgba(45,212,191,.05)}}

    /* ── Bulk Bar ───────────────────────────────────────────────────────── */
    .bulk-bar{{display:flex;align-items:center;gap:8px;padding:9px 28px;background:var(--teal-dim);border-bottom:1px solid var(--border);flex-wrap:wrap;flex-shrink:0}}
    .bulk-count{{font-size:12px;color:var(--primary);font-weight:600;white-space:nowrap;margin-right:4px}}
    .bulk-btn{{font-size:11px;padding:5px 12px;border-radius:var(--radius-sm);cursor:pointer;white-space:nowrap;transition:all .15s;border:1px solid transparent}}
    .bulk-arch{{background:var(--surface-2);border-color:var(--border);color:var(--text-2)}}
    .bulk-arch:hover{{border-color:var(--primary);color:var(--primary)}}
    .bulk-export{{background:var(--success-dim);border-color:var(--success);color:var(--success)}}
    .bulk-export:hover{{opacity:.8}}
    .bulk-clr{{background:none;border-color:var(--border);color:var(--text-3)}}
    .bulk-clr:hover{{color:var(--text);border-color:var(--border-2)}}
    .bulk-label-row{{display:flex;align-items:center;gap:6px}}
    .bulk-label-row > span{{font-size:11px;color:var(--text-3)}}
    .bulk-sep{{width:1px;height:18px;background:var(--border-2);flex-shrink:0}}

    /* ── Main Toolbar (filter chips row) ───────────────────────────────── */
    .main-toolbar{{display:flex;align-items:center;gap:8px;padding:0 28px 14px;flex-wrap:wrap;flex-shrink:0}}

    /* ── Filter chips row ───────────────────────────────────────────────── */
    .filter-chips-row{{display:flex;flex-wrap:wrap;gap:4px;align-items:center}}
    .filter-chip{{display:inline-flex;align-items:center;gap:4px;padding:3px 8px;background:var(--primary-dim);color:var(--primary);border-radius:99px;font-size:11px}}
    .filter-chip button{{background:none;border:none;color:var(--primary);cursor:pointer;font-size:11px;padding:0;line-height:1;opacity:.7}}
    .filter-chip button:hover{{opacity:1}}

    /* ── Filter Panel (popover) ─────────────────────────────────────────── */
    .filter-wrap{{position:relative;display:inline-block}}
    .filter-btn{{background:var(--surface-2);border:1px solid var(--border);color:var(--text-2);font-size:12px;padding:6px 12px;border-radius:var(--radius-sm);cursor:pointer;transition:all .15s;white-space:nowrap;display:flex;align-items:center;gap:6px}}
    .filter-btn:hover{{border-color:var(--primary);color:var(--primary)}}
    .filter-badge{{background:var(--primary);color:#fff;font-size:10px;font-weight:700;padding:1px 5px;border-radius:99px;line-height:1.4}}
    .filter-panel{{position:absolute;top:calc(100% + 8px);right:0;width:340px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:20px;box-shadow:0 16px 48px rgba(0,0,0,.6);z-index:40;display:none}}
    .filter-panel.open{{display:block}}
    .filter-group{{margin-bottom:16px}}
    .filter-group:last-child{{margin-bottom:0}}
    .filter-group-label{{font-size:10px;color:var(--text-2);text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px;font-weight:600}}
    .filter-quick-btns{{display:flex;gap:6px;margin-bottom:8px;flex-wrap:wrap}}
    .fq-btn{{background:var(--surface-2);border:1px solid var(--border);color:var(--text-2);font-size:11px;padding:4px 10px;border-radius:var(--radius-sm);cursor:pointer;transition:all .15s}}
    .fq-btn:hover{{border-color:var(--primary);color:var(--primary)}}
    .filter-date-row{{display:flex;align-items:center;gap:8px}}
    .filter-date{{background:var(--surface-2);border:1px solid var(--border);color:var(--text);font-size:12px;padding:5px 10px;border-radius:var(--radius-sm);outline:none;cursor:pointer;color-scheme:dark;flex:1}}
    .filter-date:focus{{border-color:var(--primary)}}
    body.light .filter-date{{color-scheme:light}}
    .filter-sep{{color:var(--text-3);font-size:12px}}
    .filter-cat-grid{{display:grid;grid-template-columns:1fr 1fr;gap:4px}}
    .filter-cat-lbl{{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text-2);cursor:pointer;padding:4px 6px;border-radius:var(--radius-sm);transition:background .12s;user-select:none}}
    .filter-cat-lbl:hover{{background:var(--surface-2)}}
    .filter-cat-lbl input{{accent-color:var(--primary);cursor:pointer}}
    .filter-status-lbl{{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text-2);cursor:pointer;padding:4px 6px;border-radius:var(--radius-sm);transition:background .12s;user-select:none;margin-bottom:4px}}
    .filter-status-lbl:hover{{background:var(--surface-2)}}
    .filter-status-lbl input{{accent-color:var(--primary);cursor:pointer}}
    .filter-footer{{display:flex;align-items:center;justify-content:space-between;padding-top:12px;border-top:1px solid var(--border);margin-top:4px}}
    .filter-reset-btn{{background:none;border:none;color:var(--danger);font-size:12px;cursor:pointer;padding:4px 8px;border-radius:var(--radius-sm);transition:background .15s}}
    .filter-reset-btn:hover{{background:var(--danger-dim)}}
    .filter-cnt{{font-size:12px;color:var(--text-3);white-space:nowrap}}

    /* ── Actions Menu ───────────────────────────────────────────────────── */
    .actions-wrap{{position:relative;display:inline-block}}
    .actions-menu{{display:none;position:absolute;top:calc(100% + 6px);right:0;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:8px;z-index:200;min-width:180px;box-shadow:0 12px 32px rgba(0,0,0,.5)}}
    .actions-menu.open{{display:block}}
    .actions-menu button,.actions-menu label{{display:flex;align-items:center;gap:8px;width:100%;font-size:12px;color:var(--text-2);cursor:pointer;padding:8px 10px;border-radius:var(--radius-sm);background:none;border:none;text-align:left;transition:background .12s,color .12s}}
    .actions-menu button:hover,.actions-menu label:hover{{background:var(--surface-2);color:var(--text)}}

    /* ── Column Visibility ──────────────────────────────────────────────── */
    .col-vis-wrap{{position:relative;display:inline-block}}
    .col-vis-menu{{display:none;position:absolute;top:calc(100% + 6px);right:0;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:12px;z-index:200;min-width:180px;box-shadow:0 12px 32px rgba(0,0,0,.5)}}
    .col-vis-menu.open{{display:block}}
    .col-vis-menu label{{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--text-2);cursor:pointer;padding:5px 6px;border-radius:6px;user-select:none;transition:background .12s}}
    .col-vis-menu label:hover{{color:var(--text);background:var(--surface-2)}}
    .col-vis-menu input[type=checkbox]{{accent-color:var(--primary);cursor:pointer}}
    .col-drag-handle{{font-size:16px;color:var(--text-3);cursor:grab;margin-right:-4px;flex-shrink:0}}
    .col-drag-handle:active{{cursor:grabbing}}
    .col-vis-menu label.col-dragging{{opacity:.4}}
    .col-vis-menu label.col-drag-over{{background:var(--teal-dim);color:var(--teal-text)}}

    /* ── Column hide classes ────────────────────────────────────────────── */
    body.hide-col-title .col-title{{display:none}}body.hide-col-star .col-star{{display:none}}body.hide-col-label .col-label{{display:none}}
    body.hide-col-notes .col-notes{{display:none}}body.hide-col-topic .col-topic{{display:none}}
    body.hide-col-cat .col-cat{{display:none}}body.hide-col-size .col-size{{display:none}}
    body.hide-col-msgs .col-msgs{{display:none}}body.hide-col-tok .col-tok{{display:none}}
    body.hide-col-cost .col-cost{{display:none}}body.hide-col-date .col-date{{display:none}}body.hide-col-summary .col-summary{{display:none}}

    /* ── Page layout ────────────────────────────────────────────────────── */
    .page-content{{padding:0 28px 28px;flex:1}}
    .page{{display:none}}.page.active{{display:block}}
    .project-path{{font-size:11px;color:var(--text-3);font-family:"SF Mono",monospace;margin:0 0 14px;padding:5px 10px;background:var(--card-bg);border:1px solid var(--border);border-radius:var(--radius-sm);display:inline-block}}

    /* ── Table ──────────────────────────────────────────────────────────── */
    .table-wrap{{overflow-x:auto;overflow-y:auto;max-height:calc(100vh - 320px);border-radius:var(--radius);border:1px solid var(--border);background:var(--card-bg);box-shadow:var(--shadow)}}
    table{{width:100%;border-collapse:collapse;font-size:13px}}
    thead tr{{border-bottom:1px solid var(--border)}}
    thead th{{text-align:left;padding:11px 16px;font-weight:600;color:var(--text-3);white-space:nowrap;font-size:10px;text-transform:uppercase;letter-spacing:.6px;position:sticky;top:0;z-index:2;background:var(--card-bg)}}
    tbody tr{{border-bottom:1px solid var(--border);transition:background .12s}}
    tbody tr:last-child{{border-bottom:none}}
    tbody tr:hover{{background:var(--teal-dim)}}
    tbody tr:hover .copy-resume-btn{{opacity:1}}
    td{{padding:12px 16px;vertical-align:middle}}
    .num{{color:var(--text-3);font-size:12px}}
    .session-id{{font-family:"SF Mono","Fira Code",monospace;font-size:11px;color:var(--primary);white-space:nowrap}}
    .session-id span{{color:var(--text-3)}}
    .topic{{color:var(--text-2);line-height:1.5;max-width:240px;font-size:12px}}
    .date{{white-space:nowrap;color:var(--text-2);font-size:12px}}
    .size{{white-space:nowrap;color:var(--text-3);font-size:12px}}
    .msgs{{text-align:center;color:var(--text-2);font-size:12px}}

    /* Title cell two-line layout */
    .title-cell{{min-width:180px;max-width:260px}}
    .title-main{{margin-bottom:2px}}
    .title-sub{{font-size:11px;color:var(--text-3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:240px;line-height:1.4}}
    .title-id{{font-family:"SF Mono","Fira Code",monospace;font-size:10px;color:var(--text-3);margin-top:1px;line-height:1}}
    .title-display{{color:var(--text-2);font-size:12.5px;cursor:pointer;border-radius:4px;padding:2px 5px;margin:-2px -5px;transition:background .15s,color .15s;display:inline-block;line-height:1.4}}
    .title-display:hover{{background:var(--surface-3);color:var(--text)}}
    .title-display.has-title{{color:var(--text);font-weight:500}}
    .title-display.placeholder{{color:var(--text-3);font-style:italic}}
    .title-display.auto-title{{color:var(--text-2);font-style:normal}}
    .title-input{{background:var(--surface-2);border:1px solid var(--primary);border-radius:var(--radius-sm);color:var(--text);font-size:12.5px;padding:4px 8px;outline:none;width:100%;max-width:220px}}

    /* Category pills */
    .col-cat{{min-width:80px;max-width:220px}}
    .cat-pills{{display:flex;flex-wrap:wrap;gap:3px;align-items:center}}
    .cat-pill{{display:inline-flex;align-items:center;padding:3px 10px;border-radius:99px;font-size:11px;font-weight:600;white-space:nowrap}}
    .cp-figma{{background:#ede9fe;color:#6d28d9}}
    .cp-vscode{{background:#dbeafe;color:#1d4ed8}}
    .cp-git{{background:#ffedd5;color:#c2410c}}
    .cp-slack{{background:#fce7f3;color:#be185d}}
    .cp-setup{{background:#d1fae5;color:#065f46}}
    .cp-general{{background:#f3f4f6;color:#374151}}
    .cp-system{{background:#fef9c3;color:#92400e}}
    body.dark .cp-figma{{background:#2e1065;color:#c4b5fd}}
    body.dark .cp-vscode{{background:#1e3a5f;color:#93c5fd}}
    body.dark .cp-git{{background:#431407;color:#fb923c}}
    body.dark .cp-slack{{background:#500724;color:#f9a8d4}}
    body.dark .cp-setup{{background:#064e3b;color:#6ee7b7}}
    body.dark .cp-general{{background:#374151;color:#d1d5db}}
    body.dark .cp-system{{background:#422006;color:#fcd34d}}
    .cp-python{{background:#dcfce7;color:#166534}}.cp-javascript{{background:#fefce8;color:#854d0e}}
    .cp-js{{background:#fefce8;color:#854d0e}}
    .cp-css{{background:#fdf4ff;color:#7e22ce}}.cp-database{{background:#e0f2fe;color:#0369a1}}
    .cp-docker{{background:#ecfeff;color:#0e7490}}.cp-api{{background:#f0fdfa;color:#0f766e}}
    .cp-testing{{background:#fff7ed;color:#c2410c}}.cp-shell{{background:#f1f5f9;color:#334155}}
    body.dark .cp-python{{background:#14532d;color:#86efac}}
    body.dark .cp-javascript{{background:#422006;color:#fcd34d}}
    body.dark .cp-js{{background:#422006;color:#fcd34d}}
    body.dark .cp-css{{background:#3b0764;color:#d8b4fe}}
    body.dark .cp-database{{background:#0c4a6e;color:#7dd3fc}}
    body.dark .cp-docker{{background:#083344;color:#67e8f9}}
    body.dark .cp-api{{background:#022c22;color:#5eead4}}
    body.dark .cp-testing{{background:#431407;color:#fb923c}}
    body.dark .cp-shell{{background:#1e293b;color:#94a3b8}}

    /* Action cell — hidden until row hover */
    /* Copy resume button — lives under title, visible on row hover */
    .copy-resume-btn{{display:inline-flex;align-items:center;gap:3px;margin-top:5px;font-size:11px;padding:3px 7px;background:var(--surface-2);border:1px solid var(--border);color:var(--text-3);border-radius:var(--radius-sm);cursor:pointer;transition:all .15s;white-space:nowrap;opacity:0}}
    .copy-resume-btn:hover{{background:var(--primary-dim);border-color:var(--primary);color:var(--primary)}}
    .copy-resume-btn.copied{{background:var(--success-dim);border-color:var(--success);color:var(--success);opacity:1}}
    /* Summary column */
    .col-summary{{white-space:nowrap}}
    /* 3-dot row menu */
    .col-menu{{width:32px;text-align:center;padding:8px 4px}}
    .row-menu-wrap{{position:relative;display:inline-block}}
    .row-menu-btn{{background:none;border:none;color:var(--text-3);cursor:pointer;padding:2px 4px;border-radius:var(--radius-sm);transition:color .15s,background .15s;line-height:1;display:flex;align-items:center}}
    .row-menu-btn:hover{{color:var(--text);background:var(--surface-3)}}
    .row-menu-dropdown{{display:none;position:absolute;right:0;top:100%;background:var(--card-bg);border:1px solid var(--border);border-radius:var(--radius-sm);box-shadow:0 4px 16px rgba(0,0,0,.12);z-index:100;min-width:150px;padding:4px 0}}
    .row-menu-dropdown.open{{display:block}}
    .row-menu-dropdown button{{display:flex;align-items:center;gap:8px;width:100%;padding:8px 14px;background:none;border:none;color:var(--text);font-size:13px;cursor:pointer;text-align:left;transition:background .12s}}
    .row-menu-dropdown button:hover{{background:var(--teal-dim);color:var(--teal-text)}}
    .row-menu-dropdown button.row-menu-danger{{color:var(--danger)}}
    .row-menu-dropdown button.row-menu-danger:hover{{background:var(--danger-dim);color:var(--danger)}}
    .sum-btn{{display:inline-flex;align-items:center;gap:4px;font-size:12px;padding:4px 9px;background:var(--success-dim);border:1px solid transparent;color:var(--success);border-radius:var(--radius-sm);cursor:pointer;transition:all .15s;white-space:nowrap}}
    .sum-btn:hover{{background:var(--success);color:#fff}}
    .view-btn{{display:inline-flex;align-items:center;justify-content:center;font-size:13px;padding:4px 7px;background:var(--primary-dim);border:1px solid transparent;color:var(--primary);border-radius:var(--radius-sm);cursor:pointer;transition:all .15s}}
    .view-btn:hover{{background:var(--primary);color:#fff}}
    .resume-btn{{font-family:"SF Mono","Fira Code",monospace;font-size:10px;background:var(--surface-2);border:1px solid var(--border);color:var(--text-2);padding:4px 10px;border-radius:var(--radius-sm);cursor:default;user-select:all;white-space:nowrap;display:inline-block}}

    /* Search highlight */
    .hl{{background:rgba(251,191,36,.25);color:var(--text);border-radius:2px;padding:0 1px}}
    body.light .hl{{background:rgba(251,191,36,.45)}}

    /* Modal — frosted glass */
    .modal-overlay{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);z-index:100;align-items:center;justify-content:center;padding:24px}}
    .modal-overlay.open{{display:flex}}
    .modal{{background:color-mix(in srgb,var(--card-bg) 94%,transparent);backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);border:1px solid var(--border);border-radius:16px;width:100%;max-width:680px;max-height:85vh;display:flex;flex-direction:column;box-shadow:0 24px 64px rgba(0,0,0,.8);animation:fadeUp .18s ease}}
    @keyframes fadeUp{{from{{opacity:0;transform:translateY(10px)}}to{{opacity:1;transform:translateY(0)}}}}
    .modal-header{{padding:16px 20px;border-bottom:1px solid var(--border);display:flex;align-items:flex-start;gap:12px;flex-shrink:0}}
    .modal-header-text{{flex:1;min-width:0}}
    .modal-title{{font-size:14px;font-weight:600;color:var(--text);line-height:1.4}}
    .modal-meta{{font-size:11px;color:var(--text-3);margin-top:3px;font-family:"SF Mono",monospace}}
    .modal-close{{background:none;border:none;color:var(--text-3);font-size:18px;cursor:pointer;padding:2px;transition:color .15s;flex-shrink:0}}
    .modal-close:hover{{color:var(--text)}}
    .modal-body{{padding:12px 16px;overflow-y:auto;flex:1;display:flex;flex-direction:column}}
    .date-divider{{text-align:center;margin:12px 0 8px;flex-shrink:0}}
    .date-divider span{{font-size:10px;color:var(--text-3);background:var(--surface-2);border:1px solid var(--border);padding:3px 12px;border-radius:99px;letter-spacing:.4px}}
    .msg-row{{display:flex;flex-direction:column;margin-bottom:8px;flex-shrink:0}}
    .msg-row.user{{align-items:flex-end}}
    .msg-row.assistant{{align-items:flex-start}}
    .msg-bubble{{padding:9px 13px;border-radius:12px;font-size:12.5px;line-height:1.65;word-break:break-word;max-width:82%;white-space:pre-wrap}}
    .msg-row.user .msg-bubble{{background:var(--primary-dim);border:1px solid var(--border-2);color:var(--text);border-bottom-right-radius:3px}}
    .msg-row.assistant .msg-bubble{{background:var(--success-dim);border:1px solid var(--border);color:var(--text);border-bottom-left-radius:3px}}
    .msg-time{{font-size:10px;color:var(--text-3);margin-top:3px;padding:0 2px}}
    .msg-row.user .msg-time{{text-align:right}}
    .msg-row.assistant .msg-time{{text-align:left}}
    .modal-footer{{padding:14px 20px;border-top:1px solid var(--border);flex-shrink:0;display:flex;align-items:center;gap:10px}}
    .modal-footer .resume-btn{{flex:1}}
    .msg-count-badge{{font-size:11px;color:var(--text-3);white-space:nowrap}}

    /* Summary popup */
    .sum-overlay{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);z-index:100;align-items:center;justify-content:center;padding:24px}}
    .sum-overlay.open{{display:flex}}
    .sum-popup{{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);width:100%;max-width:500px;box-shadow:0 16px 40px rgba(0,0,0,.6);animation:fadeUp .18s ease}}
    .sum-popup-header{{padding:14px 18px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:10px}}
    .sum-popup-title{{flex:1;font-size:13px;font-weight:600;color:var(--success);line-height:1.3}}
    .sum-popup-body{{padding:16px 18px;font-size:13px;color:var(--text-2);line-height:1.75}}

    /* Delete/archive buttons */
    .arch-btn{{background:none;border:none;color:var(--text-3);font-size:13px;cursor:pointer;padding:4px 6px;border-radius:var(--radius-sm);transition:color .15s,background .15s;line-height:1}}
    .arch-btn:hover{{color:var(--primary);background:var(--primary-dim)}}
    .arch-restore-btn{{font-size:11px;padding:4px 10px;background:var(--primary-dim);border:1px solid var(--border);color:var(--primary);border-radius:var(--radius-sm);cursor:pointer;transition:all .15s;white-space:nowrap}}
    .arch-restore-btn:hover{{background:var(--primary);color:#fff}}

    /* Delete confirm modal */
    .del-modal{{background:var(--surface);border:1px solid var(--danger);border-radius:var(--radius);width:100%;max-width:480px;box-shadow:0 20px 50px rgba(0,0,0,.7);animation:fadeUp .18s ease}}
    .del-modal-header{{padding:16px 20px;border-bottom:1px solid var(--border)}}
    .del-modal-title{{font-size:14px;font-weight:600;color:var(--danger)}}
    .del-modal-body{{padding:16px 20px}}
    .del-modal-footer{{padding:14px 20px;border-top:1px solid var(--border);display:flex;justify-content:flex-end;gap:8px}}
    .btn-cancel{{background:var(--surface-2);border:1px solid var(--border);color:var(--text-2);font-size:12px;padding:7px 16px;border-radius:var(--radius-sm);cursor:pointer;transition:background .15s}}
    .btn-cancel:hover{{background:var(--surface-3);color:var(--text)}}

    /* Keyboard shortcuts overlay */
    .kbd-overlay{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);z-index:200;align-items:center;justify-content:center;padding:24px}}
    .kbd-overlay.open{{display:flex}}
    .kbd-box{{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);width:100%;max-width:400px;box-shadow:0 16px 40px rgba(0,0,0,.6);animation:fadeUp .18s ease}}
    .kbd-header{{padding:14px 20px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between}}
    .kbd-title{{font-size:13px;font-weight:600;color:var(--text)}}
    .kbd-body{{padding:16px 20px;display:grid;grid-template-columns:auto 1fr;gap:6px 16px;align-items:center}}
    .kbd-key{{font-family:"SF Mono","Fira Code",monospace;font-size:11px;background:var(--surface-2);border:1px solid var(--border-2);color:var(--text-2);padding:3px 8px;border-radius:5px;white-space:nowrap;text-align:center}}
    .kbd-desc{{font-size:12px;color:var(--text-2)}}
    /* Toast */
    .toast{{position:fixed;bottom:28px;left:50%;transform:translateX(-50%);background:var(--surface);border:1px solid var(--border);color:var(--text);font-size:12.5px;padding:10px 18px;border-radius:var(--radius-sm);box-shadow:0 8px 24px rgba(0,0,0,.5);z-index:200;opacity:0;transition:opacity .2s;pointer-events:none;white-space:nowrap}}
    .toast.show{{opacity:1}}

    footer{{padding:16px 28px;font-size:11px;color:var(--text-3);border-top:1px solid var(--border);flex-shrink:0}}

    /* Sort */
    .sortable{{cursor:pointer;user-select:none}}.sortable:hover{{color:var(--text-2)}}
    .sort-icon{{font-family:'Material Symbols Outlined';font-variation-settings:'FILL' 0,'wght' 200,'GRAD' 0,'opsz' 20;font-size:14px;color:var(--text-3);margin-left:2px;vertical-align:middle;line-height:1;display:inline-block;user-select:none;text-transform:none}}
    .sortable.sort-asc .sort-icon,.sortable.sort-desc .sort-icon{{color:var(--primary)}}
    /* Stars */
    .col-star{{text-align:center;width:32px;padding:8px 4px}}
    .star-btn{{background:none;border:none;cursor:pointer;font-size:15px;color:var(--text-3);padding:2px 4px;border-radius:4px;transition:color .15s,transform .1s;line-height:1}}
    .star-btn:hover{{color:var(--warning);transform:scale(1.2)}}
    .star-btn.starred{{color:var(--warning)}}
    /* Color labels */
    .col-label{{width:32px;text-align:center;padding:8px 4px}}
    .label-dot{{display:inline-block;width:12px;height:12px;border-radius:50%;background:var(--surface-3);border:1px solid var(--border-2);cursor:pointer;transition:transform .15s;vertical-align:middle}}
    .label-dot:hover{{transform:scale(1.35)}}
    .label-dot.lc-red{{background:#ef4444;border-color:#ef4444}}.label-dot.lc-orange{{background:#f97316;border-color:#f97316}}
    .label-dot.lc-yellow{{background:#eab308;border-color:#eab308}}.label-dot.lc-green{{background:#22c55e;border-color:#22c55e}}
    .label-dot.lc-blue{{background:#3b82f6;border-color:#3b82f6}}.label-dot.lc-purple{{background:#a855f7;border-color:#a855f7}}
    .label-dot.lc-pink{{background:#ec4899;border-color:#ec4899}}
    .label-picker{{position:fixed;z-index:300;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:10px 14px;display:flex;gap:10px;align-items:center;box-shadow:0 12px 32px rgba(0,0,0,.7);animation:fadeUp .12s ease}}
    .lp-swatch{{width:18px;height:18px;border-radius:50%;cursor:pointer;border:2px solid transparent;transition:transform .12s,border-color .12s;flex-shrink:0}}
    .lp-swatch:hover{{transform:scale(1.3);border-color:rgba(255,255,255,.5)}}
    .lp-none{{background:none;border:1px dashed var(--border-2);font-size:11px;color:var(--text-3);cursor:pointer;display:inline-flex;align-items:center;justify-content:center;border-radius:50%;transition:border-color .12s,color .12s}}
    .lp-none:hover{{border-color:var(--text);color:var(--text)}}
    /* Notes */
    .col-notes{{min-width:80px;max-width:150px}}
    .notes-disp{{color:var(--text-3);font-size:11px;cursor:pointer;padding:3px 6px;border-radius:4px;transition:background .15s,color .15s;display:inline-block;max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;vertical-align:middle}}
    .notes-disp:hover{{background:var(--surface-2);color:var(--text-2)}}
    .notes-disp.has-note{{color:var(--text-2)}}
    .notes-input{{background:var(--surface-2);border:1px solid var(--primary);border-radius:var(--radius-sm);color:var(--text);font-size:11px;padding:5px 8px;outline:none;width:140px;resize:vertical;min-height:55px;font-family:inherit}}
    /* Copy resume button */
    .copy-btn{{display:inline-flex;align-items:center;gap:4px;font-size:11px;padding:4px 7px;background:var(--surface-2);border:1px solid var(--border);color:var(--text-3);border-radius:var(--radius-sm);cursor:pointer;transition:all .15s;white-space:nowrap}}
    .copy-btn:hover{{background:var(--primary-dim);border-color:var(--primary);color:var(--primary)}}
    .copy-btn.copied{{background:var(--success-dim);border-color:var(--success);color:var(--success)}}

    /* Modal search row */
    .modal-search-row{{padding:8px 20px 10px;border-bottom:1px solid var(--border);flex-shrink:0}}
    .modal-search-input{{width:100%;background:var(--surface-2);border:1px solid var(--border);border-radius:var(--radius-sm);padding:7px 12px;color:var(--text);font-size:12px;outline:none;transition:border-color .15s}}
    .modal-search-input:focus{{border-color:var(--primary)}}
    .modal-search-input::placeholder{{color:var(--text-3)}}
    .modal-fs-btn{{background:none;border:none;color:var(--text-3);font-size:14px;cursor:pointer;padding:2px 5px;border-radius:4px;transition:color .15s;flex-shrink:0;line-height:1}}
    .modal-fs-btn:hover{{color:var(--text)}}
    .modal.fullscreen{{max-width:100%;max-height:100vh;height:100vh;border-radius:0}}
    .modal-overlay.fullscreen-active{{padding:0}}

    /* Message copy button */
    .msg-bubble{{position:relative}}
    .msg-copy-btn{{position:absolute;top:5px;right:6px;background:rgba(0,0,0,.4);border:none;color:var(--text-2);font-size:10px;cursor:pointer;padding:2px 6px;border-radius:3px;opacity:0;transition:opacity .15s;line-height:1.4}}
    .msg-row:hover .msg-copy-btn{{opacity:1}}
    .msg-copy-btn:hover{{color:#fff;background:rgba(0,0,0,.7)}}
    /* Token / cost columns */
    .tok{{white-space:nowrap;color:var(--teal);font-size:12px;cursor:default;font-weight:500}}
    .cost-cell{{white-space:nowrap;color:var(--success);font-size:12px;font-weight:500}}

    /* Checkboxes */
    .col-check{{width:32px;text-align:center;padding:8px 4px}}
    .col-check input[type=checkbox]{{accent-color:var(--primary);cursor:pointer;width:13px;height:13px}}

    /* ── Material Symbols Outlined ──────────────────────────────────────── */
    .mi{{font-family:'Material Symbols Outlined';font-variation-settings:'FILL' 0,'wght' 300,'GRAD' 0,'opsz' 20;font-size:18px;line-height:1;vertical-align:middle;user-select:none;display:inline-block;flex-shrink:0;text-transform:none}}
    .mi-sm{{font-size:15px}}.mi-xs{{font-size:13px}}
    .star-btn .mi{{font-size:17px;transition:font-variation-settings .15s,color .15s}}
    .star-btn.starred .mi{{font-variation-settings:'FILL' 1,'wght' 500,'GRAD' 0,'opsz' 20}}
    .star-filled{{font-variation-settings:'FILL' 1,'wght' 500,'GRAD' 0,'opsz' 20;color:var(--warning)}}

    /* ── Main Pages (Stats / Sessions) ───────────────────────────────── */
    .main-page{{display:none;flex-direction:column;flex:1;overflow-y:auto;height:100vh}}
    .main-page.active{{display:flex}}

    /* ── Sub-tab row ─────────────────────────────────────────────────── */
    .sub-tab-row{{display:flex;gap:6px;padding:0 28px 16px;overflow-x:auto;flex-shrink:0;scrollbar-width:none}}
    .sub-tab-row::-webkit-scrollbar{{display:none}}
    .sub-tab{{display:inline-flex;align-items:center;gap:6px;padding:6px 14px;border-radius:99px;cursor:pointer;font-size:12.5px;font-weight:500;white-space:nowrap;transition:all .15s;background:var(--card-bg);border:1px solid var(--border);color:var(--text-2);user-select:none;flex-shrink:0}}
    .sub-tab:hover{{border-color:var(--teal);color:var(--teal-text)}}
    .sub-tab.active{{background:var(--teal);color:#fff;border-color:var(--teal)}}
    .sub-tab-badge{{font-size:10px;font-weight:700;padding:1px 6px;border-radius:99px;line-height:1.5;background:var(--teal-dim);color:var(--teal)}}
    .sub-tab.active .sub-tab-badge{{background:rgba(255,255,255,.25);color:#fff}}
    .sub-tab.nav-dim{{opacity:.4}}

    /* ── Project breakdown table ──────────────────────────────────────── */
    .proj-breakdown-wrap{{margin:0 28px 24px;border-radius:var(--radius);border:1px solid var(--border);background:var(--card-bg);box-shadow:var(--shadow);overflow:hidden;flex-shrink:0}}
    .proj-breakdown-title{{font-size:11px;color:var(--text-3);text-transform:uppercase;letter-spacing:.5px;font-weight:600;padding:14px 18px 10px;border-bottom:1px solid var(--border)}}
    .proj-breakdown-table{{width:100%;border-collapse:collapse;font-size:12.5px}}
    .proj-breakdown-table thead th{{padding:10px 16px;font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:var(--text-3);font-weight:600;text-align:left;background:var(--card-bg)}}
    .proj-breakdown-table tbody tr{{border-top:1px solid var(--border)}}
    .proj-breakdown-table tbody tr:hover{{background:var(--teal-dim)}}
    .proj-b-name{{color:var(--text);font-weight:500;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding:10px 16px}}
    .proj-b-num{{color:var(--text-2);text-align:right;white-space:nowrap;padding:10px 16px}}
  </style>
</head>
<body>

  <!-- SIDEBAR -->
  <nav class="sidebar">
    <div class="sidebar-logo">
      <div class="sidebar-logo-icon"><span class="mi" style="font-size:16px">terminal</span></div>
      <span class="sidebar-logo-text">Sessions</span>
    </div>
    <div class="sidebar-nav">
      <div class="nav-section-label">Main Menu</div>
      <div class="nav-item active" data-main="stats" onclick="showMain('stats')"><span class="nav-icon mi mi-sm">bar_chart</span> Stats</div>
      <div class="nav-item" data-main="sessions" onclick="showMain('sessions')"><span class="nav-icon mi mi-sm">chat_bubble</span> Sessions<span class="nav-badge">{total}</span></div>
    </div>
    <div class="sidebar-bottom">
      <button class="icon-btn" onclick="openKbd()" title="Keyboard shortcuts (?)"><span class="mi mi-sm">keyboard</span> Shortcuts</button>
      <button class="icon-btn" id="darkmode-btn" onclick="toggleDarkMode()" title="Toggle theme"><span class="mi mi-sm">light_mode</span> Theme</button>
    </div>
  </nav>

  <!-- MAIN AREA -->
  <div class="main-area">

    <!-- MAIN PAGE: STATS -->
    <div class="main-page active" id="main-stats">
      <div class="welcome-header">
        <div>
          <h1 class="welcome-h1">Overview</h1>
          <p class="welcome-sub">Analytics &nbsp;&middot;&nbsp; {total} sessions &nbsp;&middot;&nbsp; {total_projects} projects</p>
        </div>
      </div>

      <!-- PRIMARY STAT CARDS -->
      <div class="stats-bar">
        <div class="stat-card card-peach"><div class="stat-value">{total}</div><div class="stat-label">Total Sessions</div></div>
        <div class="stat-card card-mint"><div class="stat-value">{total_msgs:,}</div><div class="stat-label">Messages</div></div>
        <div class="stat-card card-lavender"><div class="stat-value">{fmt_tokens(total_tokens)}</div><div class="stat-label">Total Tokens</div></div>
        <div class="stat-card card-sky"><div class="stat-value">{fmt_cost(total_cost)}</div><div class="stat-label">Est. Cost</div></div>
      </div>

      <!-- SECONDARY STAT CARDS (row 1) -->
      <div class="stats-bar-secondary">
        <div class="stat-card card-sm"><div class="stat-value">{fmt_tokens(total_inp_tok)}</div><div class="stat-label">Input Tokens</div></div>
        <div class="stat-card card-sm"><div class="stat-value">{fmt_tokens(total_out_tok)}</div><div class="stat-label">Output Tokens</div></div>
        <div class="stat-card card-sm"><div class="stat-value">{this_week}</div><div class="stat-label">This Week</div></div>
        <div class="stat-card card-sm"><div class="stat-value">{today_count}</div><div class="stat-label">Today</div></div>
      </div>

      <!-- SECONDARY STAT CARDS (row 2) -->
      <div class="stats-bar-secondary">
        <div class="stat-card card-sm"><div class="stat-value">{avg_msgs}</div><div class="stat-label">Avg Msgs / Session</div></div>
        <div class="stat-card card-sm"><div class="stat-value">{esc(busiest_day)}</div><div class="stat-label">Busiest Day</div></div>
        <div class="stat-card card-sm"><div class="stat-value">{esc(top_proj)}</div><div class="stat-label">Top Project</div></div>
        <div class="stat-card card-sm"><div class="stat-value">{total_projects}</div><div class="stat-label">Projects</div></div>
      </div>

      <!-- ACTIVITY HEATMAP HERO CARD -->
      <div class="heatmap-card">
        <div class="heatmap-section" id="heatmap-section"></div>
      </div>

      <!-- PROJECT BREAKDOWN -->
      <div class="proj-breakdown-wrap">
        <div class="proj-breakdown-title">Projects</div>
        <table class="proj-breakdown-table">
          <thead><tr>
            <th>Project</th>
            <th style="text-align:right">Sessions</th>
            <th style="text-align:right">Messages</th>
            <th style="text-align:right">Tokens</th>
            <th style="text-align:right">Cost</th>
          </tr></thead>
          <tbody>{proj_breakdown_html}</tbody>
        </table>
      </div>

      <footer>Auto-generated by generate.py &nbsp;&middot;&nbsp; Updated {generated}</footer>
    </div>

    <!-- MAIN PAGE: SESSIONS -->
    <div class="main-page" id="main-sessions">

      <!-- WELCOME HEADER -->
      <div class="welcome-header">
        <div>
          <h1 class="welcome-h1">Sessions</h1>
          <p class="welcome-sub">Your Claude Code history &nbsp;&middot;&nbsp; {total} sessions</p>
        </div>
        <div class="welcome-actions">
          <div class="search-wrap">
            <span class="search-icon mi">search</span>
            <input class="search-input" id="search-input" type="text" placeholder="Search sessions..." oninput="doSearch(this.value)"/>
            <button class="search-clear" id="search-clear" onclick="clearSearch()"><span class="mi mi-xs">close</span></button>
            <span class="search-count" id="search-count"></span>
          </div>
          <div class="filter-wrap">
            <button class="icon-btn filter-btn" id="filter-btn" onclick="toggleFilterPanel()">
              <span class="mi mi-sm">tune</span> Filter <span class="filter-badge" id="filter-badge" style="display:none">0</span>
            </button>
            <div class="filter-panel" id="filter-panel">
              <div class="filter-group">
                <div class="filter-group-label">Time</div>
                <div class="filter-quick-btns">
                  <button class="fq-btn" onclick="setQuickDate('today')">Today</button>
                  <button class="fq-btn" onclick="setQuickDate('week')">This week</button>
                  <button class="fq-btn" onclick="setQuickDate('month')">This month</button>
                </div>
                <div class="filter-date-row">
                  <input type="date" class="filter-date" id="filter-from" onchange="applyFilters()" title="From">
                  <span class="filter-sep">&#8212;</span>
                  <input type="date" class="filter-date" id="filter-to" onchange="applyFilters()" title="To">
                </div>
              </div>
              <div class="filter-group">
                <div class="filter-group-label">Category</div>
                <div class="filter-cat-grid">
                  <label class="filter-cat-lbl"><input type="checkbox" class="cat-check" value="Figma" onchange="applyFilters()" checked> Figma</label>
                  <label class="filter-cat-lbl"><input type="checkbox" class="cat-check" value="VS Code" onchange="applyFilters()" checked> VS Code</label>
                  <label class="filter-cat-lbl"><input type="checkbox" class="cat-check" value="Git" onchange="applyFilters()" checked> Git</label>
                  <label class="filter-cat-lbl"><input type="checkbox" class="cat-check" value="Python" onchange="applyFilters()" checked> Python</label>
                  <label class="filter-cat-lbl"><input type="checkbox" class="cat-check" value="JavaScript" onchange="applyFilters()" checked> JavaScript</label>
                  <label class="filter-cat-lbl"><input type="checkbox" class="cat-check" value="CSS" onchange="applyFilters()" checked> CSS</label>
                  <label class="filter-cat-lbl"><input type="checkbox" class="cat-check" value="Database" onchange="applyFilters()" checked> Database</label>
                  <label class="filter-cat-lbl"><input type="checkbox" class="cat-check" value="Docker" onchange="applyFilters()" checked> Docker</label>
                  <label class="filter-cat-lbl"><input type="checkbox" class="cat-check" value="API" onchange="applyFilters()" checked> API</label>
                  <label class="filter-cat-lbl"><input type="checkbox" class="cat-check" value="Testing" onchange="applyFilters()" checked> Testing</label>
                  <label class="filter-cat-lbl"><input type="checkbox" class="cat-check" value="Shell" onchange="applyFilters()" checked> Shell</label>
                  <label class="filter-cat-lbl"><input type="checkbox" class="cat-check" value="Slack" onchange="applyFilters()" checked> Slack</label>
                  <label class="filter-cat-lbl"><input type="checkbox" class="cat-check" value="Setup" onchange="applyFilters()" checked> Setup</label>
                  <label class="filter-cat-lbl"><input type="checkbox" class="cat-check" value="General" onchange="applyFilters()" checked> General</label>
                </div>
              </div>
              <div class="filter-group">
                <div class="filter-group-label">Status</div>
                <label class="filter-status-lbl"><input type="checkbox" id="filter-starred" onchange="applyFilters()"> <span class="mi mi-xs">star</span> Starred only</label>
                <label class="filter-status-lbl"><input type="checkbox" id="filter-notitle" onchange="applyFilters()"> Custom title only</label>
              </div>
              <div class="filter-footer">
                <span class="filter-cnt" id="filter-cnt-vis"></span>
                <button class="filter-reset-btn" onclick="clearFilters()">Reset all filters</button>
              </div>
            </div>
          </div>
          <div class="col-vis-wrap">
            <button class="icon-btn" onclick="toggleColMenu()" title="Columns"><span class="mi mi-sm">view_column</span> Cols</button>
            <div class="col-vis-menu" id="col-vis-menu">
              <label draggable="true" data-col="star"><span class="col-drag-handle mi">drag_indicator</span><input type="checkbox" class="col-toggle" data-col="star" checked> Stars</label>
              <label draggable="true" data-col="label"><span class="col-drag-handle mi">drag_indicator</span><input type="checkbox" class="col-toggle" data-col="label" checked> Labels</label>
              <label draggable="true" data-col="notes"><span class="col-drag-handle mi">drag_indicator</span><input type="checkbox" class="col-toggle" data-col="notes" checked> Notes</label>
              <label draggable="true" data-col="title"><span class="col-drag-handle mi">drag_indicator</span><input type="checkbox" class="col-toggle" data-col="title" checked> Title</label>
              <label draggable="true" data-col="topic"><span class="col-drag-handle mi">drag_indicator</span><input type="checkbox" class="col-toggle" data-col="topic" checked> First Message</label>
              <label draggable="true" data-col="cat"><span class="col-drag-handle mi">drag_indicator</span><input type="checkbox" class="col-toggle" data-col="cat" checked> Category</label>
              <label draggable="true" data-col="date"><span class="col-drag-handle mi">drag_indicator</span><input type="checkbox" class="col-toggle" data-col="date" checked> Date</label>
              <label draggable="true" data-col="summary"><span class="col-drag-handle mi">drag_indicator</span><input type="checkbox" class="col-toggle" data-col="summary" checked> Summary</label>
              <label draggable="true" data-col="size"><span class="col-drag-handle mi">drag_indicator</span><input type="checkbox" class="col-toggle" data-col="size" checked> Size</label>
              <label draggable="true" data-col="msgs"><span class="col-drag-handle mi">drag_indicator</span><input type="checkbox" class="col-toggle" data-col="msgs" checked> Messages</label>
              <label draggable="true" data-col="tok"><span class="col-drag-handle mi">drag_indicator</span><input type="checkbox" class="col-toggle" data-col="tok" checked> Tokens</label>
              <label draggable="true" data-col="cost"><span class="col-drag-handle mi">drag_indicator</span><input type="checkbox" class="col-toggle" data-col="cost" checked> Cost</label>
            </div>
          </div>
          <div class="actions-wrap">
            <button class="icon-btn" onclick="toggleActionsMenu()">Actions <span class="mi mi-xs">expand_more</span></button>
            <div class="actions-menu" id="actions-menu">
              <button onclick="exportCSV()"><span class="mi mi-sm">download</span> Export CSV</button>
              <button onclick="exportAnnotations()"><span class="mi mi-sm">download</span> Annotations</button>
              <label><span class="mi mi-sm">upload</span> Import <input type="file" style="display:none" accept=".json" onchange="importAnnotations(event)"></label>
            </div>
          </div>
        </div>
      </div>

      <!-- SUB-TAB ROW -->
      <div class="sub-tab-row">
        {''.join(sub_tabs)}
      </div>

      <!-- BULK ACTION BAR -->
      <div class="bulk-bar" id="bulk-bar" style="display:none">
        <span class="bulk-count" id="bulk-count">0 selected</span>
        <div class="bulk-sep"></div>
        <button class="bulk-btn bulk-arch"   onclick="bulkArchive()"><span class="mi mi-sm">inventory_2</span> Archive</button>
        <div class="bulk-sep"></div>
        <div class="bulk-label-row">
          <span>Label:</span>
          <div class="lp-swatch" style="background:#ef4444" onclick="bulkSetLabel('red')"    title="Red"></div>
          <div class="lp-swatch" style="background:#f97316" onclick="bulkSetLabel('orange')" title="Orange"></div>
          <div class="lp-swatch" style="background:#eab308" onclick="bulkSetLabel('yellow')" title="Yellow"></div>
          <div class="lp-swatch" style="background:#22c55e" onclick="bulkSetLabel('green')"  title="Green"></div>
          <div class="lp-swatch" style="background:#3b82f6" onclick="bulkSetLabel('blue')"   title="Blue"></div>
          <div class="lp-swatch" style="background:#a855f7" onclick="bulkSetLabel('purple')" title="Purple"></div>
          <div class="lp-swatch" style="background:#ec4899" onclick="bulkSetLabel('pink')"   title="Pink"></div>
          <button class="lp-swatch lp-none" onclick="bulkSetLabel('')" style="width:18px;height:18px" title="Remove label"><span class="mi mi-xs">close</span></button>
        </div>
        <div class="bulk-sep"></div>
        <button class="bulk-btn bulk-export" onclick="exportSelectedCSV()"><span class="mi mi-sm">download</span> CSV</button>
        <button class="bulk-btn bulk-clr"    onclick="clearSelection()"><span class="mi mi-sm">close</span> Clear</button>
      </div>

      <span id="filter-cnt" style="display:none"></span>

      <!-- FILTER CHIPS -->
      <div class="main-toolbar">
        <div class="filter-chips-row" id="filter-chips-row"></div>
      </div>

      <!-- PAGE CONTENT -->
      <div class="page-content">
        {''.join(pages)}
      </div>

      <footer>Sessions in ~/.claude/projects/ &nbsp;&middot;&nbsp; {total} sessions &nbsp;&middot;&nbsp; Updated {generated}</footer>
    </div>

  </div><!-- /.main-area -->

  <!-- LABEL PICKER -->
  <div class="label-picker" id="label-picker" style="display:none">
    <button class="lp-swatch lp-none" onclick="setLabel('')" style="width:18px;height:18px" title="Remove label"><span class="mi mi-xs">close</span></button>
    <div class="lp-swatch" style="background:#ef4444" onclick="setLabel('red')"    title="Red"></div>
    <div class="lp-swatch" style="background:#f97316" onclick="setLabel('orange')" title="Orange"></div>
    <div class="lp-swatch" style="background:#eab308" onclick="setLabel('yellow')" title="Yellow"></div>
    <div class="lp-swatch" style="background:#22c55e" onclick="setLabel('green')"  title="Green"></div>
    <div class="lp-swatch" style="background:#3b82f6" onclick="setLabel('blue')"   title="Blue"></div>
    <div class="lp-swatch" style="background:#a855f7" onclick="setLabel('purple')" title="Purple"></div>
    <div class="lp-swatch" style="background:#ec4899" onclick="setLabel('pink')"   title="Pink"></div>
  </div>

  <!-- MODAL -->
  <div class="modal-overlay" id="modal-overlay" onclick="handleOverlayClick(event)">
    <div class="modal">
      <div class="modal-header">
        <div class="modal-header-text">
          <div class="modal-title" id="modal-title"></div>
          <div class="modal-meta" id="modal-meta"></div>
        </div>
        <button class="modal-fs-btn" id="modal-fs-btn" onclick="toggleModalFullscreen()" title="Fullscreen"><span class="mi">open_in_full</span></button>
        <button class="modal-close" onclick="closeModal()"><span class="mi">close</span></button>
      </div>
      <div class="modal-search-row">
        <input class="modal-search-input" id="modal-search" type="text" placeholder="Search messages..." oninput="filterModalMessages(this.value)">
      </div>
      <div class="modal-body" id="modal-body"></div>
      <div class="modal-footer">
        <span class="resume-btn" id="modal-resume"></span>
        <span class="msg-count-badge" id="modal-msg-count"></span>
        <button class="copy-btn" id="modal-export-md-btn" title="Export session as Markdown"><span class="mi mi-sm">download</span> MD</button>
      </div>
    </div>
  </div>

  <!-- SUMMARY POPUP -->
  <div class="sum-overlay" id="sum-overlay" onclick="if(event.target===this)closeSummary()">
    <div class="sum-popup">
      <div class="sum-popup-header">
        <div class="sum-popup-title" id="sum-popup-title"></div>
        <button class="modal-close" onclick="closeSummary()"><span class="mi">close</span></button>
      </div>
      <div class="sum-popup-body" id="sum-popup-body"></div>
    </div>
  </div>


  <!-- KEYBOARD SHORTCUTS -->
  <div class="kbd-overlay" id="kbd-overlay" onclick="if(event.target===this)closeKbd()">
    <div class="kbd-box">
      <div class="kbd-header">
        <span class="kbd-title">Keyboard Shortcuts</span>
        <button class="modal-close" onclick="closeKbd()"><span class="mi">close</span></button>
      </div>
      <div class="kbd-body">
        <span class="kbd-key">/</span><span class="kbd-desc">Focus search</span>
        <span class="kbd-key">?</span><span class="kbd-desc">Show shortcuts</span>
        <span class="kbd-key">d</span><span class="kbd-desc">Toggle dark / light mode</span>
        <span class="kbd-key">Esc</span><span class="kbd-desc">Close modal / clear search</span>
        <span class="kbd-key">&#8679; click</span><span class="kbd-desc">Bulk select rows</span>
      </div>
    </div>
  </div>

  <!-- TOAST -->
  <div class="toast" id="toast"></div>

  <script>
    const sessions = {session_data};
    const heatmapData = {heatmap_data_json};
    const sparklineData = {sparkline_json};

    // ── Titles (localStorage) ──────────────────────────────────────────────
    function titleKey(id) {{ return 'claude-title-' + id; }}

    function applyTitle(el, id) {{
      var userTitle = localStorage.getItem(titleKey(id));
      if (userTitle) {{
        el.textContent = userTitle;
        el.classList.remove('placeholder', 'auto-title');
        el.classList.add('has-title');
      }} else {{
        var s = sessions[id];
        var auto = s ? (s.short_title || s.title || '').slice(0, 80) : '';
        if ((s && s.short_title || '').length > 80) auto += '\u2026';
        if (auto) {{
          el.textContent = auto;
          el.title = s.title || '';
          el.classList.remove('placeholder', 'has-title');
          el.classList.add('auto-title');
        }} else {{
          el.textContent = 'Add title...';
          el.classList.remove('has-title', 'auto-title');
          el.classList.add('placeholder');
        }}
      }}
    }}

    function loadTitles() {{
      document.querySelectorAll('.title-cell').forEach(function(cell) {{
        var id = cell.getAttribute('data-id');
        applyTitle(cell.querySelector('.title-display'), id);
        updateRowSearch(id);
      }});
    }}

    function editTitle(id, el) {{
      var current = localStorage.getItem(titleKey(id)) ||
                    (sessions[id] ? sessions[id].short_title || sessions[id].title || '' : '');
      var input   = document.createElement('input');
      input.type        = 'text';
      input.className   = 'title-input';
      input.value       = current;
      input.placeholder = 'Enter a title...';
      input.setAttribute('data-editing', id);

      function save() {{
        var val = input.value.trim();
        var autoT = sessions[id] ? (sessions[id].short_title || sessions[id].title || '') : '';
        if (val && val !== autoT) {{
          localStorage.setItem(titleKey(id), val);
        }} else {{
          localStorage.removeItem(titleKey(id));
        }}
        el.style.display = '';
        input.remove();
        applyTitle(el, id);
        updateRowSearch(id);
        var q = document.getElementById('search-input').value;
        if (q) doSearch(q);
      }}

      input.addEventListener('blur', save);
      input.addEventListener('keydown', function(e) {{
        if (e.key === 'Enter')  {{ e.preventDefault(); input.blur(); }}
        if (e.key === 'Escape') {{ input.value = current; input.blur(); }}
      }});

      el.style.display = 'none';
      el.parentElement.insertBefore(input, el.nextSibling);
      input.focus();
    }}

    function updateRowSearch(id) {{
      var title = localStorage.getItem(titleKey(id)) || '';
      document.querySelectorAll('tr[data-id="' + id + '"]').forEach(function(row) {{
        var base = row.getAttribute('data-search') || '';
        row.setAttribute('data-search-full', base + ' ' + title.toLowerCase());
      }});
    }}

    // ── Search ──────────────────────────────────────────────────────────────
    function doSearch(query) {{
      var q = query.trim().toLowerCase();
      document.getElementById('search-clear').classList.toggle('visible', q.length > 0);
      var totalMatches = 0;

      document.querySelectorAll('.sub-tab[data-tab]').forEach(function(tab) {{
        var tabId = tab.getAttribute('data-tab');
        var page  = document.getElementById('page-' + tabId);
        if (!page) return;
        var rows = page.querySelectorAll('tbody tr');
        var tabMatches = 0; var tabVisible = 0;

        rows.forEach(function(row) {{
          if (row.dataset.hidden) return;
          tabVisible++;
          var corpus = row.getAttribute('data-search-full') || row.getAttribute('data-search') || '';
          var matches = !q || corpus.includes(q);
          if (!matches) row.style.display = 'none';
          if (matches) tabMatches++;
        }});

        totalMatches += tabMatches;
        var badge = document.getElementById('nb-' + tabId);
        if (badge) badge.textContent = q ? (tabMatches + '/' + tabVisible) : tabVisible;
        tab.classList.toggle('nav-dim', tabMatches === 0 && q.length > 0);
      }});

      var countEl = document.getElementById('search-count');
      countEl.textContent = q ? (totalMatches + ' result' + (totalMatches !== 1 ? 's' : '')) : '';
      highlightSearch(q);
      applyFilters();
    }}

    function highlightSearch(q) {{
      // highlight in title-display and title-sub cells
      document.querySelectorAll('.title-display, .title-sub').forEach(function(el) {{
        // restore original text (stored in data-orig)
        if (!el.dataset.orig) el.dataset.orig = el.textContent;
        var orig = el.dataset.orig;
        if (!q || !orig.toLowerCase().includes(q)) {{
          el.textContent = orig; return;
        }}
        var re = new RegExp('(' + q.replace(/[.*+?^${{}}()|[\\]\\\\]/g, '\\\\$&') + ')', 'gi');
        el.innerHTML = esc(orig).replace(re, '<mark class="hl">$1</mark>');
      }});
    }}

    function clearSearch() {{
      var input = document.getElementById('search-input');
      input.value = '';
      doSearch('');
      input.focus();
    }}

    // ── Chat modal ──────────────────────────────────────────────────────────
    function openModal(id) {{
      var s = sessions[id];
      if (!s) return;

      var title = localStorage.getItem(titleKey(id)) || s.title;
      document.getElementById('modal-title').textContent = title;
      document.getElementById('modal-meta').textContent  = s.meta;
      document.getElementById('modal-resume').textContent = s.resume;
      document.getElementById('modal-msg-count').textContent = s.messages.length + ' messages';

      var body = document.getElementById('modal-body');
      body.innerHTML = '';

      if (!s.messages || s.messages.length === 0) {{
        body.innerHTML = '<div style="color:#444;font-size:13px;padding:20px 0">No messages found in this session.</div>';
      }} else {{
        var lastDate = null;

        s.messages.forEach(function(m) {{
          var role = m[0], text = m[1], ts = m[2] || '';

          // Parse timestamp
          var timeStr = '', dateStr = '';
          if (ts) {{
            var d = new Date(ts);
            if (!isNaN(d)) {{
              timeStr = d.toLocaleTimeString([], {{hour:'2-digit', minute:'2-digit'}});
              dateStr = d.toLocaleDateString([], {{weekday:'short', month:'short', day:'numeric', year:'numeric'}});
            }}
          }}

          // Date divider
          if (dateStr && dateStr !== lastDate) {{
            var div = document.createElement('div');
            div.className = 'date-divider';
            div.innerHTML = '<span>' + esc(dateStr) + '</span>';
            body.appendChild(div);
            lastDate = dateStr;
          }}

          // Message row (WhatsApp style)
          var row = document.createElement('div');
          row.className = 'msg-row ' + role;

          var bubble = document.createElement('div');
          bubble.className = 'msg-bubble';
          bubble.textContent = text;

          // Copy button
          var copyBtn = document.createElement('button');
          copyBtn.className = 'msg-copy-btn';
          copyBtn.innerHTML = '<span class="mi mi-xs">content_copy</span>';
          copyBtn.title = 'Copy message';
          (function(t, btn) {{
            btn.onclick = function(e) {{
              e.stopPropagation();
              navigator.clipboard.writeText(t).then(function() {{
                btn.innerHTML = '<span class="mi mi-xs">check</span>';
                setTimeout(function() {{ btn.innerHTML = '<span class="mi mi-xs">content_copy</span>'; }}, 1500);
              }}).catch(function() {{}});
            }};
          }})(text, copyBtn);
          bubble.appendChild(copyBtn);

          var timeEl = document.createElement('div');
          timeEl.className = 'msg-time';
          timeEl.textContent = (role === 'user' ? 'You' : 'Claude') + (timeStr ? '  ' + timeStr : '');

          row.appendChild(bubble);
          row.appendChild(timeEl);
          body.appendChild(row);
        }});
      }}

      // Reset search
      var ms = document.getElementById('modal-search');
      if (ms) {{ ms.value = ''; }}
      // Wire export MD button
      var mdBtn = document.getElementById('modal-export-md-btn');
      if (mdBtn) {{ mdBtn.onclick = function() {{ exportSessionMD(id); }}; }}

      document.getElementById('modal-overlay').classList.add('open');
      document.body.style.overflow = 'hidden';
      // Scroll to bottom (newest message last, like WhatsApp)
      requestAnimationFrame(function() {{ body.scrollTop = body.scrollHeight; }});
    }}

    function closeModal() {{
      document.getElementById('modal-overlay').classList.remove('open');
      document.body.style.overflow = '';
      // Exit fullscreen
      var modal = document.querySelector('.modal');
      if (modal) {{ modal.classList.remove('fullscreen'); }}
      document.getElementById('modal-overlay').classList.remove('fullscreen-active');
      var fsBtn = document.getElementById('modal-fs-btn');
      if (fsBtn) fsBtn.innerHTML = '<span class="mi">open_in_full</span>';
    }}

    function handleOverlayClick(e) {{
      if (e.target === document.getElementById('modal-overlay')) closeModal();
    }}

    function openKbd()  {{ document.getElementById('kbd-overlay').classList.add('open'); }}
    function closeKbd() {{ document.getElementById('kbd-overlay').classList.remove('open'); }}

    document.addEventListener('keydown', function(e) {{
      if (e.key === 'Escape') {{
        closeModal(); closeSummary(); closeDelModal(); closeLabelPicker(); closeKbd();
        document.getElementById('col-vis-menu').classList.remove('open');
        document.getElementById('filter-panel').classList.remove('open');
        document.getElementById('actions-menu').classList.remove('open');
      }}
      if (e.key === '/' && !e.target.matches('input,textarea')) {{ e.preventDefault(); document.getElementById('search-input').focus(); }}
      if (e.key === 'd' && !e.target.matches('input,textarea')) toggleDarkMode();
      if (e.key === '?' && !e.target.matches('input,textarea')) openKbd();
    }});
    document.addEventListener('click', function(e) {{
      if (!e.target.closest('.filter-wrap')) document.getElementById('filter-panel').classList.remove('open');
      if (!e.target.closest('.actions-wrap')) document.getElementById('actions-menu').classList.remove('open');
      if (!e.target.closest('.col-vis-wrap')) document.getElementById('col-vis-menu').classList.remove('open');
      if (!e.target.closest('.label-picker') && !e.target.closest('.label-dot')) closeLabelPicker();
    }});

    // ── Main page switching (Stats / Sessions) ─────────────────────────────
    function showMain(name) {{
      document.querySelectorAll('.main-page').forEach(function(p) {{ p.classList.remove('active'); }});
      document.querySelectorAll('.nav-item[data-main]').forEach(function(n) {{ n.classList.remove('active'); }});
      var page = document.getElementById('main-' + name);
      if (page) page.classList.add('active');
      var nav = document.querySelector('.nav-item[data-main="' + name + '"]');
      if (nav) nav.classList.add('active');
    }}

    // ── Sub-tab switching (inside Sessions page) ────────────────────────────
    function showTab(name) {{
      document.querySelectorAll('.page').forEach(function(p) {{ p.classList.remove('active'); }});
      document.querySelectorAll('.sub-tab').forEach(function(b) {{ b.classList.remove('active'); }});
      var page = document.getElementById('page-' + name);
      if (page) page.classList.add('active');
      var tab = document.querySelector('.sub-tab[data-tab="' + name + '"]');
      if (tab) tab.classList.add('active');
      sortState = {{ col: null, dir: 1 }};
      clearSelection();
      var q = document.getElementById('search-input').value;
      if (q) doSearch(q); else applyFilters();
    }}

    // ── Utils ────────────────────────────────────────────────────────────────
    function esc(s) {{
      return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }}

    // ── Summary popup ───────────────────────────────────────────────────────
    function openSummary(id) {{
      var s = sessions[id];
      if (!s) return;
      var title = localStorage.getItem(titleKey(id)) || s.title;
      document.getElementById('sum-popup-title').textContent = title;
      document.getElementById('sum-popup-body').textContent  = s.summary || 'No summary available.';
      document.getElementById('sum-overlay').classList.add('open');
      document.body.style.overflow = 'hidden';
    }}

    function closeSummary() {{
      document.getElementById('sum-overlay').classList.remove('open');
      document.body.style.overflow = '';
    }}

    // ── Delete ──────────────────────────────────────────────────────────────
    var pendingDeleteId = null;

    function toggleRowMenu(btn) {{
      closeRowMenus(btn);
      var dd = btn.nextElementSibling;
      dd.classList.toggle('open');
    }}
    function closeRowMenus(except) {{
      document.querySelectorAll('.row-menu-dropdown.open').forEach(function(d) {{
        if (d.previousElementSibling !== except) d.classList.remove('open');
      }});
    }}
    document.addEventListener('click', function(e) {{
      if (!e.target.closest('.row-menu-wrap')) closeRowMenus();
    }});
    function applyDeletions() {{
      document.querySelectorAll('tr[data-id]').forEach(function(row) {{
        var id = row.getAttribute('data-id');
        var inArchived = !!row.closest('#page-archived');
        if (!inArchived && localStorage.getItem('claude-archived-' + id)) {{
          row.dataset.hidden = '1';
          row.style.display = 'none';
        }}
      }});
    }}

    function showToast(msg) {{
      var t = document.getElementById('toast');
      t.textContent = msg;
      t.classList.add('show');
      setTimeout(function() {{ t.classList.remove('show'); }}, 4000);
    }}

    // ── Filters ─────────────────────────────────────────────────────────────
    function applyFilters() {{
      var catChecks = document.querySelectorAll('.cat-check');
      var checkedCats = Array.from(catChecks).filter(function(cb){{ return cb.checked; }}).map(function(cb){{ return cb.value; }});
      var allCatsSelected = checkedCats.length === catChecks.length;
      var from    = document.getElementById('filter-from').value;
      var to      = document.getElementById('filter-to').value;
      var starred = document.getElementById('filter-starred').checked;
      var notitle = document.getElementById('filter-notitle').checked;
      var q       = document.getElementById('search-input').value.trim().toLowerCase();
      var hasF    = !!(from || to || starred || notitle || !allCatsSelected);

      var page = document.querySelector('.page.active'); if (!page) return;
      var rows = page.querySelectorAll('tbody tr'); var vis = 0;
      rows.forEach(function(row) {{
        if (row.dataset.hidden) {{ row.style.display = 'none'; return; }}
        var id = row.getAttribute('data-id');
        var show = true;
        if (!allCatsSelected) {{ var rCats=(row.getAttribute('data-cat')||'').split(','); if (!rCats.some(function(c){{return checkedCats.indexOf(c.trim())!==-1;}})) show=false; }}
        var d = (row.getAttribute('data-date')||'').slice(0,10);
        if (from && d < from) show = false;
        if (to   && d > to)   show = false;
        if (starred && !localStorage.getItem('claude-star-'  + id)) show = false;
        if (notitle && !localStorage.getItem('claude-title-' + id)) show = false;
        if (q) {{ var c = row.getAttribute('data-search-full')||row.getAttribute('data-search')||''; if (!c.includes(q)) show = false; }}
        row.style.display = show ? '' : 'none';
        if (show) vis++;
      }});
      var validCnt = Array.from(rows).filter(function(r){{ return !r.dataset.hidden; }}).length;
      var cntText = (hasF||q) ? vis+'/'+validCnt+' shown' : '';
      document.getElementById('filter-cnt').textContent = cntText;
      var fcv = document.getElementById('filter-cnt-vis'); if (fcv) fcv.textContent = cntText;
      var an = document.querySelector('.sub-tab.active');
      if (an) {{
        var tabId = an.getAttribute('data-tab');
        var badge = document.getElementById('nb-' + tabId);
        if (badge) badge.textContent = (hasF||q) ? vis+'/'+validCnt : validCnt;
      }}
      updateFilterChips();
    }}

    function clearFilters() {{
      document.getElementById('filter-from').value = '';
      document.getElementById('filter-to').value = '';
      document.querySelectorAll('.cat-check').forEach(function(cb){{ cb.checked = true; }});
      document.getElementById('filter-starred').checked = false;
      document.getElementById('filter-notitle').checked = false;
      applyFilters();
    }}

    // ── Filter panel & actions menu toggles ─────────────────────────────────
    function toggleFilterPanel() {{ document.getElementById('filter-panel').classList.toggle('open'); }}
    function toggleActionsMenu() {{ document.getElementById('actions-menu').classList.toggle('open'); }}

    // ── Quick date presets ───────────────────────────────────────────────────
    function setQuickDate(range) {{
      var now = new Date();
      var from = document.getElementById('filter-from');
      var to   = document.getElementById('filter-to');
      var fmt  = function(d){{ return d.toISOString().slice(0,10); }};
      to.value = fmt(now);
      if (range === 'today') {{ from.value = fmt(now); }}
      else if (range === 'week')  {{ var d=new Date(now); d.setDate(d.getDate()-6); from.value=fmt(d); }}
      else if (range === 'month') {{ var d=new Date(now); d.setDate(d.getDate()-29); from.value=fmt(d); }}
      applyFilters();
    }}

    // ── Filter chips ─────────────────────────────────────────────────────────
    function updateFilterChips() {{
      var row   = document.getElementById('filter-chips-row');
      var badge = document.getElementById('filter-badge');
      if (!row) return;
      var chips = []; var count = 0;
      var from = document.getElementById('filter-from').value;
      var to   = document.getElementById('filter-to').value;
      if (from || to) {{ count++; chips.push({{label:(from||'\u2026')+' \u2192 '+(to||'\u2026'),clear:'date'}}); }}
      var catChecks = document.querySelectorAll('.cat-check');
      var checked = Array.from(catChecks).filter(function(cb){{ return cb.checked; }});
      if (checked.length < catChecks.length) {{ count++; chips.push({{label:checked.map(function(c){{return c.value;}}).join(', '),clear:'cat'}}); }}
      if (document.getElementById('filter-starred').checked) {{ count++; chips.push({{label:'Starred',clear:'starred'}}); }}
      if (document.getElementById('filter-notitle').checked) {{ count++; chips.push({{label:'Custom title',clear:'notitle'}}); }}
      row.innerHTML = chips.map(function(c){{
        return '<span class="filter-chip">'+esc(c.label)+'<button onclick="clearFilterChip(&quot;'+c.clear+'&quot;)"><span class="mi mi-xs">close</span></button></span>';
      }}).join('');
      badge.style.display = count ? '' : 'none';
      badge.textContent   = count;
    }}

    function clearFilterChip(type) {{
      if (type==='date') {{ document.getElementById('filter-from').value=''; document.getElementById('filter-to').value=''; }}
      else if (type==='cat')     {{ document.querySelectorAll('.cat-check').forEach(function(cb){{ cb.checked=true; }}); }}
      else if (type==='starred') {{ document.getElementById('filter-starred').checked=false; }}
      else if (type==='notitle') {{ document.getElementById('filter-notitle').checked=false; }}
      applyFilters();
    }}

    // ── Archive ──────────────────────────────────────────────────────────────
    function archKey(id) {{ return 'claude-archived-' + id; }}

    function archiveSession(id) {{
      localStorage.setItem(archKey(id), '1');
      document.querySelectorAll('tr[data-id="'+id+'"]').forEach(function(row) {{
        if (!row.closest('#page-archived')) {{ row.dataset.hidden = '1'; row.style.display = 'none'; }}
      }});
      buildArchivedTab();
      applyFilters();
      showToast('Archived. Restore it from the Archived tab.');
    }}

    function restoreSession(id) {{
      localStorage.removeItem(archKey(id));
      document.querySelectorAll('tr[data-id="'+id+'"]').forEach(function(row) {{
        if (!row.closest('#page-archived')) {{ delete row.dataset.hidden; row.style.display = ''; }}
      }});
      buildArchivedTab();
      applyFilters();
      showToast('Session restored.');
    }}

    function buildArchivedTab() {{
      var page = document.getElementById('page-archived'); if (!page) return;
      var ids = Object.keys(sessions).filter(function(id){{ return !!localStorage.getItem(archKey(id)); }});
      var badge = document.getElementById('nb-archived');
      if (badge) badge.textContent = ids.length;
      if (ids.length === 0) {{ page.innerHTML = '<p style="color:#555;padding:24px;font-size:13px">No archived sessions.</p>'; return; }}
      ids.sort(function(a,b){{ return (sessions[b].date_iso||'').localeCompare(sessions[a].date_iso||''); }});
      var rows = ids.map(function(id) {{
        var s = sessions[id];
        var title = localStorage.getItem('claude-title-'+id) || s.title;
        var corpus = (id+' '+title+' '+(s.category||'')+' '+(s.title||'')).toLowerCase();
        return '<tr data-id="'+id+'" data-search="'+esc(corpus)+'">' +
          '<td class="session-id">'+esc(id.slice(0,8))+'<span>'+esc(id.slice(8))+'</span></td>' +
          '<td class="title-cell"><span class="title-display '+(localStorage.getItem('claude-title-'+id)?'has-title':'placeholder')+'">'+esc(title)+'</span></td>' +
          '<td class="date">'+esc((s.date_iso||'').slice(0,16).replace('T',' '))+'</td>' +
          '<td class="msgs">'+(s.msg_count||0)+'</td>' +
          '<td><button class="view-btn" onclick="openModal(\\\''+id+'\\\')"><span class="mi mi-sm">chat_bubble</span></button></td>' +
          '<td><button class="arch-restore-btn" onclick="restoreSession(\\\''+id+'\\\')"><span class="mi mi-sm">restore</span> Restore</button></td>' +
          '</tr>';
      }}).join('');
      page.innerHTML = '<div class="project-path">Archived sessions &mdash; click Restore to bring back</div>' +
        '<div class="table-wrap"><table><thead><tr>' +
        '<th>Session ID</th><th>Title</th><th>Date</th><th>Msgs</th><th>Chats</th><th></th><th></th>' +
        '</tr></thead><tbody>'+rows+'</tbody></table></div>';
    }}

    // ── Recent tab ───────────────────────────────────────────────────────────
    function fmtTok(n) {{
      if (!n) return '\u2014';
      if (n>=1000000) return (n/1000000).toFixed(1)+'M';
      if (n>=1000) return (n/1000).toFixed(1)+'K';
      return String(n);
    }}
    function copyText(text, btn) {{
      navigator.clipboard.writeText(text).then(function() {{
        var orig = btn.innerHTML; btn.innerHTML = '<span class="mi mi-xs">check</span> Copied'; btn.classList.add('copied');
        setTimeout(function(){{ btn.innerHTML = orig; btn.classList.remove('copied'); }}, 2000);
        showToast('Copied to clipboard!');
      }}).catch(function(){{ showToast('Copy failed'); }});
    }}

    function relDate(iso) {{
      if (!iso) return '';
      var d = new Date(iso);
      if (isNaN(d)) return iso.slice(0,16).replace('T',' ');
      var now = new Date();
      var diff = Math.floor((now - d) / 86400000);
      var time = d.toLocaleTimeString([], {{hour:'2-digit', minute:'2-digit'}});
      if (diff === 0) return 'Today ' + time;
      if (diff === 1) return 'Yesterday ' + time;
      if (diff < 7)  return diff + ' days ago';
      return d.toLocaleDateString([], {{month:'short', day:'numeric'}});
    }}

    function buildRecentTab() {{
      var page = document.getElementById('page-recent'); if (!page) return;
      var weekAgo = new Date(Date.now() - 7*24*60*60*1000);
      var ids = Object.keys(sessions).filter(function(id) {{
        return sessions[id].date_iso && new Date(sessions[id].date_iso) > weekAgo;
      }}).sort(function(a,b){{ return (sessions[b].date_iso||'').localeCompare(sessions[a].date_iso||''); }});
      var badge = document.getElementById('nb-recent');
      if (badge) badge.textContent = ids.length;
      if (ids.length === 0) {{ page.innerHTML = '<p style="color:#555;padding:24px;font-size:13px">No sessions in the last 7 days.</p>'; return; }}
      var rows = ids.map(function(id) {{
        var s = sessions[id];
        var title = localStorage.getItem('claude-title-'+id) || s.title;
        var star  = localStorage.getItem('claude-star-'+id) ? '<span class="mi mi-sm star-filled">star</span>' : '';
        var corpus = (id+' '+title+' '+(s.category||'')+' '+(s.title||'')).toLowerCase();
        return '<tr data-id="'+id+'" data-date="'+(s.date_iso||'')+'" data-cat="'+esc(s.category||'')+'" data-search="'+esc(corpus)+'">' +
          '<td style="text-align:center">'+star+'</td>' +
          '<td class="session-id">'+esc(id.slice(0,8))+'<span>'+esc(id.slice(8))+'</span></td>' +
          '<td class="title-cell"><span class="title-display '+(localStorage.getItem('claude-title-'+id)?'has-title':'placeholder')+'">'+esc(title)+'</span></td>' +
          '<td class="date" title="'+(s.date_iso||'').slice(0,16).replace('T',' ')+'">'+relDate(s.date_iso||'')+'</td>' +
          '<td class="msgs">'+(s.msg_count||0)+'</td>' +
          '<td class="tok">'+fmtTok(s.total_tokens||0)+'</td>' +
          '<td><button class="view-btn" onclick="openModal(\\\''+id+'\\\')"><span class="mi mi-sm">chat_bubble</span></button></td>' +
          '<td><button class="copy-btn" data-res="'+esc(s.resume||'')+'" onclick="copyText(this.dataset.res,this)"><span class="mi mi-sm">arrow_forward</span> Copy</button></td>' +
          '</tr>';
      }}).join('');
      page.innerHTML = '<div class="project-path"><span class="mi mi-sm">history</span> Sessions from the last 7 days &mdash; all projects</div>' +
        '<div class="table-wrap"><table><thead><tr>' +
        '<th></th><th>Session ID</th><th>Title</th><th>Date &amp; Time</th><th>Msgs</th><th>Tokens</th><th>Chats</th><th>Resume</th>' +
        '</tr></thead><tbody>'+rows+'</tbody></table></div>';
    }}

    // ── Heatmap ──────────────────────────────────────────────────────────────
    function buildHeatmap() {{
      var section = document.getElementById('heatmap-section');
      if (!section) return;
      var today = new Date(); today.setHours(0,0,0,0);
      // Align start to nearest past Sunday, 52 full weeks back
      var start = new Date(today);
      start.setDate(start.getDate() - today.getDay() - 51 * 7);
      // Build array of week columns
      var weeks = [];
      var d = new Date(start);
      while (weeks.length < 53) {{
        var week = [];
        for (var i = 0; i < 7; i++) {{
          var key = d.toISOString().slice(0, 10);
          week.push({{ date: key, count: heatmapData[key] || 0, future: d > today }});
          d = new Date(d); d.setDate(d.getDate() + 1);
        }}
        weeks.push(week);
      }}
      var maxCount = 1;
      Object.keys(heatmapData).forEach(function(k) {{ if (heatmapData[k] > maxCount) maxCount = heatmapData[k]; }});
      // Month labels
      var monthHtml = '<div class="heatmap-months">';
      var lastMonth = -1;
      weeks.forEach(function(week) {{
        var dt = new Date(week[0].date + 'T12:00:00Z');
        var m  = dt.getUTCMonth();
        var lbl = (m !== lastMonth) ? dt.toLocaleString('default', {{ month: 'short', timeZone: 'UTC' }}) : '';
        monthHtml += '<div class="heatmap-month-label">' + esc(lbl) + '</div>';
        lastMonth = m;
      }});
      monthHtml += '</div>';
      // Day grid
      var gridHtml = '<div class="heatmap-grid">';
      weeks.forEach(function(week) {{
        gridHtml += '<div class="heatmap-col">';
        week.forEach(function(day) {{
          var lvl = day.future ? 'future'
                  : day.count === 0 ? 'lv-0'
                  : day.count === 1 ? 'lv-1'
                  : day.count <= 3  ? 'lv-2'
                  : day.count <= 6  ? 'lv-3' : 'lv-4';
          var tip = day.date + (day.count ? ': ' + day.count + ' session' + (day.count !== 1 ? 's' : '') : ': no sessions');
          gridHtml += '<div class="heatmap-day ' + lvl + '" title="' + esc(tip) + '"></div>';
        }});
        gridHtml += '</div>';
      }});
      gridHtml += '</div>';
      // Sparkline (last 12 weeks)
      var maxW = Math.max.apply(null, sparklineData.concat([1]));
      var sparkHtml = '<div class="sparkline-wrap">';
      sparklineData.forEach(function(cnt, i) {{
        var h   = Math.max(2, Math.round(cnt / maxW * 28));
        var tip = 'Week -' + (11 - i) + ': ' + cnt + ' session' + (cnt !== 1 ? 's' : '');
        sparkHtml += '<div class="sparkline-bar" style="height:' + h + 'px" title="' + esc(tip) + '"></div>';
      }});
      sparkHtml += '</div>';
      var collapsed = localStorage.getItem('claude-heatmap-collapsed') === '1';
      section.classList.toggle('collapsed', collapsed);
      section.innerHTML =
        '<div class="heatmap-top">' +
          '<span class="heatmap-heading">Activity &mdash; past year</span>' +
          '<div style="display:flex;align-items:center;gap:8px">' +
            '<div style="display:flex;align-items:center;gap:8px">' +
              '<span style="font-size:10px;color:var(--text-3)">12 weeks</span>' +
              sparkHtml +
            '</div>' +
            '<button class="heatmap-toggle" id="heatmap-toggle" onclick="toggleHeatmap()" title="Toggle heatmap">' +
              (collapsed ? '<span class="mi mi-sm">expand_more</span>' : '<span class="mi mi-sm">expand_less</span>') +
            '</button>' +
          '</div>' +
        '</div>' +
        '<div class="heatmap-body">' + monthHtml + gridHtml + '</div>';
    }}

    // ── Modal search & fullscreen ─────────────────────────────────────────────
    function filterModalMessages(q) {{
      q = q.trim().toLowerCase();
      document.querySelectorAll('#modal-body .msg-row').forEach(function(row) {{
        var b = row.querySelector('.msg-bubble');
        var matches = !q || (b && b.textContent.toLowerCase().includes(q));
        row.style.display = matches ? '' : 'none';
      }});
      document.querySelectorAll('#modal-body .date-divider').forEach(function(div) {{
        var sib = div.nextElementSibling, vis = false;
        while (sib && !sib.classList.contains('date-divider')) {{
          if (sib.style.display !== 'none') {{ vis = true; break; }}
          sib = sib.nextElementSibling;
        }}
        div.style.display = (vis || !q) ? '' : 'none';
      }});
    }}
    function toggleModalFullscreen() {{
      var modal   = document.querySelector('.modal');
      var overlay = document.getElementById('modal-overlay');
      var isFs    = modal.classList.toggle('fullscreen');
      overlay.classList.toggle('fullscreen-active', isFs);
      document.getElementById('modal-fs-btn').innerHTML = isFs ? '<span class="mi">close_fullscreen</span>' : '<span class="mi">open_in_full</span>';
    }}

    // ── Bulk selection ───────────────────────────────────────────────────────
    function getVisibleRows() {{
      var page = document.querySelector('.page.active');
      if (!page) return [];
      return Array.from(page.querySelectorAll('tbody tr')).filter(function(r) {{
        return r.style.display !== 'none' && !r.dataset.hidden;
      }});
    }}
    function getSelected() {{
      return Array.from(document.querySelectorAll('.row-check:checked')).map(function(cb) {{
        return cb.id.replace('chk-', '');
      }});
    }}
    function toggleRowCheck(id) {{ updateBulkBar(); }}
    function toggleSelectAll() {{
      var master = document.getElementById('select-all');
      getVisibleRows().forEach(function(row) {{
        var cb = document.getElementById('chk-' + row.getAttribute('data-id'));
        if (cb) cb.checked = master.checked;
      }});
      updateBulkBar();
    }}
    function updateBulkBar() {{
      var sel = getSelected();
      var bar = document.getElementById('bulk-bar');
      bar.style.display = sel.length ? '' : 'none';
      document.getElementById('bulk-count').textContent = sel.length + ' selected';
      var vis = getVisibleRows();
      var sa  = document.getElementById('select-all');
      if (sa) {{
        sa.indeterminate = sel.length > 0 && sel.length < vis.length;
        sa.checked       = sel.length > 0 && sel.length === vis.length;
      }}
    }}
    function clearSelection() {{
      document.querySelectorAll('.row-check').forEach(function(cb) {{ cb.checked = false; }});
      var sa = document.getElementById('select-all');
      if (sa) {{ sa.checked = false; sa.indeterminate = false; }}
      updateBulkBar();
    }}
    function bulkArchive() {{
      var ids = getSelected(); if (!ids.length) return;
      ids.forEach(function(id) {{ archiveSession(id); }});
      clearSelection();
      showToast('Archived ' + ids.length + ' session(s).');
    }}
    function bulkSetLabel(color) {{
      var ids = getSelected(); if (!ids.length) return;
      ids.forEach(function(id) {{
        var dot = document.getElementById('ldot-' + id); if (!dot) return;
        dot.className = 'label-dot';
        if (color) {{ localStorage.setItem('claude-label-' + id, color); dot.classList.add('lc-' + color); dot.title = color; }}
        else {{ localStorage.removeItem('claude-label-' + id); dot.title = 'Set label'; }}
      }});
      showToast('Label set for ' + ids.length + ' session(s).');
    }}

    // ── Export / Import ──────────────────────────────────────────────────────
    function exportSessionMD(id) {{
      var s = sessions[id]; if (!s) return;
      var title = localStorage.getItem('claude-title-' + id) || s.title || id;
      var lines = [
        '# ' + title, '',
        '**Session:** `' + id + '`  ',
        '**Date:** ' + (s.date_iso || '').slice(0, 16).replace('T', ' ') + '  ',
        '**Category:** ' + (s.category || '') + '  ',
        '**Messages:** ' + (s.messages ? s.messages.length : 0) + '  ',
        '**Tokens:** ' + fmtTok(s.total_tokens || 0) + '  ',
        '**Cost:** ' + (s.cost_usd ? '$' + s.cost_usd.toFixed(4) : '—') + '  ',
        '**Resume:** `' + (s.resume || '') + '`',
        '', '---', ''
      ];
      if (s.messages) {{
        s.messages.forEach(function(m) {{
          var role = m[0], text = m[1], ts = m[2] || '';
          var label = role === 'user' ? '### You' : '### Claude';
          var time = '';
          if (ts) {{ var d = new Date(ts); if (!isNaN(d)) time = ' *' + d.toLocaleTimeString([], {{hour:'2-digit',minute:'2-digit'}}) + '*'; }}
          lines.push(label + time, '', text, '', '---', '');
        }});
      }}
      var fname = title.replace(/[^a-z0-9]+/gi, '-').toLowerCase().slice(0, 60) + '.md';
      downloadText(fname, lines.join('\\n'), 'text/markdown');
    }}

    function downloadText(filename, text, mime) {{
      var blob = new Blob([text], {{ type: mime }});
      var url  = URL.createObjectURL(blob);
      var a    = document.createElement('a');
      a.href = url; a.download = filename; a.click();
      setTimeout(function() {{ URL.revokeObjectURL(url); }}, 1000);
    }}
    function sessionsToCSV(ids) {{
      var header = ['ID','Title','Date','Category','Messages','Tokens','Cost','Notes','Starred'];
      var rows   = [header];
      ids.forEach(function(id) {{
        var s = sessions[id]; if (!s) return;
        var cell = function(v) {{
          var sv = String(v == null ? '' : v);
          return sv.includes(',') || sv.includes('"') || sv.includes('\\n')
            ? '"' + sv.replace(/"/g, '""') + '"' : sv;
        }};
        rows.push([
          cell(id),
          cell(localStorage.getItem('claude-title-' + id) || ''),
          cell((s.date_iso || '').slice(0,16).replace('T',' ')),
          cell(s.category || ''),
          cell(s.msg_count || 0),
          cell(s.total_tokens || 0),
          cell(s.cost_usd ? s.cost_usd.toFixed(4) : '0'),
          cell(localStorage.getItem('claude-notes-' + id) || ''),
          cell(localStorage.getItem('claude-star-' + id) ? 'yes' : '')
        ].join(','));
      }});
      return rows.join('\\n');
    }}
    function exportCSV() {{
      var ids = getVisibleRows().map(function(r) {{ return r.getAttribute('data-id'); }});
      downloadText('sessions-export.csv', sessionsToCSV(ids), 'text/csv');
    }}
    function exportSelectedCSV() {{
      var ids = getSelected(); if (!ids.length) return;
      downloadText('sessions-selected.csv', sessionsToCSV(ids), 'text/csv');
    }}
    function exportAnnotations() {{
      var data = {{}};
      Object.keys(sessions).forEach(function(id) {{
        var entry = {{}};
        var t = localStorage.getItem('claude-title-' + id); if (t) entry.title  = t;
        var s = localStorage.getItem('claude-star-'  + id); if (s) entry.star   = 1;
        var l = localStorage.getItem('claude-label-' + id); if (l) entry.label  = l;
        var n = localStorage.getItem('claude-notes-' + id); if (n) entry.notes  = n;
        if (Object.keys(entry).length) data[id] = entry;
      }});
      downloadText('annotations.json', JSON.stringify(data, null, 2), 'application/json');
    }}
    function importAnnotations(e) {{
      var file = e.target.files[0]; if (!file) return;
      var reader = new FileReader();
      reader.onload = function(ev) {{
        try {{
          var data = JSON.parse(ev.target.result);
          var count = 0;
          Object.keys(data).forEach(function(id) {{
            var entry = data[id];
            if (entry.title) localStorage.setItem('claude-title-' + id, entry.title);
            if (entry.star)  localStorage.setItem('claude-star-'  + id, '1');
            if (entry.label) localStorage.setItem('claude-label-' + id, entry.label);
            if (entry.notes) localStorage.setItem('claude-notes-' + id, entry.notes);
            count++;
          }});
          showToast('Imported annotations for ' + count + ' sessions. Reloading...');
          setTimeout(function() {{ location.reload(); }}, 1500);
        }} catch(err) {{ showToast('Import failed: invalid JSON'); }}
      }};
      reader.readAsText(file);
      e.target.value = '';
    }}

    // ── Stars ───────────────────────────────────────────────────────────────
    function starKey(id) {{ return 'claude-star-' + id; }}
    function toggleStar(id) {{
      var btn = document.getElementById('star-' + id);
      if (localStorage.getItem(starKey(id))) {{
        localStorage.removeItem(starKey(id));
        btn.classList.remove('starred');
      }} else {{
        localStorage.setItem(starKey(id), '1');
        btn.classList.add('starred');
      }}
    }}
    function loadStars() {{
      document.querySelectorAll('.star-btn').forEach(function(btn) {{
        var id = btn.id.replace('star-', '');
        if (localStorage.getItem(starKey(id))) {{ btn.classList.add('starred'); }}
      }});
    }}

    // ── Color labels ────────────────────────────────────────────────────────
    var activeLabelId = null;
    function labelKey(id) {{ return 'claude-label-' + id; }}
    function openLabelPicker(id, el) {{
      activeLabelId = id;
      var picker = document.getElementById('label-picker');
      var rect = el.getBoundingClientRect();
      picker.style.display = 'flex';
      picker.style.top  = (rect.bottom + window.scrollY + 6) + 'px';
      picker.style.left = Math.max(4, rect.left + window.scrollX - 60) + 'px';
    }}
    function closeLabelPicker() {{
      document.getElementById('label-picker').style.display = 'none';
      activeLabelId = null;
    }}
    function setLabel(color) {{
      var id = activeLabelId; if (!id) return;
      var dot = document.getElementById('ldot-' + id); if (!dot) {{ closeLabelPicker(); return; }}
      dot.className = 'label-dot';
      if (color) {{ localStorage.setItem(labelKey(id), color); dot.classList.add('lc-' + color); dot.title = color; }}
      else {{ localStorage.removeItem(labelKey(id)); dot.title = 'Set label'; }}
      closeLabelPicker();
    }}
    function loadLabels() {{
      document.querySelectorAll('.label-dot').forEach(function(dot) {{
        var id = dot.id.replace('ldot-', '');
        var c = localStorage.getItem(labelKey(id));
        if (c) {{ dot.classList.add('lc-' + c); dot.title = c; }} else {{ dot.title = 'Set label'; }}
      }});
    }}

    // ── Notes ────────────────────────────────────────────────────────────────
    function notesKey(id) {{ return 'claude-notes-' + id; }}
    function editNotes(id, el) {{
      var current = localStorage.getItem(notesKey(id)) || '';
      var ta = document.createElement('textarea');
      ta.className = 'notes-input'; ta.value = current; ta.placeholder = 'Add notes...';
      function save() {{
        var val = ta.value.trim();
        if (val) {{ localStorage.setItem(notesKey(id), val); el.textContent = val.length > 28 ? val.slice(0,28)+'…' : val; el.classList.add('has-note'); }}
        else {{ localStorage.removeItem(notesKey(id)); el.textContent = '+'; el.classList.remove('has-note'); }}
        el.style.display = ''; ta.remove();
      }}
      ta.addEventListener('blur', save);
      ta.addEventListener('keydown', function(e) {{ if (e.key === 'Escape') {{ ta.value = current; ta.blur(); }} }});
      el.style.display = 'none'; el.parentElement.insertBefore(ta, el.nextSibling); ta.focus();
    }}
    function loadNotes() {{
      document.querySelectorAll('[id^="notes-"]').forEach(function(el) {{
        var id = el.id.replace('notes-', '');
        var note = localStorage.getItem(notesKey(id));
        if (note) {{ el.textContent = note.length > 28 ? note.slice(0,28)+'…' : note; el.classList.add('has-note'); }}
      }});
    }}

    // ── Sort ─────────────────────────────────────────────────────────────────
    var sortState = {{ col: null, dir: 1 }};
    function sortBy(col, th) {{
      var page = document.querySelector('.page.active'); if (!page) return;
      var tbody = page.querySelector('tbody'); if (!tbody) return;
      if (sortState.col === col) {{ sortState.dir *= -1; }} else {{ sortState.col = col; sortState.dir = 1; }}
      document.querySelectorAll('.sortable').forEach(function(h) {{
        var si = h.querySelector('.sort-icon'); if (si) si.textContent = 'unfold_more';
        h.classList.remove('sort-asc','sort-desc');
      }});
      if (th) {{
        var si = th.querySelector('.sort-icon');
        if (si) si.textContent = sortState.dir === 1 ? 'arrow_upward' : 'arrow_downward';
        th.classList.add(sortState.dir === 1 ? 'sort-asc' : 'sort-desc');
      }}
      var rows = Array.from(tbody.querySelectorAll('tr'));
      rows.sort(function(a,b) {{
        var va = getSortVal(a,col), vb = getSortVal(b,col);
        return va < vb ? -sortState.dir : va > vb ? sortState.dir : 0;
      }});
      rows.forEach(function(r) {{ tbody.appendChild(r); }});
    }}
    function getSortVal(row, col) {{
      var id = row.getAttribute('data-id');
      if (col==='num')    return parseInt(row.querySelector('.col-num') && row.querySelector('.col-num').textContent || '0');
      if (col==='date')   return row.getAttribute('data-date') || '';
      if (col==='msgs')   return parseInt(row.getAttribute('data-msgs') || '0');
      if (col==='tokens') return parseInt(row.getAttribute('data-tokens') || '0');
      if (col==='cost')   return parseFloat(row.getAttribute('data-cost') || '0');
      if (col==='cat')    return (row.getAttribute('data-cat') || '').toLowerCase();
      if (col==='title')  return (localStorage.getItem('claude-title-' + id) || '').toLowerCase();
      if (col==='star')   return localStorage.getItem('claude-star-' + id) ? 0 : 1;
      return '';
    }}

    // ── Column visibility ────────────────────────────────────────────────────
    var colVis = {{}};
    function toggleColVis(col) {{
      var hidden = document.body.classList.toggle('hide-col-' + col);
      colVis[col] = !hidden; localStorage.setItem('claude-col-vis', JSON.stringify(colVis));
    }}
    function toggleColMenu() {{ document.getElementById('col-vis-menu').classList.toggle('open'); }}
    function loadColVis() {{
      var saved = localStorage.getItem('claude-col-vis');
      if (saved) {{ try {{ colVis = JSON.parse(saved); }} catch(e) {{}} }}
      document.querySelectorAll('.col-toggle').forEach(function(cb) {{
        var col = cb.getAttribute('data-col');
        var vis = colVis[col] !== false;
        cb.checked = vis;
        if (!vis) document.body.classList.add('hide-col-' + col);
        cb.onchange = function() {{ toggleColVis(col); }};
      }});
    }}

    // ── Column drag-to-reorder ───────────────────────────────────────────────
    // Columns that map directly to a <th>/<td> class (topic is inside title cell)
    var REORDERABLE = ['title','star','label','notes','cat','date','summary','size','msgs','tok','cost'];
    // Full column order including fixed columns
    var FULL_COLS   = ['check','num','title','star','label','notes','summary','cat','date','size','msgs','tok','cost','menu'];

    function getMenuColOrder() {{
      var order = [];
      document.querySelectorAll('#col-vis-menu label[data-col]').forEach(function(lbl) {{
        var col = lbl.getAttribute('data-col');
        if (REORDERABLE.indexOf(col) >= 0) order.push(col);
      }});
      return order;
    }}

    function applyColOrder() {{
      var reorderable = getMenuColOrder();
      var ri = 0;
      var fullOrder = FULL_COLS.map(function(col) {{
        return REORDERABLE.indexOf(col) >= 0 ? reorderable[ri++] : col;
      }});
      document.querySelectorAll('table').forEach(function(table) {{
        table.querySelectorAll('tr').forEach(function(row) {{
          fullOrder.forEach(function(col) {{
            var cell = row.querySelector('.col-' + col);
            if (cell) row.appendChild(cell);
          }});
        }});
      }});
      localStorage.setItem('claude-col-order', JSON.stringify(reorderable));
    }}

    function loadColOrder() {{
      var saved = localStorage.getItem('claude-col-order');
      if (!saved) return;
      try {{
        var order = JSON.parse(saved);
        var menu = document.getElementById('col-vis-menu');
        // Reorder labels in menu to match saved order
        order.forEach(function(col) {{
          var lbl = menu.querySelector('label[data-col="' + col + '"]');
          if (lbl) menu.appendChild(lbl);
        }});
        applyColOrder();
      }} catch(e) {{}}
    }}

    var _dragLbl = null;
    function initColDrag() {{
      var menu = document.getElementById('col-vis-menu');
      menu.querySelectorAll('label[draggable]').forEach(function(lbl) {{
        lbl.addEventListener('dragstart', function(e) {{
          _dragLbl = lbl;
          e.dataTransfer.effectAllowed = 'move';
          setTimeout(function() {{ lbl.classList.add('col-dragging'); }}, 0);
        }});
        lbl.addEventListener('dragend', function() {{
          lbl.classList.remove('col-dragging');
          menu.querySelectorAll('label').forEach(function(l) {{ l.classList.remove('col-drag-over'); }});
          applyColOrder();
        }});
        lbl.addEventListener('dragover', function(e) {{
          e.preventDefault();
          if (!_dragLbl || _dragLbl === lbl) return;
          menu.querySelectorAll('label').forEach(function(l) {{ l.classList.remove('col-drag-over'); }});
          lbl.classList.add('col-drag-over');
          var rect = lbl.getBoundingClientRect();
          if (e.clientY < rect.top + rect.height / 2) {{
            menu.insertBefore(_dragLbl, lbl);
          }} else {{
            menu.insertBefore(_dragLbl, lbl.nextSibling);
          }}
        }});
        lbl.addEventListener('dragleave', function() {{
          lbl.classList.remove('col-drag-over');
        }});
        lbl.addEventListener('drop', function(e) {{ e.preventDefault(); }});
      }});
    }}

    // ── Dark mode (follows OS by default; localStorage overrides) ───────────
    function applyTheme(dark) {{
      document.body.classList.toggle('dark', dark);
      var btn = document.getElementById('darkmode-btn');
      if (btn) btn.innerHTML = dark ? '<span class="mi mi-sm">dark_mode</span> Theme' : '<span class="mi mi-sm">light_mode</span> Theme';
    }}
    function toggleDarkMode() {{
      var nowDark = !document.body.classList.contains('dark');
      localStorage.setItem('claude-theme', nowDark ? 'dark' : 'light');
      applyTheme(nowDark);
    }}
    function loadDarkMode() {{
      var stored = localStorage.getItem('claude-theme');
      var osDark = window.matchMedia && window.matchMedia('(prefers-color-scheme:dark)').matches;
      applyTheme(stored ? stored === 'dark' : osDark);
      if (window.matchMedia) {{
        window.matchMedia('(prefers-color-scheme:dark)').addEventListener('change', function(e) {{
          if (!localStorage.getItem('claude-theme')) applyTheme(e.matches);
        }});
      }}
    }}

    // ── Copy resume command ─────────────────────────────────────────────────
    function copyResume(id) {{
      var s = sessions[id];
      if (!s) return;
      navigator.clipboard.writeText(s.resume).then(function() {{
        var btn = document.getElementById('copybtn-' + id);
        if (btn) {{
          var origHtml = btn.innerHTML;
          btn.innerHTML = '<span class="mi mi-xs">check</span> Copied!';
          btn.classList.add('copied');
          setTimeout(function() {{ btn.innerHTML = origHtml; btn.classList.remove('copied'); }}, 2000);
        }}
        showToast('Resume command copied to clipboard!');
      }}).catch(function() {{
        showToast('Copy failed — select manually from the tooltip');
      }});
    }}

    // ── Heatmap toggle ───────────────────────────────────────────────────────
    function toggleHeatmap() {{
      var sec = document.getElementById('heatmap-section');
      var btn = document.getElementById('heatmap-toggle');
      var collapsed = sec.classList.toggle('collapsed');
      localStorage.setItem('claude-heatmap-collapsed', collapsed ? '1' : '0');
      if (btn) btn.innerHTML = collapsed ? '<span class="mi mi-sm">expand_more</span>' : '<span class="mi mi-sm">expand_less</span>';
    }}

    // URL hash deep-link
    if (window.location.hash) {{
      var hid = window.location.hash.slice(1);
      if (sessions[hid]) {{ openModal(hid); history.replaceState(null,'',window.location.pathname); }}
    }}

    // ── Init ────────────────────────────────────────────────────────────────
    loadTitles();
    loadStars();
    loadLabels();
    loadNotes();
    loadColVis();
    initColDrag();
    loadColOrder();
    loadDarkMode();
    // Populate relative dates in all static date cells
    document.querySelectorAll('td.col-date[data-iso]').forEach(function(td) {{
      td.textContent = relDate(td.getAttribute('data-iso'));
    }});
    buildHeatmap();
    buildRecentTab();
    buildArchivedTab();
    applyDeletions();
    applyFilters();
  </script>
</body>
</html>"""

# ── Hook installer ────────────────────────────────────────────────────────────

def install_hook() -> None:
    """Auto-install the Stop hook into ~/.claude/settings.json if not already present."""
    settings_path = HOME / ".claude" / "settings.json"
    script_path   = str(Path(__file__).resolve())
    hook_command  = f"python3 {script_path}"

    # Read existing settings or start fresh
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            settings = {}
    else:
        settings = {}

    # Check if our hook is already present
    for entry in settings.get("hooks", {}).get("Stop", []):
        for hook in entry.get("hooks", []):
            if hook.get("command") == hook_command:
                return  # Already installed, nothing to do

    # Add the hook
    settings.setdefault("hooks", {}).setdefault("Stop", []).append({
        "matcher": "",
        "hooks": [{"type": "command", "command": hook_command}],
    })

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    print(f"✓ Auto-update hook installed in {settings_path}")
    print("  Your dashboard will now regenerate after every Claude Code session.")

# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    install_hook()
    projects = scan()
    html     = build_html(projects)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    total = sum(len(v) for v in projects.values())
    print(f"✓ Generated {OUTPUT_FILE} — {total} sessions across {len(projects)} projects")
