"""Tests for dates and triggers semantics, on the model directly (no binding)."""

import unittest
from datetime import date

from arc42ext.dates import add, parse_date, parse_duration
from arc42ext.model import (WHOLE, Baseline, Document, Element, Event, Link, Revisit, Subscription)
from arc42ext.triggers import Triggers


class TestDates(unittest.TestCase):

    def test_parse_duration(self):
        self.assertEqual(parse_duration("P1Y6M").months, 6)
        for bad in ("P", "P1H", "PT1M", "1M", "P1M1Y"):
            self.assertIsNone(parse_duration(bad), bad)

    def test_parse_date(self):
        self.assertEqual(parse_date("2026-02-28"), date(2026, 2, 28))
        self.assertIsNone(parse_date("2026-02-30"))
        self.assertIsNone(parse_date("2026-2-3"))

    def test_month_end_clamping(self):
        self.assertEqual(add(date(2026, 1, 31), parse_duration("P1M")), date(2026, 2, 28))

    def test_years_before_months(self):
        # 2028-02-29 + P1Y = 2029-02-28, then + P1M = 2029-03-28
        self.assertEqual(add(date(2028, 2, 29), parse_duration("P1Y1M")), date(2029, 3, 28))

    def test_weeks_and_days(self):
        self.assertEqual(add(date(2026, 1, 1), parse_duration("P1W2D")), date(2026, 1, 10))


def base_document():
    doc = Document()
    doc.elements = [Element("sh-arch", "stakeholder-role"), Element("sh-cfo", "stakeholder-role"),
                    Element("adr-001", "decision"), Element("adr-002", "decision"),
                    Element("in-001", "input"), Element("need-x", "need")]
    doc.links = [Link("adr-001", "owned-by", "sh-arch"), Link("adr-001", "uses-input", "in-001"),
                 Link("in-001", "owned-by", "sh-cfo"), Link("adr-001", "addresses", "need-x"),
                 Link("adr-002", "owned-by", "sh-arch"), Link("adr-002", "addresses", "need-x")]
    doc.baselines = [Baseline("adr-001", date(2026, 1, 1)), Baseline("adr-002", date(2026, 3, 1))]
    return doc


class TestMatching(unittest.TestCase):

    def test_active_at_successor_baseline(self):
        doc = base_document()
        doc.links.append(Link("adr-002", "supersedes", "adr-001"))
        t = Triggers(doc)
        self.assertTrue(t.is_active("adr-001", date(2026, 2, 28)))
        self.assertFalse(t.is_active("adr-001", date(2026, 3, 1)))

    def test_inputs_scope(self):
        doc = base_document()
        doc.subscriptions = [Subscription("adr-001", "stakeholder.changed")]
        event = Event("ev-001", "stakeholder.changed", date(2026, 5, 1), "sh-cfo")
        self.assertEqual(Triggers(doc).match(event), {"adr-001": frozenset({"in-001"})})

    def test_whole_absorbs_inputs(self):
        doc = base_document()
        doc.links[0] = Link("adr-001", "owned-by", "sh-cfo")
        doc.subscriptions = [Subscription("adr-001", "stakeholder.changed")]
        event = Event("ev-001", "stakeholder.changed", date(2026, 5, 1), "sh-cfo")
        self.assertEqual(Triggers(doc).match(event), {"adr-001": WHOLE})

    def test_subject_filter(self):
        doc = base_document()
        doc.elements.append(Element("need-y", "need"))
        doc.topics = {"messaging": ["need-x", "need-y"]}
        doc.subscriptions = [Subscription("adr-001", "alternative.emerged", subject="need-y")]
        event = Event("ev-001", "alternative.emerged", date(2026, 5, 1), "topic:messaging")
        self.assertEqual(Triggers(doc).match(event), {})


class TestTimeEvaluation(unittest.TestCase):

    def doc_with_time(self, revisits=(), events=()):
        doc = base_document()
        doc.subscriptions = [Subscription("adr-001", "time.elapsed", every=parse_duration("P6M"))]
        doc.revisits = list(revisits)
        doc.events = list(events)
        return doc

    def test_due_is_inclusive(self):
        status = Triggers(self.doc_with_time()).status(date(2026, 7, 1))
        self.assertEqual([(d.subscriber, d.date) for d in status.due], [("adr-001", date(2026, 7, 1))])
        self.assertEqual(Triggers(self.doc_with_time()).status(date(2026, 6, 30)).due, [])

    def test_recorded_event_stops_due(self):
        event = Event("ev-001", "time.elapsed", date(2026, 7, 1), "adr-001")
        self.assertEqual(Triggers(self.doc_with_time(events=[event])).status(date(2026, 8, 1)).due, [])

    def test_inputs_revisit_does_not_reset_anchor(self):
        revisit = Revisit("rv-001", "ev-x", "adr-001", frozenset({"in-001"}), "sh-cfo", None, None,
                          outcome="amended", closed=date(2026, 3, 1), effect="unchanged")
        t = Triggers(self.doc_with_time([revisit]))
        self.assertEqual(t.anchor("adr-001", date(2026, 7, 1)), date(2026, 1, 1))

    def test_whole_revisit_resets_anchor(self):
        revisit = Revisit("rv-001", "ev-x", "adr-001", WHOLE, "sh-arch", None, None,
                          outcome="confirmed", closed=date(2026, 3, 1))
        t = Triggers(self.doc_with_time([revisit]))
        self.assertEqual(t.anchor("adr-001", date(2026, 7, 1)), date(2026, 3, 1))
        self.assertEqual(t.status(date(2026, 8, 31)).due, [])


class TestSupersededOutcome(unittest.TestCase):

    def findings(self, successor_links):
        doc = base_document()
        doc.links += successor_links
        doc.events = [Event("ev-001", "time.elapsed", date(2026, 5, 1), "adr-001")]
        doc.subscriptions = [Subscription("adr-001", "time.elapsed", every=parse_duration("P12M"))]
        doc.revisits = [Revisit("rv-001", "ev-001", "adr-001", WHOLE, "sh-arch", date(2026, 5, 1), date(2026, 5, 31),
                                outcome="superseded", closed=date(2026, 5, 20), successor="adr-002")]
        return [f.rule for f in Triggers(doc).validate(date(2026, 5, 21))]

    def test_successor_with_supersedes_link_is_accepted(self):
        self.assertNotIn("T15", self.findings([Link("adr-002", "supersedes", "adr-001")]))

    def test_successor_without_link_or_with_reversed_link_is_rejected(self):
        self.assertIn("T15", self.findings([]))
        self.assertIn("T15", self.findings([Link("adr-001", "supersedes", "adr-002")]))


if __name__ == "__main__":
    unittest.main()
