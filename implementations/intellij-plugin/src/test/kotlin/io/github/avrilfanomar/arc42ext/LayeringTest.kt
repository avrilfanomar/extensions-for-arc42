package io.github.avrilfanomar.arc42ext

import org.junit.Assert.assertEquals
import org.junit.Test
import java.nio.file.Files
import kotlin.io.path.name
import kotlin.io.path.readLines

/**
 * The layers of the reference checker, kept apart the same way: the concept (model) knows nothing of
 * AsciiDoc, and neither the concept nor the binding (asciidoc) knows the IDE.
 */
class LayeringTest {

    private val sources = Repository.root.resolve("implementations/intellij-plugin/src/main/kotlin/io/github/avrilfanomar/arc42ext")

    @Test
    fun modelDependsOnNothingElse() {
        assertEquals(emptyList<String>(), imports("model", "com.intellij.", "$PACKAGE.asciidoc", "$PACKAGE.ide"))
    }

    @Test
    fun bindingDoesNotDependOnTheIde() {
        assertEquals(emptyList<String>(), imports("asciidoc", "com.intellij.", "$PACKAGE.ide"))
    }

    private fun imports(layer: String, vararg forbidden: String): List<String> =
        Files.walk(sources.resolve(layer)).use { files ->
            files.filter { it.name.endsWith(".kt") }.toList().flatMap { file ->
                file.readLines().filter { line ->
                    line.startsWith("import ") && forbidden.any { line.removePrefix("import ").startsWith(it) }
                }.map { "${file.name}: $it" }
            }
        }

    private companion object {
        const val PACKAGE = "io.github.avrilfanomar.arc42ext"
    }
}
