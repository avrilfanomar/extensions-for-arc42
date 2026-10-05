"""Runs every conformance case of the AsciiDoc binding (see extensions/*/conformance/README.adoc)."""

import json
import unittest
from datetime import date
from pathlib import Path

from arc42ext.__main__ import check
from arc42ext.report import summary

REPO = Path(__file__).resolve().parents[3]
CASES = sorted(REPO.glob("extensions/*/conformance/asciidoc/*/"))
KEYS = ["errors", "warnings", "due", "missing_revisits", "open", "overdue"]


def as_set(values):
    return {json.dumps(v, sort_keys=True) for v in values}


class TestConformance(unittest.TestCase):

    def test_cases_exist(self):
        self.assertGreaterEqual(len(CASES), 30)

    def test_cases(self):
        for case in CASES:
            with self.subTest(case=f"{case.parent.parent.parent.name}/{case.name}"):
                expected = json.loads((case / "expected.json").read_text())
                findings, status = check(case / "document.adoc", date.fromisoformat(expected["date"]))
                actual = summary(findings, status)
                for key in KEYS:
                    self.assertEqual(as_set(actual[key]), as_set(expected.get(key, [])),
                                     f"{key}; findings: {[str(f) for f in findings]}")
                self.assertNotIn("B1", actual["errors"], "conformance cases must not contain notation errors")


if __name__ == "__main__":
    unittest.main()
