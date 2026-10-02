// Small client-side helpers. Everything else is server-rendered HTML + HTMX.

// ---- Bulk selection on the jobs list ---------------------------------------
// Rows carry <input class="pick" name="ids">; the bulk bar's buttons post the
// checked ones (or all=1 for "every job matching the filters") to /jobs/bulk.
(function () {
  const $ = (sel) => document.querySelector(sel);

  function refresh() {
    const bar = $("#bulk-bar");
    if (!bar) return;
    const picks = [...document.querySelectorAll("#job-list .pick")];
    const checked = picks.filter((p) => p.checked).length;
    const all = $("#bulk-all") && $("#bulk-all").value === "1";
    const total = Number(bar.dataset.total || 0);
    const n = all ? total : checked;
    bar.hidden = n === 0;
    $("#bulk-count").textContent = `${n} seleccionada${n === 1 ? "" : "s"}`;
    const selectAll = $("#bulk-select-all");
    if (selectAll) selectAll.hidden = all || checked < picks.length;
    const pagePick = $(".pick-page");
    if (pagePick) {
      pagePick.checked = picks.length > 0 && checked === picks.length;
      pagePick.indeterminate = checked > 0 && checked < picks.length;
    }
  }

  function clearAll() {
    document.querySelectorAll("#job-list .pick").forEach((p) => (p.checked = false));
    if ($("#bulk-all")) $("#bulk-all").value = "0";
    refresh();
  }

  document.addEventListener("change", (e) => {
    if (e.target.matches(".pick-page")) {
      document.querySelectorAll("#job-list .pick").forEach((p) => (p.checked = e.target.checked));
      if ($("#bulk-all")) $("#bulk-all").value = "0";
    } else if (e.target.matches(".pick")) {
      if (!e.target.checked && $("#bulk-all")) $("#bulk-all").value = "0";
    } else {
      return;
    }
    refresh();
  });

  document.addEventListener("click", (e) => {
    if (e.target.closest("#bulk-select-all")) {
      document.querySelectorAll("#job-list .pick").forEach((p) => (p.checked = true));
      $("#bulk-all").value = "1";
      refresh();
    } else if (e.target.closest("#bulk-clear")) {
      clearAll();
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && $("#bulk-bar") && !$("#bulk-bar").hidden) clearAll();
  });

  // New results (filters, paging, bulk actions) start with nothing selected.
  document.addEventListener("htmx:afterSettle", refresh);
})();

// ---- Pipeline log: stay pinned to the bottom unless the user scrolled up ----
(function () {
  let pinned = true;
  document.addEventListener("htmx:beforeSwap", (e) => {
    const log = document.getElementById("log");
    if (log && e.detail.target.id === "run-panel") {
      pinned = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
    }
  });
  const stick = () => {
    const log = document.getElementById("log");
    if (log && pinned) log.scrollTop = log.scrollHeight;
  };
  document.addEventListener("htmx:afterSettle", stick);
  window.addEventListener("load", stick);
})();

// ---- Setup > Portales: country checkbox toggles all its portals; groups collapse ----
(function () {
  const STORE = "applypilot.portals.open";
  const openGroups = () => {
    try { return new Set(JSON.parse(localStorage.getItem(STORE) || "[]")); } catch { return new Set(); }
  };
  const saveOpen = (set) => {
    try { localStorage.setItem(STORE, JSON.stringify([...set])); } catch { /* storage unavailable: just don't remember */ }
  };

  function sync(group) {
    const srcs = [...group.querySelectorAll(".src")];
    const active = srcs.filter((s) => s.checked);
    const toggle = group.querySelector(".group-toggle");
    toggle.checked = active.length === srcs.length;
    toggle.indeterminate = active.length > 0 && active.length < srcs.length;
    group.querySelector("[data-count]").textContent = active.length;
    // Collapsed headers name the first active portals so the overview needs no scrolling.
    const names = active.map((s) => s.dataset.name);
    const shown = names.slice(0, 3).join(", ");
    group.querySelector("[data-active-names]").textContent =
      names.length === 0 ? "Ninguno activo" : names.length > 3 ? `${shown} y ${names.length - 3} más` : shown;
  }

  function setOpen(group, open, remember = true) {
    group.classList.toggle("is-collapsed", !open);
    group.querySelector(".pgroup-body").hidden = !open;
    group.querySelector(".pgroup-expand").setAttribute("aria-expanded", String(open));
    if (remember) {
      const set = openGroups();
      open ? set.add(group.dataset.group) : set.delete(group.dataset.group);
      saveOpen(set);
    }
  }

  function init() {
    const open = openGroups();
    document.querySelectorAll(".pgroup").forEach((g) => {
      sync(g);
      setOpen(g, open.has(g.dataset.group), false);
    });
  }

  document.addEventListener("change", (e) => {
    const group = e.target.closest(".pgroup");
    if (!group) return;
    if (e.target.matches(".group-toggle")) {
      group.querySelectorAll(".src").forEach((s) => (s.checked = e.target.checked));
    }
    sync(group);
  });
  document.addEventListener("click", (e) => {
    const expand = e.target.closest(".pgroup-expand");
    if (expand) {
      const group = expand.closest(".pgroup");
      setOpen(group, group.classList.contains("is-collapsed"));
    } else if (e.target.closest("[data-expand-all], [data-collapse-all]")) {
      const open = !!e.target.closest("[data-expand-all]");
      document.querySelectorAll(".pgroup").forEach((g) => setOpen(g, open));
    }
  });
  document.addEventListener("DOMContentLoaded", init);
  document.addEventListener("htmx:afterSettle", init);
})();
