package io.github.avrilfanomar.arc42ext.model

/** Elements and links of one document, with the derived inverse relations and rules L1, L3-L8. */
class LinkGraph(
    val elementList: List<Element>,
    val links: List<Link>,
    vocabulary: List<VocabularyEntry> = emptyList(),
    reservedSchemes: Set<String> = emptySet(),
) {
    /** The first element with each ID (L1 reports the others). */
    val elements: Map<String, Element> = elementList.reversed().associateBy { it.id }

    private val customLinkTypes: Map<String, LinkRule> =
        vocabulary.filter { it.type == "link" }.associate { it.name to LinkRule(it.fromKinds, it.toKinds) }
    private val reservedSchemes: Set<String> =
        reservedSchemes + vocabulary.filter { ':' in it.name }.map { Catalog.namespaceOf(it.name) }
    private val outgoing: Map<String, List<Link>> = links.groupBy { it.source }
    private val incoming: Map<String, List<Link>> = links.groupBy { it.target }

    val linkTypes: Map<String, LinkRule> get() = Catalog.LINK_TYPES + customLinkTypes

    /** A target is an external URI when it has a scheme that is not reserved (L3). */
    fun isExternal(target: String): Boolean =
        URI.containsMatchIn(target) && target.substringBefore(':') !in reservedSchemes

    fun kindOf(id: String): String? = elements[id]?.kind

    /** Links written at an element, in document order. */
    fun linksFrom(id: String): List<Link> = outgoing[id].orEmpty()

    /** Links into an element: the derived inverse relation, never written as links of their own. */
    fun linksTo(id: String): List<Link> = incoming[id].orEmpty()

    fun validate(): List<Finding> =
        checkUniqueIds() + checkTargets() + checkKinds() + checkSupersedesAcyclic() + checkKnownLinkTypes() +
            checkSingleOwner()

    /** L1: element IDs are unique. */
    private fun checkUniqueIds(): List<Finding> {
        val seen = HashSet<String>()
        return elementList.filterNot { seen.add(it.id) }
            .map { Finding("L1", "duplicate element ID '${it.id}'", it.location) }
    }

    /** L3: link sources and targets resolve, or targets are external URIs. */
    private fun checkTargets(): List<Finding> = links.flatMap { link ->
        listOfNotNull(
            if (link.source !in elements) Finding("L3", "link source '${link.source}' is not an element", link.location) else null,
            if (link.target !in elements && !isExternal(link.target)) {
                Finding("L3", "link target '${link.target}' does not resolve", link.location)
            } else null,
        )
    }

    /** L4: source and target kinds are allowed by the link type. */
    private fun checkKinds(): List<Finding> {
        val types = linkTypes
        return links.mapNotNull { link ->
            val rule = types[link.type] ?: return@mapNotNull null // reported by L7
            val sourceKind = kindOf(link.source) ?: return@mapNotNull null // reported by L3
            val targetKind = kindOf(link.target) ?: return@mapNotNull null
            if ((rule.from == null || sourceKind in rule.from) && (rule.to == null || targetKind in rule.to)) {
                null
            } else {
                Finding("L4", "'${link.type}' does not allow $sourceKind -> $targetKind (${link.source} -> ${link.target})",
                    link.location)
            }
        }
    }

    /** L5: the supersedes graph is acyclic. Reports one link per cycle. */
    private fun checkSupersedesAcyclic(): List<Finding> {
        val graph = links.filter { it.type == "supersedes" }.groupBy { it.source }
        val findings = mutableListOf<Finding>()
        val visiting = HashSet<String>()
        val done = HashSet<String>()

        fun visit(node: String) {
            visiting += node
            for (link in graph[node].orEmpty()) {
                val next = link.target
                if (next in visiting) {
                    findings += Finding("L5", "'supersedes' cycle through $node -> $next", link.location)
                } else if (next !in done) {
                    visit(next)
                }
            }
            visiting -= node
            done += node
        }

        for (node in graph.keys) {
            if (node !in visiting && node !in done) visit(node)
        }
        return findings
    }

    /** L7: every link type used is core or declared. */
    private fun checkKnownLinkTypes(): List<Finding> {
        val types = linkTypes
        return links.filter { it.type !in types }.map { Finding("L7", "unknown link type '${it.type}'", it.location) }
    }

    /** L8: at most one owned-by link per element. */
    private fun checkSingleOwner(): List<Finding> =
        links.filter { it.type == "owned-by" }.groupBy { it.source }.filterValues { it.size > 1 }
            .map { (source, owned) -> Finding("L8", "'$source' has ${owned.size} owned-by links", owned.first().location) }

    companion object {
        private val URI = Regex("^[A-Za-z][A-Za-z0-9+.-]*:")

        fun of(document: Arc42Document) =
            LinkGraph(document.elements, document.links, document.vocabulary, document.reservedSchemes)

        /** L6: declared custom names are namespaced, listed once, and refer to known kinds. */
        fun validateVocabulary(vocabulary: List<VocabularyEntry>): List<Finding> {
            val findings = mutableListOf<Finding>()
            val seen = HashSet<Pair<String, String>>()
            val kinds = Catalog.CORE_KINDS + vocabulary.filter { it.type == "kind" }.map { it.name }
            for (entry in vocabulary) {
                if (!Catalog.isNamespaced(entry.name)) {
                    findings += Finding("L6", "custom ${entry.type} '${entry.name}' is not of the form <namespace>:<name>",
                        entry.location)
                }
                if (!seen.add(entry.type to entry.name)) {
                    findings += Finding("L6", "custom ${entry.type} '${entry.name}' is declared more than once", entry.location)
                }
                if (entry.type == "link") {
                    for (kind in entry.fromKinds.orEmpty() + entry.toKinds.orEmpty()) {
                        if (kind !in kinds) {
                            findings += Finding("L6", "custom link type '${entry.name}' refers to unknown kind '$kind'",
                                entry.location)
                        }
                    }
                }
            }
            return findings
        }
    }
}
