package io.github.avrilfanomar.arc42ext.ide.toolwindow

import com.intellij.icons.AllIcons
import com.intellij.ide.BrowserUtil
import com.intellij.ide.CommonActionsManager
import com.intellij.ide.DefaultTreeExpander
import com.intellij.ide.util.treeView.TreeState
import com.intellij.openapi.Disposable
import com.intellij.openapi.actionSystem.ActionManager
import com.intellij.openapi.actionSystem.ActionUpdateThread
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.DefaultActionGroup
import com.intellij.openapi.actionSystem.Separator
import com.intellij.openapi.components.service
import com.intellij.openapi.fileEditor.OpenFileDescriptor
import com.intellij.openapi.project.DumbAwareAction
import com.intellij.openapi.project.DumbAwareToggleAction
import com.intellij.openapi.project.Project
import com.intellij.openapi.ui.SimpleToolWindowPanel
import com.intellij.ui.ColoredTreeCellRenderer
import com.intellij.ui.DoubleClickListener
import com.intellij.ui.ScrollPaneFactory
import com.intellij.ui.SimpleTextAttributes
import com.intellij.ui.TreeSpeedSearch
import com.intellij.ui.treeStructure.Tree
import com.intellij.util.ui.tree.TreeUtil
import io.github.avrilfanomar.arc42ext.ide.Arc42Bundle
import io.github.avrilfanomar.arc42ext.ide.Arc42ProjectService
import io.github.avrilfanomar.arc42ext.ide.Arc42Snapshot
import io.github.avrilfanomar.arc42ext.model.Catalog
import io.github.avrilfanomar.arc42ext.model.Severity
import java.awt.event.KeyAdapter
import java.awt.event.KeyEvent
import java.awt.event.MouseEvent
import javax.swing.Icon
import javax.swing.JComponent
import javax.swing.JTree
import javax.swing.tree.DefaultMutableTreeNode
import javax.swing.tree.DefaultTreeModel

/** The content of the arc42 tool window: the elements of the project's arc42 documents and their links. */
class Arc42Panel(private val project: Project) : SimpleToolWindowPanel(true, true), Disposable {

    private val root = DefaultMutableTreeNode()
    private val model = DefaultTreeModel(root)
    private val tree = Tree(model)
    private var snapshot: Arc42Snapshot? = null
    private var groupByKind = false

    init {
        tree.isRootVisible = false
        tree.showsRootHandles = true
        tree.cellRenderer = Arc42TreeRenderer()
        tree.emptyText.text = Arc42Bundle["tree.loading"]
        TreeSpeedSearch.installOn(tree, true) { it.lastPathComponent.toString() }
        object : DoubleClickListener() {
            override fun onDoubleClick(event: MouseEvent) = navigate()
        }.installOn(tree)
        tree.addKeyListener(object : KeyAdapter() {
            override fun keyPressed(event: KeyEvent) {
                if (event.keyCode == KeyEvent.VK_ENTER && navigate()) event.consume()
            }
        })
        setContent(ScrollPaneFactory.createScrollPane(tree, true))
        toolbar = createToolbar()
        project.service<Arc42ProjectService>().subscribe(this) { snapshot ->
            if (snapshot != null) {
                val first = this.snapshot == null
                this.snapshot = snapshot
                rebuild(first)
            }
        }
    }

    private fun rebuild(first: Boolean) {
        val snapshot = snapshot ?: return
        val state = TreeState.createOn(tree, root)
        root.removeAllChildren()
        buildTree(snapshot, groupByKind).forEach(root::add)
        model.reload()
        if (first) {
            TreeUtil.expand(tree, if (snapshot.analyses.size == 1) 2 else 1)
        } else {
            state.applyTo(tree, root)
        }
        tree.emptyText.text = Arc42Bundle["tree.empty"]
        tree.emptyText.appendLine(Arc42Bundle["tree.empty.hint"])
    }

    private fun navigate(): Boolean {
        val node = TreeUtil.getLastUserObject(Arc42Node::class.java, tree.selectionPath) ?: return false
        if (node is LinkNode && node.url != null) {
            BrowserUtil.browse(node.url)
            return true
        }
        val location = node.location ?: return false
        val file = snapshot?.file(location.file) ?: return false
        OpenFileDescriptor(project, file, location.line - 1, 0).navigate(true)
        return true
    }

    private fun createToolbar(): JComponent {
        val expander = DefaultTreeExpander(tree)
        val common = CommonActionsManager.getInstance()
        val actions = DefaultActionGroup(
            object : DumbAwareAction(Arc42Bundle.messagePointer("action.refresh.text"),
                Arc42Bundle.messagePointer("action.refresh.description"), AllIcons.Actions.Refresh) {
                override fun actionPerformed(event: AnActionEvent) = project.service<Arc42ProjectService>().refresh()
            },
            object : DumbAwareToggleAction(Arc42Bundle.messagePointer("action.groupByKind.text"),
                Arc42Bundle.messagePointer("action.groupByKind.description"), AllIcons.Actions.GroupBy) {
                override fun isSelected(event: AnActionEvent) = groupByKind

                override fun setSelected(event: AnActionEvent, state: Boolean) {
                    groupByKind = state
                    rebuild(false)
                }

                override fun getActionUpdateThread() = ActionUpdateThread.EDT
            },
            Separator.getInstance(),
            common.createExpandAllAction(expander, tree),
            common.createCollapseAllAction(expander, tree),
        )
        val toolbar = ActionManager.getInstance().createActionToolbar(TOOLBAR_PLACE, actions, true)
        toolbar.targetComponent = this
        return toolbar.component
    }

    override fun dispose() = Unit

    private companion object {
        const val TOOLBAR_PLACE = "Arc42ToolWindow"
    }
}

private class Arc42TreeRenderer : ColoredTreeCellRenderer() {

    override fun customizeCellRenderer(
        tree: JTree, value: Any?, selected: Boolean, expanded: Boolean, leaf: Boolean, row: Int, hasFocus: Boolean,
    ) {
        when (val node = TreeUtil.getUserObject(value)) {
            is DocumentNode -> {
                icon = AllIcons.FileTypes.Text
                append(node.name)
                hint(node.analysis.document.title)
                if (node.analysis.findings.isNotEmpty()) {
                    append("  " + Arc42Bundle["node.problems.count", node.analysis.findings.size],
                        SimpleTextAttributes.ERROR_ATTRIBUTES)
                }
            }
            is ProblemsNode -> {
                icon = AllIcons.Toolwindows.Problems
                append(Arc42Bundle["node.problems"])
                hint(node.count.toString())
            }
            is FindingNode -> {
                val finding = node.finding
                icon = if (finding.severity == Severity.ERROR) AllIcons.General.Error else AllIcons.General.Warning
                append(finding.rule + "  ", SimpleTextAttributes.REGULAR_BOLD_ATTRIBUTES)
                append(finding.message)
                finding.location?.let { hint("${it.file.substringAfterLast('/')}:${it.line}") }
            }
            is GroupNode -> {
                icon = AllIcons.Nodes.Folder
                append(node.title.ifEmpty { Arc42Bundle["node.noSection"] })
                hint(node.count.toString())
            }
            is ElementNode -> {
                icon = kindIcon(node.element.kind)
                append(node.element.id, SimpleTextAttributes.REGULAR_BOLD_ATTRIBUTES)
                append("  " + node.element.title)
                hint(node.element.kind)
            }
            is LinkNode -> {
                append(if (node.outgoing) "${node.link.type} → " else "← ${node.link.type}  ", SimpleTextAttributes.GRAYED_ATTRIBUTES)
                append(node.otherId, when {
                    node.url != null -> SimpleTextAttributes.LINK_PLAIN_ATTRIBUTES
                    node.other == null -> SimpleTextAttributes.ERROR_ATTRIBUTES
                    else -> SimpleTextAttributes.REGULAR_ATTRIBUTES
                })
                node.other?.let { hint(it.title) }
            }
            is TriggersNode -> {
                icon = AllIcons.Vcs.History
                append(Arc42Bundle["node.triggers"])
                node.baseline?.let { hint(Arc42Bundle["node.triggers.baseline", it.date]) }
            }
            is SubscriptionNode -> {
                append("on " + node.subscription.eventType)
                hint(node.subscription.clauses)
            }
            is RevisitNode -> {
                val revisit = node.revisit
                append(revisit.id, SimpleTextAttributes.REGULAR_BOLD_ATTRIBUTES)
                append("  " + (node.event?.type ?: revisit.event))
                hint(listOf(revisit.scope, revisit.responsible).filter { it.isNotEmpty() }.joinToString(" · "))
                append("  " + if (revisit.isOpen) {
                    Arc42Bundle["node.revisit.open", revisit.due]
                } else {
                    Arc42Bundle["node.revisit.closed", revisit.outcome, revisit.closed]
                })
            }
        }
    }

    private fun hint(text: String) {
        if (text.isNotEmpty()) append("  $text", SimpleTextAttributes.GRAYED_ATTRIBUTES)
    }

    private fun kindIcon(kind: String): Icon = when (kind) {
        Catalog.STAKEHOLDER_ROLE -> AllIcons.General.User
        "decision" -> AllIcons.Nodes.Bookmark
        "need" -> AllIcons.Nodes.Target
        "input" -> AllIcons.Nodes.Parameter
        "quality-goal", "quality-scenario" -> AllIcons.Nodes.Favorite
        else -> AllIcons.Nodes.Tag
    }
}
