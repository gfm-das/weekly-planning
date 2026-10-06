/* Client-side search, dark mode, mobile sidebar, and wiki edit UI for the Weekly Planning wiki. */
(function () {
  "use strict";

  var THEME_KEY = "gfm-wiki-theme";
  var API = "/api/wiki";

  function queryTheme() {
    try {
      var m = /[?&]theme=(dark|light)\b/i.exec(location.search);
      if (m) return m[1].toLowerCase();
    } catch (e) {}
    return null;
  }

  function preferredTheme() {
    var q = queryTheme();
    if (q) return q;
    try {
      var saved = localStorage.getItem(THEME_KEY);
      if (saved === "light" || saved === "dark") return saved;
    } catch (e) {}
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    var btn = document.getElementById("themeToggle");
    if (btn) btn.textContent = theme === "dark" ? "Light mode" : "Dark mode";
  }

  applyTheme(preferredTheme());

  function qs(name) {
    try {
      return new URLSearchParams(location.search).get(name);
    } catch (e) {
      return null;
    }
  }

  function isDemoEdit() {
    return qs("demoEdit") === "1";
  }

  function portalToken() {
    try {
      return localStorage.getItem("mission_access_token") || "";
    } catch (e) {
      return "";
    }
  }

  function show(el) {
    if (el) el.classList.remove("is-hidden");
  }
  function hide(el) {
    if (el) el.classList.add("is-hidden");
  }

  function revealEditorTabs(canEdit) {
    document.querySelectorAll("[data-page-tabs]").forEach(function (nav) {
      nav.querySelectorAll(".tab-edit, .tab-history, .tab-create").forEach(function (tab) {
        if (canEdit) show(tab);
        else hide(tab);
      });
    });
  }

  async function api(path, options) {
    options = options || {};
    var headers = Object.assign({ Accept: "application/json" }, options.headers || {});
    var token = portalToken();
    if (token) headers.Authorization = "Bearer " + token;
    if (options.body && typeof options.body === "object" && !(options.body instanceof FormData)) {
      headers["Content-Type"] = "application/json";
      options = Object.assign({}, options, { body: JSON.stringify(options.body) });
    }
    var res = await fetch(API + path, Object.assign({}, options, { headers: headers }));
    var data = null;
    try { data = await res.json(); } catch (e) { data = null; }
    if (!res.ok) {
      var err = new Error((data && data.error) || ("Request failed (" + res.status + ")"));
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  async function checkCanEdit() {
    if (isDemoEdit()) return true;
    if (!portalToken()) return false;
    try {
      var me = await api("/me");
      return !!(me && me.can_edit);
    } catch (e) {
      return false;
    }
  }

  /* —— Demo stubs for screenshots / local preview (?demoEdit=1) —— */
  var DEMO_MARKDOWN = [
    "---",
    "title: Overview",
    "slug: overview",
    "lead: is the portal home page with customizable cards.",
    "summary: Portal Overview page for missionaries and managers.",
    "status: full",
    "navboxes: [using]",
    "infobox_title: Overview",
    'icon: "🏠"',
    'infobox_rows: ["Who|Everyone", "Managers|Glimpse too"]',
    "tags: [overview]",
    "---",
    "",
    "## Usage",
    "",
    "1. After signing in, open **Overview** from the menu.",
    "2. Use the week selector when you want another reporting week.",
    "3. Drag cards by the grip handle to rearrange your layout.",
    "",
    "## How it works",
    "",
    "- Overview cards live in one container.",
    "- The page talks to portal-api.",
    "",
    "## See also",
    "",
    "- [Glimpse](glimpse.html)",
    "- [Weekly Planning](weekly-planning.html)"
  ].join("\n");

  var DEMO_PREVIEW = [
    "<h2 id=\"usage\">Usage</h2>",
    "<ol><li>After signing in, open <strong>Overview</strong> from the menu.</li>",
    "<li>Use the week selector when you want another reporting week.</li>",
    "<li>Drag cards by the grip handle to rearrange your layout.</li></ol>",
    "<h2 id=\"how-it-works\">How it works</h2>",
    "<ul><li>Overview cards live in one container.</li>",
    "<li>The page talks to portal-api.</li></ul>",
    "<h2 id=\"see-also\">See also</h2>",
    "<ul><li><a href=\"glimpse.html\">Glimpse</a></li>",
    "<li><a href=\"weekly-planning.html\">Weekly Planning</a></li></ul>"
  ].join("\n");

  function demoPreviewHtml(md) {
    // Tiny fallback so live typing still updates something in demo mode without the API.
    var body = String(md || "");
    var cut = body.indexOf("\n---");
    if (body.indexOf("---") === 0 && cut > 0) {
      var end = body.indexOf("\n---", 3);
      if (end !== -1) body = body.slice(end + 4).replace(/^\n+/, "");
    }
    return body
      .replace(/^## (.+)$/gm, "<h2>$1</h2>")
      .replace(/^\d+\. (.+)$/gm, "<li>$1</li>")
      .replace(/^- (.+)$/gm, "<li>$1</li>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>')
      .replace(/(<li>.*<\/li>\n?)+/g, function (m) {
        return m.indexOf("1.") >= 0 || /^\d/.test(md) ? "<ol>" + m + "</ol>" : "<ul>" + m + "</ul>";
      })
      || DEMO_PREVIEW;
  }

  /* —— Editor page —— */
  function initEditor() {
    var form = document.getElementById("wikiEditor");
    if (!form) return;

    var isNew = qs("new") === "1";
    var page = qs("page") || (isNew ? "" : "overview");
    var heading = document.getElementById("editHeading");
    var lead = document.getElementById("editLead");
    var gate = document.getElementById("editAuthGate");
    var mdBox = document.getElementById("editMarkdown");
    var preview = document.getElementById("editPreview");
    var status = document.getElementById("editStatus");
    var slugField = document.getElementById("newSlugField");
    var slugInput = document.getElementById("editSlug");
    var summaryInput = document.getElementById("editSummary");
    var cancelBtn = document.getElementById("editCancel");
    var previewTimer = null;
    var demo = isDemoEdit();

    function setStatus(msg, kind) {
      if (!status) return;
      status.textContent = msg || "";
      status.classList.remove("is-error", "is-ok");
      if (kind) status.classList.add(kind);
    }

    function syncTabs() {
      var tabs = document.getElementById("editPageTabs");
      if (tabs) tabs.setAttribute("data-slug", page || "");
      var read = document.getElementById("editTabRead");
      var hist = document.getElementById("editTabHistory");
      if (page) {
        var href = page === "index" ? "index.html" : page + ".html";
        if (read) read.href = href + (demo ? "?demoEdit=1" : "");
        if (hist) {
          hist.href = "history.html?page=" + encodeURIComponent(page) + (demo ? "&demoEdit=1" : "");
          show(hist);
        }
      }
    }

    async function refreshPreview() {
      var md = mdBox.value;
      if (demo) {
        preview.innerHTML = demoPreviewHtml(md);
        return;
      }
      try {
        var data = await api("/preview", { method: "POST", body: { markdown: md } });
        preview.innerHTML = data.html || "<p class=\"muted\">Empty preview.</p>";
      } catch (e) {
        preview.innerHTML = "<p class=\"muted\">Preview unavailable: " + escapeHtml(e.message) + "</p>";
      }
    }

    function schedulePreview() {
      clearTimeout(previewTimer);
      previewTimer = setTimeout(refreshPreview, 350);
    }

    function escapeHtml(s) {
      return String(s).replace(/[&<>"']/g, function (c) {
        return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
      });
    }

    cancelBtn.addEventListener("click", function () {
      if (page) {
        location.href = (page === "index" ? "index.html" : page + ".html") + (demo ? "?demoEdit=1" : "");
      } else {
        location.href = "index.html" + (demo ? "?demoEdit=1" : "");
      }
    });

    mdBox.addEventListener("input", schedulePreview);

    form.addEventListener("submit", async function (e) {
      e.preventDefault();
      setStatus("Saving…");
      if (demo) {
        setStatus("Demo mode — save is not sent to the server.", "is-ok");
        return;
      }
      try {
        var payload = { markdown: mdBox.value, summary: summaryInput.value || "" };
        if (isNew) {
          var slug = (slugInput.value || "").trim().toLowerCase();
          payload.slug = slug;
          await api("/pages", { method: "POST", body: payload });
          page = slug;
          setStatus("Created. Opening page…", "is-ok");
          location.href = slug + ".html";
        } else {
          await api("/pages/" + encodeURIComponent(page), { method: "PUT", body: payload });
          setStatus("Saved. Rebuilt the wiki.", "is-ok");
        }
      } catch (err) {
        setStatus(err.message || "Save failed", "is-error");
      }
    });

    (async function boot() {
      var can = await checkCanEdit();
      revealEditorTabs(can);
      syncTabs();
      if (!can) {
        hide(form);
        show(gate);
        return;
      }
      hide(gate);
      show(form);
      if (isNew) {
        if (heading) heading.textContent = "Create new page";
        if (lead) lead.textContent = "Pick a slug (lowercase letters, numbers, hyphens), write markdown, then Save.";
        show(slugField);
        mdBox.value = [
          "---",
          "title: New page",
          "slug: new-page",
          "lead: needs a short lead clause.",
          "summary: Stub.",
          "status: stub",
          "stub: true",
          "navboxes: [admin]",
          "infobox_title: New page",
          'icon: "📄"',
          'infobox_rows: ["Status|Stub"]',
          "tags: []",
          "---",
          "",
          "## Usage",
          "",
          "Describe how to use this feature.",
          "",
          "## See also",
          "",
          "- [Main page](index.html)"
        ].join("\n");
        if (slugInput) slugInput.value = "new-page";
      } else if (demo) {
        if (heading) heading.textContent = "Edit: Overview";
        mdBox.value = DEMO_MARKDOWN;
      } else {
        try {
          var data = await api("/pages/" + encodeURIComponent(page));
          mdBox.value = data.markdown || "";
          if (heading) heading.textContent = "Edit: " + (data.title || page);
        } catch (err) {
          setStatus(err.message || "Could not load page", "is-error");
          mdBox.value = "";
        }
      }
      syncTabs();
      refreshPreview();
    })();
  }

  /* —— History page —— */
  function initHistory() {
    var list = document.getElementById("historyList");
    if (!list) return;
    var page = qs("page") || "overview";
    var demo = isDemoEdit();
    var gate = document.getElementById("historyAuthGate");
    var heading = document.getElementById("historyHeading");
    var read = document.getElementById("historyTabRead");
    var edit = document.getElementById("historyTabEdit");
    var href = page === "index" ? "index.html" : page + ".html";
    if (read) read.href = href + (demo ? "?demoEdit=1" : "");
    if (edit) {
      edit.href = "edit.html?page=" + encodeURIComponent(page) + (demo ? "&demoEdit=1" : "");
    }
    if (heading) heading.textContent = "History: " + page;

    function render(edits) {
      if (!edits || !edits.length) {
        list.innerHTML = "<p class=\"history-empty\">No edits recorded yet for this page.</p>";
        return;
      }
      var rows = edits.map(function (e) {
        return "<tr><td>" + escape(e.when || "") + "</td><td>" + escape(e.who || "") +
          "</td><td>" + escape(e.summary || "") + "</td><td>" + escape(e.action || "edit") + "</td></tr>";
      }).join("");
      list.innerHTML = "<table><thead><tr><th>When (UTC)</th><th>Who</th><th>Summary</th><th>Action</th></tr></thead><tbody>" +
        rows + "</tbody></table>";
    }

    function escape(s) {
      return String(s).replace(/[&<>"']/g, function (c) {
        return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
      });
    }

    (async function boot() {
      var can = await checkCanEdit();
      revealEditorTabs(can);
      if (edit && can) show(edit);
      if (!can) {
        show(gate);
        list.innerHTML = "";
        return;
      }
      hide(gate);
      if (demo) {
        render([
          { when: "2026-10-05T17:40:00+00:00", who: "Data Analyst (demo)", summary: "Restyled lead paragraph", action: "edit" },
          { when: "2026-10-04T09:12:00+00:00", who: "AP (demo)", summary: "Created page", action: "create" }
        ]);
        return;
      }
      try {
        var data = await api("/pages/" + encodeURIComponent(page) + "/history");
        render(data.edits || []);
      } catch (err) {
        list.innerHTML = "<p class=\"history-empty\">" + escape(err.message || "Could not load history") + "</p>";
      }
    })();
  }


  /* ---- Private (admin) pages: fetch article with portal Bearer token ---- */
  async function loadPrivateArticle() {
    var body = document.body;
    if (!body || body.getAttribute("data-private") !== "1") return;
    var gate = document.getElementById("wikiPrivateGate");
    var mount = document.getElementById("wikiPrivateMount");
    var slug = (gate && gate.getAttribute("data-private-slug")) || body.getAttribute("data-page") || "";
    if (!slug) return;
    if (!portalToken()) return; // keep sign-in stub visible
    try {
      var data = await api("/private/" + encodeURIComponent(slug));
      var article = document.querySelector("article.wiki-article");
      if (!article || !data || !data.html) return;
      article.innerHTML = data.html;
      if (data.title) document.title = data.title + " \u2014 Weekly Planning Wiki";
      revealEditorTabs(await checkCanEdit());
    } catch (err) {
      if (gate && err && err.status === 401) {
        // session gone — stub already shows sign-in
        return;
      }
      if (gate) {
        var p = document.createElement("p");
        p.className = "muted";
        p.textContent = (err && err.message) || "Could not load this page.";
        gate.appendChild(p);
      }
    }
  }


  document.addEventListener("DOMContentLoaded", function () {
    applyTheme(preferredTheme());

    var btn = document.getElementById("themeToggle");
    if (btn) {
      btn.addEventListener("click", function () {
        var next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
        try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
        applyTheme(next);
      });
    }

    var toggle = document.getElementById("sidebarToggle");
    var backdrop = document.getElementById("sidebarBackdrop");
    function closeSidebar() {
      document.body.classList.remove("sidebar-open");
      if (toggle) toggle.setAttribute("aria-expanded", "false");
    }
    function openSidebar() {
      document.body.classList.add("sidebar-open");
      if (toggle) toggle.setAttribute("aria-expanded", "true");
    }
    if (toggle) {
      toggle.addEventListener("click", function () {
        if (document.body.classList.contains("sidebar-open")) closeSidebar();
        else openSidebar();
      });
    }
    if (backdrop) backdrop.addEventListener("click", closeSidebar);
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeSidebar();
    });
    var side = document.querySelector(".wiki-sidebar");
    if (side) {
      side.addEventListener("click", function (e) {
        var a = e.target.closest("a");
        if (a && window.matchMedia("(max-width: 900px)").matches) closeSidebar();
      });
    }

    // Search
    var input = document.getElementById("wikiSearch");
    var results = document.getElementById("wikiSearchResults");
    if (input && results) {
      var index = [];
      var base = document.body.getAttribute("data-wiki-base") || ".";
      fetch(base + "/search-index.json")
        .then(function (r) { return r.json(); })
        .then(function (data) {
          index = data || [];
          if (!portalToken()) return;
          return api("/private/search-index").then(function (priv) {
            if (priv && priv.pages && priv.pages.length) index = priv.pages;
          }).catch(function () {});
        })
        .catch(function () { index = []; });

      function hideResults() {
        results.classList.remove("open");
        results.innerHTML = "";
      }
      function showResults(q) {
        q = (q || "").trim().toLowerCase();
        if (q.length < 2) { hideResults(); return; }
        var hits = [];
        for (var i = 0; i < index.length; i++) {
          var item = index[i];
          var hay = (item.title + " " + (item.summary || "") + " " + (item.tags || []).join(" ")).toLowerCase();
          if (hay.indexOf(q) !== -1) hits.push(item);
          if (hits.length >= 12) break;
        }
        if (!hits.length) {
          results.innerHTML = "<li><span style='padding:0.35rem 0.5rem;display:block;color:var(--wiki-muted)'>No pages found — try another word, elder.</span></li>";
          results.classList.add("open");
          return;
        }
        results.innerHTML = hits.map(function (h) {
          return "<li><a href=\"" + h.href + "\">" + escapeHtml(h.title) + "</a></li>";
        }).join("");
        results.classList.add("open");
      }
      function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, function (c) {
          return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
        });
      }
      input.addEventListener("input", function () { showResults(input.value); });
      input.addEventListener("focus", function () { showResults(input.value); });
      document.addEventListener("click", function (e) {
        if (!results.contains(e.target) && e.target !== input) hideResults();
      });
    }

    // Article tabs: show Edit/History when signed-in editor (or demo)
    checkCanEdit().then(function (can) {
      revealEditorTabs(can);
      if (can && isDemoEdit()) {
        document.querySelectorAll("[data-page-tabs] .tab-edit, [data-page-tabs] .tab-history, [data-page-tabs] .tab-create").forEach(function (a) {
          if (a.href && a.href.indexOf("demoEdit=") === -1) {
            a.href += (a.href.indexOf("?") >= 0 ? "&" : "?") + "demoEdit=1";
          }
        });
      }
    });

    loadPrivateArticle();
    initEditor();
    initHistory();
  });
})();
