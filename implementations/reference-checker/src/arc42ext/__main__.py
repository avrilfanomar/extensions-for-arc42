"""CLI entry point for arc42ext."""

import argparse
import sys
from datetime import date
from pathlib import Path

from . import report
from .analysis import analyze
from .dates import parse_date


def check(path, on: date):
    """Read a document and return (findings, status). Shared by the CLI and the tests."""
    analysis = analyze(path, on)
    return analysis.findings, analysis.status


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

    serve_parser = subparsers.add_parser("serve", help="Browse revisit status and elements in a local web page "
                                                       "that reloads when the document changes")
    serve_parser.add_argument("document", type=Path, help="Path to .adoc document")
    serve_parser.add_argument("--date", help="Evaluation date (YYYY-MM-DD, default: today, as it changes)")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Address to listen on (default: 127.0.0.1)")
    serve_parser.add_argument("--port", type=int, default=8042, help="Port (default: 8042; 0 picks a free one)")
    serve_parser.add_argument("--open", action="store_true", help="Open the page in a browser")
    serve_parser.add_argument("--editor-url", metavar="TEMPLATE",
                              help="Link source locations to an editor, e.g. 'vscode://file{path}:{line}'")

    args = parser.parse_args(argv)
    fixed = None
    if args.date:
        fixed = parse_date(args.date)
        if fixed is None:
            parser.error(f"invalid --date '{args.date}', expected YYYY-MM-DD")
    if not args.document.is_file():
        parser.error(f"no such file: {args.document}")

    if args.command == "serve":
        from .server import serve  # the HTTP modules load only for this command
        return serve(args.document, fixed, args.host, args.port, args.editor_url, args.open)

    findings, status = check(args.document, fixed or date.today())

    if args.command == "validate":
        print(report.findings_text(findings))
        return 1 if any(f.severity == "error" for f in findings) else 0

    print(report.status_json(findings, status) if args.json else report.status_text(findings, status, args.suggest))
    return 2 if status.needs_action else 0


if __name__ == "__main__":
    sys.exit(main())
