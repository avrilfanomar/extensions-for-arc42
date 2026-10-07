package io.github.avrilfanomar.arc42ext.screenshots

import com.intellij.ide.ui.LafManager
import com.intellij.ide.ui.UISettings
import com.intellij.notification.Notification
import com.intellij.notification.NotificationsManager
import com.intellij.openapi.actionSystem.ActionManager
import com.intellij.openapi.actionSystem.ActionToolbar
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.application.EDT
import com.intellij.openapi.application.ex.ApplicationManagerEx
import com.intellij.openapi.application.ModalityState
import com.intellij.openapi.application.asContextElement
import com.intellij.openapi.command.WriteCommandAction
import com.intellij.openapi.components.Service
import com.intellij.openapi.components.service
import com.intellij.openapi.diagnostic.logger
import com.intellij.openapi.editor.Document
import com.intellij.openapi.editor.LogicalPosition
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.fileEditor.FileEditorManager
import com.intellij.openapi.fileEditor.OpenFileDescriptor
import com.intellij.openapi.project.DumbService
import com.intellij.openapi.project.Project
import com.intellij.openapi.startup.ProjectActivity
import com.intellij.openapi.vfs.LocalFileSystem
import com.intellij.openapi.wm.IdeFocusManager
import com.intellij.openapi.wm.ToolWindow
import com.intellij.openapi.wm.ToolWindowId
import com.intellij.openapi.wm.ToolWindowManager
import com.intellij.openapi.wm.WindowManager
import com.intellij.openapi.wm.ex.ToolWindowEx
import com.intellij.ui.EditorNotificationPanel
import com.intellij.ui.treeStructure.Tree
import com.intellij.util.ui.UIUtil
import com.intellij.util.ui.tree.TreeUtil
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import java.awt.Dialog
import java.awt.Frame
import java.awt.Rectangle
import java.awt.Robot
import java.awt.Window
import java.nio.file.Files
import java.nio.file.Path
import javax.imageio.ImageIO
import javax.swing.tree.DefaultMutableTreeNode
import javax.swing.tree.TreePath
import kotlin.time.Duration.Companion.seconds

private val LOG = logger<ScreenshotDriver>()

/**
 * The EDT even while a modal dialog shows, so that waiting for the IDE can't hang on one. Only for reading the UI:
 * changes to the IDE belong in [Dispatchers.EDT].
 */
private val ANY_MODALITY = Dispatchers.EDT + ModalityState.any().asContextElement()

/**
 * Captures the Marketplace screenshots of the arc42 tool window, then exits the IDE: with 0 if every screenshot
 * was taken, else with 1 after capturing `failure.png`. Does nothing unless the system property
 * `arc42ext.screenshots.dir` names the directory to write to.
 */
class ScreenshotDriver : ProjectActivity {
    override suspend fun execute(project: Project) {
        val dir = System.getProperty("arc42ext.screenshots.dir") ?: return
        project.service<DriverScope>().scope.launch { Screenshots(project, Path.of(dir)).runAndExit() }
    }
}

/** Runs the driver outside the startup activities, so that it doesn't hold them up. */
@Service(Service.Level.PROJECT)
internal class DriverScope(val scope: CoroutineScope)

private class Screenshots(private val project: Project, private val dir: Path) {

    private lateinit var tree: Tree
    private lateinit var document: Document

    suspend fun runAndExit() {
        val exitCode = try {
            withTimeout(300.seconds) { run() }
            0
        } catch (e: Throwable) {
            LOG.warn("Screenshots failed", e)
            report("FAILED: $e")
            runCatching { capture("failure") }
            1
        }
        // Exit outside this coroutine, which closing the project cancels. A dialog that is still open would keep a
        // non-modal exit from running.
        val modality = if (dialogs().isEmpty()) ModalityState.nonModal() else ModalityState.any()
        ApplicationManager.getApplication().invokeLater({ ApplicationManagerEx.getApplicationEx().exit(true, true, exitCode) }, modality)
    }

    private suspend fun run() {
        Files.createDirectories(dir)
        Files.deleteIfExists(dir.resolve("failure.png"))
        waitFor("indexing to finish", 240) { (!DumbService.isDumb(project)).takeIf { it } }
        withContext(Dispatchers.EDT) { setUpIde() }
        tree = waitFor("arc42 tree with adr-007") { arc42Tree()?.takeIf { it.node(element("adr-007")) != null } }

        shot("01-overview", editorLine = 0) {
            expandOnly(group("Architecture Decisions"))
        }
        shot("02-links", editorLine = lineOf("[[adr-007]]")) {
            select(expandOnly(element("adr-007")))
        }
        shot("03-group-by-kind", editorLine = 0) {
            toggleGroupByKind()
            waitFor("tree grouped by kind") { tree.node(group("decision")) }
            expandOnly(group("decision"))
            expandOnly(group("stakeholder-role"), collapseOthers = false)
            tree.clearSelection()
        }
        shot("04-triggers", editorLine = lineOf("[[adr-007]]")) {
            toggleGroupByKind()
            waitFor("tree grouped by section") { tree.node(group("Architecture Decisions")) }
            val triggers = expandOnly(element("adr-007"), { it.userObject?.toString() == "triggers" })
            select(triggers)
            tree.scrollPathToVisible(TreePath(triggers.lastLeaf.path))
        }
        // An unsaved edit that breaks a link target: the tool window reports it as you type (rule L3).
        val original = "relates-to:: <<adr-007>>, <<adr-004>>"
        val broken = "relates-to:: <<adr-007>>, <<adr-005>>"
        shot("05-problems", editorLine = lineOf(original)) {
            edit(original, broken)
            val problems = waitFor("problems node") { tree.node { it.userObject?.toString() == "problems" } }
            select(expandOnly(problems).firstLeaf)
        }
        withContext(Dispatchers.EDT) { edit(broken, original) }
    }

    /** Sets up the state that every screenshot shares: theme, window size, the open document, the tool window. */
    private fun setUpIde() {
        val lafManager = LafManager.getInstance()
        val themes = lafManager.installedThemes.toList()
        report("themes: " + themes.joinToString { it.name })
        val light = themes.firstOrNull { it.name == "Light" } ?: themes.first { !it.isDark }
        if (lafManager.currentUIThemeLookAndFeel?.id != light.id) {
            lafManager.setCurrentLookAndFeel(light, false)
            lafManager.updateUI()
        }

        // The status bar shows the progress of background tasks, which some IDEs run for minutes after startup.
        val uiSettings = UISettings.getInstance()
        if (uiSettings.showStatusBar) {
            uiSettings.showStatusBar = false
            uiSettings.fireUISettingsChanged()
        }

        // There is no window manager under Xvfb to size the window.
        val frame = WindowManager.getInstance().getFrame(project)!!
        frame.extendedState = Frame.NORMAL
        frame.bounds = Rectangle(0, 0, WIDTH, HEIGHT)
        frame.validate()

        val path = "${project.basePath}/docs/arc42.adoc"
        val file = LocalFileSystem.getInstance().refreshAndFindFileByPath(path) ?: error("no $path")
        FileEditorManager.getInstance(project).openFile(file, true)
        document = FileDocumentManager.getInstance().getDocument(file)!!

        ToolWindowManager.getInstance(project).getToolWindow(ToolWindowId.PROJECT_VIEW)?.hide()
        val toolWindow = arc42ToolWindow()
        toolWindow.show()
        (toolWindow as ToolWindowEx).stretchWidth(TOOL_WINDOW_WIDTH - toolWindow.component.width)
    }

    private suspend fun shot(name: String, editorLine: Int, arrange: suspend () -> Unit) {
        report(name)
        withContext(Dispatchers.EDT) {
            arrange()
            scrollEditorTo(editorLine)
            IdeFocusManager.getInstance(project).requestFocus(tree, true)
        }
        delay(1.seconds)
        capture(name)
    }

    private suspend fun capture(name: String) {
        // Some dialogs close by themselves, such as the progress of a task that blocks the IDE.
        if (name != "failure") waitFor("dialogs to close") { dialogs().isEmpty().takeIf { it } }
        val bounds = withContext(ANY_MODALITY) {
            NotificationsManager.getNotificationsManager()
                .getNotificationsOfType(Notification::class.java, project).forEach(Notification::expire)
            val frame = WindowManager.getInstance().getFrame(project)!!
            // Banners above the editor, such as one that suggests an AsciiDoc plugin, aren't about this plugin.
            UIUtil.findComponentsOfType(frame.rootPane, EditorNotificationPanel::class.java).forEach { it.isVisible = false }
            Rectangle(frame.locationOnScreen, frame.size)
        }
        delay(300)
        val image = Robot().createScreenCapture(bounds)
        ImageIO.write(image, "png", dir.resolve("$name.png").toFile())
        report("wrote $name.png (${image.width}×${image.height})")
    }

    private fun arc42ToolWindow(): ToolWindow =
        ToolWindowManager.getInstance(project).getToolWindow("arc42") ?: error("no arc42 tool window")

    private fun arc42Tree(): Tree? = UIUtil.findComponentOfType(arc42ToolWindow().component, Tree::class.java)

    private fun toggleGroupByKind() {
        val toolbar = UIUtil.uiTraverser(arc42ToolWindow().component).filter(ActionToolbar::class.java).first()
            ?: error("no arc42 toolbar")
        val action = toolbar.actions.single { it.templateText == "Group by Kind" }
        ActionManager.getInstance().tryToExecute(action, null, toolbar.component, "Arc42ToolWindow", true)
    }

    /** Collapses the tree except for the path to the node that [first] finds, then expands that path. */
    private fun expandOnly(
        first: (DefaultMutableTreeNode) -> Boolean,
        vararg then: (DefaultMutableTreeNode) -> Boolean,
        collapseOthers: Boolean = true,
    ): DefaultMutableTreeNode {
        if (collapseOthers) {
            for (row in tree.rowCount - 1 downTo 1) tree.collapseRow(row)
        }
        var node = tree.node(first) ?: error("no node in the tree")
        tree.expandPath(TreePath(node.path))
        for (next in then) {
            node = node.children().toList().map { it as DefaultMutableTreeNode }.single(next)
            tree.expandPath(TreePath(node.path))
        }
        return node
    }

    private fun expandOnly(node: DefaultMutableTreeNode) = expandOnly({ it === node })

    private fun select(node: DefaultMutableTreeNode) {
        tree.selectionPath = TreePath(node.path)
    }

    private fun edit(old: String, new: String) {
        val start = document.text.indexOf(old).also { check(it >= 0) { "no '$old' in the document" } }
        WriteCommandAction.runWriteCommandAction(project) { document.replaceString(start, start + old.length, new) }
    }

    private fun lineOf(text: String): Int =
        document.text.lineSequence().indexOfFirst { it.startsWith(text) }.also { check(it >= 0) { "no '$text'" } }

    /** Shows [line] two lines below the top of the editor. */
    private fun scrollEditorTo(line: Int) {
        val file = FileDocumentManager.getInstance().getFile(document)!!
        val editor = FileEditorManager.getInstance(project).openTextEditor(OpenFileDescriptor(project, file, line, 0), false)!!
        editor.scrollingModel.disableAnimation()
        val top = editor.logicalPositionToXY(LogicalPosition(maxOf(line - 2, 0), 0)).y
        editor.scrollingModel.scrollVertically(top)
    }

    /** Polls [condition] on the EDT until it returns a value. */
    private suspend fun <T : Any> waitFor(what: String, seconds: Int = 30, condition: () -> T?): T {
        val deadline = System.currentTimeMillis() + seconds * 1000
        while (true) {
            withContext(ANY_MODALITY) { condition() }?.let { return it }
            check(System.currentTimeMillis() < deadline) { "timed out waiting for $what; open dialogs: ${dialogs()}" }
            delay(200)
        }
    }

    /** The titles of the dialogs that show. */
    private fun dialogs(): List<String> = Window.getWindows().filter { it is Dialog && it.isShowing }.map { (it as Dialog).title }

    private fun report(message: String) {
        LOG.info(message)
        println("[screenshots] $message")
    }

    private companion object {
        const val WIDTH = 1280
        const val HEIGHT = 800
        const val TOOL_WINDOW_WIDTH = 680
    }
}

private fun Tree.node(predicate: (DefaultMutableTreeNode) -> Boolean): DefaultMutableTreeNode? =
    TreeUtil.findNode(model.root as DefaultMutableTreeNode) { predicate(it) }

private fun element(id: String): (DefaultMutableTreeNode) -> Boolean = { it.userObject?.toString()?.startsWith("$id ") == true }

private fun group(title: String): (DefaultMutableTreeNode) -> Boolean = { it.userObject?.toString() == title }
