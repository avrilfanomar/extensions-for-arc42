"""Triggers extension: matching, time evaluation, revisit status and rules T1-T17."""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from .catalog import (CORE_EVENT_TYPES, CORE_KINDS, EFFECTS, LINK_TYPES, OUTCOMES, SUBSCRIBER_KINDS, TIME_ELAPSED,
                      is_namespaced)
from .dates import add
from .links import LinkGraph
from .model import WHOLE, Document, Event, Finding, Revisit, Subscription

TOPIC_PREFIX = "topic:"


@dataclass
class DueSubscription:
    subscriber: str
    date: date


@dataclass
class MissingRevisit:
    event: str
    subscriber: str
    scope: object
    responsible: Optional[str]
    due: Optional[date]


@dataclass
class Status:
    date: date
    due: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    open: list = field(default_factory=list)
    overdue: list = field(default_factory=list)

    @property
    def needs_action(self) -> bool:
        return bool(self.due or self.missing or self.overdue)


def format_scope(scope) -> object:
    return WHOLE if scope == WHOLE else sorted(scope)


class Triggers:
    """The triggers model of one document, on top of its link graph."""

    def __init__(self, doc: Document, graph: Optional[LinkGraph] = None):
        self.doc = doc
        self.graph = graph or LinkGraph.from_document(doc)
        self.types = dict(CORE_EVENT_TYPES)
        for event_type in doc.event_types:
            self.types.setdefault(event_type.name, event_type)

        self.baseline = {}
        for b in doc.baselines:
            if b.date is not None:
                self.baseline.setdefault(b.subscriber, b.date)

        self.subscriptions = defaultdict(list)
        for sub in doc.subscriptions:
            self.subscriptions[sub.subscriber].append(sub)

        self.events = {}
        for event in doc.events:
            self.events.setdefault(event.id, event)
        self.revisits = {}
        for revisit in doc.revisits:
            self.revisits.setdefault(revisit.id, revisit)

    # --- semantics -------------------------------------------------------

    def subscription(self, subscriber: str, event_type: str) -> Optional[Subscription]:
        for sub in self.subscriptions.get(subscriber, []):
            if sub.event_type == event_type:
                return sub
        return None

    def is_active(self, subscriber: str, on: date) -> bool:
        """Active at a date unless a superseding decision has a baseline on or before it."""
        for successor in self.graph.superseded_by(subscriber):
            successor_baseline = self.baseline.get(successor)
            if successor_baseline is not None and successor_baseline <= on:
                return False
        return True

    def resolve_subject(self, event: Event) -> list:
        if event.subject.startswith(TOPIC_PREFIX):
            return list(self.doc.topics.get(event.subject[len(TOPIC_PREFIX):], []))
        return [event.subject]

    def match(self, event: Event) -> dict:
        """Subscribers reached by an event (T7), each with its merged scope (T8)."""
        event_type = self.types.get(event.type)
        if event_type is None or event.date is None:
            return {}
        subjects = set(self.resolve_subject(event))
        reached = {}
        for subscriber in self.subscriptions:
            sub = self.subscription(subscriber, event.type)
            baseline = self.baseline.get(subscriber)
            if sub is None or baseline is None or event.date < baseline:
                continue
            if not self.is_active(subscriber, event.date):
                continue
            targets = {sub.subject} & subjects if sub.subject else subjects
            scopes = []
            for route in event_type.routes:
                for first, end in self.graph.follow(subscriber, route.steps):
                    if end in targets:
                        scopes.append(WHOLE if route.scope == WHOLE else frozenset({first}))
            if scopes:
                reached[subscriber] = WHOLE if WHOLE in scopes else frozenset().union(*scopes)
        return reached

    def response_duration(self, sub: Optional[Subscription], event_type):
        return (sub.due if sub and sub.due else None) or event_type.default_due

    def expected_responsible(self, subscriber: str, event: Event) -> Optional[str]:
        sub = self.subscription(subscriber, event.type)
        if sub and sub.responsible:
            return sub.responsible
        responsible = self.types[event.type].default_responsible
        if responsible == "owner":
            return self.graph.owner(subscriber)
        if responsible == "subject":
            return None if event.subject.startswith(TOPIC_PREFIX) else event.subject
        return responsible

    def expected_due(self, subscriber: str, event: Event) -> Optional[date]:
        duration = self.response_duration(self.subscription(subscriber, event.type), self.types[event.type])
        return add(event.date, duration) if duration and event.date else None

    def anchor(self, subscriber: str, on: date, inclusive: bool = True) -> Optional[date]:
        """T14(a): the baseline, or the latest whole-scope confirmed/amended close date."""
        baseline = self.baseline.get(subscriber)
        if baseline is None:
            return None
        closes = [r.closed for r in self.revisits.values()
                  if r.subscriber == subscriber and r.scope == WHOLE and r.outcome in ("confirmed", "amended")
                  and r.closed is not None and (r.closed <= on if inclusive else r.closed < on)]
        return max([baseline] + closes)

    def time_due_date(self, sub: Subscription, on: date, inclusive: bool = True) -> Optional[date]:
        """T14(b): when the time subscription falls due, as seen at a date."""
        if sub.at is not None:
            return sub.at
        anchor = self.anchor(sub.subscriber, on, inclusive)
        if anchor is None or sub.every is None:
            return None
        return add(anchor, sub.every)

    def follow_on_due(self, revisit: Revisit) -> Optional[date]:
        inputs_revisit = self.revisits.get(revisit.follows)
        event = self.events.get(revisit.event)
        if inputs_revisit is None or inputs_revisit.closed is None or event is None or event.type not in self.types:
            return None
        duration = self.response_duration(self.subscription(revisit.subscriber, event.type), self.types[event.type])
        return add(inputs_revisit.closed, duration) if duration else None

    def status(self, on: date) -> Status:
        status = Status(on)
        for subscriber in sorted(self.subscriptions):
            sub = self.subscription(subscriber, TIME_ELAPSED)
            if sub is None or subscriber not in self.baseline or not self.is_active(subscriber, on):
                continue
            due_date = self.time_due_date(sub, on)
            if due_date is None or on < due_date:
                continue
            since = sub.at if sub.at is not None else self.anchor(subscriber, on)
            recorded = any(e.type == TIME_ELAPSED and e.subject == subscriber and e.date and e.date >= since
                           for e in self.events.values())
            if not recorded:
                status.due.append(DueSubscription(subscriber, due_date))

        recorded_pairs = {(r.event, r.subscriber) for r in self.revisits.values() if not r.follows}
        for event in self.events.values():
            for subscriber, scope in sorted(self.match(event).items()):
                if (event.id, subscriber) not in recorded_pairs:
                    status.missing.append(MissingRevisit(
                        event.id, subscriber, scope,
                        self.expected_responsible(subscriber, event), self.expected_due(subscriber, event)))

        for revisit in self.revisits.values():
            if revisit.is_open:
                status.open.append(revisit.id)
                if revisit.due is not None and on > revisit.due:
                    status.overdue.append(revisit.id)
        return status

    # --- rules -----------------------------------------------------------

    def validate(self, on: date) -> list:
        findings = []
        findings += self._check_subscriptions()
        findings += self._check_custom_types()
        findings += self._check_events()
        findings += self._check_time_events()
        findings += self._check_revisits(on)
        findings += self._check_supersession()
        return findings

    def _check_supersession(self) -> list:
        """T16: a decision that supersedes a subscriber needs a baseline, or the subscriber never
        becomes inactive and keeps being revisited."""
        findings = []
        subscribers = set(self.baseline) | set(self.subscriptions)
        reported = set()
        for link in self.graph.links:
            if link.type != "supersedes" or link.source not in self.graph.elements:
                continue
            if link.target in subscribers and link.source not in self.baseline and link.source not in reported:
                reported.add(link.source)
                findings.append(Finding("T16", f"superseding decision '{link.source}' has no baseline, so its "
                                               f"supersession of '{link.target}' never takes effect", link.location,
                                               "warning"))
        return findings

    def _check_subscriptions(self) -> list:
        """T1, T2, T3."""
        findings = []
        for b in self.doc.baselines:
            if b.subscriber not in self.graph.elements:
                findings.append(Finding("T1", f"baseline for '{b.subscriber}', which is not an element", b.location))
        baseline_counts = Counter(b.subscriber for b in self.doc.baselines)

        for subscriber, subs in self.subscriptions.items():
            where = subs[0].location
            kind = self.graph.kind_of(subscriber)
            if kind is None:
                findings.append(Finding("T1", f"subscriber '{subscriber}' is not an element", where))
            elif kind not in SUBSCRIBER_KINDS:
                findings.append(Finding("T1", f"subscriber '{subscriber}' is a {kind}, not a decision, risk or debt",
                                        where))
            if baseline_counts[subscriber] == 0:
                findings.append(Finding("T1", f"subscriber '{subscriber}' has no baseline date", where))
            elif baseline_counts[subscriber] > 1:
                findings.append(Finding("T1", f"subscriber '{subscriber}' has more than one baseline", where))

            seen_types = set()
            for sub in subs:
                if sub.event_type in seen_types:
                    findings.append(Finding("T1", f"'{subscriber}' has more than one '{sub.event_type}' subscription",
                                            sub.location))
                seen_types.add(sub.event_type)
            if TIME_ELAPSED not in seen_types:
                findings.append(Finding("T2", f"'{subscriber}' has no time.elapsed backstop", where, "warning"))

            owner = self.graph.owner(subscriber)
            for sub in subs:
                if sub.event_type not in self.types:
                    findings.append(Finding("T1", f"unknown event type '{sub.event_type}'", sub.location))
                    continue
                is_time = sub.event_type == TIME_ELAPSED
                if is_time and (sub.every is None) == (sub.at is None):
                    findings.append(Finding("T1", "time.elapsed needs exactly one of 'every <duration>' or 'at <date>'",
                                            sub.location))
                if not is_time and (sub.every is not None or sub.at is not None):
                    findings.append(Finding("T1", f"'every'/'at' only apply to time.elapsed, not {sub.event_type}",
                                            sub.location))
                if sub.responsible is None and self.types[sub.event_type].default_responsible == "owner" \
                        and owner is None:
                    findings.append(Finding("T3", f"'{subscriber}' has no owned-by link and its {sub.event_type} "
                                                  f"subscription does not override responsible", sub.location))
                if sub.responsible is not None and self.graph.kind_of(sub.responsible) != "stakeholder-role":
                    findings.append(Finding("T3", f"responsible '{sub.responsible}' is not a stakeholder role",
                                            sub.location))
        return findings

    def _check_custom_types(self) -> list:
        """T1: custom event types are complete, published and use valid routes."""
        findings = []
        known_kinds = CORE_KINDS | self.graph.custom_kinds
        link_types = {**LINK_TYPES, **self.graph.custom_link_types}
        names = Counter(t.name for t in self.doc.event_types)
        for t in self.doc.event_types:
            def bad(message):
                findings.append(Finding("T1", f"custom event type '{t.name}': {message}", t.location))
            if t.name in CORE_EVENT_TYPES:
                bad("redefines a core event type")
            elif not is_namespaced(t.name, event_type=True):
                bad("name is not of the form <namespace>:<name>")
            if names[t.name] > 1:
                bad("defined more than once")
            if t.mode != "published":
                bad("mode must be 'published' in v0.1")
            if t.subject_kind not in known_kinds:
                bad(f"unknown subject kind '{t.subject_kind}'")
            if not t.routes:
                bad("has no routes")
            for route in t.routes:
                unknown = [s for s in route.steps if s not in link_types]
                if unknown:
                    bad(f"route uses unknown link type(s) {', '.join(unknown)}")
                if route.scope == "inputs" and (not route.steps or route.steps[0] != "uses-input"):
                    bad("scope 'inputs' requires a route starting with uses-input")
            if t.default_due is None:
                bad("default response has no due duration")
            if t.default_responsible not in ("owner", "subject") and \
                    self.graph.kind_of(t.default_responsible) != "stakeholder-role":
                bad(f"default responsible '{t.default_responsible}' is not owner, subject or a stakeholder role")
            if t.default_responsible == "subject" and t.subject_kind != "stakeholder-role":
                bad("default responsible 'subject' requires subject kind 'stakeholder-role'")
        return findings

    def _check_events(self) -> list:
        """T4 (event IDs) and T5."""
        findings = []
        seen = set()
        for event in self.doc.events:
            if event.id in seen:
                findings.append(Finding("T4", f"duplicate event ID '{event.id}'", event.location))
            seen.add(event.id)
            event_type = self.types.get(event.type)
            if event_type is None:
                findings.append(Finding("T5", f"event '{event.id}' has unknown type '{event.type}'", event.location))
                continue
            if event.subject.startswith(TOPIC_PREFIX):
                topic = event.subject[len(TOPIC_PREFIX):]
                if topic not in self.doc.topics:
                    findings.append(Finding("T5", f"event '{event.id}': topic '{topic}' is not in the topic map",
                                            event.location))
                elif event_type.subject_kind is not None:
                    for element_id in self.doc.topics[topic]:
                        if self.graph.kind_of(element_id) != event_type.subject_kind:
                            findings.append(Finding(
                                "T5", f"event '{event.id}': topic '{topic}' maps to '{element_id}', "
                                      f"which is not a {event_type.subject_kind}", event.location))
            else:
                kind = self.graph.kind_of(event.subject)
                expected = event_type.subject_kind
                if kind is None:
                    findings.append(Finding("T5", f"event '{event.id}': subject '{event.subject}' does not resolve",
                                            event.location))
                elif expected is None and kind not in SUBSCRIBER_KINDS:
                    findings.append(Finding("T5", f"event '{event.id}': subject '{event.subject}' is not a subscriber",
                                            event.location))
                elif expected is not None and kind != expected:
                    findings.append(Finding("T5", f"event '{event.id}': subject '{event.subject}' is a {kind}, "
                                                  f"not a {expected}", event.location))
            missing = [k for k, required in event_type.payload.items() if required and not event.payload.get(k)]
            if missing:
                findings.append(Finding("T5", f"event '{event.id}' lacks required payload: {', '.join(missing)}",
                                        event.location))
        for topic, element_ids in self.doc.topics.items():
            for element_id in element_ids:
                if element_id not in self.graph.elements:
                    findings.append(Finding("T5", f"topic '{topic}' maps to unknown element '{element_id}'"))
        return findings

    def _check_time_events(self) -> list:
        """T14(e): a time.elapsed event is dated on the day its subscription fell due."""
        findings = []
        for event in self.doc.events:
            if event.type != TIME_ELAPSED or event.date is None:
                continue
            sub = self.subscription(event.subject, TIME_ELAPSED)
            if sub is None:
                continue
            due_date = self.time_due_date(sub, event.date, inclusive=False)
            if due_date is not None and event.date != due_date:
                findings.append(Finding("T14", f"time.elapsed event '{event.id}' is dated {event.date}, "
                                               f"but '{event.subject}' fell due on {due_date}", event.location))
        return findings

    def _check_revisits(self, on: date) -> list:
        """T4 (revisit IDs), T8-T11, T15-T17."""
        findings = []
        seen = set()
        pairs = Counter()
        follow_ons = Counter()
        matches = {}
        for revisit in self.doc.revisits:
            where = revisit.location
            if revisit.id in seen:
                findings.append(Finding("T4", f"duplicate revisit ID '{revisit.id}'", where))
            seen.add(revisit.id)

            event = self.events.get(revisit.event)
            if event is None or revisit.subscriber not in self.graph.elements:
                findings.append(Finding("T17", f"revisit '{revisit.id}' refers to an unknown event or subscriber", where))
                continue
            if event.type not in self.types:
                continue  # reported by T5

            if revisit.follows:
                follow_ons[(revisit.event, revisit.subscriber)] += 1
                findings += self._check_follow_on(revisit)
            else:
                pairs[(revisit.event, revisit.subscriber)] += 1
                if event.id not in matches:
                    matches[event.id] = self.match(event)
                scope = matches[event.id].get(revisit.subscriber)
                if scope is None:
                    findings.append(Finding("T17", f"revisit '{revisit.id}': event '{event.id}' does not reach "
                                                   f"'{revisit.subscriber}'", where))
                else:
                    if revisit.scope != scope:
                        findings.append(Finding("T8", f"revisit '{revisit.id}' has scope {format_scope(revisit.scope)}"
                                                      f", expected {format_scope(scope)}", where))
                    expected = self.expected_responsible(revisit.subscriber, event)
                    if expected is not None and revisit.responsible != expected:
                        findings.append(Finding("T10", f"revisit '{revisit.id}' is assigned to "
                                                       f"'{revisit.responsible}', expected '{expected}'", where))
                    due = self.expected_due(revisit.subscriber, event)
                    if due is not None and revisit.due != due:
                        findings.append(Finding("T11", f"revisit '{revisit.id}' is due {revisit.due}, "
                                                       f"expected {due}", where))

            findings += self._check_outcome(revisit, event)

            if revisit.is_open and not self.is_active(revisit.subscriber, on):
                findings.append(Finding("T16", f"revisit '{revisit.id}' is open, but '{revisit.subscriber}' "
                                               f"is superseded", where))

        for (event_id, subscriber), count in list(pairs.items()) + list(follow_ons.items()):
            if count > 1:
                findings.append(Finding("T9", f"{count} revisits for event '{event_id}' and '{subscriber}'"))
        return findings

    def _check_follow_on(self, revisit: Revisit) -> list:
        findings = []
        where = revisit.location
        inputs_revisit = self.revisits.get(revisit.follows)
        if inputs_revisit is None or inputs_revisit.event != revisit.event or \
                inputs_revisit.subscriber != revisit.subscriber or inputs_revisit.scope == WHOLE or \
                inputs_revisit.outcome != "amended" or inputs_revisit.effect != "reopened":
            findings.append(Finding("T17", f"revisit '{revisit.id}' follows '{revisit.follows}', which is not an "
                                           f"inputs-scoped revisit of the same event and subscriber amended with "
                                           f"effect: reopened", where))
            return findings
        if revisit.scope != WHOLE:
            findings.append(Finding("T15", f"follow-on revisit '{revisit.id}' must have scope whole", where))
        owner = self.graph.owner(revisit.subscriber)
        if owner is not None and revisit.responsible != owner:
            findings.append(Finding("T10", f"follow-on revisit '{revisit.id}' is assigned to "
                                           f"'{revisit.responsible}', expected the owner '{owner}'", where))
        due = self.follow_on_due(revisit)
        if due is not None and revisit.due != due:
            findings.append(Finding("T11", f"follow-on revisit '{revisit.id}' is due {revisit.due}, expected {due}",
                                    where))
        return findings

    def _check_outcome(self, revisit: Revisit, event: Event) -> list:
        """T15."""
        def bad(message):
            return [Finding("T15", f"revisit '{revisit.id}': {message}", revisit.location)]

        if revisit.outcome is None:
            return bad("has a closed date but no outcome") if revisit.closed else []
        if revisit.outcome not in OUTCOMES:
            return bad(f"unknown outcome '{revisit.outcome}'")
        findings = []
        if revisit.closed is None:
            findings += bad("is closed but has no closed date")
        if revisit.outcome == "dismissed":
            if not revisit.rationale:
                findings += bad("dismissed without a rationale")
            if self.types[event.type].mode == "evaluated":
                findings += bad(f"{event.type} revisits cannot be dismissed")
        elif revisit.outcome == "superseded":
            if not revisit.successor:
                findings += bad("superseded without a successor")
            elif revisit.successor not in self.graph.superseded_by(revisit.subscriber):
                findings += bad(f"successor '{revisit.successor}' has no supersedes link to '{revisit.subscriber}'")
        elif revisit.outcome == "amended" and revisit.scope != WHOLE:
            if revisit.effect not in EFFECTS:
                findings += bad("an inputs-scoped amended revisit needs effect: unchanged or reopened")
            elif revisit.effect == "reopened" and not any(r.follows == revisit.id for r in self.revisits.values()):
                findings += bad("effect: reopened, but no follow-on revisit follows it")
        return findings


def validate(doc: Document, on: date, graph: Optional[LinkGraph] = None) -> list:
    return Triggers(doc, graph).validate(on)


def status(doc: Document, on: date, graph: Optional[LinkGraph] = None) -> Status:
    return Triggers(doc, graph).status(on)
