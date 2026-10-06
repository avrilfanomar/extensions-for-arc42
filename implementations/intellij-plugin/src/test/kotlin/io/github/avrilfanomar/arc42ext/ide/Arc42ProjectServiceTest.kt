package io.github.avrilfanomar.arc42ext.ide

import com.intellij.openapi.command.WriteCommandAction
import com.intellij.openapi.components.service
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.util.Disposer
import com.intellij.openapi.wm.ToolWindowEP
import com.intellij.testFramework.PlatformTestUtil
import com.intellij.testFramework.fixtures.BasePlatformTestCase
import com.intellij.ui.treeStructure.Tree
import com.intellij.util.ui.UIUtil
import com.intellij.util.ui.tree.TreeUtil
import io.github.avrilfanomar.arc42ext.ide.toolwindow.Arc42Node
import io.github.avrilfanomar.arc42ext.ide.toolwindow.Arc42Panel
import io.github.avrilfanomar.arc42ext.ide.toolwindow.Arc42ToolWindowFactory
import io.github.avrilfanomar.arc42ext.ide.toolwindow.ElementNode
import io.github.avrilfanomar.arc42ext.ide.toolwindow.GroupNode
import io.github.avrilfanomar.arc42ext.ide.toolwindow.LinkNode
import io.github.avrilfanomar.arc42ext.ide.toolwindow.buildTree
import javax.swing.tree.DefaultMutableTreeNode

class Arc42ProjectServiceTest : BasePlatformTestCase() {

    override fun setUp() {
        super.setUp()
        myFixture.addFileToProject("docs/arc42.adoc", "= Order Platform\n\ninclude::chapters/01.adoc[]\n\ninclude::chapters/09.adoc[]\n")
        myFixture.addFileToProject("docs/chapters/01.adoc", """
            == Introduction and Goals

            Extensions used: links v0.1.0

            === Stakeholders

            * [[sh-arch]]Software Architect
        """.trimIndent())
        myFixture.addFileToProject("docs/chapters/09.adoc", """
            == Architecture Decisions

            [[adr-001]]
            === ADR-001: Message broker

            [.links]
            owned-by:: <<sh-arch>>
        """.trimIndent())
        myFixture.addFileToProject("notes.adoc", "= Notes\n\nNo declaration.\n")
    }

    fun testFindsTheRootOfADocumentSplitIntoChapters() {
        val snapshot = project.service<Arc42ProjectService>().analyzeProject()
        val analysis = snapshot.analyses.single()

        assertTrue(snapshot.presentablePath(analysis.document.source).endsWith("docs/arc42.adoc"))
        assertEquals("Order Platform", analysis.document.title)
        assertEmpty(analysis.findings)
        val adr = analysis.graph.elements.getValue("adr-001")
        assertEquals("09.adoc", snapshot.file(adr.location.file)?.name)
        assertEquals(3, adr.location.line)
    }

    fun testReadsUnsavedChanges() {
        val chapter = myFixture.findFileInTempDir("docs/chapters/09.adoc")
        val document = FileDocumentManager.getInstance().getDocument(chapter)!!
        WriteCommandAction.runWriteCommandAction(project) {
            document.setText(document.text.replace("<<sh-arch>>", "<<sh-nobody>>"))
        }

        val analysis = project.service<Arc42ProjectService>().analyzeProject().analyses.single()

        assertEquals(listOf("L3"), analysis.findings.map { it.rule })
        assertTrue(FileDocumentManager.getInstance().isDocumentUnsaved(document))
    }

    fun testTreeShowsLinksInBothDirections() {
        val snapshot = project.service<Arc42ProjectService>().analyzeProject()
        val document = buildTree(snapshot, groupByKind = false).single()

        assertEquals(listOf("Introduction and Goals", "Architecture Decisions"), document.childNodes<GroupNode>().map { it.title })
        val architect = document.find<ElementNode> { it.element.id == "sh-arch" }
        val adr = document.find<ElementNode> { it.element.id == "adr-001" }
        assertEquals(listOf("← owned-by adr-001"), architect.childNodes<LinkNode>().map { it.render() })
        assertEquals(listOf("owned-by → sh-arch"), adr.childNodes<LinkNode>().map { it.render() })

        val byKind = buildTree(snapshot, groupByKind = true).single()
        assertEquals(listOf("stakeholder-role", "decision"), byKind.childNodes<GroupNode>().map { it.title })
    }

    fun testToolWindowShowsEveryNode() {
        val registered = ToolWindowEP.EP_NAME.extensionList.single { it.id == "arc42" }
        assertEquals(Arc42ToolWindowFactory::class.java.name, registered.factoryClass)

        val panel = Arc42Panel(project)
        Disposer.register(testRootDisposable, panel)
        val tree = UIUtil.findComponentOfType(panel, Tree::class.java)!!
        project.service<Arc42ProjectService>().refresh()
        // The light project outlives a test, so the panel may first show a snapshot of an earlier one.
        val expected = listOf("adr-001  ADR-001: Message broker  decision", "owned-by → sh-arch  Software Architect")
        val deadline = System.currentTimeMillis() + 10_000
        var rows = renderRows(tree)
        while (!rows.containsAll(expected) && System.currentTimeMillis() < deadline) {
            Thread.sleep(20)
            rows = renderRows(tree)
        }
        assertTrue(rows.toString(), rows.containsAll(expected))
    }

    private fun renderRows(tree: Tree): List<String> {
        PlatformTestUtil.dispatchAllInvocationEventsInIdeEventQueue()
        TreeUtil.expandAll(tree)
        PlatformTestUtil.dispatchAllInvocationEventsInIdeEventQueue()
        return (0 until tree.rowCount).map { row ->
            val node = tree.getPathForRow(row).lastPathComponent
            tree.cellRenderer.getTreeCellRendererComponent(tree, node, false, true, false, row, false).toString()
        }
    }

    private fun LinkNode.render() = if (outgoing) "${link.type} → $otherId" else "← ${link.type} $otherId"

    private inline fun <reified T : Arc42Node> DefaultMutableTreeNode.childNodes(): List<T> =
        children().toList().map { (it as DefaultMutableTreeNode).userObject }.filterIsInstance<T>()

    private inline fun <reified T : Arc42Node> DefaultMutableTreeNode.find(predicate: (T) -> Boolean): DefaultMutableTreeNode =
        depthFirstEnumeration().toList().map { it as DefaultMutableTreeNode }
            .single { (it.userObject as? T)?.let(predicate) == true }
}
