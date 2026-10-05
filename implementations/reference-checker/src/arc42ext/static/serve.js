// arc42ext serve: live reload, copy buttons, auto-submitting controls, catalogue filter.
// Every page works without this script; it only makes it faster to use.
(() => {
  const version = document.body.dataset.version;
  const live = document.getElementById("live");
  live.hidden = false;
  let timer = null;

  // Reload when the document (or a file it includes) changes.
  async function poll() {
    try {
      const response = await fetch("/api/version", { cache: "no-store" });
      const current = (await response.text()).trim();
      live.dataset.state = "live";
      live.textContent = "Live";
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

  // Catalogue filter.
  const filter = document.getElementById("filter");
  if (filter) {
    filter.hidden = false;
    filter.addEventListener("input", () => {
      const query = filter.value.trim().toLowerCase();
      for (const row of document.querySelectorAll("[data-filter-row]")) {
        row.hidden = query !== "" && !row.textContent.toLowerCase().includes(query);
      }
      for (const group of document.querySelectorAll("[data-filter-group]")) {
        group.hidden = !group.querySelector("[data-filter-row]:not([hidden])");
      }
    });
  }
})();
