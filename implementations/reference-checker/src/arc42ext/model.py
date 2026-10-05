"""Core data model for arc42 extensions (concept layer, binding-agnostic)."""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional, Union

from .dates import Duration

WHOLE = "whole"

# A revisit scope is either WHOLE or a set of input element IDs.
Scope = Union[str, frozenset]


@dataclass(frozen=True)
class Location:
    """Source location for error reporting."""
    file: str
    line: int

    def __str__(self):
        return f"{self.file}:{self.line}"


@dataclass
class Element:
    """An identifiable piece of content in the document."""
    id: str
    kind: str
    title: Optional[str] = None
    section: Optional[str] = None
    location: Optional[Location] = None


@dataclass
class Link:
    """A directed, typed relation from an element to an element or external URI."""
    source: str
    type: str
    target: str
    location: Optional[Location] = None


@dataclass
class VocabularyEntry:
    """A declared custom kind or link type."""
    type: str  # "kind" or "link"
    name: str
    from_kinds: Optional[frozenset] = None  # link types only; None means any
    to_kinds: Optional[frozenset] = None
    location: Optional[Location] = None


@dataclass(frozen=True)
class Route:
    """A sequence of link types followed from a subscriber, and the scope it yields."""
    steps: tuple
    scope: str  # WHOLE or "inputs"


@dataclass
class EventType:
    """Definition of a class of change that can trigger revisits."""
    name: str
    mode: str  # "published" or "evaluated"
    subject_kind: Optional[str]  # None: the subject is the subscriber itself
    routes: list
    payload: dict  # {attribute: is_required}
    default_responsible: str  # "owner", "subject" or a stakeholder-role ID
    default_due: Optional[Duration]
    custom: bool = False
    location: Optional[Location] = None


@dataclass
class Baseline:
    subscriber: str
    date: Optional[date]
    location: Optional[Location] = None


@dataclass
class Subscription:
    """A subscriber's declaration that it wants to be notified of an event type."""
    subscriber: str
    event_type: str
    every: Optional[Duration] = None
    at: Optional[date] = None
    due: Optional[Duration] = None
    responsible: Optional[str] = None
    subject: Optional[str] = None
    location: Optional[Location] = None


@dataclass
class Event:
    """An entry in the append-only event log."""
    id: str
    type: str
    date: Optional[date]
    subject: str  # element ID or "topic:<name>"
    payload: dict = field(default_factory=dict)
    publisher: str = ""
    location: Optional[Location] = None


@dataclass
class Revisit:
    """The obligation created when an event reaches a subscriber."""
    id: str
    event: str
    subscriber: str
    scope: Scope
    responsible: str
    opened: Optional[date]
    due: Optional[date]
    outcome: Optional[str] = None  # None while open
    closed: Optional[date] = None
    rationale: str = ""
    successor: Optional[str] = None
    effect: Optional[str] = None
    follows: Optional[str] = None
    location: Optional[Location] = None

    @property
    def is_open(self) -> bool:
        return self.outcome is None


@dataclass
class Finding:
    """A rule violation. Severity is "error" (MUST) or "warning" (SHOULD)."""
    rule: str
    message: str
    location: Optional[Location] = None
    severity: str = "error"

    def __str__(self):
        prefix = f"{self.location}: " if self.location else ""
        return f"{prefix}{self.severity} {self.rule}: {self.message}"


@dataclass
class Document:
    """Everything a binding extracts from one document."""
    source: str = ""
    title: str = ""
    files: list = field(default_factory=list)  # every file read: the source and what it includes
    extensions: dict = field(default_factory=dict)  # name -> version
    elements: list = field(default_factory=list)
    links: list = field(default_factory=list)
    vocabulary: list = field(default_factory=list)
    reserved_schemes: set = field(default_factory=set)  # prefixes that are not URI schemes
    baselines: list = field(default_factory=list)
    subscriptions: list = field(default_factory=list)
    event_types: list = field(default_factory=list)  # custom types only
    events: list = field(default_factory=list)
    revisits: list = field(default_factory=list)
    topics: dict = field(default_factory=dict)  # topic name -> [element IDs]
    notation_findings: list = field(default_factory=list)
