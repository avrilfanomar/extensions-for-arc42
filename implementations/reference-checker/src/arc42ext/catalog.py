"""Core vocabulary of the links extension and core event types of the triggers extension."""

import re

from .dates import parse_duration
from .model import WHOLE, EventType, Route

CORE_KINDS = frozenset({
    "stakeholder-role", "requirement", "quality-goal", "quality-scenario",
    "constraint", "need", "decision", "input", "risk", "debt",
})

# Link type -> (allowed source kinds, allowed target kinds); None means any kind.
LINK_TYPES = {
    "owned-by": (None, frozenset({"stakeholder-role"})),
    "uses-input": (frozenset({"decision", "risk", "debt"}), frozenset({"input"})),
    "addresses": (frozenset({"decision"}), frozenset({"need"})),
    "supersedes": (frozenset({"decision"}), frozenset({"decision"})),
    "relates-to": (None, None),
}

SUBSCRIBER_KINDS = frozenset({"decision", "risk", "debt"})

OUTCOMES = frozenset({"confirmed", "amended", "superseded", "dismissed"})
EFFECTS = frozenset({"unchanged", "reopened"})

TIME_ELAPSED = "time.elapsed"

CORE_EVENT_TYPES = {
    t.name: t for t in [
        EventType(
            name=TIME_ELAPSED,
            mode="evaluated",
            subject_kind=None,
            routes=[Route((), WHOLE)],
            payload={},
            default_responsible="owner",
            default_due=parse_duration("P30D"),
        ),
        EventType(
            name="stakeholder.changed",
            mode="published",
            subject_kind="stakeholder-role",
            routes=[Route(("uses-input", "owned-by"), "inputs"), Route(("owned-by",), WHOLE)],
            payload={"previous": True, "new": True, "reason": False},
            default_responsible="subject",
            default_due=parse_duration("P30D"),
        ),
        EventType(
            name="alternative.emerged",
            mode="published",
            subject_kind="need",
            routes=[Route(("addresses",), WHOLE)],
            payload={"candidate": True, "category": True, "claim": True, "source": True, "maturity": False},
            default_responsible="owner",
            default_due=parse_duration("P60D"),
        ),
    ]
}

_NAMESPACED = re.compile(r"^[a-z][a-z0-9-]*:[a-z][a-z0-9-]*$")
_NAMESPACED_EVENT = re.compile(r"^[a-z][a-z0-9-]*:[a-z][a-z0-9.-]*$")


def is_namespaced(name: str, event_type: bool = False) -> bool:
    """Check the `<namespace>:<name>` form (event type names may also contain dots)."""
    return bool((_NAMESPACED_EVENT if event_type else _NAMESPACED).match(name))


def namespace_of(name: str) -> str:
    return name.split(":", 1)[0]
