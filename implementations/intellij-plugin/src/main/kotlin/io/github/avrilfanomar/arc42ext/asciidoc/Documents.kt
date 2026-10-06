package io.github.avrilfanomar.arc42ext.asciidoc

import io.github.avrilfanomar.arc42ext.model.Analysis
import io.github.avrilfanomar.arc42ext.model.LinkGraph

/** The extensions this implementation reads, as named in an `Extensions used:` declaration. */
val SUPPORTED_EXTENSIONS: Set<String> = setOf("links", "triggers")

private val INCLUDE = Regex("""^include::([^\[]+)\[.*]\s*$""")

/** Reads the document at [path] and checks it: notation (B1) and the links rules L1, L3-L8. */
fun analyze(path: String, sources: Sources): Analysis {
    val document = AsciiDocReader(sources).read(path)
    val graph = LinkGraph.of(document)
    val findings = document.notationFindings + LinkGraph.validateVocabulary(document.vocabulary) + graph.validate()
    return Analysis(document, graph, findings)
}

/**
 * Finds the arc42 documents among [candidates] and analyzes them.
 *
 * A document is often split into files: a root that includes one file per chapter. The declaration then sits
 * in an included file, which alone would lack the elements of the other chapters. So a document is a candidate
 * that no other candidate includes and whose text, includes followed, declares one of [SUPPORTED_EXTENSIONS].
 */
fun discover(candidates: Collection<String>, sources: Sources): List<Analysis> {
    val included = HashSet<String>()
    for (path in candidates) {
        for (line in sources.text(path)?.lines().orEmpty()) {
            val include = INCLUDE.find(line) ?: continue
            sources.resolve(path, include.groupValues[1].trim())?.takeIf { it != path }?.let { included += it }
        }
    }
    return candidates.filter { it !in included }.sorted()
        .map { analyze(it, sources) }
        .filter { analysis -> analysis.document.extensions.keys.any { it in SUPPORTED_EXTENSIONS } }
}
