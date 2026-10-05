"""The GUI's data on the triggers example: the dashboard matches the example's hand-written
evaluation, the catalogue shows derived inverse links, and the suggested rows, once pasted,
leave nothing due or missing."""

import tempfile
import unittest
from datetime import date
from pathlib import Path

from arc42ext.analysis import analyze, catalogue, dashboard, element_detail
from arc42ext.model import WHOLE

REPO = Path(__file__).resolve().parents[3]
TRIGGERS_EXAMPLE = REPO / "extensions/triggers/EN/example.adoc"


def paste(text: str, role: str, row: str) -> str:
    """Append a row to the table with the given role, as a user would."""
    start = text.index(f"[{role}]")
    end = text.index("\n|===", text.index("|===", start) + 4)
    return f"{text[:end]}\n\n{row}{text[end:]}"


class TestDashboard(unittest.TestCase):

    def test_matches_the_expected_evaluation(self):
        board = dashboard(analyze(TRIGGERS_EXAMPLE, date(2026, 10, 4)))
        self.assertEqual((board.due, board.missing, board.open), ([], [], []))
        [item] = board.overdue
        self.assertEqual((item.revisit.id, item.subscriber, item.responsible, item.due, item.days_left),
                         ("rv-004", "adr-007", "sh-architect", date(2026, 10, 3), -1))
        self.assertEqual((item.event.id, item.event.type), ("ev-003", "alternative.emerged"))
        self.assertEqual(board.roles, ["sh-product-owner", "sh-cfo", "sh-ops", "sh-architect"])

    def test_role_filter(self):
        a = analyze(TRIGGERS_EXAMPLE, date(2026, 10, 4))
        self.assertTrue(dashboard(a, role="sh-cfo").empty)
        self.assertEqual([i.revisit.id for i in dashboard(a, role="sh-architect").overdue], ["rv-004"])

    def test_due_subscription_suggests_event_and_revisit_rows(self):
        board = dashboard(analyze(TRIGGERS_EXAMPLE, date(2026, 10, 28)))
        [item] = board.due
        self.assertEqual((item.subscriber, item.due, item.responsible), ("adr-007", date(2026, 10, 28), "sh-architect"))
        self.assertEqual([(r.table, r.text) for r in item.rows], [
            ("triggers-events", "|ev-006 |2026-10-28 |time.elapsed |adr-007 | |"),
            ("triggers-revisits", "|rv-006 |ev-006 |adr-007 |whole |sh-architect |2026-10-28 |2026-11-27 | | |"),
        ])

    def test_pasted_rows_leave_nothing_due_or_missing(self):
        on = date(2026, 10, 28)
        text = TRIGGERS_EXAMPLE.read_text()
        for item in dashboard(analyze(TRIGGERS_EXAMPLE, on)).due:
            for row in item.rows:
                text = paste(text, f".{row.table}", row.text)
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "example.adoc"
            copy.write_text(text)
            a = analyze(copy, on)
        self.assertEqual([str(f) for f in a.findings], [])
        self.assertEqual((a.status.due, a.status.missing, a.status.open), ([], [], ["rv-004", "rv-006"]))

    def test_missing_revisit_row_is_ready_to_paste(self):
        text = TRIGGERS_EXAMPLE.read_text()
        start = text.index("\n|rv-005\n")
        text = text[:start] + text[text.index("\n|===", start):]  # drop rv-005
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "example.adoc"
            copy.write_text(text)
            [item] = dashboard(analyze(copy, date(2026, 10, 4))).missing
            self.assertEqual((item.event.id, item.subscriber, item.scope, item.due), ("ev-004", "adr-007", WHOLE,
                                                                                     date(2026, 10, 19)))
            copy.write_text(paste(text, ".triggers-revisits", item.rows[0].text))
            a = analyze(copy, date(2026, 10, 4))
        self.assertEqual(a.findings, [])
        self.assertEqual(a.status.missing, [])


class TestCatalogue(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.a = analyze(TRIGGERS_EXAMPLE, date(2026, 10, 4))

    def test_groups_in_document_order(self):
        groups = dict(catalogue(self.a))
        self.assertEqual(list(groups)[:3], ["Introduction and Goals", "Architecture Constraints",
                                            "Architecture Decisions"])
        self.assertEqual([e.element.id for e in groups["Architecture Decisions"]][:2], ["adr-004", "adr-007"])
        self.assertIn("decision", dict(catalogue(self.a, by="kind")))

    def test_incoming_links(self):
        self.assertEqual(element_detail(self.a, "sh-cfo").incoming, {"owned-by": ["con-001", "in-007-cost"]})
        need = element_detail(self.a, "need-async-messaging")
        self.assertEqual((need.incoming["addresses"], need.topics), (["adr-004", "adr-007"], ["messaging"]))

    def test_superseded_subscriber(self):
        state = element_detail(self.a, "adr-004").state
        self.assertEqual((state.active, state.superseded_by, state.next_due),
                         (False, [("adr-007", date(2026, 3, 2))], None))

    def test_subscriber_timeline(self):
        detail = element_detail(self.a, "adr-007")
        self.assertEqual([(t.event_id, [r.id for r in t.revisits], t.missing) for t in detail.timeline], [
            ("ev-001", ["rv-001"], False), ("ev-002", ["rv-002", "rv-003"], False), ("ev-003", ["rv-004"], False),
            ("ev-004", ["rv-005"], False)])
        self.assertEqual((detail.state.next_due, detail.state.open_revisits), (date(2026, 10, 28), ["rv-004"]))
        stakeholder = next(s for s in detail.subscriptions if s.event_type == "stakeholder.changed")
        self.assertEqual((stakeholder.responsible_rule, stakeholder.duration), ("subject", "P30D"))

    def test_role_lists_what_it_owes(self):
        self.assertEqual([i.revisit.id for i in element_detail(self.a, "sh-architect").assigned.overdue], ["rv-004"])
        self.assertIsNone(element_detail(self.a, "adr-007").assigned)
        self.assertIsNone(element_detail(self.a, "nope"))


if __name__ == "__main__":
    unittest.main()
