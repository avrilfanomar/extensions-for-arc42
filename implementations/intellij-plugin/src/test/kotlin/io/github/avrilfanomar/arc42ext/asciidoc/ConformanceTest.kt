package io.github.avrilfanomar.arc42ext.asciidoc

import io.github.avrilfanomar.arc42ext.Repository
import io.github.avrilfanomar.arc42ext.model.Severity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.io.path.name
import kotlin.io.path.readText

/**
 * Runs every conformance case of the AsciiDoc binding (extensions/(name)/conformance/README.adoc) for the rules
 * this implementation checks: links L1 and L3-L8. Cases of the triggers extension count too, as they declare
 * triggers, which reserves `topic:` (L3). As in the reference checker, rules are compared as sets of IDs, and
 * no case may contain a notation error (B1).
 */
class ConformanceTest {

    @Test
    fun casesExist() {
        assertTrue(Repository.conformanceCases.size >= 40)
    }

    @Test
    fun linksRules() {
        val covered = mutableSetOf<String>()
        val failures = Repository.conformanceCases.mapNotNull { case ->
            val name = "${case.parent.parent.name}/${case.name}"
            val analysis = analyze(case.resolve("document.adoc").toString(), FileSources())
            val expected = expectedRules(case.resolve("expected.json").readText())
            covered += expected
            val actual = analysis.findings.map { "${it.severity}:${it.rule}" }.toSet()
            when {
                "${Severity.ERROR}:B1" in actual -> "$name: notation error: ${analysis.findings}"
                actual.filter { ":L" in it }.toSet() != expected -> "$name: expected $expected, got ${analysis.findings}"
                else -> null
            }
        }
        assertEquals("", failures.joinToString("\n"))
        assertEquals(listOf("L1", "L3", "L4", "L5", "L6", "L7", "L8").map { "${Severity.ERROR}:$it" }.toSet(), covered)
    }

    @Test
    fun topicIsReservedOnlyUnderTriggers() {
        val names = Repository.conformanceCases.map { it.name }
        assertFalse("links case 11 is missing", names.none { it.startsWith("11-topic-uri-links-only") })
        assertFalse("triggers case 30 is missing", names.none { it.startsWith("30-topic-reserved-under-triggers") })
    }

    /** The links rules of an expected.json, as "ERROR:L3" and "WARNING:Ln". */
    private fun expectedRules(json: String): Set<String> =
        listOf("errors" to Severity.ERROR, "warnings" to Severity.WARNING).flatMap { (key, severity) ->
            val list = Regex(""""$key"\s*:\s*\[([^\]]*)]""").find(json)?.groupValues?.get(1).orEmpty()
            Regex(""""([^"]+)"""").findAll(list).map { it.groupValues[1] }.filter { it.startsWith("L") }
                .map { "$severity:$it" }.toList()
        }.toSet()
}
