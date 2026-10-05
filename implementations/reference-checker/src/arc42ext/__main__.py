"""CLI entry point for arc42ext."""

import argparse
import sys
from datetime import date
from pathlib import Path

from . import binding_asciidoc, links, report, triggers
from .dates import parse_date
from .links import LinkGraph


def check(path, on: date):
    """Read a document and return (findings, status). Shared by the CLI and the tests."""
    doc = binding_asciidoc.read(path)
    graph = LinkGraph.from_document(doc)
    findings = list(doc.notation_findings) + links.validate(doc) + triggers.validate(doc, on, graph)
    return findings, triggers.status(doc, on, graph)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="arc42ext", description="Reference checker for arc42 extensions")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="Report rule violations (exit 1 on any error)")
    validate_parser.add_argument("document", type=Path, help="Path to .adoc document")
    validate_parser.add_argument("--date", help="Evaluation date (YYYY-MM-DD, default: today)")

    status_parser = subparsers.add_parser("status", help="Report due, missing, open and overdue revisits "
                                                         "(exit 2 if action is needed)")
    status_parser.add_argument("document", type=Path, help="Path to .adoc document")
    status_parser.add_argument("--date", help="Evaluation date (YYYY-MM-DD, default: today)")
    status_parser.add_argument("--json", action="store_true", help="Output JSON")
    status_parser.add_argument("--suggest", action="store_true", help="Print table rows ready to paste")

    args = parser.parse_args(argv)
    on = date.today()
    if args.date:
        on = parse_date(args.date)
        if on is None:
            parser.error(f"invalid --date '{args.date}', expected YYYY-MM-DD")
    if not args.document.is_file():
        parser.error(f"no such file: {args.document}")

    findings, status = check(args.document, on)

    if args.command == "validate":
        print(report.findings_text(findings))
        return 1 if any(f.severity == "error" for f in findings) else 0

    print(report.status_json(findings, status) if args.json else report.status_text(findings, status, args.suggest))
    return 2 if status.needs_action else 0


if __name__ == "__main__":
    sys.exit(main())
