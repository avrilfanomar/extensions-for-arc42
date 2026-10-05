"""Tests for the AsciiDoc binding reader."""

import tempfile
import unittest
from pathlib import Path

from arc42ext import binding_asciidoc
from arc42ext.model import WHOLE


def read(text, extra_files=None):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name, content in (extra_files or {}).items():
            (root / name).write_text(content, encoding="utf-8")
        (root / "doc.adoc").write_text(text, encoding="utf-8")
        return binding_asciidoc.read(root / "doc.adoc")


class TestBinding(unittest.TestCase):

    def test_includes_are_followed_with_locations(self):
        doc = read("= Doc\n\ninclude::part.adoc[]\n", {"part.adoc": "== Part\n\n* [[rq-001]]Requirement\n"})
        self.assertEqual([e.id for e in doc.elements], ["rq-001"])
        self.assertTrue(doc.elements[0].location.file.endswith("part.adoc"))
        self.assertEqual(doc.elements[0].location.line, 3)

    def test_missing_include_is_reported(self):
        doc = read("= Doc\n\ninclude::nowhere.adoc[]\n")
        self.assertEqual([f.rule for f in doc.notation_findings], ["B1"])

    def test_listing_comment_and_help_blocks_are_skipped(self):
        doc = read("""= Doc

----
[[adr-001]]
----

////
[[adr-002]]
////

// [[adr-003]]

ifdef::arc42help[]
[[adr-004]]
endif::arc42help[]

[[adr-005]]
=== ADR-005
""")
        self.assertEqual([e.id for e in doc.elements], ["adr-005"])

    def test_inline_anchor_in_table_cell(self):
        doc = read("""= Doc

[options="header",cols="1,2,2"]
|===
|Role/Name|Contact|Expectations
| [[sh-cfo]]CFO | finance | Cost
|===
""")
        self.assertEqual([(e.id, e.kind, e.title) for e in doc.elements], [("sh-cfo", "stakeholder-role", "CFO")])

    def test_local_links_belong_to_nearest_anchored_section(self):
        doc = read("""= Doc

[[adr-007]]
=== ADR-007

==== Context

[.links]
uses-input:: <<in-1>>, <<in-2,second input>>
""")
        self.assertEqual([(l.source, l.type, l.target) for l in doc.links],
                         [("adr-007", "uses-input", "in-1"), ("adr-007", "uses-input", "in-2")])

    def test_links_outside_element_section_are_reported(self):
        doc = read("= Doc\n\n== Plain\n\n[.links]\nowned-by:: <<sh-a>>\n")
        self.assertEqual(doc.links, [])
        self.assertEqual([f.rule for f in doc.notation_findings], ["B1"])

    def test_tabular_links(self):
        doc = read("""= Doc

[.links]
|===
|Source |owned-by |relates-to

|<<risk-001>>
|<<sh-ops>>
|https://example.com, <<td-001>>
|===
""")
        self.assertEqual([(l.source, l.type, l.target) for l in doc.links],
                         [("risk-001", "owned-by", "sh-ops"), ("risk-001", "relates-to", "https://example.com"),
                          ("risk-001", "relates-to", "td-001")])

    def test_vocabulary_prefix_defines_custom_kind(self):
        doc = read("""= Doc

[.vocabulary]
|===
|Type |Name |Prefix |From |To |Description
|kind |acme:product |acme-product- | | |Product requirement
|===

* [[acme-product-1]]One-click checkout
""")
        self.assertEqual([(e.id, e.kind) for e in doc.elements], [("acme-product-1", "acme:product")])

    def test_subscriptions_and_clauses(self):
        doc = read("""= Doc

[[adr-001]]
=== ADR-001

[.triggers]
baseline:: 2026-03-02
on time.elapsed:: every P3M
on alternative.emerged:: due P60D, responsible <<sh-arch>>, subject <<need-x>>
on stakeholder.changed:: sometimes
""")
        self.assertEqual(doc.baselines[0].date.isoformat(), "2026-03-02")
        time_sub, alt_sub, _ = doc.subscriptions
        self.assertEqual(str(time_sub.every), "P3M")
        self.assertEqual((str(alt_sub.due), alt_sub.responsible, alt_sub.subject), ("P60D", "sh-arch", "need-x"))
        self.assertEqual([f.rule for f in doc.notation_findings], ["T1"])

    def test_invalid_date_is_t13(self):
        doc = read("= Doc\n\n[[adr-001]]\n=== A\n\n[.triggers]\nbaseline:: 2026-02-30\n")
        self.assertEqual([f.rule for f in doc.notation_findings], ["T13"])

    def test_revisit_closing_fields(self):
        doc = read("""= Doc

[.triggers-revisits]
|===
|ID |Event |Subscriber |Scope |Responsible |Opened |Due |Outcome |Closed |Rationale
|rv-1 |ev-1 |<<adr-001>> |in-1, in-2 |sh-cfo |2026-01-01 |2026-01-31 |amended |2026-01-10 |Lower weight. effect: reopened
|rv-2 |ev-1 |adr-001 |whole |sh-arch |2026-01-10 |2026-02-09 | | |follows: rv-1
|===
""")
        first, second = doc.revisits
        self.assertEqual((first.subscriber, first.scope, first.effect, first.rationale),
                         ("adr-001", frozenset({"in-1", "in-2"}), "reopened", "Lower weight."))
        self.assertEqual((second.scope, second.outcome, second.follows, second.is_open), (WHOLE, None, "rv-1", True))

    def test_wrong_table_columns_are_reported(self):
        doc = read("= Doc\n\n[.triggers-events]\n|===\n|ID |Date\n|ev-1 |2026-01-01\n|===\n")
        self.assertEqual(doc.events, [])
        self.assertEqual([f.rule for f in doc.notation_findings], ["B1"])

    def test_event_type_routes(self):
        doc = read("""= Doc

[.triggers-event-types]
|===
|Name |Mode |Subject kind |Routes |Payload |Default response
|acme:x |published |stakeholder-role |uses-input/owned-by -> inputs; owned-by -> whole |a; b: note (optional) |responsible: subject; due: P10D
|===
""")
        event_type = doc.event_types[0]
        self.assertEqual([(r.steps, r.scope) for r in event_type.routes],
                         [(("uses-input", "owned-by"), "inputs"), (("owned-by",), WHOLE)])
        self.assertEqual(event_type.payload, {"a": True, "b": False})
        self.assertEqual((event_type.default_responsible, str(event_type.default_due)), ("subject", "P10D"))


    def test_closing_fields_ignore_trailing_period(self):
        doc = read("""= Doc

[.triggers-revisits]
|===
|ID |Event |Subscriber |Scope |Responsible |Opened |Due |Outcome |Closed |Rationale
|rv-001 |ev-001 |adr-001 |whole |sh-a |2026-01-01 |2026-02-01 |superseded |2026-01-05 |Replaced by successor: adr-002.
|rv-002 |ev-002 |adr-001 |in-001 |sh-a |2026-01-01 |2026-02-01 |amended |2026-01-05 |Weight lowered, effect: reopened.
|===
""")
        self.assertEqual(doc.revisits[0].successor, "adr-002")
        self.assertEqual(doc.revisits[1].effect, "reopened")

    def test_table_role_on_description_list_is_reported_not_crashing(self):
        for role in ("vocabulary", "triggers-events", "triggers-revisits"):
            with self.subTest(role=role):
                doc = read(f"= Doc\n\n[.{role}]\nfoo:: bar\nbaz:: qux\n")
                self.assertEqual([f.rule for f in doc.notation_findings], ["B1"])


if __name__ == "__main__":
    unittest.main()
