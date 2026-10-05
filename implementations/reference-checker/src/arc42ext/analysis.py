"""What the web GUI shows, as plain data: one analysis of a document at a date, the revisit
dashboard and the element catalogue. No HTML here (see pages.py)."""

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

from . import binding_asciidoc, links
from .binding_asciidoc import EVENT_PREFIX, REVISIT_PREFIX, event_row, next_id, revisit_row
from .catalog import TIME_ELAPSED
from .links import LinkGraph
from .model import Document, Element, Event, Revisit
from .triggers import Status, Triggers

ROLE = "stakeholder-role"


@dataclass
class Analysis:
    path: Path
    date: date
    doc: Document
    graph: LinkGraph
    triggers: Triggers
    findings: list
    status: Status


def analyze(path, on: date) -> Analysis:
    """Read a document and evaluate it at a date: rule violations and revisit status."""
    doc = binding_asciidoc.read(path)
    graph = LinkGraph.from_document(doc)
    model = Triggers(doc, graph)
    findings = list(doc.notation_findings) + links.validate(doc) + model.validate(on)
    return Analysis(Path(path), on, doc, graph, model, findings, model.status(on))


# --- revisit dashboard ------------------------------------------------------


@dataclass
class Row:
    """A row to append to a table of the document."""
    table: str  # "triggers-events" or "triggers-revisits"
    text: str


@dataclass
class Item:
    """Something that needs action, or is waiting on someone."""
    state: str  # "overdue", "due", "missing" or "open"
    subscriber: str
    responsible: Optional[str]
    due: Optional[date]
    days_left: Optional[int]  # negative when overdue
    event: Optional[Event] = None  # None for a due time subscription
    revisit: Optional[Revisit] = None  # recorded revisits only
    scope: object = None
    rows: list = field(default_factory=list)


@dataclass
class Dashboard:
    overdue: list
    due: list
    missing: list
    open: list
    roles: list  # stakeholder-role IDs, for the filter

    @property
    def empty(self) -> bool:
        return not (self.overdue or self.due or self.missing or self.open)


def _days_left(due: Optional[date], on: date) -> Optional[int]:
    return (due - on).days if due else None


def dashboard(a: Analysis, role: Optional[str] = None) -> Dashboard:
    """Due time subscriptions, missing, overdue and open revisits, each with who owes it and by when.
    Missing and due items carry the rows to paste, with the next free IDs filled in."""
    model, on = a.triggers, a.date
    event_ids = [e.id for e in a.doc.events]
    revisit_ids = [r.id for r in a.doc.revisits]

    def new_revisit(event_id, subscriber, scope, responsible, due):
        revisit = Revisit(next_id(revisit_ids, REVISIT_PREFIX), event_id, subscriber, scope, responsible or "", on, due)
        revisit_ids.append(revisit.id)
        return Row("triggers-revisits", revisit_row(revisit))

    missing = []
    for m in a.status.missing:
        missing.append(Item("missing", m.subscriber, m.responsible, m.due, _days_left(m.due, on),
                            event=model.events.get(m.event), scope=m.scope,
                            rows=[new_revisit(m.event, m.subscriber, m.scope, m.responsible, m.due)]))

    due = []
    for d in a.status.due:
        # The event that evaluating this subscription records (T14d), and the revisit it then needs.
        event = Event(next_id(event_ids, EVENT_PREFIX), TIME_ELAPSED, d.date, d.subscriber)
        event_ids.append(event.id)
        rows = [Row("triggers-events", event_row(event))]
        for subscriber, scope in sorted(model.match(event).items()):
            rows.append(new_revisit(event.id, subscriber, scope, model.expected_responsible(subscriber, event),
                                    model.expected_due(subscriber, event)))
        due.append(Item("due", d.subscriber, model.expected_responsible(d.subscriber, event), d.date,
                        _days_left(d.date, on), rows=rows))

    recorded = {"overdue": [], "open": []}
    for revisit_id in a.status.open:
        revisit = model.revisits[revisit_id]
        state = "overdue" if revisit_id in a.status.overdue else "open"
        recorded[state].append(Item(state, revisit.subscriber, revisit.responsible, revisit.due,
                                    _days_left(revisit.due, on), event=model.events.get(revisit.event),
                                    revisit=revisit, scope=revisit.scope))

    def pick(items):
        items = [i for i in items if role is None or i.responsible == role]
        return sorted(items, key=lambda i: (i.due or date.max, i.subscriber))

    roles = list(dict.fromkeys(e.id for e in a.doc.elements if e.kind == ROLE))
    return Dashboard(pick(recorded["overdue"]), pick(due), pick(missing), pick(recorded["open"]), roles)


# --- element catalogue ------------------------------------------------------


@dataclass
class SubscriberState:
    baseline: Optional[date]
    active: bool
    superseded_by: list  # [(successor ID, date it takes effect or None)]
    next_due: Optional[date]  # when its time.elapsed subscription falls due, seen at the evaluation date
    open_revisits: list  # revisit IDs


@dataclass
class Entry:
    element: Element
    owner: Optional[str]
    outgoing: int
    incoming: int
    state: Optional[SubscriberState]


@dataclass
class SubscriptionView:
    event_type: str
    known: bool
    parameter: str  # "every P3M", "at 2026-12-31" or ""
    subject: Optional[str]
    responsible: Optional[str]  # a role ID, or None when it is the event's subject (or unresolved)
    responsible_rule: str  # "override", "owner", "subject" or "default"
    duration: str
    duration_rule: str  # "override" or "default"


@dataclass
class TimelineEntry:
    event_id: str
    event: Optional[Event]  # None when a revisit names an unknown event
    revisits: list  # this subscriber's revisits for the event, in the order opened
    missing: bool  # the event reaches the subscriber, but no revisit is recorded


@dataclass
class Detail:
    element: Element
    owner: Optional[str]
    outgoing: dict  # link type -> [targets]
    incoming: dict  # link type -> [sources]
    topics: list
    state: Optional[SubscriberState] = None
    subscriptions: list = field(default_factory=list)
    timeline: list = field(default_factory=list)
    assigned: Optional[Dashboard] = None  # for a stakeholder role


def _is_subscriber(a: Analysis, element_id: str) -> bool:
    return element_id in a.triggers.baseline or element_id in a.triggers.subscriptions


def subscriber_state(a: Analysis, element_id: str) -> Optional[SubscriberState]:
    if not _is_subscriber(a, element_id):
        return None
    model = a.triggers
    time_sub = model.subscription(element_id, TIME_ELAPSED)
    active = model.is_active(element_id, a.date)
    return SubscriberState(
        baseline=model.baseline.get(element_id),
        active=active,
        superseded_by=[(s, model.baseline.get(s)) for s in a.graph.superseded_by(element_id)],
        next_due=model.time_due_date(time_sub, a.date) if time_sub and active else None,
        open_revisits=[r for r in a.status.open if model.revisits[r].subscriber == element_id],
    )


def catalogue(a: Analysis, by: str = "section") -> list:
    """Elements grouped by arc42 section or by kind, in document order: [(group, [Entry])]."""
    outgoing = Counter(link.source for link in a.graph.links)
    groups = {}
    for element in a.graph.elements.values():  # first element of each ID, in document order
        key = (element.kind if by == "kind" else element.section) or "(none)"
        groups.setdefault(key, []).append(Entry(
            element, a.graph.owner(element.id), outgoing[element.id], len(a.graph.sources(element.id)),
            subscriber_state(a, element.id)))
    return list(groups.items())


def _grouped(pairs) -> dict:
    grouped = {}
    for link_type, value in pairs:
        grouped.setdefault(link_type, []).append(value)
    return grouped


def _subscription_view(a: Analysis, sub) -> SubscriptionView:
    event_type = a.triggers.types.get(sub.event_type)
    parameter = f"every {sub.every}" if sub.every else f"at {sub.at.isoformat()}" if sub.at else ""
    if sub.responsible:
        responsible, rule = sub.responsible, "override"
    elif event_type is None:
        responsible, rule = None, "default"
    elif event_type.default_responsible == "owner":
        responsible, rule = a.graph.owner(sub.subscriber), "owner"
    elif event_type.default_responsible == "subject":
        responsible, rule = None, "subject"
    else:
        responsible, rule = event_type.default_responsible, "default"
    duration = a.triggers.response_duration(sub, event_type) if event_type else sub.due
    return SubscriptionView(sub.event_type, event_type is not None, parameter, sub.subject, responsible, rule,
                            str(duration) if duration else "", "override" if sub.due else "default")


def _timeline(a: Analysis, element_id: str) -> list:
    model = a.triggers
    revisits = {}
    for revisit in a.doc.revisits:
        if revisit.subscriber == element_id:
            revisits.setdefault(revisit.event, []).append(revisit)
    reached = {event.id for event in model.events.values() if element_id in model.match(event)}
    entries = []
    for event_id in sorted(reached | set(revisits), key=lambda e: (
            getattr(model.events.get(e), "date", None) or date.max, e)):
        recorded = sorted(revisits.get(event_id, []), key=lambda r: (r.opened or date.max, r.id))
        entries.append(TimelineEntry(event_id, model.events.get(event_id), recorded,
                                     missing=event_id in reached and not any(not r.follows for r in recorded)))
    return entries


def element_detail(a: Analysis, element_id: str) -> Optional[Detail]:
    """One element: its links both ways, and its subscriptions and revisit history if it is a subscriber."""
    element = a.graph.elements.get(element_id)
    if element is None:
        return None
    detail = Detail(
        element, a.graph.owner(element_id),
        outgoing=_grouped((link.type, link.target) for link in a.graph.links if link.source == element_id),
        incoming=_grouped((link.type, link.source) for link in a.graph.sources(element_id)),
        topics=[topic for topic, ids in a.doc.topics.items() if element_id in ids],
        state=subscriber_state(a, element_id))
    if detail.state:
        detail.subscriptions = [_subscription_view(a, s) for s in a.triggers.subscriptions.get(element_id, [])]
        detail.timeline = _timeline(a, element_id)
    if element.kind == ROLE:
        detail.assigned = dashboard(a, role=element_id)
    return detail
