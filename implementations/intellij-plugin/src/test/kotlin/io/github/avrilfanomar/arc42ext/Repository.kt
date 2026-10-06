package io.github.avrilfanomar.arc42ext

import java.nio.file.Files
import java.nio.file.Path
import kotlin.io.path.isDirectory
import kotlin.io.path.name

/** The repository this plugin lives in: its extensions/ hold the conformance cases and examples. */
object Repository {
    val root: Path = Path.of(
        System.getProperty("arc42ext.repository") ?: error("run the tests with Gradle, which sets arc42ext.repository")
    ).toRealPath()

    val linksExample: Path = root.resolve("extensions/links/EN/example.adoc")
    val triggersExample: Path = root.resolve("extensions/triggers/EN/example.adoc")

    /** Every conformance case of the AsciiDoc binding, of every extension. */
    val conformanceCases: List<Path> = Files.list(root.resolve("extensions")).use { extensions ->
        extensions.toList().map { it.resolve("conformance/asciidoc") }.filter { it.isDirectory() }
            .flatMap { dir -> Files.list(dir).use { it.toList() } }
            .filter { it.isDirectory() }
            .sortedBy { "${it.parent.parent.parent.name}/${it.name}" }
    }
}
