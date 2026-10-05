// arc42ext serve: live reload, copy buttons, auto-submitting controls, catalogue filter.
// Every page works without this script; it only makes it faster to use.
(() => {
  const version = document.body.dataset.version;
  const live = document.getElementById("live");
  live.hidden = false;
  let timer = null;
  let lastUpdate = Date.now();

  // Reload when the document (or a file it includes) changes.
  async function poll() {
    try {
      const response = await fetch("/api/version", { cache: "no-store" });
      const current = (await response.text()).trim();
      live.dataset.state = "live";
      const elapsed = Math.floor((Date.now() - lastUpdate) / 1000);
      live.textContent = `Live • Updated ${elapsed}s ago`;
      if (response.ok && current !== version) {
        location.reload();
        return;
      }
    } catch {
      live.dataset.state = "offline";
      live.textContent = "Server stopped";
    }
    schedule();
  }

  function schedule() {
    clearTimeout(timer);
    if (!document.hidden) timer = setTimeout(poll, 1500);
  }

  document.addEventListener("visibilitychange", () => (document.hidden ? clearTimeout(timer) : poll()));
  schedule();

  // Copy a suggested row.
  document.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-copy]");
    if (!button) return;
    const text = document.getElementById(button.dataset.copy).textContent;
    try {
      await navigator.clipboard.writeText(text);
      button.textContent = "Copied";
    } catch {
      const range = document.createRange();
      range.selectNodeContents(document.getElementById(button.dataset.copy));
      getSelection().removeAllRanges();
      getSelection().addRange(range);
      button.textContent = "Press Ctrl+C";
    }
    setTimeout(() => (button.textContent = "Copy"), 1500);
  });

  // Date and role controls apply on change; their submit buttons are for when scripts are off.
  for (const form of document.querySelectorAll("form[data-autosubmit]")) {
    form.querySelector("button[type=submit]")?.setAttribute("hidden", "");
    for (const control of form.querySelectorAll("input, select")) {
      control.addEventListener("change", () => form.requestSubmit());
    }
  }

  // Catalogue filter and search.
  const filter = document.getElementById("filter");
  if (filter) {
    filter.hidden = false;

    // Debounced search
    let searchTimer = null;
    filter.addEventListener("input", () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        const query = filter.value.trim().toLowerCase();
        let visibleCount = 0;
        for (const row of document.querySelectorAll("[data-filter-row]")) {
          const visible = query === "" || row.textContent.toLowerCase().includes(query);
          row.hidden = !visible;
          if (visible) visibleCount++;
        }
        for (const group of document.querySelectorAll("[data-filter-group]")) {
          group.hidden = !group.querySelector("[data-filter-row]:not([hidden])");
        }
        // Update result count
        const resultCount = document.getElementById("result-count");
        if (resultCount) {
          const total = document.querySelectorAll("[data-filter-row]").length;
          resultCount.textContent = query ? `Showing ${visibleCount} of ${total}` : "";
        }
      }, 300);
    });
  }

  // Table sorting
  for (const table of document.querySelectorAll("table[data-sortable]")) {
    const headers = table.querySelectorAll("th[data-sort]");
    headers.forEach((header, index) => {
      header.style.cursor = "pointer";
      header.addEventListener("click", () => {
        const tbody = table.querySelector("tbody");
        const rows = Array.from(tbody.querySelectorAll("tr"));
        const currentOrder = header.dataset.order || "asc";
        const newOrder = currentOrder === "asc" ? "desc" : "asc";
        const column = header.dataset.sort;

        // Remove sort indicators from other headers
        headers.forEach(h => {
          h.dataset.order = "";
          h.textContent = h.textContent.replace(" ↑", "").replace(" ↓", "");
        });

        // Sort rows
        rows.sort((a, b) => {
          const aCell = a.children[index];
          const bCell = b.children[index];
          let aVal = aCell.textContent.trim();
          let bVal = bCell.textContent.trim();

          // Numeric columns
          if (column === "num") {
            aVal = parseInt(aVal) || 0;
            bVal = parseInt(bVal) || 0;
          }

          if (aVal < bVal) return newOrder === "asc" ? -1 : 1;
          if (aVal > bVal) return newOrder === "asc" ? 1 : -1;
          return 0;
        });

        // Update DOM
        rows.forEach(row => tbody.appendChild(row));

        // Update header
        header.dataset.order = newOrder;
        header.textContent += newOrder === "asc" ? " ↑" : " ↓";
      });
    });
  }

  // Collapsible sections with state persistence.
  const STORAGE_KEY = "arc42ext-collapsed-sections";
  const collapsed = new Set(JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]"));

  for (const details of document.querySelectorAll("details.collapsible[data-section-id]")) {
    const id = details.dataset.sectionId;
    if (collapsed.has(id)) {
      details.removeAttribute("open");
    }
    details.addEventListener("toggle", () => {
      if (details.open) {
        collapsed.delete(id);
      } else {
        collapsed.add(id);
      }
      localStorage.setItem(STORAGE_KEY, JSON.stringify([...collapsed]));
    });
  }

  // Handle fragment identifiers to auto-expand sections.
  if (location.hash) {
    const target = document.querySelector(location.hash);
    if (target) {
      const details = target.closest("details.collapsible");
      if (details) details.open = true;
    }
  }

  // Share button - copy current URL to clipboard.
  for (const btn of document.querySelectorAll(".share-btn")) {
    btn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(location.href);
        btn.classList.add("copied");
        const original = btn.textContent;
        btn.textContent = "Link copied!";
        setTimeout(() => {
          btn.classList.remove("copied");
          btn.textContent = original;
        }, 2000);
      } catch {
        // Fallback for browsers without clipboard API
        alert(`Copy this URL: ${location.href}`);
      }
    });
  }

  // Keyboard shortcuts
  document.addEventListener("keydown", (e) => {
    // Ignore if user is typing in an input
    if (e.target.matches("input, select, textarea")) {
      return;
    }

    // / - Focus search/filter
    if (e.key === "/" && filter) {
      e.preventDefault();
      filter.focus();
      filter.select();
    }

    // d - Dashboard
    if (e.key === "d") {
      e.preventDefault();
      location.href = "/";
    }

    // e - Elements catalogue
    if (e.key === "e") {
      e.preventDefault();
      location.href = "/elements";
    }

    // ? - Show keyboard shortcuts help
    if (e.key === "?") {
      e.preventDefault();
      showKeyboardHelp();
    }

    // Escape - Close modals/overlays
    if (e.key === "Escape") {
      const help = document.getElementById("keyboard-help");
      if (help) help.remove();
    }
  });

  // Show keyboard shortcuts help overlay
  function showKeyboardHelp() {
    // Remove existing help if present
    const existing = document.getElementById("keyboard-help");
    if (existing) {
      existing.remove();
      return;
    }

    const help = document.createElement("div");
    help.id = "keyboard-help";
    help.innerHTML = `
      <div class="help-overlay">
        <div class="help-content">
          <h2>Keyboard Shortcuts</h2>
          <dl class="help-shortcuts">
            <dt><kbd>/</kbd></dt><dd>Focus search / filter input</dd>
            <dt><kbd>d</kbd></dt><dd>Go to Dashboard</dd>
            <dt><kbd>e</kbd></dt><dd>Go to Elements catalogue</dd>
            <dt><kbd>?</kbd></dt><dd>Show this help</dd>
            <dt><kbd>Esc</kbd></dt><dd>Close overlays</dd>
          </dl>
          <p class="help-hint">Press <kbd>Esc</kbd> or <kbd>?</kbd> to close</p>
        </div>
      </div>
    `;
    document.body.appendChild(help);

    // Close on click outside
    help.addEventListener("click", (e) => {
      if (e.target === help || e.target.classList.contains("help-overlay")) {
        help.remove();
      }
    });
  }

  // Track recently viewed elements in sessionStorage
  const currentPath = location.pathname;
  if (currentPath.startsWith("/elements/") && currentPath !== "/elements") {
    const elementId = decodeURIComponent(currentPath.split("/elements/")[1]);
    const recent = JSON.parse(sessionStorage.getItem("recent-elements") || "[]");
    const updated = [elementId, ...recent.filter(id => id !== elementId)].slice(0, 5);
    sessionStorage.setItem("recent-elements", JSON.stringify(updated));
  }
})();
