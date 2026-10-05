"""AsciiDoc binding: reads the notation defined in links/EN/template.adoc and
triggers/EN/template.adoc into the binding-agnostic model.

This is the only module that knows about AsciiDoc. It is line-oriented and does not
need an AsciiDoc processor. Problems with the notation itself are reported as rule B1;
invalid dates and durations as T13.
"""

import re
from pathlib import Path
from typing import Optional

from .dates import parse_date, parse_duration
from .model import (WHOLE, Baseline, Document, Element, Event, EventType, Finding, Link, Location, Revisit, Route,
                    Subscription, VocabularyEntry)

CORE_PREFIXES = {
    "sh-": "stakeholder-role",
    "rq-": "requirement",
    "qg-": "quality-goal",
    "qs-": "quality-scenario",
    "con-": "constraint",
    "need-": "need",
    "adr-": "decision",
    "in-": "input",
    "risk-": "risk",
    "td-": "debt",
}

TOPIC_SCHEME = "topic"

_INCLUDE = re.compile(r"^include::([^\[]+)\[.*\]\s*$")
_HEADING = re.compile(r"^(={1,6})\s+(\S.*)$")
_BLOCK_ANCHOR = re.compile(r"^\[\[([A-Za-z0-9_:.-]+)(?:,[^\]]*)?\]\]\s*$")
_INLINE_ANCHOR = re.compile(r"\[\[([A-Za-z0-9_:.-]+)(?:,[^\]]*)?\]\]")
_ATTRIBUTES = re.compile(r"^\[([^\[].*)\]$")
_DELIMITER = re.compile(r"^(-{4,}|\.{4,}|\+{4,}|/{4,})$")
_DLIST = re.compile(r"^(\S.*?)::(?:\s+(.*))?$")
_XREF = re.compile(r"<<\s*([^,>\s]+)\s*(?:,[^>]*)?>>")
_DECLARATION = re.compile(r"^Extensions used:\s*(.*)$")
_CLOSING_FIELD = re.compile(r"\b(effect|follows|successor):\s*([A-Za-z0-9_:-]+(?:\.[A-Za-z0-9_:-]+)*)")

TABLE_COLUMNS = {
    "vocabulary": ["type", "name", "prefix", "from", "to", "description"],
    "triggers-events": ["id", "date", "type", "subject", "payload", "published by"],
    "triggers-revisits": ["id", "event", "subscriber", "scope", "responsible", "opened", "due", "outcome", "closed",
                          "rationale"],
    "triggers-topics": ["topic", "elements"],
    "triggers-event-types": ["name", "mode", "subject kind", "routes", "payload", "default response"],
}
ROLES = {"links", "triggers", "vocabulary", "triggers-subscriptions", *TABLE_COLUMNS}


def _roles(attributes: str) -> set:
    roles = set(re.findall(r"(?:^|[,#%\s])\.([A-Za-z0-9_-]+)", attributes))
    m = re.search(r"role=\"?([^\",\]]+)\"?", attributes)
    if m:
        roles.update(m.group(1).split())
    return roles


def _normalize(text: str) -> str:
    """Replace xrefs by their IDs."""
    return _XREF.sub(lambda m: m.group(1), text).strip()


def _ids(text: str) -> list:
    return [token.strip() for token in _normalize(text).split(",") if token.strip()]


def _load(path: Path, findings: list, seen=()) -> list:
    lines = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        location = Location(str(path), number)
        m = _INCLUDE.match(raw)
        if m:
            target = (path.parent / m.group(1).strip()).resolve()
            if target in seen or not target.is_file():
                findings.append(Finding("B1", f"cannot include '{m.group(1)}'", location))
            else:
                lines += _load(target, findings, (*seen, target))
            continue
        lines.append((raw.rstrip(), location))
    return lines


def _strip(lines: list) -> list:
    """Drop comments, delimited listing/literal/passthrough/comment blocks and arc42help blocks."""
    kept = []
    delimiter = None
    help_depth = 0
    for text, location in lines:
        stripped = text.strip()
        if delimiter:
            if stripped == delimiter:
                delimiter = None
            continue
        if help_depth:
            if stripped.startswith("ifdef::arc42help[]"):
                help_depth += 1
            elif stripped in ("endif::arc42help[]", "endif::[]"):
                help_depth -= 1
            continue
        if stripped == "ifdef::arc42help[]":
            help_depth = 1
            continue
        if stripped.startswith("ifdef::arc42help["):
            continue  # single-line conditional
        if _DELIMITER.match(stripped):
            delimiter = stripped
            continue
        if stripped.startswith("//"):
            continue
        kept.append((text, location))
    return kept


class _Block:
    def __init__(self, role, form, rows, location, sections, section_title):
        self.role = role
        self.form = form  # "dlist" or "table"
        self.rows = rows  # dlist: [(term, value, location)]; table: [[(cell, location)]]
        self.location = location
        self.sections = sections  # enclosing section anchors, innermost first
        self.section_title = section_title


class _Reader:
    def __init__(self, path: Path):
        self.path = path
        self.doc = Document(source=str(path))
        self.findings = self.doc.notation_findings
        self.lines = _strip(_load(path, self.findings))
        self.anchors = []  # (id, title, location, chapter title, is_block)
        self.sections = []  # (level, anchor id or None, title)
        self.blocks = []
        self.prefixes = dict(CORE_PREFIXES)

    # --- pass 1: structure ------------------------------------------------

    def _chapter(self) -> Optional[str]:
        for level, _, title in self.sections:
            if level == 1:
                return title
        return None

    def _section_anchors(self) -> tuple:
        return tuple(anchor for _, anchor, _ in reversed(self.sections) if anchor)

    def _scan_inline_anchors(self, text: str, location: Location):
        for m in _INLINE_ANCHOR.finditer(text):
            title = text[m.end():].split("|")[0].replace("**", "").strip()
            self.anchors.append((m.group(1), title, location, self._chapter(), False))

    def _read_table(self, i: int):
        cells = []
        columns = None
        i += 1
        while i < len(self.lines) and not self.lines[i][0].strip().startswith("|==="):
            text, location = self.lines[i]
            self._scan_inline_anchors(text, location)
            stripped = text.strip()
            if stripped.startswith("|"):
                parts = stripped.split("|")[1:]
                if columns is None:
                    columns = len(parts)
                cells += [[p.strip(), location] for p in parts]
            elif stripped and cells:
                cells[-1][0] = f"{cells[-1][0]} {stripped}".strip()
            i += 1
        rows = []
        if columns:
            for k in range(0, len(cells), columns):
                row = [tuple(c) for c in cells[k:k + columns]]
                row += [("", row[-1][1])] * (columns - len(row))
                rows.append(row)
        return rows, i + 1

    def read_structure(self):
        pending_anchor = None
        pending_roles = set()
        i = 0
        while i < len(self.lines):
            text, location = self.lines[i]
            stripped = text.strip()
            if not stripped:
                i += 1
                continue

            declaration = _DECLARATION.match(stripped)
            if declaration:
                for part in declaration.group(1).split(","):
                    name, _, version = part.strip().partition(" ")
                    if name:
                        self.doc.extensions[name] = version.strip().lstrip("v")

            anchor = _BLOCK_ANCHOR.match(stripped)
            if anchor:
                pending_anchor = (anchor.group(1), location)
                i += 1
                continue

            attributes = _ATTRIBUTES.match(stripped)
            if attributes and not stripped.startswith("[["):
                pending_roles |= _roles(attributes.group(1))
                i += 1
                continue

            heading = _HEADING.match(stripped)
            if heading:
                level = len(heading.group(1)) - 1
                title = heading.group(2).strip()
                while self.sections and self.sections[-1][0] >= level:
                    self.sections.pop()
                anchor_id = pending_anchor[0] if pending_anchor else None
                self.sections.append((level, anchor_id, title))
                if pending_anchor:
                    self.anchors.append((anchor_id, title, pending_anchor[1], self._chapter(), True))
                pending_anchor, pending_roles = None, set()
                i += 1
                continue

            if pending_anchor:
                self.anchors.append((pending_anchor[0], stripped, pending_anchor[1], self._chapter(), True))
                pending_anchor = None

            role = next((r for r in sorted(pending_roles) if r in ROLES), None)
            if stripped.startswith("|==="):
                rows, i = self._read_table(i)
                if role:
                    self.blocks.append(_Block(role, "table", rows, location, self._section_anchors(),
                                              self._chapter()))
                pending_roles = set()
                continue

            if role and _DLIST.match(stripped):
                items = []
                while i < len(self.lines):
                    text, item_location = self.lines[i]
                    m = _DLIST.match(text.strip())
                    if not text.strip() or not m:
                        break
                    items.append((m.group(1).strip(), (m.group(2) or "").strip(), item_location))
                    i += 1
                self.blocks.append(_Block(role, "dlist", items, location, self._section_anchors(), self._chapter()))
                pending_roles = set()
                continue

            self._scan_inline_anchors(text, location)
            pending_roles = set()
            i += 1

    # --- pass 2: model ------------------------------------------------------

    def kind_of(self, element_id: str) -> Optional[str]:
        for prefix in sorted(self.prefixes, key=len, reverse=True):
            if element_id.startswith(prefix):
                return self.prefixes[prefix]
        return None

    def _note(self, message: str, location: Location, rule: str = "B1"):
        self.findings.append(Finding(rule, message, location))

    def _date(self, text: str, location: Location, what: str, required: bool = True):
        text = text.strip()
        if not text:
            if required:
                self._note(f"{what} is missing", location, "T13")
            return None
        value = parse_date(text)
        if value is None:
            self._note(f"{what} '{text}' is not a YYYY-MM-DD date", location, "T13")
        return value

    def _duration(self, text: str, location: Location, what: str):
        value = parse_duration(text)
        if value is None:
            self._note(f"{what} '{text.strip()}' is not a duration such as P30D or P1Y6M", location, "T13")
        return value

    def _owner_section(self, block: _Block) -> Optional[str]:
        for anchor in block.sections:
            if self.kind_of(anchor):
                return anchor
        self._note(f"[.{block.role}] block is not inside a section anchored to an element", block.location)
        return None

    def _check_header(self, block: _Block) -> bool:
        expected = TABLE_COLUMNS[block.role]
        header = [cell.lower() for cell, _ in block.rows[0]] if block.rows else []
        if header != expected:
            self._note(f"[.{block.role}] table must have the columns {' | '.join(expected)}", block.location)
            return False
        return True

    def build(self) -> Document:
        for block in list(self.blocks):
            if block.role in TABLE_COLUMNS and block.form != "table":
                self._note(f"[.{block.role}] must be a table", block.location)
                self.blocks.remove(block)

        for block in self.blocks:
            if block.role == "vocabulary" and self._check_header(block):
                self._read_vocabulary(block)

        for anchor_id, title, location, chapter, _ in self.anchors:
            kind = self.kind_of(anchor_id)
            if kind:
                self.doc.elements.append(Element(anchor_id, kind, title, chapter, location))

        readers = {
            "links": self._read_links,
            "triggers": self._read_local_subscriptions,
            "triggers-subscriptions": self._read_subscription_table,
            "triggers-events": self._read_events,
            "triggers-revisits": self._read_revisits,
            "triggers-topics": self._read_topics,
            "triggers-event-types": self._read_event_types,
        }
        for block in self.blocks:
            if block.role in TABLE_COLUMNS and block.form == "table" and block.role != "vocabulary":
                if not self._check_header(block):
                    continue
            if block.role in readers:
                readers[block.role](block)
        return self.doc

    def _read_vocabulary(self, block: _Block):
        for row in block.rows[1:]:
            (kind_or_link, _), (name, location), (prefix, _), (from_kinds, _), (to_kinds, _), _ = row
            kind_or_link = kind_or_link.strip().lower()
            if kind_or_link == "kind":
                self.doc.vocabulary.append(VocabularyEntry("kind", name, location=location))
                if not prefix:
                    self._note(f"custom kind '{name}' has no prefix", location)
                elif any(prefix.startswith(p) or p.startswith(prefix) for p in CORE_PREFIXES):
                    self._note(f"prefix '{prefix}' of '{name}' overlaps a core prefix", location)
                else:
                    self.prefixes[prefix] = name
            elif kind_or_link == "link":
                def kinds(text):
                    values = {k.strip() for k in text.split(",") if k.strip()}
                    return None if not values or "any" in values else frozenset(values)
                self.doc.vocabulary.append(VocabularyEntry("link", name, kinds(from_kinds), kinds(to_kinds), location))
            else:
                self._note(f"vocabulary type must be 'kind' or 'link', not '{kind_or_link}'", location)

    def _read_links(self, block: _Block):
        if block.form == "dlist":
            source = self._owner_section(block)
            if source:
                for link_type, value, location in block.rows:
                    for target in _ids(value):
                        self.doc.links.append(Link(source, link_type, target, location))
            return
        if not block.rows:
            return
        header = [cell for cell, _ in block.rows[0]]
        for row in block.rows[1:]:
            sources = _ids(row[0][0])
            if len(sources) != 1:
                self._note("the first cell of a [.links] row must hold exactly one source", row[0][1])
                continue
            for column in range(1, len(header)):
                cell, location = row[column]
                for target in _ids(cell):
                    self.doc.links.append(Link(sources[0], header[column], target, location))

    def _subscription(self, subscriber: str, event_type: str, clauses: str, location: Location) -> Subscription:
        sub = Subscription(subscriber, event_type, location=location)
        for clause in _ids(clauses):
            if clause.lower() in ("yes", "✓"):
                continue
            word, _, rest = clause.partition(" ")
            rest = rest.strip()
            if word == "every":
                sub.every = self._duration(rest, location, "period")
            elif word == "at":
                sub.at = self._date(rest, location, "target date")
            elif word == "due":
                sub.due = self._duration(rest, location, "due")
            elif word == "responsible":
                sub.responsible = rest
            elif word == "subject":
                sub.subject = rest
            else:
                self._note(f"unknown subscription clause '{clause}'", location, "T1")
        return sub

    def _read_local_subscriptions(self, block: _Block):
        subscriber = self._owner_section(block)
        if not subscriber:
            return
        for term, value, location in block.rows:
            if term == "baseline":
                self.doc.baselines.append(Baseline(subscriber, self._date(value, location, "baseline"), location))
            elif term.startswith("on "):
                self.doc.subscriptions.append(self._subscription(subscriber, term[3:].strip(), value, location))
            else:
                self._note(f"unknown [.triggers] entry '{term}'", location)

    def _read_subscription_table(self, block: _Block):
        if not block.rows:
            return
        header = [cell for cell, _ in block.rows[0]]
        if [h.lower() for h in header[:2]] != ["subscriber", "baseline"]:
            self._note("[.triggers-subscriptions] must start with the columns Subscriber | Baseline", block.location)
            return
        for row in block.rows[1:]:
            subscribers = _ids(row[0][0])
            if len(subscribers) != 1:
                self._note("the Subscriber cell must hold exactly one element", row[0][1])
                continue
            subscriber = subscribers[0]
            if row[1][0]:
                self.doc.baselines.append(Baseline(subscriber, self._date(row[1][0], row[1][1], "baseline"),
                                                   row[1][1]))
            for column in range(2, len(header)):
                cell, location = row[column]
                if cell:
                    self.doc.subscriptions.append(self._subscription(subscriber, header[column], cell, location))

    def _read_events(self, block: _Block):
        for row in block.rows[1:]:
            (event_id, location), (when, _), (event_type, _), (subject, _), (payload, _), (publisher, _) = row
            values = {}
            for pair in payload.split(";"):
                key, _, value = pair.partition(":")
                if key.strip():
                    values[key.strip()] = value.strip()
            self.doc.events.append(Event(event_id, event_type, self._date(when, location, f"date of {event_id}"),
                                         _normalize(subject), values, publisher, location))

    def _read_revisits(self, block: _Block):
        for row in block.rows[1:]:
            cells = [cell for cell, _ in row]
            location = row[0][1]
            revisit_id, event, subscriber, scope, responsible, opened, due, outcome, closed, rationale = cells
            fields = {}
            rationale = _normalize(rationale)
            for m in _CLOSING_FIELD.finditer(rationale):
                fields[m.group(1)] = m.group(2)
            rationale = _CLOSING_FIELD.sub("", rationale).strip(" ;")
            self.doc.revisits.append(Revisit(
                id=revisit_id,
                event=_normalize(event),
                subscriber=_normalize(subscriber),
                scope=WHOLE if scope.strip().lower() == WHOLE else frozenset(_ids(scope)),
                responsible=_normalize(responsible),
                opened=self._date(opened, location, f"opened date of {revisit_id}"),
                due=self._date(due, location, f"due date of {revisit_id}"),
                outcome=outcome.strip().lower() or None,
                closed=self._date(closed, location, f"closed date of {revisit_id}", required=False),
                rationale=rationale,
                successor=fields.get("successor"),
                effect=fields.get("effect"),
                follows=fields.get("follows"),
                location=location,
            ))

    def _read_topics(self, block: _Block):
        for row in block.rows[1:]:
            topic = row[0][0].strip()
            if topic.startswith(f"{TOPIC_SCHEME}:"):
                topic = topic[len(TOPIC_SCHEME) + 1:]
            self.doc.topics[topic] = _ids(row[1][0])

    def _read_event_types(self, block: _Block):
        for row in block.rows[1:]:
            (name, location), (mode, _), (subject_kind, _), (routes_text, _), (payload_text, _), (response, _) = row
            routes = []
            for text in routes_text.split(";"):
                if not text.strip():
                    continue
                steps, arrow, scope = text.partition("->")
                steps, scope = steps.strip(), scope.strip()
                if not arrow or scope not in (WHOLE, "inputs"):
                    self._note(f"route '{text.strip()}' must be '<link types> -> whole|inputs'", location, "T1")
                    continue
                routes.append(Route(() if steps == "self" else tuple(s.strip() for s in steps.split("/")), scope))
            payload = {}
            for item in payload_text.split(";"):
                attribute = item.partition(":")[0].replace("(optional)", "").strip()
                if attribute:
                    payload[attribute] = "(optional)" not in item
            responsible, due = "", None
            for pair in response.split(";"):
                key, _, value = pair.partition(":")
                if key.strip() == "responsible":
                    responsible = _normalize(value)
                elif key.strip() == "due":
                    due = self._duration(value, location, "default due")
            self.doc.event_types.append(EventType(name.strip(), mode.strip(), subject_kind.strip(), routes, payload,
                                                  responsible, due, custom=True, location=location))


def read(path) -> Document:
    """Read an AsciiDoc document (following includes) into the model."""
    reader = _Reader(Path(path))
    reader.read_structure()
    # The `topic:` scheme is reserved by the triggers extension (L3): only reserve it when the
    # document declares triggers, so a links-only document may still use topic: as an external URI.
    if "triggers" in reader.doc.extensions:
        reader.doc.reserved_schemes.add(TOPIC_SCHEME)
    return reader.build()
