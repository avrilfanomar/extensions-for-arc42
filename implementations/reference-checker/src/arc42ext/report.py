"""Text and JSON output for the CLI. The JSON shape matches the conformance expected.json files."""

import json

from .model import WHOLE
from .triggers import Status, format_scope


def summary(findings: list, status: Status) -> dict:
    return {
        "date": status.date.isoformat(),
        "errors": sorted({f.rule for f in findings if f.severity == "error"}),
        "warnings": sorted({f.rule for f in findings if f.severity == "warning"}),
        "due": [{"subscriber": d.subscriber, "date": d.date.isoformat()} for d in status.due],
        "missing_revisits": [{
            "event": m.event,
            "subscriber": m.subscriber,
            "scope": format_scope(m.scope),
            "responsible": m.responsible,
            "due": m.due.isoformat() if m.due else None,
        } for m in status.missing],
        "open": sorted(status.open),
        "overdue": sorted(status.overdue),
    }


def findings_text(findings: list) -> str:
    if not findings:
        return "No rule violations."
    return "\n".join(str(f) for f in sorted(findings, key=lambda f: (f.severity != "error", str(f.location or ""))))


def status_json(findings: list, status: Status) -> str:
    data = summary(findings, status)
    data["findings"] = [{"rule": f.rule, "severity": f.severity, "message": f.message,
                         "location": str(f.location) if f.location else None} for f in findings]
    return json.dumps(data, indent=2)


def status_text(findings: list, status: Status, suggest: bool = False) -> str:
    lines = [f"Status at {status.date.isoformat()}"]
    errors = sum(1 for f in findings if f.severity == "error")
    if errors:
        lines.append(f"  ({errors} rule violation(s); run 'arc42ext validate' for details)")

    def section(title, items):
        lines.append(f"\n{title}:")
        lines.extend(f"  {item}" for item in items) if items else lines.append("  none")

    section("Due time subscriptions", [f"{d.subscriber}: due {d.date}" for d in status.due])
    section("Missing revisits", [
        f"{m.event} -> {m.subscriber}: scope {_scope(m.scope)}, responsible {m.responsible or '?'}, due {m.due}"
        for m in status.missing])
    section("Open revisits", status.open)
    section("Overdue revisits", status.overdue)

    if suggest and (status.due or status.missing):
        lines.append("\nSuggested rows (fill in IDs):")
        for d in status.due:
            lines.append(f"  [.triggers-events]  |ev-? |{d.date} |time.elapsed |{d.subscriber} | |")
        for m in status.missing:
            lines.append(f"  [.triggers-revisits] |rv-? |{m.event} |{m.subscriber} |{_scope(m.scope)} "
                         f"|{m.responsible or ''} |{status.date} |{m.due or ''} | | |")
    return "\n".join(lines)


def _scope(scope) -> str:
    return WHOLE if scope == WHOLE else ", ".join(sorted(scope))
