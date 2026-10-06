package io.github.avrilfanomar.arc42ext.asciidoc

import java.io.IOException
import java.nio.file.Files
import java.nio.file.Path

/**
 * Supplies the text of the files a reader follows. Paths are opaque names chosen by the implementation;
 * they end up in every [io.github.avrilfanomar.arc42ext.model.Location].
 */
interface Sources {
    /** The text of [path], or null when it cannot be read. */
    fun text(path: String): String?

    /** The file an `include::` [target] written in [from] refers to, or null when there is none. */
    fun resolve(from: String, target: String): String?
}

/** Files on disk, named by their normalized absolute paths. */
class FileSources : Sources {
    override fun text(path: String): String? = try {
        Files.readString(Path.of(path))
    } catch (_: IOException) {
        null
    }

    override fun resolve(from: String, target: String): String? {
        val file = Path.of(from).toAbsolutePath().parent.resolve(target).normalize()
        return if (Files.isRegularFile(file)) file.toString() else null
    }
}
