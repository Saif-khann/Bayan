"""Web demo: ask the Saudi Labor Law, or review an employment contract."""
import html
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import gradio as gr
from google import genai
from pypdf import PdfReader

from answer import answer
from hybrid import HybridSearch
from review_contract import review_clause, split_clauses

engine = HybridSearch()
client = genai.Client()
MAX_CLAUSES = 25
SAMPLE = Path("data/contracts/sample_contract_en.txt").read_text(encoding="utf-8")
ARTICLES = {r["article_number"]: r for r in
            json.loads(Path("data/processed/labor_law_en.json").read_text(encoding="utf-8"))}
AMENDMENTS = {a["id"]: a for a in
              json.loads(Path("data/processed/labor_law_en_amendments.json").read_text(encoding="utf-8"))}
CITATION = re.compile(r"(?:Article|المادة)\s*\(?(\d+)\)?")
BUSY = '<p class="note">The AI service is busy right now. Wait a minute and try again.</p>'

EMPTY_ASK = """<div class="empty"><p>Ask about probation, leave, wages, working hours,
termination, or end-of-service pay. Every answer cites the articles it relies on,
using the text currently in force.</p></div>"""

TOGGLE_HINT = '<span class="hint"><span class="show">Show text and history</span><span class="hide">Hide</span></span>'


# ---------- rendering ----------

def format_text(text: str) -> str:
    """Escape model output, keep paragraphs, bold, and highlight article citations."""
    out = []
    for line in (l.strip() for l in text.split("\n")):
        if not line:
            continue
        line = re.sub(r"^[\*\-]\s+", "• ", line)
        line = html.escape(line)
        line = line.replace("[", "").replace("]", "")
        line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
        line = CITATION.sub(lambda m: f'<span class="cite">{m.group(0)}</span>', line)
        out.append(f'<p dir="auto">{line}</p>')
    return "".join(out)


def article_panel(n: int) -> str:
    """One cited article, expandable into its amendment history."""
    r = ARTICLES[n]
    where = " / ".join(x for x in (r["part"], r["chapter"]) if x)
    events = [("2005", "Original text", html.escape(r["text"]))]
    for aid in r["amendments"]:
        a = AMENDMENTS[aid]
        body = html.escape(a["instruction"])
        if a["text"]:
            body += "\n\n" + html.escape(a["text"])
        events.append((a["date"][-4:] if a["date"] else "", f"Amended by Royal Decree {a['decree']}", body))

    items = []
    for i, (year, what, body) in enumerate(events):
        current = i == len(events) - 1
        tag = '<span class="inforce">In force</span>' if current else ""
        items.append(f'<li class="{"current" if current else "past"}"><div class="ev">'
                     f'<span class="when">{year}</span><span class="what">{what}</span>{tag}</div>'
                     f'<div class="body">{body}</div></li>')
    return (f'<details class="article"><summary><span class="num">Article {n}</span>'
            f'<span class="meta">{html.escape(where)}</span>{TOGGLE_HINT}</summary>'
            f'<ol class="timeline">{"".join(items)}</ol></details>')


STATUS = {"violation": ("Violation", "bad"), "needs_review": ("Needs review", "warn"),
          "compliant": ("Compliant", "ok")}


def clause_block(c: dict, r: dict) -> str:
    label, cls = STATUS.get(r["status"], STATUS["needs_review"])
    cites = "".join(f'<span class="cite">Article {n}</span>' for n in r["articles"])
    detail = ""
    if r["status"] != "compliant":
        detail = f'<p class="issue" dir="auto">{html.escape(r.get("issue", ""))}</p>'
        if r.get("suggested_fix"):
            detail += (f'<div class="fix"><span>Suggested wording</span>'
                       f'<p dir="auto">{html.escape(r["suggested_fix"])}</p></div>')
    return (f'<div class="clause {cls}"><div class="head"><span class="status">{label}</span>'
            f'<span class="cnum">Clause {c["number"]}</span>{cites}</div>'
            f'<p class="ctext" dir="auto">{html.escape(c["text"])}</p>{detail}</div>')


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


# ---------- actions ----------

def ask(question: str):
    question = (question or "").strip()[:500]
    if not question:
        yield EMPTY_ASK
        return
    yield '<p class="note">Searching the law and writing an answer…</p>'
    try:
        text, _, _, _ = answer(question, engine, client)
    except Exception:
        yield BUSY
        return
    cited = []
    for m in CITATION.finditer(text):
        n = int(m.group(1))
        if n in engine.by_num and n not in cited:  # only articles in force
            cited.append(n)
    out = f'<div class="answer">{format_text(text)}</div>'
    if cited:
        out += '<div class="sources"><h3>Sources</h3>' + "".join(article_panel(n) for n in cited) + "</div>"
    yield out


def read_contract(contract_text: str, contract_file) -> str:
    if contract_file:
        path = Path(contract_file)
        if path.suffix.lower() == ".pdf":
            return "\n".join(p.extract_text() or "" for p in PdfReader(path).pages)
        return path.read_text(encoding="utf-8")
    return contract_text or ""


def review(contract_text: str, contract_file):
    preamble, clauses = split_clauses(read_contract(contract_text, contract_file))
    if not clauses:
        yield ('<p class="note">No numbered clauses found. Put each clause on its own line, '
               'starting with a number, like <code>1. Probation: ...</code></p>')
        return

    clauses = clauses[:MAX_CLAUSES]
    results = []
    for i, c in enumerate(clauses, 1):
        yield f'<p class="note">Checking clause {i} of {len(clauses)}…</p>'
        try:
            r = review_clause(c, preamble, engine, client)
        except Exception:
            r = {"status": "needs_review", "articles": [], "suggested_fix": "",
                 "issue": "The AI service did not respond for this clause. Run the review again."}
        results.append((c, r))
        time.sleep(2)  # free-tier rate limit

    by_status = {s: [(c, r) for c, r in results if r["status"] == s] for s in STATUS}
    flagged = by_status["violation"] + by_status["needs_review"]
    ok = by_status["compliant"]

    v, nr = len(by_status["violation"]), len(by_status["needs_review"])
    parts = [f'<span class="bad">{plural(v, "violation")}</span>' if v
             else '<span class="ok">No violations found</span>']
    if nr:
        parts.append(f'<span class="warn">{nr} to review</span>')
    parts.append(f'<span class="ok">{len(ok)} compliant</span>')
    out = f'<div class="summary">{"".join(parts)}</div>'

    out += "".join(clause_block(c, r) for c, r in flagged)
    if ok:
        out += (f'<details class="okgroup"><summary>Show {plural(len(ok), "compliant clause")}</summary>'
                + "".join(clause_block(c, r) for c, r in ok) + "</details>")
    yield out


# ---------- layout ----------

CSS = """
:root { --ink:#1F5C45; --ink-tint:rgba(31,92,69,.09); --bad:#B42318; --warn:#B54708; }
.dark { --ink:#7CC4A2; --ink-tint:rgba(124,196,162,.13); --bad:#F97066; --warn:#FDB022; }
footer { display:none !important; }
.gradio-container { max-width:780px !important; margin:0 auto !important; }

#title { padding:28px 0 8px; }
#title h1 { font-size:1.75rem; font-weight:600; letter-spacing:-.01em; margin:0 0 6px; }
#title p { margin:0; color:var(--body-text-color-subdued); max-width:60ch; }
.note, .empty p, .fine { color:var(--body-text-color-subdued); }
.fine { font-size:.82rem; margin-top:24px; }

.answer { padding-top:8px; }
.answer p { font-size:1.04rem; line-height:1.75; margin:0 0 12px; max-width:68ch; }
.answer p:last-child { font-size:.84rem; color:var(--body-text-color-subdued); }
.cite { display:inline-block; padding:0 6px; margin:0 2px; border-radius:4px;
        background:var(--ink-tint); color:var(--ink); font-weight:500; white-space:nowrap; }

/* ---- expandable rows: chevron + hint ---- */
details.article > summary, details.okgroup > summary {
        list-style:none; cursor:pointer; display:flex; gap:10px; align-items:baseline;
        border-radius:4px; }
details.article > summary::-webkit-details-marker,
details.okgroup > summary::-webkit-details-marker { display:none; }
details.article > summary::before, details.okgroup > summary::before {
        content:""; flex:none; align-self:center; width:6px; height:6px; margin:0 4px 0 2px;
        border-right:2px solid var(--body-text-color-subdued);
        border-bottom:2px solid var(--body-text-color-subdued);
        transform:rotate(-45deg); }
details[open] > summary::before { transform:rotate(45deg); }
@media (prefers-reduced-motion: no-preference) {
        details > summary::before { transition:transform .15s ease; } }
details > summary:focus-visible { outline:2px solid var(--ink); outline-offset:3px; }
details.article > summary:hover .num { text-decoration:underline; text-underline-offset:3px; }
.hint { flex:none; margin-left:auto; font-size:.8rem; color:var(--body-text-color-subdued); }
.hint .hide, details[open] .hint .show { display:none; }
details[open] .hint .hide { display:inline; }

/* ---- sources ---- */
.sources h3 { font-size:.9rem; font-weight:600; margin:24px 0 4px; color:var(--body-text-color-subdued); }
details.article { border-top:1px solid var(--border-color-primary); padding:12px 0; }
details.article .num { font-weight:600; color:var(--ink); white-space:nowrap; }
details.article .meta { flex:1 1 auto; min-width:0; color:var(--body-text-color-subdued);
        font-size:.85rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.timeline { list-style:none; margin:14px 0 4px; padding:0 0 0 14px;
        border-left:2px solid var(--border-color-primary); }
.timeline li { margin:0 0 16px; }
.timeline .ev { display:flex; gap:10px; align-items:baseline; font-size:.85rem; }
.timeline .when { font-weight:600; }
.timeline .inforce { color:var(--ink); font-weight:600; }
.timeline .body { white-space:pre-line; font-size:.92rem; line-height:1.6; margin-top:4px; }
.timeline .past { opacity:.55; }
.timeline .current .body { border-left:3px solid var(--ink); padding-left:10px; margin-left:-17px; }

/* ---- contract review ---- */
.summary { display:flex; gap:20px; font-weight:600; padding:16px 0; }
.summary .bad { color:var(--bad); } .summary .warn { color:var(--warn); }
.summary .ok { color:var(--body-text-color-subdued); }
.clause { border-top:1px solid var(--border-color-primary); padding:16px 0 16px 14px;
        border-left:3px solid transparent; }
.clause.bad { border-left-color:var(--bad); } .clause.warn { border-left-color:var(--warn); }
.clause .head { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
.clause .status { font-weight:600; }
.clause.bad .status { color:var(--bad); } .clause.warn .status { color:var(--warn); }
.clause.ok .status { color:var(--body-text-color-subdued); }
.clause .cnum { color:var(--body-text-color-subdued); font-size:.85rem; }
.clause .ctext { margin:8px 0; line-height:1.6; }
.clause .issue { margin:0 0 10px; line-height:1.6; }
.fix { background:var(--background-fill-secondary); border-radius:6px; padding:10px 12px; }
.fix span { font-size:.8rem; color:var(--body-text-color-subdued); }
.fix p { margin:4px 0 0; line-height:1.6; }
details.okgroup { border-top:1px solid var(--border-color-primary); padding-top:12px; }
details.okgroup > summary { color:var(--body-text-color-subdued); padding-bottom:4px; }

@media (max-width:600px) { details.article .meta { display:none; } }
"""

theme = gr.themes.Base(
    primary_hue="emerald",
    neutral_hue="gray",
    font=[gr.themes.GoogleFont("IBM Plex Sans Arabic"), "system-ui", "sans-serif"],
    radius_size=gr.themes.sizes.radius_sm,
).set(
    button_primary_background_fill="#1F5C45",
    button_primary_background_fill_hover="#174A37",
    button_primary_text_color="#FFFFFF",
    button_primary_background_fill_dark="#2F7A5C",
    button_primary_background_fill_hover_dark="#3A8C6A",
)

with gr.Blocks(title="Saudi Labor Law Assistant") as demo:
    gr.HTML('<div id="title"><h1>Saudi Labor Law Assistant</h1>'
            '<p>Answers and contract checks grounded in the official Labor Law, '
            'including every amendment through 2024.</p></div>')

    with gr.Tab("Ask"):
        with gr.Row(equal_height=True):
            question = gr.Textbox(show_label=False, container=False, scale=6, autofocus=True,
                                  placeholder="Ask in English or Arabic")
            ask_btn = gr.Button("Ask", variant="primary", scale=1, min_width=90)
        gr.Examples(["What is the maximum probation period?",
                     "How much notice must an employer give to end a contract?",
                     "ما هي مدة إجازة الوضع؟",
                     "Can I work for another company on the side?"],
                    inputs=question)
        ask_out = gr.HTML(EMPTY_ASK)
        ask_btn.click(ask, question, ask_out, show_progress="minimal")
        question.submit(ask, question, ask_out, show_progress="minimal")

    with gr.Tab("Review a contract"):
        gr.HTML('<p class="note">Paste an employment contract with numbered clauses, or upload '
                'a .txt or PDF file. Each clause is checked against the law.</p>')
        contract_text = gr.Textbox(show_label=False, lines=8, max_lines=24, value=SAMPLE)
        contract_file = gr.File(label="Or upload a file", file_types=[".txt", ".pdf"],
                                type="filepath", height=110)
        review_btn = gr.Button("Review contract", variant="primary")
        review_out = gr.HTML()
        review_btn.click(review, [contract_text, contract_file], review_out)

    gr.HTML('<p class="fine">Demo project, not legal advice. Do not upload real or confidential contracts.</p>')

demo.queue(default_concurrency_limit=1)
demo.launch(theme=theme, css=CSS)