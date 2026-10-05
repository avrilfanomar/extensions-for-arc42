"""Tests for links extension rules."""

import unittest

from arc42ext.links import LinkGraph, validate_vocabulary
from arc42ext.model import Element, Link, Location, VocabularyEntry


def rules(graph):
    return [f.rule for f in graph.validate()]


def graph(elements, links, vocabulary=(), reserved=()):
    return LinkGraph([Element(i, k) for i, k in elements], [Link(*l) for l in links], vocabulary, reserved)


ARCH = ("sh-arch", "stakeholder-role")
ADR1 = ("adr-001", "decision")


class TestLinksRules(unittest.TestCase):

    def test_valid_minimal_graph(self):
        self.assertEqual(rules(graph([ARCH, ADR1], [("adr-001", "owned-by", "sh-arch")])), [])

    def test_l1_duplicate_id_reported_at_duplicate(self):
        g = LinkGraph([Element("sh-arch", "stakeholder-role", location=Location("a", 1)),
                       Element("sh-arch", "stakeholder-role", location=Location("a", 9))], [])
        findings = g.validate()
        self.assertEqual([f.rule for f in findings], ["L1"])
        self.assertEqual(findings[0].location.line, 9)

    def test_l3_dangling_target(self):
        self.assertEqual(rules(graph([ADR1], [("adr-001", "owned-by", "sh-nonexistent")])), ["L3"])

    def test_l3_dangling_source(self):
        self.assertIn("L3", rules(graph([ARCH], [("adr-404", "owned-by", "sh-arch")])))

    def test_l3_external_uri_allowed(self):
        self.assertEqual(rules(graph([ADR1, ARCH], [("adr-001", "owned-by", "sh-arch"),
                                                    ("adr-001", "relates-to", "https://example.com/doc")])), [])

    def test_l3_reserved_scheme_is_not_a_uri(self):
        g = graph([ADR1], [("adr-001", "relates-to", "topic:messaging")], reserved={"topic"})
        self.assertEqual(rules(g), ["L3"])

    def test_l3_declared_namespace_is_not_a_uri(self):
        vocabulary = [VocabularyEntry("kind", "acme:product")]
        g = graph([ADR1], [("adr-001", "relates-to", "acme:checkout")], vocabulary)
        self.assertEqual(rules(g), ["L3"])

    def test_l4_kind_mismatch(self):
        g = graph([ADR1, ("rq-001", "requirement")], [("adr-001", "supersedes", "rq-001")])
        self.assertEqual(rules(g), ["L4"])

    def test_l4_any_allows_custom_kinds(self):
        vocabulary = [VocabularyEntry("kind", "acme:product")]
        g = graph([("acme-p-1", "acme:product"), ARCH], [("acme-p-1", "owned-by", "sh-arch")], vocabulary)
        self.assertEqual(rules(g), [])

    def test_l5_supersedes_cycle(self):
        g = graph([ADR1, ("adr-002", "decision"), ("adr-003", "decision")],
                  [("adr-001", "supersedes", "adr-002"), ("adr-002", "supersedes", "adr-003"),
                   ("adr-003", "supersedes", "adr-001")])
        findings = g.validate()
        self.assertEqual([f.rule for f in findings], ["L5"])

    def test_l7_unknown_link_type(self):
        self.assertEqual(rules(graph([ADR1, ARCH], [("adr-001", "owned_by", "sh-arch")])), ["L7"])

    def test_l7_declared_custom_link_type(self):
        vocabulary = [VocabularyEntry("link", "acme:implements", frozenset({"decision"}), None)]
        g = graph([ADR1, ("adr-002", "decision")], [("adr-001", "acme:implements", "adr-002")], vocabulary)
        self.assertEqual(rules(g), [])

    def test_l8_two_owners(self):
        g = graph([ADR1, ARCH, ("sh-cfo", "stakeholder-role")],
                  [("adr-001", "owned-by", "sh-arch"), ("adr-001", "owned-by", "sh-cfo")])
        self.assertEqual(rules(g), ["L8"])

    def test_l6_vocabulary(self):
        findings = validate_vocabulary([
            VocabularyEntry("link", "implements"),
            VocabularyEntry("kind", "acme:product"),
            VocabularyEntry("kind", "acme:product"),
            VocabularyEntry("link", "acme:covers", frozenset({"acme:unknown"}), None),
        ])
        self.assertEqual(len(findings), 3)
        self.assertEqual({f.rule for f in findings}, {"L6"})

    def test_follow_returns_first_hop(self):
        g = graph([ADR1, ("in-001", "input"), ("sh-cfo", "stakeholder-role")],
                  [("adr-001", "uses-input", "in-001"), ("in-001", "owned-by", "sh-cfo")])
        self.assertEqual(g.follow("adr-001", ("uses-input", "owned-by")), [("in-001", "sh-cfo")])
        self.assertEqual(g.follow("adr-001", ()), [(None, "adr-001")])

    def test_sources_are_the_derived_inverse(self):
        g = graph([ADR1, ("adr-002", "decision"), ARCH],
                  [("adr-001", "owned-by", "sh-arch"), ("adr-002", "owned-by", "sh-arch"),
                   ("adr-002", "supersedes", "adr-001"), ("adr-002", "relates-to", "https://example.com")])
        self.assertEqual([(l.source, l.type) for l in g.sources("sh-arch")],
                         [("adr-001", "owned-by"), ("adr-002", "owned-by")])
        self.assertEqual([l.source for l in g.sources("adr-001", "supersedes")], ["adr-002"])
        self.assertEqual(g.sources("adr-001", "owned-by"), [])
        self.assertEqual(g.superseded_by("adr-001"), ["adr-002"])


if __name__ == "__main__":
    unittest.main()
