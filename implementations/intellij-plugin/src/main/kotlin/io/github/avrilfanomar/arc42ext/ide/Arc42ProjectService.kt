package io.github.avrilfanomar.arc42ext.ide

import com.intellij.openapi.Disposable
import com.intellij.openapi.application.EDT
import com.intellij.openapi.application.readAction
import com.intellij.openapi.components.Service
import com.intellij.openapi.diagnostic.thisLogger
import com.intellij.openapi.editor.EditorFactory
import com.intellij.openapi.editor.event.DocumentEvent
import com.intellij.openapi.editor.event.DocumentListener
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.progress.ProgressManager
import com.intellij.openapi.project.Project
import com.intellij.openapi.project.guessProjectDir
import com.intellij.openapi.roots.ProjectFileIndex
import com.intellij.openapi.util.Disposer
import com.intellij.openapi.vfs.VfsUtilCore
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.openapi.vfs.VirtualFileManager
import com.intellij.openapi.vfs.newvfs.BulkFileListener
import com.intellij.openapi.vfs.newvfs.events.VFileCreateEvent
import com.intellij.openapi.vfs.newvfs.events.VFileDeleteEvent
import com.intellij.openapi.vfs.newvfs.events.VFileEvent
import com.intellij.openapi.vfs.newvfs.events.VFileMoveEvent
import com.intellij.openapi.vfs.newvfs.events.VFilePropertyChangeEvent
import com.intellij.util.concurrency.annotations.RequiresReadLock
import io.github.avrilfanomar.arc42ext.asciidoc.Sources
import io.github.avrilfanomar.arc42ext.asciidoc.discover
import io.github.avrilfanomar.arc42ext.model.Analysis
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch
import java.io.IOException

/**
 * The arc42 documents of a project, analyzed in the background. The analysis runs again shortly after an
 * AsciiDoc file changes, in an editor (unsaved) or on disk.
 */
@Service(Service.Level.PROJECT)
class Arc42ProjectService(private val project: Project, private val scope: CoroutineScope) : Disposable {

    private val requests = Channel<Unit>(Channel.CONFLATED)
    private val latest = MutableStateFlow<Arc42Snapshot?>(null)

    /** The latest analysis; null until the first one completes. */
    val snapshot: StateFlow<Arc42Snapshot?> = latest.asStateFlow()

    init {
        scope.launch {
            requests.receiveAsFlow().collectLatest {
                delay(DEBOUNCE_MILLIS)
                try {
                    latest.value = readAction { analyzeProject() }
                } catch (e: CancellationException) { // also ProcessCanceledException
                    throw e
                } catch (e: Exception) {
                    // Keep collecting: the next change may well read fine.
                    thisLogger().error("cannot analyze the arc42 documents", e)
                }
            }
        }
        EditorFactory.getInstance().eventMulticaster.addDocumentListener(object : DocumentListener {
            override fun documentChanged(event: DocumentEvent) {
                val file = FileDocumentManager.getInstance().getFile(event.document) ?: return
                if (isAsciiDoc(file.name) && (ProjectFileIndex.getInstance(project).isInContent(file) || isRead(file))) {
                    refresh()
                }
            }
        }, this)
        project.messageBus.connect(this).subscribe(VirtualFileManager.VFS_CHANGES, object : BulkFileListener {
            override fun before(events: List<VFileEvent>) {
                // A deleted directory can only be recognized as one before it is gone.
                if (events.any { it is VFileDeleteEvent && it.file.isDirectory }) refresh()
            }

            override fun after(events: List<VFileEvent>) {
                if (events.any(::changesDocuments)) refresh()
            }
        })
        refresh()
    }

    /** Analyzes the project again soon. */
    fun refresh() {
        requests.trySend(Unit)
    }

    /** Calls [listener] on the EDT with the latest snapshot and every new one, until [parent] is disposed. */
    fun subscribe(parent: Disposable, listener: (Arc42Snapshot?) -> Unit) {
        val job = scope.launch(Dispatchers.EDT) { snapshot.collect(listener) }
        Disposer.register(parent) { job.cancel() }
    }

    /** Finds and analyzes the arc42 documents among the AsciiDoc files of the project content. */
    @RequiresReadLock
    fun analyzeProject(): Arc42Snapshot {
        val sources = VfsSources()
        val candidates = mutableListOf<String>()
        ProjectFileIndex.getInstance(project).iterateContent { file ->
            ProgressManager.checkCanceled()
            if (!file.isDirectory && isAsciiDoc(file.name)) candidates += sources.add(file)
            true
        }
        return Arc42Snapshot(discover(candidates, sources), sources.files, project.guessProjectDir())
    }

    private fun isRead(file: VirtualFile): Boolean = latest.value?.file(file.path) == file

    private fun changesDocuments(event: VFileEvent): Boolean = when {
        isAsciiDoc(event.path) -> true
        event is VFilePropertyChangeEvent -> event.isRename && (isAsciiDoc(event.oldPath) || event.file.isDirectory)
        event is VFileCreateEvent -> event.isDirectory
        event is VFileMoveEvent -> event.file.isDirectory
        else -> false
    }

    override fun dispose() = Unit

    private companion object {
        const val DEBOUNCE_MILLIS = 300L
        val EXTENSIONS = setOf("adoc", "asciidoc")

        fun isAsciiDoc(name: String): Boolean = name.substringAfterLast('.', "").lowercase() in EXTENSIONS
    }
}

/** The arc42 documents of a project at one moment, and the files they were read from. */
class Arc42Snapshot(
    val analyses: List<Analysis>,
    private val files: Map<String, VirtualFile>,
    private val baseDir: VirtualFile?,
) {
    /** The file behind a path of a [io.github.avrilfanomar.arc42ext.model.Location]. */
    fun file(path: String): VirtualFile? = files[path]

    /** A path to show: relative to the project directory where possible. */
    fun presentablePath(path: String): String {
        val file = files[path] ?: return path
        return baseDir?.let { VfsUtilCore.getRelativePath(file, it) } ?: file.presentableUrl
    }
}

/** Files through the VFS, with the unsaved changes of open documents. Needs read access. */
private class VfsSources : Sources {
    val files = HashMap<String, VirtualFile>()

    fun add(file: VirtualFile): String = file.path.also { files[it] = file }

    override fun text(path: String): String? {
        ProgressManager.checkCanceled()
        val file = files[path]?.takeIf { it.isValid } ?: return null
        FileDocumentManager.getInstance().getCachedDocument(file)?.let { return it.text }
        return try {
            VfsUtilCore.loadText(file)
        } catch (_: IOException) {
            null
        }
    }

    override fun resolve(from: String, target: String): String? {
        val base = files[from]?.parent ?: return null
        val file = if (target.startsWith("/")) base.fileSystem.findFileByPath(target) else base.findFileByRelativePath(target)
        return file?.takeIf { !it.isDirectory }?.let(::add)
    }
}
