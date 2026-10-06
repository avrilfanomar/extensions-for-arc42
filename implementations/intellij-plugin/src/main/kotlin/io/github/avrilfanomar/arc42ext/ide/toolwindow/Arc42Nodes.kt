package io.github.avrilfanomar.arc42ext.ide.toolwindow

import com.intellij.ide.util.treeView.PathElementIdProvider
import io.github.avrilfanomar.arc42ext.ide.Arc42Snapshot
import io.github.avrilfanomar.arc42ext.model.Analysis
import io.github.avrilfanomar.arc42ext.model.Arc42Document
import io.github.avrilfanomar.arc42ext.model.Baseline
import io.github.avrilfanomar.arc42ext.model.Catalog
import io.github.avrilfanomar.arc42ext.model.Element
import io.github.avrilfanomar.arc42ext.model.Event
import io.github.avrilfanomar.arc42ext.model.Finding
import io.github.avrilfanomar.arc42ext.model.Link
import io.github.avrilfanomar.arc42ext.model.Location
import io.github.avrilfanomar.arc42ext.model.Revisit
import io.github.avrilfanomar.arc42ext.model.Subscription
import javax.swing.tree.DefaultMutableTreeNode

/**
 * What a node of the arc42 tree stands for. [toString] is what speed search matches; the path element ID
 * keeps nodes expanded and selected across refreshes.
 */
sealed class Arc42Node(private val id: String) : PathElementIdProvider {
    /** Where double-click and Enter lead. */
    open val location: Location? get() = null

    override fun getPathElementId(): String = id
}

class DocumentNode(val analysis: Analysis, val name: String) : Arc42Node("document:${analysis.document.source}") {
    override val location get() = Location(analysis.document.source, 1)
    override fun toString() = name
}

class ProblemsNode(val count: Int) : Arc42Node("problems") {
    override fun toString() = "problems"
}

class FindingNode(val finding: Finding) : Arc42Node("finding:$finding") {
    override val location get() = finding.location
    override fun toString() = "${finding.rule} ${finding.message}"
}

/** An arc42 section, or a kind of element. An empty [title] gathers the elements outside every section. */
class GroupNode(val title: String, val count: Int) : Arc42Node("group:$title") {
    override fun toString() = title
}

class ElementNode(val element: Element) : Arc42Node("element:${element.id}") {
    override val location get() = element.location
    override fun toString() = "${element.id} ${element.title}"
}

/**
 * A link written at the element ([outgoing]), or a link into it. [other] is the element at the other end, if
 * there is one; a [url] is an external target. Navigation goes to the other element, else to the link itself.
 */
class LinkNode(val link: Link, val outgoing: Boolean, val other: Element?, val url: String?) :
    Arc42Node("link:${link.type}:" + if (outgoing) ">${link.target}" else "<${link.source}") {
    val otherId: String get() = if (outgoing) link.target else link.source
    override val location get() = other?.location ?: link.location
    override fun toString() = "${link.type} $otherId"
}

class TriggersNode(val baseline: Baseline?) : Arc42Node("triggers") {
    override val location get() = baseline?.location
    override fun toString() = "triggers"
}

class SubscriptionNode(val subscription: Subscription) : Arc42Node("subscription:${subscription.eventType}") {
    override val location get() = subscription.location
    override fun toString() = "on ${subscription.eventType}"
}

class RevisitNode(val revisit: Revisit, val event: Event?) : Arc42Node("revisit:${revisit.id}") {
    override val location get() = revisit.location
    override fun toString() = revisit.id
}

/** The arc42 tree of a snapshot: per document its problems, then its elements by arc42 section or by kind. */
internal fun buildTree(snapshot: Arc42Snapshot, groupByKind: Boolean): List<DefaultMutableTreeNode> =
    snapshot.analyses.map { analysis ->
        node(DocumentNode(analysis, snapshot.presentablePath(analysis.document.source))) {
            if (analysis.findings.isNotEmpty()) {
                add(node(ProblemsNode(analysis.findings.size)) { analysis.findings.forEach { add(node(FindingNode(it))) } })
            }
            val elements = analysis.graph.elementList
            val groups = if (groupByKind) {
                elements.groupBy { it.kind }.toSortedMap(compareBy({ kindOrder(it) }, { it }))
            } else {
                elements.groupBy { it.section.orEmpty() }
            }
            for ((title, members) in groups) {
                add(node(GroupNode(title, members.size)) { members.forEach { add(elementNode(analysis, it)) } })
            }
        }
    }

private fun kindOrder(kind: String): Int = Catalog.CORE_KINDS.indexOf(kind).takeIf { it >= 0 } ?: Catalog.CORE_KINDS.size

private fun elementNode(analysis: Analysis, element: Element) = node(ElementNode(element)) {
    val graph = analysis.graph
    for (link in graph.linksFrom(element.id)) {
        add(node(LinkNode(link, true, graph.elements[link.target], link.target.takeIf { graph.isExternal(it) })))
    }
    for (link in graph.linksTo(element.id)) {
        add(node(LinkNode(link, false, graph.elements[link.source], null)))
    }
    triggersNode(analysis.document, element.id)?.let(::add)
}

private fun triggersNode(document: Arc42Document, id: String): DefaultMutableTreeNode? {
    val baseline = document.baselines.firstOrNull { it.subscriber == id }
    val subscriptions = document.subscriptions.filter { it.subscriber == id }
    val revisits = document.revisits.filter { it.subscriber == id }
    if (baseline == null && subscriptions.isEmpty() && revisits.isEmpty()) return null
    val events = document.events.associateBy { it.id }
    return node(TriggersNode(baseline)) {
        subscriptions.forEach { add(node(SubscriptionNode(it))) }
        revisits.forEach { add(node(RevisitNode(it, events[it.event]))) }
    }
}

private fun node(value: Arc42Node, children: DefaultMutableTreeNode.() -> Unit = {}) =
    DefaultMutableTreeNode(value).apply(children)
