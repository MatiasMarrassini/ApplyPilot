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

// ---- Setup > Portales: a country checkbox toggles all its portals ----------
(function () {
  function sync(group) {
    const srcs = [...group.querySelectorAll(".src")];
    const on = srcs.filter((s) => s.checked).length;
    const toggle = group.querySelector(".group-toggle");
    toggle.checked = on === srcs.length;
    toggle.indeterminate = on > 0 && on < srcs.length;
    const count = group.querySelector("[data-count]");
    if (count) count.textContent = on;
  }
  const syncAll = () => document.querySelectorAll(".pgroup").forEach(sync);

  document.addEventListener("change", (e) => {
    const group = e.target.closest(".pgroup");
    if (!group) return;
    if (e.target.matches(".group-toggle")) {
      group.querySelectorAll(".src").forEach((s) => (s.checked = e.target.checked));
    }
    sync(group);
  });
  document.addEventListener("DOMContentLoaded", syncAll);
  document.addEventListener("htmx:afterSettle", syncAll);
})();
