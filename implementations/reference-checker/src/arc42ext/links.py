"""Links extension: link graph, traversal and rules L1, L3-L8."""

import re
from collections import Counter, defaultdict
from typing import Optional

from .catalog import CORE_KINDS, LINK_TYPES, is_namespaced, namespace_of
from .model import Document, Element, Finding, Link

_URI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


class LinkGraph:
    """Elements and links of one document, with lookups used by other extensions."""

    def __init__(self, elements: list, links: list, vocabulary: list = (), reserved_schemes=()):
        self.element_list = list(elements)
        self.links = list(links)
        self.elements: dict = {}
        for element in self.element_list:
            self.elements.setdefault(element.id, element)

        self.custom_kinds = {v.name for v in vocabulary if v.type == "kind"}
        self.custom_link_types = {v.name: (v.from_kinds, v.to_kinds) for v in vocabulary if v.type == "link"}
        self.reserved_schemes = set(reserved_schemes)
        self.reserved_schemes.update(namespace_of(v.name) for v in vocabulary if ":" in v.name)

        self._out = defaultdict(list)
        for link in self.links:
            self._out[(link.source, link.type)].append(link.target)

    @classmethod
    def from_document(cls, doc: Document) -> "LinkGraph":
        return cls(doc.elements, doc.links, doc.vocabulary, doc.reserved_schemes)

    def link_types(self) -> dict:
        return {**LINK_TYPES, **self.custom_link_types}

    def is_external(self, target: str) -> bool:
        """A target is an external URI when it has a scheme that is not reserved (L3)."""
        return bool(_URI.match(target)) and target.split(":", 1)[0] not in self.reserved_schemes

    def kind_of(self, element_id: str) -> Optional[str]:
        element = self.elements.get(element_id)
        return element.kind if element else None

    def targets(self, source: str, link_type: str) -> list:
        return list(self._out.get((source, link_type), []))

    def owner(self, element_id: str) -> Optional[str]:
        owners = self.targets(element_id, "owned-by")
        return owners[0] if owners else None

    def follow(self, source: str, steps: tuple) -> list:
        """Follow link types in order. Returns (first hop, end) pairs; the empty route yields (None, source)."""
        if not steps:
            return [(None, source)]
        results = []
        for first in self.targets(source, steps[0]):
            ends = [first]
            for step in steps[1:]:
                ends = [t for e in ends for t in self.targets(e, step)]
            results.extend((first, end) for end in ends)
        return results

    def superseded_by(self, element_id: str) -> list:
        return [link.source for link in self.links if link.type == "supersedes" and link.target == element_id]

    def validate(self) -> list:
        findings = []
        findings += self._check_unique_ids()
        findings += self._check_targets()
        findings += self._check_kinds()
        findings += self._check_supersedes_acyclic()
        findings += self._check_known_link_types()
        findings += self._check_single_owner()
        return findings

    def _check_unique_ids(self) -> list:
        """L1: element IDs are unique."""
        seen = set()
        findings = []
        for element in self.element_list:
            if element.id in seen:
                findings.append(Finding("L1", f"duplicate element ID '{element.id}'", element.location))
            seen.add(element.id)
        return findings

    def _check_targets(self) -> list:
        """L3: link sources and targets resolve, or targets are external URIs."""
        findings = []
        for link in self.links:
            if link.source not in self.elements:
                findings.append(Finding("L3", f"link source '{link.source}' is not an element", link.location))
            if link.target not in self.elements and not self.is_external(link.target):
                findings.append(Finding("L3", f"link target '{link.target}' does not resolve", link.location))
        return findings

    def _check_kinds(self) -> list:
        """L4: source and target kinds are allowed by the link type."""
        findings = []
        types = self.link_types()
        for link in self.links:
            if link.type not in types or link.source not in self.elements or link.target not in self.elements:
                continue  # reported by L7 or L3
            allowed_from, allowed_to = types[link.type]
            source_kind, target_kind = self.kind_of(link.source), self.kind_of(link.target)
            if (allowed_from is not None and source_kind not in allowed_from) or \
                    (allowed_to is not None and target_kind not in allowed_to):
                findings.append(Finding(
                    "L4", f"'{link.type}' does not allow {source_kind} -> {target_kind} "
                          f"({link.source} -> {link.target})", link.location))
        return findings

    def _check_supersedes_acyclic(self) -> list:
        """L5: the supersedes graph is acyclic. Reports one link per cycle."""
        graph = defaultdict(list)
        for link in self.links:
            if link.type == "supersedes":
                graph[link.source].append(link)

        findings = []
        state = {}  # node -> "visiting" | "done"

        def visit(node):
            state[node] = "visiting"
            for link in graph.get(node, []):
                nxt = link.target
                if state.get(nxt) == "visiting":
                    findings.append(Finding("L5", f"'supersedes' cycle through {node} -> {nxt}", link.location))
                elif nxt not in state:
                    visit(nxt)
            state[node] = "done"

        for node in list(graph):
            if node not in state:
                visit(node)
        return findings

    def _check_known_link_types(self) -> list:
        """L7: every link type used is core or declared."""
        types = self.link_types()
        return [Finding("L7", f"unknown link type '{link.type}'", link.location)
                for link in self.links if link.type not in types]

    def _check_single_owner(self) -> list:
        """L8: at most one owned-by link per element."""
        counts = Counter(link.source for link in self.links if link.type == "owned-by")
        findings = []
        reported = set()
        for link in self.links:
            if link.type == "owned-by" and counts[link.source] > 1 and link.source not in reported:
                reported.add(link.source)
                findings.append(Finding("L8", f"'{link.source}' has {counts[link.source]} owned-by links", link.location))
        return findings


def validate_vocabulary(vocabulary: list) -> list:
    """L6: declared custom names are namespaced, listed once, and refer to known kinds."""
    findings = []
    seen = set()
    kinds = set(CORE_KINDS) | {v.name for v in vocabulary if v.type == "kind"}
    for entry in vocabulary:
        if not is_namespaced(entry.name):
            findings.append(Finding("L6", f"custom {entry.type} '{entry.name}' is not of the form <namespace>:<name>",
                                    entry.location))
        if (entry.type, entry.name) in seen:
            findings.append(Finding("L6", f"custom {entry.type} '{entry.name}' is declared more than once", entry.location))
        seen.add((entry.type, entry.name))
        if entry.type == "link":
            for kind in (entry.from_kinds or set()) | (entry.to_kinds or set()):
                if kind not in kinds:
                    findings.append(Finding("L6", f"custom link type '{entry.name}' refers to unknown kind '{kind}'",
                                            entry.location))
    return findings


def validate(doc: Document) -> list:
    return validate_vocabulary(doc.vocabulary) + LinkGraph.from_document(doc).validate()
