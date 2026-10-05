"""The examples validate cleanly, the triggers example's hand-written evaluation matches
the checker, and removing all extension markup leaves plain arc42."""

import re
import unittest
from datetime import date
from pathlib import Path

from arc42ext.__main__ import check

REPO = Path(__file__).resolve().parents[3]
LINKS_EXAMPLE = REPO / "extensions/links/EN/example.adoc"
TRIGGERS_EXAMPLE = REPO / "extensions/triggers/EN/example.adoc"
EVALUATION_DATE = date(2026, 10, 4)

ARC42_SECTIONS = [
    ("section-introduction-and-goals", "Introduction and Goals"),
    ("section-architecture-constraints", "Architecture Constraints"),
    ("section-context-and-scope", "Context and Scope"),
    ("section-solution-strategy", "Solution Strategy"),
    ("section-building-block-view", "Building Block View"),
    ("section-runtime-view", "Runtime View"),
    ("section-deployment-view", "Deployment View"),
    ("section-concepts", "Crosscutting Concepts"),
    ("section-design-decisions", "Architecture Decisions"),
    ("section-quality-scenarios", "Quality Requirements"),
    ("section-technical-risks", "Risks and Technical Debts"),
    ("section-glossary", "Glossary"),
]

EXTENSION_ROLE = re.compile(r"^\[\.(links|triggers[\w-]*|vocabulary)\]$")
ELEMENT_ANCHOR = re.compile(r"\[\[(sh|rq|qg|qs|con|need|adr|in|risk|td)-[^\]]*\]\]")


def strip_extensions(text: str) -> str:
    """Remove extension markup: role blocks, the declaration, element anchors and xrefs to them,
    the Revisit Triggers subsection and the evaluation appendix."""
    text = re.sub(r"\n=== Revisit Triggers\n.*?(?=\n\[\[section-)", "\n", text, flags=re.S)
    text = re.sub(r"\n\[appendix\]\n== Expected evaluation.*", "\n", text, flags=re.S)
    out, lines, i = [], text.splitlines(), 0
    while i < len(lines):
        line = lines[i]
        if EXTENSION_ROLE.match(line.strip()):
            i += 1
            if i < len(lines) and lines[i].startswith("|==="):
                i += 1
                while i < len(lines) and not lines[i].startswith("|==="):
                    i += 1
                i += 1
            else:
                while i < len(lines) and lines[i].strip():
                    i += 1
            continue
        if line.startswith("Extensions used:"):
            i += 1
            continue
        out.append(ELEMENT_ANCHOR.sub("", line))
        i += 1
    return "\n".join(out)


class TestExamples(unittest.TestCase):

    def test_examples_have_no_findings(self):
        for example in (LINKS_EXAMPLE, TRIGGERS_EXAMPLE):
            with self.subTest(example=example.parent.parent.name):
                findings, _ = check(example, EVALUATION_DATE)
                self.assertEqual([str(f) for f in findings], [])

    def test_triggers_status_matches_expected_evaluation(self):
        text = TRIGGERS_EXAMPLE.read_text()
        summary_table = text.split("=== Summary", 1)[1]
        written = dict(re.findall(r"^\|([A-Z][\w ]+?) \|(.+)$", summary_table, re.M))

        def ids(value):
            return [] if value.strip() == "none" else [v.strip() for v in value.split(",")]

        _, status = check(TRIGGERS_EXAMPLE, EVALUATION_DATE)
        self.assertEqual([d.subscriber for d in status.due], ids(written["Due time subscriptions"]))
        self.assertEqual([m.event for m in status.missing], ids(written["Missing revisits"]))
        self.assertEqual(status.open, ids(written["Open revisits"]))
        self.assertEqual(status.overdue, ids(written["Overdue revisits"]))
        self.assertEqual(status.open, ["rv-004"])

    def test_stripped_examples_are_plain_arc42(self):
        for example in (LINKS_EXAMPLE, TRIGGERS_EXAMPLE):
            with self.subTest(example=example.parent.parent.name):
                stripped = strip_extensions(example.read_text())
                for anchor, title in ARC42_SECTIONS:
                    self.assertIn(f"[[{anchor}]]\n== {title}", stripped)
                self.assertIn("|Role/Name|Contact|Expectations", stripped)
                for token in ("[.links]", "[.triggers", "[.vocabulary]", "Extensions used:", "[[adr-", "[[sh-"):
                    self.assertNotIn(token, stripped)
                # the stakeholders table still has three cells per row
                table = stripped.split("|Role/Name|Contact|Expectations", 1)[1].split("|===", 1)[0]
                cells = [line for line in table.splitlines() if line.startswith("|")]
                self.assertEqual(len(cells) % 3, 0)


if __name__ == "__main__":
    unittest.main()
