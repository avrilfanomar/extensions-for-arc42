package io.github.avrilfanomar.arc42ext.asciidoc

import io.github.avrilfanomar.arc42ext.model.Arc42Document
import io.github.avrilfanomar.arc42ext.model.Baseline
import io.github.avrilfanomar.arc42ext.model.Element
import io.github.avrilfanomar.arc42ext.model.Event
import io.github.avrilfanomar.arc42ext.model.Finding
import io.github.avrilfanomar.arc42ext.model.Link
import io.github.avrilfanomar.arc42ext.model.Location
import io.github.avrilfanomar.arc42ext.model.Revisit
import io.github.avrilfanomar.arc42ext.model.Subscription
import io.github.avrilfanomar.arc42ext.model.VocabularyEntry

/**
 * Reads the AsciiDoc binding of links/EN/template.adoc and triggers/EN/template.adoc into the model.
 *
 * Like the binding, it is line-oriented and needs no AsciiDoc processor. It follows `include::` directives
 * and ignores comments, listing and literal blocks, and `ifdef::arc42help[]` blocks. Problems with the
 * notation itself are reported as rule B1. It mirrors the reference checker's `binding_asciidoc.py`;
 * of the triggers notation it reads what is shown (subscriptions, events, revisits) and checks only the
 * table columns.
 */
class AsciiDocReader(private val sources: Sources) {

    private class Line(val text: String, val location: Location)

    private class Anchor(val id: String, val title: String, val location: Location, val chapter: String?)

    private class Section(val level: Int, val anchor: String?, val title: String)

    private class Item(val term: String, val value: String, val location: Location)

    private class Cell(val text: String, val location: Location)

    private class Block(
        val role: String,
        val items: List<Item>, // a description list
        val rows: List<List<Cell>>?, // a table; null for a description list
        val location: Location,
        val sections: List<String>, // enclosing section anchors, innermost first
    )

    private val findings = mutableListOf<Finding>()
    private val files = mutableListOf<String>()
    private val anchors = mutableListOf<Anchor>()
    private val sections = mutableListOf<Section>()
    private val blocks = mutableListOf<Block>()
    private val prefixes = LinkedHashMap(CORE_PREFIXES)
    private val extensions = LinkedHashMap<String, String>()
    private var title = ""
    private var lines: List<Line> = emptyList()

    private val elements = mutableListOf<Element>()
    private val links = mutableListOf<Link>()
    private val vocabulary = mutableListOf<VocabularyEntry>()
    private val baselines = mutableListOf<Baseline>()
    private val subscriptions = mutableListOf<Subscription>()
    private val events = mutableListOf<Event>()
    private val revisits = mutableListOf<Revisit>()

    /** Reads the document at [path], following its includes. A reader reads one document. */
    fun read(path: String): Arc42Document {
        check(files.isEmpty()) { "an AsciiDocReader reads one document" }
        lines = strip(load(path, setOf(path)))
        if (files.isEmpty()) findings += Finding("B1", "cannot read '$path'", null)
        readStructure()
        build()
        // The `topic:` scheme is reserved by the triggers extension (L3): only reserve it when the document
        // declares triggers, so a links-only document may still use topic: as an external URI.
        val reserved = if ("triggers" in extensions) setOf(TOPIC_SCHEME) else emptySet()
        return Arc42Document(path, title, files.toList(), extensions.toMap(), elements.toList(), links.toList(),
            vocabulary.toList(), reserved, baselines.toList(), subscriptions.toList(), events.toList(),
            revisits.toList(), findings.toList())
    }

    // --- reading lines --------------------------------------------------------

    private fun load(path: String, seen: Set<String>): List<Line> {
        val text = sources.text(path) ?: return emptyList()
        files += path
        val lines = mutableListOf<Line>()
        text.lines().forEachIndexed { index, raw ->
            val location = Location(path, index + 1)
            val include = INCLUDE.find(raw)
            if (include == null) {
                lines += Line(raw.trimEnd(), location)
                return@forEachIndexed
            }
            val target = sources.resolve(path, include.groupValues[1].trim())
            if (target == null || target in seen) {
                note("cannot include '${include.groupValues[1]}'", location)
            } else {
                lines += load(target, seen + target)
            }
        }
        return lines
    }

    /** Drops comments, delimited listing/literal/passthrough/comment blocks and arc42help blocks. */
    private fun strip(lines: List<Line>): List<Line> {
        val kept = mutableListOf<Line>()
        var delimiter: String? = null
        var helpDepth = 0
        for (line in lines) {
            val stripped = line.text.trim()
            when {
                delimiter != null -> if (stripped == delimiter) delimiter = null
                helpDepth > 0 -> when {
                    stripped.startsWith("ifdef::arc42help[]") -> helpDepth++
                    stripped == "endif::arc42help[]" || stripped == "endif::[]" -> helpDepth--
                }
                stripped == "ifdef::arc42help[]" -> helpDepth = 1
                stripped.startsWith("ifdef::arc42help[") -> Unit // single-line conditional
                DELIMITER.matches(stripped) -> delimiter = stripped
                stripped.startsWith("//") -> Unit
                else -> kept += line
            }
        }
        return kept
    }

    // --- pass 1: structure ------------------------------------------------------

    private fun chapter(): String? = sections.firstOrNull { it.level == 1 }?.title

    private fun sectionAnchors(): List<String> = sections.reversed().mapNotNull { it.anchor }

    private fun scanInlineAnchors(text: String, location: Location) {
        for (match in INLINE_ANCHOR.findAll(text)) {
            val title = text.substring(match.range.last + 1).substringBefore('|').replace("**", "").trim()
            anchors += Anchor(match.groupValues[1], title, location, chapter())
        }
    }

    /** Reads the table that starts at line [start]. Returns its rows and the index of the line after it. */
    private fun readTable(start: Int): Pair<List<List<Cell>>, Int> {
        val cells = mutableListOf<Cell>()
        var columns: Int? = null
        var i = start + 1
        while (i < lines.size && !lines[i].text.trim().startsWith("|===")) {
            val line = lines[i]
            scanInlineAnchors(line.text, line.location)
            val stripped = line.text.trim()
            if (stripped.startsWith("|")) {
                val parts = stripped.split("|").drop(1)
                if (columns == null) columns = parts.size
                cells += parts.map { Cell(it.trim(), line.location) }
            } else if (stripped.isNotEmpty() && cells.isNotEmpty()) {
                val last = cells.removeAt(cells.lastIndex)
                cells += Cell("${last.text} $stripped".trim(), last.location)
            }
            i++
        }
        val rows = mutableListOf<List<Cell>>()
        if (columns != null && columns > 0) {
            for (row in cells.chunked(columns)) {
                rows += row + List(columns - row.size) { Cell("", row.last().location) }
            }
        }
        return rows to i + 1
    }

    private fun readStructure() {
        var pendingAnchor: Pair<String, Location>? = null
        var pendingRoles = mutableSetOf<String>()
        var i = 0
        while (i < lines.size) {
            val line = lines[i]
            val stripped = line.text.trim()
            if (stripped.isEmpty()) {
                i++
                continue
            }

            DECLARATION.find(stripped)?.let { declaration ->
                for (part in declaration.groupValues[1].split(",")) {
                    val name = part.trim().substringBefore(' ')
                    if (name.isNotEmpty()) {
                        extensions[name] = part.trim().substringAfter(' ', "").trim().removePrefix("v")
                    }
                }
            }

            val anchor = BLOCK_ANCHOR.find(stripped)
            if (anchor != null) {
                pendingAnchor = anchor.groupValues[1] to line.location
                i++
                continue
            }

            val attributes = ATTRIBUTES.find(stripped)
            if (attributes != null && !stripped.startsWith("[[")) {
                pendingRoles.addAll(roles(attributes.groupValues[1]))
                i++
                continue
            }

            val heading = HEADING.find(stripped)
            if (heading != null) {
                val level = heading.groupValues[1].length - 1
                val headingTitle = heading.groupValues[2].trim()
                if (level == 0 && title.isEmpty()) title = headingTitle
                while (sections.isNotEmpty() && sections.last().level >= level) sections.removeAt(sections.lastIndex)
                sections += Section(level, pendingAnchor?.first, headingTitle)
                pendingAnchor?.let { (id, location) -> anchors += Anchor(id, headingTitle, location, chapter()) }
                pendingAnchor = null
                pendingRoles = mutableSetOf()
                i++
                continue
            }

            pendingAnchor?.let { (id, location) -> anchors += Anchor(id, stripped, location, chapter()) }
            pendingAnchor = null

            val role = pendingRoles.sorted().firstOrNull { it in ROLES }
            if (stripped.startsWith("|===")) {
                val (rows, next) = readTable(i)
                if (role != null) blocks += Block(role, emptyList(), rows, line.location, sectionAnchors())
                pendingRoles = mutableSetOf()
                i = next
                continue
            }

            if (role != null && DLIST.find(stripped) != null) {
                val items = mutableListOf<Item>()
                while (i < lines.size) {
                    val item = DLIST.find(lines[i].text.trim()) ?: break
                    items += Item(item.groupValues[1].trim(), item.groupValues[2].trim(), lines[i].location)
                    i++
                }
                blocks += Block(role, items, null, line.location, sectionAnchors())
                pendingRoles = mutableSetOf()
                continue
            }

            scanInlineAnchors(line.text, line.location)
            pendingRoles = mutableSetOf()
            i++
        }
    }

    // --- pass 2: model ------------------------------------------------------------

    private fun kindOf(id: String): String? =
        prefixes.keys.sortedByDescending { it.length }.firstOrNull { id.startsWith(it) }?.let { prefixes[it] }

    private fun note(message: String, location: Location) {
        findings += Finding("B1", message, location)
    }

    private fun ownerSection(block: Block): String? {
        block.sections.firstOrNull { kindOf(it) != null }?.let { return it }
        note("[.${block.role}] block is not inside a section anchored to an element", block.location)
        return null
    }

    private fun checkHeader(block: Block): Boolean {
        val expected = TABLE_COLUMNS.getValue(block.role)
        val header = block.rows?.firstOrNull()?.map { it.text.lowercase() }.orEmpty()
        if (header == expected) return true
        note("[.${block.role}] table must have the columns ${expected.joinToString(" | ")}", block.location)
        return false
    }

    private fun build() {
        blocks.removeAll { block ->
            (block.role in TABLE_COLUMNS && block.rows == null).also {
                if (it) note("[.${block.role}] must be a table", block.location)
            }
        }

        blocks.filter { it.role == "vocabulary" && checkHeader(it) }.forEach(::readVocabulary)

        for (anchor in anchors) {
            kindOf(anchor.id)?.let { elements += Element(anchor.id, it, anchor.title, anchor.chapter, anchor.location) }
        }

        for (block in blocks) {
            if (block.role in TABLE_COLUMNS && block.role != "vocabulary" && !checkHeader(block)) continue
            when (block.role) {
                "links" -> readLinks(block)
                "triggers" -> readLocalSubscriptions(block)
                "triggers-subscriptions" -> readSubscriptionTable(block)
                "triggers-events" -> readEvents(block)
                "triggers-revisits" -> readRevisits(block)
            }
        }
    }

    private fun readVocabulary(block: Block) {
        for (row in block.rows.orEmpty().drop(1)) {
            val type = row[0].text.trim().lowercase()
            val name = row[1].text
            val prefix = row[2].text
            val location = row[1].location
            when (type) {
                "kind" -> {
                    vocabulary += VocabularyEntry("kind", name, null, null, location)
                    when {
                        prefix.isEmpty() -> note("custom kind '$name' has no prefix", location)
                        CORE_PREFIXES.keys.any { prefix.startsWith(it) || it.startsWith(prefix) } ->
                            note("prefix '$prefix' of '$name' overlaps a core prefix", location)
                        else -> prefixes[prefix] = name
                    }
                }
                "link" -> vocabulary += VocabularyEntry("link", name, kinds(row[3].text), kinds(row[4].text), location)
                else -> note("vocabulary type must be 'kind' or 'link', not '$type'", location)
            }
        }
    }

    private fun kinds(text: String): Set<String>? {
        val values = text.split(",").map { it.trim() }.filter { it.isNotEmpty() }.toSet()
        return if (values.isEmpty() || "any" in values) null else values
    }

    private fun readLinks(block: Block) {
        val rows = block.rows
        if (rows == null) {
            val source = ownerSection(block) ?: return
            for (item in block.items) {
                for (target in ids(item.value)) links += Link(source, item.term, target, item.location)
            }
            return
        }
        if (rows.isEmpty()) return
        val header = rows[0].map { it.text }
        for (row in rows.drop(1)) {
            val sources = ids(row[0].text)
            if (sources.size != 1) {
                note("the first cell of a [.links] row must hold exactly one source", row[0].location)
                continue
            }
            for (column in 1 until header.size) {
                for (target in ids(row[column].text)) links += Link(sources[0], header[column], target, row[column].location)
            }
        }
    }

    private fun readLocalSubscriptions(block: Block) {
        val subscriber = ownerSection(block) ?: return
        for (item in block.items) {
            when {
                item.term == "baseline" -> baselines += Baseline(subscriber, item.value, item.location)
                item.term.startsWith("on ") ->
                    subscriptions += Subscription(subscriber, item.term.substring(3).trim(), normalize(item.value), item.location)
                else -> note("unknown [.triggers] entry '${item.term}'", item.location)
            }
        }
    }

    private fun readSubscriptionTable(block: Block) {
        val rows = block.rows.orEmpty()
        if (rows.isEmpty()) return
        val header = rows[0].map { it.text }
        if (header.take(2).map { it.lowercase() } != listOf("subscriber", "baseline")) {
            note("[.triggers-subscriptions] must start with the columns Subscriber | Baseline", block.location)
            return
        }
        for (row in rows.drop(1)) {
            val subscriber = ids(row[0].text).singleOrNull()
            if (subscriber == null) {
                note("the Subscriber cell must hold exactly one element", row[0].location)
                continue
            }
            if (row[1].text.isNotEmpty()) baselines += Baseline(subscriber, row[1].text, row[1].location)
            for (column in 2 until header.size) {
                val cell = row[column]
                if (cell.text.isNotEmpty()) {
                    subscriptions += Subscription(subscriber, header[column], normalize(cell.text), cell.location)
                }
            }
        }
    }

    private fun readEvents(block: Block) {
        for (row in block.rows.orEmpty().drop(1)) {
            events += Event(row[0].text, row[1].text, row[2].text, normalize(row[3].text), row[0].location)
        }
    }

    private fun readRevisits(block: Block) {
        for (row in block.rows.orEmpty().drop(1)) {
            val cells = row.map { it.text }
            revisits += Revisit(
                id = cells[0],
                event = normalize(cells[1]),
                subscriber = normalize(cells[2]),
                scope = normalize(cells[3]),
                responsible = normalize(cells[4]),
                opened = cells[5],
                due = cells[6],
                outcome = cells[7].trim().lowercase(),
                closed = cells[8],
                rationale = normalize(cells[9]),
                location = row[0].location,
            )
        }
    }

    companion object {
        val CORE_PREFIXES: Map<String, String> = linkedMapOf(
            "sh-" to "stakeholder-role",
            "rq-" to "requirement",
            "qg-" to "quality-goal",
            "qs-" to "quality-scenario",
            "con-" to "constraint",
            "need-" to "need",
            "adr-" to "decision",
            "in-" to "input",
            "risk-" to "risk",
            "td-" to "debt",
        )

        const val TOPIC_SCHEME = "topic"

        private val INCLUDE = Regex("""^include::([^\[]+)\[.*]\s*$""")
        private val HEADING = Regex("""^(={1,6})\s+(\S.*)$""")
        private val BLOCK_ANCHOR = Regex("""^\[\[([A-Za-z0-9_:.-]+)(?:,[^\]]*)?]]\s*$""")
        private val INLINE_ANCHOR = Regex("""\[\[([A-Za-z0-9_:.-]+)(?:,[^\]]*)?]]""")
        private val ATTRIBUTES = Regex("""^\[([^\[].*)]$""")
        private val DELIMITER = Regex("""^(-{4,}|\.{4,}|\+{4,}|/{4,})$""")
        private val DLIST = Regex("""^(\S.*?)::(?:\s+(.*))?$""")
        private val XREF = Regex("""<<\s*([^,>\s]+)\s*(?:,[^>]*)?>>""")
        private val DECLARATION = Regex("""^Extensions used:\s*(.*)$""")
        private val ROLE_SHORTHAND = Regex("""(?:^|[,#%\s])\.([A-Za-z0-9_-]+)""")
        private val ROLE_ATTRIBUTE = Regex("""role="?([^",\]]+)"?""")

        private val TABLE_COLUMNS: Map<String, List<String>> = mapOf(
            "vocabulary" to listOf("type", "name", "prefix", "from", "to", "description"),
            "triggers-events" to listOf("id", "date", "type", "subject", "payload", "published by"),
            "triggers-revisits" to listOf("id", "event", "subscriber", "scope", "responsible", "opened", "due",
                "outcome", "closed", "rationale"),
            "triggers-topics" to listOf("topic", "elements"),
            "triggers-event-types" to listOf("name", "mode", "subject kind", "routes", "payload", "default response"),
        )
        private val ROLES: Set<String> = setOf("links", "triggers", "triggers-subscriptions") + TABLE_COLUMNS.keys

        private fun roles(attributes: String): Set<String> {
            val roles = ROLE_SHORTHAND.findAll(attributes).map { it.groupValues[1] }.toMutableSet()
            ROLE_ATTRIBUTE.find(attributes)?.let { roles += it.groupValues[1].split(Regex("\\s+")).filter(String::isNotEmpty) }
            return roles
        }

        /** Replaces xrefs by their IDs. */
        private fun normalize(text: String): String = XREF.replace(text) { it.groupValues[1] }.trim()

        private fun ids(text: String): List<String> = normalize(text).split(",").map { it.trim() }.filter { it.isNotEmpty() }
    }
}
