"""HTML pages of the web GUI (see server.py). Every piece of document text goes through esc() or
text(); pages use no inline scripts or styles, so the server can send a strict Content-Security-Policy."""

import html
import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urlencode

from .analysis import Analysis, Dashboard, Detail, Item
from .model import WHOLE

TOPIC_PREFIX = "topic:"
_ESCAPED_XREF = re.compile(r"&lt;&lt;\s*([A-Za-z0-9_:.-]+)\s*(?:,\s*(.*?))?&gt;&gt;")
_WEB_URL = re.compile(r"^https?://", re.I)

SECTIONS = [
    ("overdue", "Overdue", "Open revisits past their due date."),
    ("due", "Due time subscriptions", "Record the time.elapsed event, then open the revisit it needs."),
    ("missing", "Missing revisits", "An event reaches these subscribers, but no revisit is recorded yet."),
    ("open", "Open", "Open revisits that are not yet due."),
]
TABLES = {"triggers-events": "Events", "triggers-revisits": "Revisits"}


@dataclass
class Context:
    """What every page needs besides its own data."""
    path: Path  # the document, as given on the command line
    version: str  # the live-reload token the page was rendered at
    today: date  # the real date, to tell a what-if evaluation date from a real one
    analysis: Optional[Analysis] = None  # None when the document could not be read
    date_param: Optional[str] = None  # ?date= as given; kept on every link
    editor_url: Optional[str] = None
    notices: list = field(default_factory=list)  # plain-text messages shown above the page


# --- helpers ----------------------------------------------------------------


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def href(ctx: Context, path: str, **params) -> str:
    query = {"date": ctx.date_param} if ctx.date_param else {}
    query.update({key: value for key, value in params.items() if value})
    return path + ("?" + urlencode(query) if query else "")


def element_href(ctx: Context, element_id: str) -> str:
    return href(ctx, "/elements/" + quote(element_id, safe=""))


def text(ctx: Context, value: str) -> str:
    """Escape document text, then turn <<id>> and <<id,label>> into links to known elements."""
    def link(m):
        target = html.unescape(m.group(1))
        label = m.group(2) or m.group(1)  # both already escaped
        if ctx.analysis and target in ctx.analysis.graph.elements:
            return f'<a href="{esc(element_href(ctx, target))}">{label}</a>'
        return label
    return _ESCAPED_XREF.sub(link, esc(value))


def ref(ctx: Context, value: Optional[str], title: bool = True) -> str:
    """An element ID as a link, with its title; an external URI or unknown value as text."""
    if not value:
        return '<span class="muted">—</span>'
    element = ctx.analysis.graph.elements.get(value) if ctx.analysis else None
    if element is None:
        if _WEB_URL.match(value):
            return f'<a href="{esc(value)}" rel="noopener noreferrer">{esc(value)}</a>'
        return f"<code>{esc(value)}</code>"
    out = f'<a class="id" href="{esc(element_href(ctx, value))}" title="{esc(element.kind)}">{esc(value)}</a>'
    if title and element.title:
        out += f' <span class="muted">{text(ctx, element.title)}</span>'
    return out


def refs(ctx: Context, values, title: bool = False) -> str:
    return ", ".join(ref(ctx, v, title) for v in values)


def subject(ctx: Context, value: str) -> str:
    if value.startswith(TOPIC_PREFIX) and ctx.analysis:
        mapped = ctx.analysis.doc.topics.get(value[len(TOPIC_PREFIX):], [])
        return f"<code>{esc(value)}</code>" + (f" → {refs(ctx, mapped)}" if mapped else "")
    return ref(ctx, value, title=False)


def scope(ctx: Context, value) -> str:
    return "whole" if value == WHOLE else "inputs " + refs(ctx, sorted(value or ()))


def iso(value: Optional[date]) -> str:
    return value.isoformat() if value else "—"


def _days(n: int) -> str:
    return f"{n} day{'' if n == 1 else 's'}"


def relative(state: str, days: Optional[int]) -> str:
    if days is None:
        return ""
    if state == "due":
        return "fell due today" if days == 0 else f"fell due {_days(-days)} ago"
    if days < 0:
        return f"{_days(-days)} overdue"
    return "due today" if days == 0 else f"due in {_days(days)}"


def source(ctx: Context, location) -> str:
    """file:line, relative to the document's folder; a link when an editor URL template is set."""
    if location is None:
        return ""
    absolute = Path(location.file).resolve()
    try:
        shown = os.path.relpath(absolute, ctx.path.resolve().parent)
    except ValueError:  # another drive on Windows
        shown = str(absolute)
    label = esc(f"{shown}:{location.line}")
    if not ctx.editor_url:
        return f'<span class="muted">{label}</span>'
    url = ctx.editor_url.replace("{path}", quote(absolute.as_posix(), safe="/:")).replace("{line}", str(location.line))
    return f'<a href="{esc(url)}">{label}</a>'


def badge(css: str, label: str) -> str:
    return f'<span class="badge {esc(css)}">{esc(label)}</span>'


def facts(pairs) -> str:
    rows = "".join(f"<dt>{esc(label)}</dt><dd>{value}</dd>" for label, value in pairs if value)
    return f'<dl class="facts">{rows}</dl>' if rows else ""


# --- layout -----------------------------------------------------------------


def _findings_notice(ctx: Context) -> str:
    findings = ctx.analysis.findings if ctx.analysis else []
    if not findings:
        return ""
    errors = sum(1 for f in findings if f.severity == "error")
    warnings = len(findings) - errors
    counts = ", ".join(part for part in (
        f"{errors} error{'' if errors == 1 else 's'}" if errors else "",
        f"{warnings} warning{'' if warnings == 1 else 's'}" if warnings else "") if part)
    hint = " — the status may be incomplete until they are fixed" if errors else ""
    items = "".join(
        f"<li>{source(ctx, f.location)} {badge('overdue' if f.severity == 'error' else 'due', f.rule)} "
        f"{esc(f.message)}</li>"
        for f in sorted(findings, key=lambda f: (f.severity != "error", str(f.location or ""))))
    level = "error" if errors else ""
    return (f'<details class="notice {level}"><summary><strong>{counts}</strong>{esc(hint)}. '
            f'<span class="muted">Run <code>arc42ext validate</code> for the same list.</span></summary>'
            f"<ul>{items}</ul></details>")


def layout(ctx: Context, title: str, body: str, current: str = "", here: str = "/",
           keep: Optional[dict] = None) -> str:
    """The page frame: document, navigation, evaluation date and notices. `here` is the page's own path
    and `keep` the query parameters, besides the date, that the date control must carry along."""
    a = ctx.analysis
    doc_title = (a.doc.title if a and a.doc.title else "") or ctx.path.name
    nav = "".join(
        f'<a href="{esc(href(ctx, path))}"{" aria-current=page" if key == current else ""}>{label}</a>'
        for key, path, label in (("dashboard", "/", "Dashboard"), ("elements", "/elements", "Elements")))
    keep = {k: v for k, v in (keep or {}).items() if v}
    hidden = "".join(f'<input type="hidden" name="{esc(k)}" value="{esc(v)}">' for k, v in keep.items())
    reset = ""
    if ctx.date_param:
        reset = f'<a href="{esc(here + ("?" + urlencode(keep) if keep else ""))}">Reset</a>'
    value = a.date.isoformat() if a else (ctx.date_param or "")
    notices = "".join(f'<div class="notice error">{esc(n)}</div>' for n in ctx.notices)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} · {esc(doc_title)}</title>
<link rel="stylesheet" href="/static/serve.css">
<script src="/static/serve.js" defer></script>
</head>
<body data-version="{esc(ctx.version)}">
<header class="top"><div class="top-inner">
<div class="doc"><h1>{esc(doc_title)}</h1><div class="path">{esc(ctx.path)}</div></div>
<nav aria-label="Views">{nav}</nav>
<form class="controls" method="get" data-autosubmit>
<label for="date">Evaluated at</label>
<input type="date" id="date" name="date" value="{esc(value)}" required>{hidden}
<button type="submit">Apply</button>{reset}
<span id="live" class="live" hidden>Live</span>
</form>
</div></header>
<main>
{notices}{_findings_notice(ctx)}{body}
</main>
</body>
</html>
"""


# --- dashboard --------------------------------------------------------------


def _rows(ctx: Context, item: Item, key: str) -> str:
    if not item.rows:
        return ""
    on = ctx.analysis.date
    if on > ctx.today:
        note = (f'<div class="rows-note whatif">What-if for {on.isoformat()}: these rows record things that have '
                f"not happened yet. Don't paste them before then.</div>")
    else:
        note = '<div class="rows-note">Append to the document:</div>'
    out = []
    for n, row in enumerate(item.rows):
        row_id = f"row-{key}-{n}"
        button = "" if on > ctx.today else f'<button type="button" data-copy="{row_id}">Copy</button>'
        out.append(f'<div class="row"><div class="row-body"><div class="table">{TABLES[row.table]} table '
                   f'<code>[.{esc(row.table)}]</code></div><pre id="{row_id}">{esc(row.text)}</pre></div>'
                   f"{button}</div>")
    return f'<div class="rows">{note}{"".join(out)}</div>'


def _responsible(ctx: Context, item: Item) -> str:
    if item.responsible:
        return ref(ctx, item.responsible)
    return '<span class="muted">not resolved; fill it in</span>'


def item_card(ctx: Context, item: Item, key: str) -> str:
    label = {"overdue": "Overdue", "due": "Due", "missing": "Missing", "open": "Open"}[item.state]
    when = relative(item.state, item.days_left)
    head = [badge(item.state, when if item.state == "overdue" and when else f"{label} · {when}" if when else label)]
    if item.revisit:
        head.append(f'<code>{esc(item.revisit.id)}</code>')
    head.append(f'<span class="title">{ref(ctx, item.subscriber)}</span>')

    event = item.event
    event_text = payload = None
    if event:
        event_text = (f"<code>{esc(event.id)}</code> <strong>{esc(event.type)}</strong> on {iso(event.date)}, "
                      f"subject {subject(ctx, event.subject)}")
        payload = esc("; ".join(f"{k}: {v}" for k, v in event.payload.items())) or None
    elif item.state == "due":
        event_text = '<span class="muted">none yet — evaluating the time subscription records one</span>'

    body = facts([
        ("Responsible", _responsible(ctx, item)),
        ("Due", iso(item.due)),
        ("Event", event_text),
        ("Payload", payload),
        ("Scope", scope(ctx, item.scope) if item.scope is not None else None),
        ("Opened", iso(item.revisit.opened) if item.revisit else None),
        ("Rationale", text(ctx, item.revisit.rationale) if item.revisit and item.revisit.rationale else None),
        ("Source", source(ctx, item.revisit.location) if item.revisit else None),
    ])
    return f'<article class="item"><div class="item-head">{" ".join(head)}</div>{body}{_rows(ctx, item, key)}</article>'


def _sections(ctx: Context, board: Dashboard, prefix: str) -> str:
    out = []
    for state, title, lead in SECTIONS:
        items = getattr(board, state)
        if items:
            cards = "".join(item_card(ctx, item, f"{prefix}{state}-{n}") for n, item in enumerate(items))
            out.append(f'<section id="{state}"><h2>{esc(title)} <span class="muted">({len(items)})</span></h2>'
                       f'<p class="lead muted">{esc(lead)}</p>{cards}</section>')
    return "".join(out)


def dashboard_page(ctx: Context, board: Dashboard, role: Optional[str]) -> str:
    a = ctx.analysis
    tiles = "".join(
        f'<a class="count {state}{" zero" if not getattr(board, state) else ""}" href="#{state}">'
        f"<strong>{len(getattr(board, state))}</strong><span>{esc(title)}</span></a>"
        for state, title, _ in SECTIONS)
    options = "".join(
        f'<option value="{esc(r)}"{" selected" if r == role else ""}>{esc(r)}'
        f'{esc(" — " + a.graph.elements[r].title) if a.graph.elements[r].title else ""}</option>'
        for r in board.roles)
    date_input = f'<input type="hidden" name="date" value="{esc(ctx.date_param)}">' if ctx.date_param else ""
    role_form = (f'<form class="filter-bar" method="get" data-autosubmit><label for="role">Responsible</label>'
                 f'<select id="role" name="role"><option value="">Anyone</option>{options}</select>{date_input}'
                 f'<button type="submit">Apply</button></form>')
    if board.empty:
        who = f" for {ref(ctx, role, title=False)}" if role else ""
        body = f'<div class="empty">Nothing needs action{who} at {a.date.isoformat()}.</div>'
    else:
        body = _sections(ctx, board, "")
    return layout(ctx, "Dashboard", f'<div class="counts">{tiles}</div>{role_form}{body}', "dashboard", "/",
                  keep={"role": role})


# --- element catalogue ------------------------------------------------------


def _state_badges(ctx: Context, state) -> str:
    if state is None:
        return ""
    if not state.active:
        return badge("inactive", "superseded")
    overdue = sum(1 for r in state.open_revisits if r in ctx.analysis.status.overdue)
    out = []
    if overdue:
        out.append(badge("overdue", f"{overdue} overdue"))
    if len(state.open_revisits) > overdue:
        out.append(badge("open", f"{len(state.open_revisits) - overdue} open"))
    if state.next_due:
        css = "due" if state.next_due <= ctx.analysis.date else "inactive"
        out.append(badge(css, f"next {state.next_due.isoformat()}"))
    return " ".join(out)


def catalogue_page(ctx: Context, groups: list, by: str) -> str:
    switch = " · ".join(
        f"<strong>{label}</strong>" if by == key else f'<a href="{esc(href(ctx, "/elements", by=key))}">{label}</a>'
        for key, label in (("section", "Section"), ("kind", "Kind")))
    bar = (f'<div class="filter-bar"><input type="search" id="filter" placeholder="Filter by ID, title or owner" '
           f'aria-label="Filter elements" hidden><span class="muted">Group by {switch}</span></div>')
    out = []
    for group, entries in groups:
        rows = "".join(
            f"<tr data-filter-row><td>{ref(ctx, e.element.id, title=False)}</td>"
            f'<td>{text(ctx, e.element.title or "")}</td><td class="nowrap">{esc(e.element.kind)}</td>'
            f"<td>{ref(ctx, e.owner, title=False) if e.owner else ''}</td>"
            f'<td class="num">{e.outgoing}</td><td class="num">{e.incoming}</td>'
            f"<td>{_state_badges(ctx, e.state)}</td></tr>"
            for e in entries)
        out.append(f'<section data-filter-group><h2>{esc(group)} <span class="muted">({len(entries)})</span></h2>'
                   f'<div class="table-wrap"><table><thead><tr><th scope="col">ID</th><th scope="col">Title</th>'
                   f'<th scope="col">Kind</th><th scope="col">Owner</th><th scope="col">Links out</th>'
                   f'<th scope="col">Links in</th><th scope="col">Revisits</th></tr></thead>'
                   f"<tbody>{rows}</tbody></table></div></section>")
    body = "".join(out) or '<div class="empty">The document has no elements.</div>'
    return layout(ctx, "Elements", bar + body, "elements", "/elements", keep={"by": by if by != "section" else None})


def _link_list(ctx: Context, grouped: dict, arrow: str) -> str:
    if not grouped:
        return '<p class="muted">None.</p>'
    items = "".join(f'<li><div class="type">{arrow}{esc(link_type)}</div>'
                    f'{"".join(f"<div>{ref(ctx, target)}</div>" for target in targets)}</li>'
                    for link_type, targets in grouped.items())
    return f'<ul class="links">{items}</ul>'


def _revisit_line(ctx: Context, revisit) -> str:
    a = ctx.analysis
    if revisit.outcome:
        status = badge(revisit.outcome, revisit.outcome)
    elif revisit.id in a.status.overdue:
        status = badge("overdue", "overdue")
    else:
        status = badge("open", "open")
    extra = [f"{label} {value}" for label, value in (
        ("effect:", esc(revisit.effect) if revisit.effect else ""),
        ("follows", f"<code>{esc(revisit.follows)}</code>" if revisit.follows else ""),
        ("successor", ref(ctx, revisit.successor, title=False) if revisit.successor else "")) if value]
    closed = f" · closed {iso(revisit.closed)}" if revisit.closed else ""
    rationale = f'<div class="rationale">{text(ctx, revisit.rationale)}</div>' if revisit.rationale else ""
    return (f"<li><code>{esc(revisit.id)}</code> {status} {scope(ctx, revisit.scope)} · responsible "
            f"{ref(ctx, revisit.responsible, title=False)} · opened {iso(revisit.opened)} · due {iso(revisit.due)}"
            f"{closed}{' · ' + ' · '.join(extra) if extra else ''} {source(ctx, revisit.location)}{rationale}</li>")


def _timeline(ctx: Context, detail: Detail) -> str:
    if not detail.timeline:
        return '<p class="muted">No event has reached it.</p>'
    out = []
    for entry in detail.timeline:
        event = entry.event
        if event:
            head = (f"<code>{esc(event.id)}</code> <strong>{esc(event.type)}</strong> · {iso(event.date)} · "
                    f"subject {subject(ctx, event.subject)}")
            payload = "; ".join(f"{k}: {v}" for k, v in event.payload.items())
            head += f'<div class="muted">{esc(payload)}</div>' if payload else ""
        else:
            head = f"<code>{esc(entry.event_id)}</code> <span class='muted'>(not in the event log)</span>"
        missing = f' {badge("missing", "no revisit recorded")}' if entry.missing else ""
        revisits = "".join(_revisit_line(ctx, r) for r in entry.revisits)
        out.append(f'<li>{head}{missing}{f"<ul class=revisits>{revisits}</ul>" if revisits else ""}</li>')
    return f'<ol class="timeline">{"".join(out)}</ol>'


def _subscriber(ctx: Context, detail: Detail) -> str:
    state = detail.state
    if state.active:
        status = badge("active", "active")
    else:
        status = badge("inactive", "superseded")
    superseded = ", ".join(
        f"by {ref(ctx, s, title=False)} " + (f"from {iso(on)}" if on else "<span class='muted'>(no baseline, so it "
                                                                         "never takes effect)</span>")
        for s, on in state.superseded_by)
    open_count = len(state.open_revisits)
    summary = facts([
        ("State", f"{status} {superseded}"),
        ("Baseline", iso(state.baseline)),
        ("Next time.elapsed", iso(state.next_due) if state.next_due else None),
        ("Open revisits", str(open_count) if open_count else None),
    ])
    rows = []
    for s in detail.subscriptions:
        if s.responsible_rule == "subject":
            responsible = '<span class="muted">the event\'s subject role</span>'
        else:
            responsible = ref(ctx, s.responsible, title=False)
            if s.responsible_rule in ("owner", "override"):
                responsible += f' <span class="muted">({s.responsible_rule})</span>'
        unknown = "" if s.known else " " + badge("overdue", "unknown type")
        rows.append(f"<tr><td><code>{esc(s.event_type)}</code>{unknown}</td><td>{esc(s.parameter)}</td>"
                    f"<td>{ref(ctx, s.subject, title=False) if s.subject else ''}</td><td>{responsible}</td>"
                    f"<td>{esc(s.duration)}{' <span class=muted>(override)</span>' if s.duration_rule == 'override' else ''}"
                    f"</td></tr>")
    table = (f'<div class="table-wrap"><table><thead><tr><th scope="col">Event type</th><th scope="col">Parameter'
             f'</th><th scope="col">Subject filter</th><th scope="col">Responsible</th><th scope="col">Time allowed'
             f'</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>') if rows else \
        '<p class="muted">No subscriptions; it only has a baseline.</p>'
    return (f'<section><h2>Revisits</h2>{summary}<h3>Subscriptions</h3>{table}'
            f"<h3>History</h3>{_timeline(ctx, detail)}</section>")


def element_page(ctx: Context, detail: Detail) -> str:
    e = detail.element
    head = (f'<div class="element-head">{badge("inactive", e.kind)} <code>{esc(e.id)}</code>'
            f"<h2>{text(ctx, e.title or e.id)}</h2>"
            f'<div class="muted">{esc(e.section or "")} {source(ctx, e.location)}</div></div>')
    topics = (f"<p>Topics: {', '.join(f'<code>{esc(t)}</code>' for t in detail.topics)}</p>"
              if detail.topics else "")
    links = (f'<div class="grid2"><div class="panel"><h3>Links</h3>{_link_list(ctx, detail.outgoing, "")}</div>'
             f'<div class="panel"><h3>Referenced by</h3>{_link_list(ctx, detail.incoming, "← ")}{topics}</div></div>')
    body = head + links
    if detail.state:
        body += _subscriber(ctx, detail)
    if detail.assigned is not None:
        role_link = esc(href(ctx, "/", role=e.id))
        assigned = (_sections(ctx, detail.assigned, "assigned-") if not detail.assigned.empty
                    else '<div class="empty">Nothing assigned to this role needs action.</div>')
        body += (f'<section><h2>Assigned to this role</h2><p class="lead"><a href="{role_link}">Open the dashboard '
                 f"filtered to {esc(e.id)}</a></p>{assigned}</section>")
    return layout(ctx, e.id, body, "elements", "/elements/" + quote(e.id, safe=""))


# --- errors -----------------------------------------------------------------


def error_page(ctx: Context, message: str) -> str:
    body = (f'<div class="notice error"><strong>Cannot read the document.</strong> {esc(message)}</div>'
            f'<p class="muted">The page reloads when the file changes.</p>')
    return layout(ctx, "Error", body)


def not_found_page(ctx: Context, message: str) -> str:
    return layout(ctx, "Not found", f'<div class="empty">{esc(message)} <a href="{esc(href(ctx, "/elements"))}">'
                                    f"Back to the elements</a></div>")
