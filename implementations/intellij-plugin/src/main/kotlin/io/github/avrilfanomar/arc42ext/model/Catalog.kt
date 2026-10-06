package io.github.avrilfanomar.arc42ext.model

/** Core vocabulary of the links extension (links/EN/SPEC.adoc, "Vocabulary"). */
object Catalog {
    const val STAKEHOLDER_ROLE = "stakeholder-role"

    val CORE_KINDS: Set<String> = setOf(
        STAKEHOLDER_ROLE, "requirement", "quality-goal", "quality-scenario",
        "constraint", "need", "decision", "input", "risk", "debt",
    )

    /** Link type -> the source and target kinds it allows; null means any kind. */
    val LINK_TYPES: Map<String, LinkRule> = linkedMapOf(
        "owned-by" to LinkRule(null, setOf(STAKEHOLDER_ROLE)),
        "uses-input" to LinkRule(setOf("decision", "risk", "debt"), setOf("input")),
        "addresses" to LinkRule(setOf("decision"), setOf("need")),
        "supersedes" to LinkRule(setOf("decision"), setOf("decision")),
        "relates-to" to LinkRule(null, null),
    )

    private val NAMESPACED = Regex("^[a-z][a-z0-9-]*:[a-z][a-z0-9-]*$")

    /** The `<namespace>:<name>` form of custom kinds and link types. */
    fun isNamespaced(name: String): Boolean = NAMESPACED.matches(name)

    fun namespaceOf(name: String): String = name.substringBefore(':')
}

data class LinkRule(val from: Set<String>?, val to: Set<String>?)
