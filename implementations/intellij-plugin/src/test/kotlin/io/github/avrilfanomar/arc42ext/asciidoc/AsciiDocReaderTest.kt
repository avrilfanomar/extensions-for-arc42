package io.github.avrilfanomar.arc42ext.asciidoc

import io.github.avrilfanomar.arc42ext.Repository
import io.github.avrilfanomar.arc42ext.model.Link
import io.github.avrilfanomar.arc42ext.model.Location
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.nio.file.Files

class AsciiDocReaderTest {

    @get:Rule
    val folder = TemporaryFolder()

    @Test
    fun examplesAreClean() {
        for (example in listOf(Repository.linksExample, Repository.triggersExample)) {
            assertEquals(example.toString(), emptyList<Any>(), analyze(example.toString(), FileSources()).findings)
        }
    }

    @Test
    fun triggersExample() {
        val analysis = analyze(Repository.triggersExample.toString(), FileSources())
        val graph = analysis.graph
        val adr = graph.elements.getValue("adr-007")
        assertEquals("decision", adr.kind)
        assertEquals("ADR-007: Message broker selection", adr.title)
        assertEquals("Architecture Decisions", adr.section)
        assertEquals(listOf("sh-architect"), graph.linksFrom("adr-007").filter { it.type == "owned-by" }.map { it.target })
        // Inverse relations are derived, never written.
        assertTrue(graph.linksTo("sh-architect").any { it.source == "adr-007" && it.type == "owned-by" })

        val document = analysis.document
        assertEquals(mapOf("links" to "0.1.0", "triggers" to "0.1.0"), document.extensions)
        assertEquals(setOf("topic"), document.reservedSchemes)
        assertTrue(document.subscriptions.any { it.subscriber == "adr-007" && it.eventType == "time.elapsed" })
        assertTrue(document.baselines.any { it.subscriber == "adr-007" })
        val open = document.revisits.filter { it.isOpen }.map { it.id }
        assertEquals(listOf("rv-004"), open) // the example's "Expected evaluation" appendix
    }

    @Test
    fun includedFilesKeepTheirLocations() {
        val root = write("arc42.adoc", """
            = Document

            include::chapters/01.adoc[]

            include::chapters/09.adoc[leveloffset=0]
        """)
        write("chapters/01.adoc", """
            == Introduction and Goals

            Extensions used: links v0.1.0

            === Stakeholders

            * [[sh-arch]]Architect
        """)
        val chapter9 = write("chapters/09.adoc", """
            == Architecture Decisions

            [[adr-001]]
            === ADR-001: Broker

            [.links]
            owned-by:: <<sh-arch>>
        """)

        val analysis = analyze(root.path, FileSources())
        assertEquals(emptyList<Any>(), analysis.findings)
        assertEquals(Location(chapter9.path, 3), analysis.graph.elements.getValue("adr-001").location)
        assertEquals(listOf(Link("adr-001", "owned-by", "sh-arch", Location(chapter9.path, 7))), analysis.document.links)
        assertEquals(3, analysis.document.files.size)
    }

    @Test
    fun discoverFindsTheRootNotTheChapterWithTheDeclaration() {
        val root = write("arc42.adoc", "= Document\n\ninclude::01.adoc[]\n")
        val chapter = write("01.adoc", "== Introduction and Goals\n\nExtensions used: links v0.1.0\n")
        val unrelated = write("notes.adoc", "= Notes\n\nNo declaration here.\n")
        val listing = write("template.adoc", "= Template\n\n----\nExtensions used: links v0.1.0\n----\n")

        val found = discover(listOf(chapter.path, unrelated.path, listing.path, root.path), FileSources())
        assertEquals(listOf(root.path), found.map { it.document.source })
    }

    @Test
    fun includeProblemsAreNotationErrors() {
        val root = write("loop.adoc", "= Loop\n\ninclude::loop.adoc[]\ninclude::missing.adoc[]\n")
        val findings = analyze(root.path, FileSources()).findings
        assertEquals(listOf("B1", "B1"), findings.map { it.rule })
        assertEquals(listOf(3, 4), findings.map { it.location?.line })
    }

    /** The IDE reads documents as they are typed, so every cut of a valid document must read without throwing. */
    @Test
    fun halfTypedDocumentsDoNotThrow() {
        val documents = Files.walk(Repository.root.resolve("extensions")).use { paths ->
            paths.filter { it.toString().endsWith(".adoc") }.toList()
        }
        assertTrue(documents.size > 40)
        val files = FileSources()
        for (document in documents.map { it.toString() }) {
            val text = files.text(document)!!
            // Every line end, and the middle of every line.
            val cuts = text.indices.filter { text[it] == '\n' }.flatMap { end ->
                listOf(end, end - (end - text.lastIndexOf('\n', end - 1)) / 2)
            }
            for (cut in cuts) {
                val sources = object : Sources by files {
                    override fun text(path: String) = if (path == document) text.substring(0, cut) else files.text(path)
                }
                try {
                    analyze(document, sources)
                } catch (e: Exception) {
                    throw AssertionError("$document cut at offset $cut: ${text.substring(0, cut).takeLast(80)}", e)
                }
            }
        }
    }

    private fun write(path: String, text: String): File =
        File(folder.root, path).apply {
            parentFile.mkdirs()
            writeText(text.trimIndent() + "\n")
        }
}
