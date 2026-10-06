package io.github.avrilfanomar.arc42ext.model

/** A line of a file, 1-based. The file is named the way the binding's sources name it. */
data class Location(val file: String, val line: Int) {
    override fun toString() = "$file:$line"
}

/** An identifiable piece of content in the document. [section] is the arc42 chapter it lives in. */
data class Element(val id: String, val kind: String, val title: String, val section: String?, val location: Location)

/** A directed, typed relation from an element to an element or an external URI. */
data class Link(val source: String, val type: String, val target: String, val location: Location)

/** A declared custom kind or link type. For a link type, null kinds mean any kind. */
data class VocabularyEntry(
    val type: String, // "kind" or "link"
    val name: String,
    val fromKinds: Set<String>?,
    val toKinds: Set<String>?,
    val location: Location,
)

enum class Severity { ERROR, WARNING }

/** A rule violation: an error for a MUST, a warning for a SHOULD. */
data class Finding(val rule: String, val message: String, val location: Location?, val severity: Severity = Severity.ERROR) {
    override fun toString() = (location?.let { "$it: " } ?: "") + "${severity.name.lowercase()} $rule: $message"
}

// The triggers extension, as written in the document. Dates, durations and clauses are kept as text:
// this implementation shows them but does not evaluate the triggers rules.

data class Baseline(val subscriber: String, val date: String, val location: Location)

data class Subscription(val subscriber: String, val eventType: String, val clauses: String, val location: Location)

data class Event(val id: String, val date: String, val type: String, val subject: String, val location: Location)

data class Revisit(
    val id: String,
    val event: String,
    val subscriber: String,
    val scope: String,
    val responsible: String,
    val opened: String,
    val due: String,
    val outcome: String, // empty while open
    val closed: String,
    val rationale: String,
    val location: Location,
) {
    val isOpen: Boolean get() = outcome.isEmpty()
}

/** Everything a binding extracts from one document. */
data class Arc42Document(
    val source: String,
    val title: String,
    val files: List<String>, // every file read: the source and what it includes
    val extensions: Map<String, String>, // name -> version
    val elements: List<Element>,
    val links: List<Link>,
    val vocabulary: List<VocabularyEntry>,
    val reservedSchemes: Set<String>, // prefixes that are not URI schemes
    val baselines: List<Baseline>,
    val subscriptions: List<Subscription>,
    val events: List<Event>,
    val revisits: List<Revisit>,
    val notationFindings: List<Finding>,
)

/** One document, its link graph and every finding on it. */
class Analysis(val document: Arc42Document, val graph: LinkGraph, val findings: List<Finding>) {
    val errors: List<Finding> get() = findings.filter { it.severity == Severity.ERROR }
}
