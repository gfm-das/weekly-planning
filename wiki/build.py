#!/usr/bin/env python3
"""Build the Weekly Planning 3.0 static wiki from Markdown pages.

Usage (from the wiki/ folder, or any folder):
  python wiki/build.py

Writes public HTML into wiki/out/ and private (admin) HTML into wiki/out-private/,
plus search-index.json (public) and a private search index.
No third-party packages — only the Python standard library.
"""

from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PAGES = ROOT / "pages"
OUT = ROOT / "out"
OUT_PRIVATE = ROOT / "out-private"
ASSETS = ROOT / "assets"

# Markers so portal-api can extract the inject-able article body from a private HTML file.
ARTICLE_START = "<!--wiki-article-start-->"
ARTICLE_END = "<!--wiki-article-end-->"


def set_paths(root: Path | str | None = None) -> None:
    """Point the builder at another wiki root (portal-api save uses WIKI_DIR)."""
    global ROOT, PAGES, OUT, OUT_PRIVATE, ASSETS
    ROOT = Path(root).resolve() if root else Path(__file__).resolve().parent
    PAGES = ROOT / "pages"
    OUT = ROOT / "out"
    OUT_PRIVATE = ROOT / "out-private"
    ASSETS = ROOT / "assets"


def admin_sidebar_slugs() -> frozenset[str]:
    """Slugs listed under the Data and admin sidebar section."""
    for heading, links in SIDEBAR:
        if "Data" in heading and "admin" in heading.lower():
            return frozenset(item[0] for item in links)
    return frozenset()


def is_private_page(meta: dict) -> bool:
    """True when the page belongs to the Data and admin section (portal login required)."""
    slug = str(meta.get("slug") or "")
    if slug in admin_sidebar_slugs():
        return True
    navs = meta.get("navboxes") or []
    if isinstance(navs, str):
        navs = [navs]
    if "admin" in navs:
        return True
    access = str(meta.get("access") or "").strip().lower()
    if access in ("private", "admin", "login"):
        return True
    return False

# Sidebar: (heading, [(slug, label, icon), ...])
SIDEBAR = [
    ("Navigation", [
        ("index", "Main page", "🏠"),
        ("random", "Random page", "🎲"),
        ("glossary", "Glossary", "📖"),
    ]),
    ("Using the portal", [
        ("signing-in", "Signing in", "🔑"),
        ("overview", "Overview", "📋"),
        ("weekly-planning", "Weekly Planning", "📅"),
        ("glimpse", "Glimpse", "👀"),
        ("dashboards", "Dashboards", "📊"),
        ("presentation-library", "Presentation Library", "🎬"),
        ("roles-and-permissions", "Roles and permissions", "👔"),
    ]),
    ("Data and admin", [
        ("uploads-importer", "Uploads / Importer", "⬆️"),
        ("management", "Management (Places)", "🗺️"),
        ("roster", "Roster", "👥"),
        ("accounts", "Accounts", "🪪"),
        ("dbeaver-access", "DBeaver access", "🗄️"),
        ("backups-and-restore", "Backups and restore", "💾"),
        ("health-check", "Health check", "❤️"),
        ("server-overview", "Server overview", "🖥️"),
        ("troubleshooting", "Troubleshooting", "🔧"),
        ("editing-the-wiki", "Editing the wiki", "✏️"),
    ]),
    ("Installing", [
        ("installer-overview", "Installer overview", "📦"),
        ("requirements", "Requirements", "✅"),
    ]),
]

NAVBOXES = {
    "using": {
        "title": "Using the portal",
        "icon": "🚲",
        "groups": [
            ("Get started", [("signing-in", "Signing in"), ("overview", "Overview"), ("roles-and-permissions", "Roles and permissions")]),
            ("Planning", [("weekly-planning", "Weekly Planning"), ("glimpse", "Glimpse")]),
            ("Insights", [("dashboards", "Dashboards"), ("presentation-library", "Presentation Library")]),
        ],
    },
    "admin": {
        "title": "Data and admin",
        "icon": "🗂️",
        "groups": [
            ("People & places", [("uploads-importer", "Uploads / Importer"), ("management", "Management"), ("roster", "Roster"), ("accounts", "Accounts")]),
            ("Server", [("dbeaver-access", "DBeaver access"), ("backups-and-restore", "Backups and restore"), ("health-check", "Health check"), ("server-overview", "Server overview"), ("troubleshooting", "Troubleshooting"), ("editing-the-wiki", "Editing the wiki")]),
        ],
    },
    "install": {
        "title": "Installing",
        "icon": "🛠️",
        "groups": [
            ("Setup", [("installer-overview", "Installer overview"), ("requirements", "Requirements"), ("glossary", "Glossary")]),
        ],
    },
}

# All three section navboxes appear on every content page (collapsible).
ALL_NAVBOX_KEYS = ["using", "admin", "install"]

RANDOM_TIPS = [
    "P-day is for laundry and grocery runs — not for rewriting the roster by hand.",
    "District council goes smoother when everyone submitted Weekly Planning on time.",
    "Sunday is the reporting-week key. Plans lock to area + ward/branch + that Sunday.",
    "A roster upload wins over a hand-closed zone, district, or area. Trust the roster.",
    "Hiding a menu button is not security. The API and database still decide.",
    "Two companions can type the same plan at once — each save only sends what changed.",
    "Friday planning habits are fine; the week itself still keys off Sunday.",
    "If health.ps1 is green, you are cleared to tract the next ticket.",
]


def slugify(text: str) -> str:
    s = re.sub(r"<[^>]+>", "", text)
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "section"


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw = text[3:end].strip()
    body = text[end + 4:].lstrip("\n")
    meta: dict = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            meta[key] = [x.strip().strip("'\"") for x in inner.split(",") if x.strip()] if inner else []
        elif val.lower() in ("true", "yes"):
            meta[key] = True
        elif val.lower() in ("false", "no"):
            meta[key] = False
        else:
            meta[key] = val.strip("'\"")
    return meta, body


def inline(text: str) -> str:
    parts: list[str] = []
    last = 0
    for m in re.finditer(r"`([^`]+)`", text):
        parts.append(_inline_fmt(text[last:m.start()]))
        parts.append("<code>" + html.escape(m.group(1)) + "</code>")
        last = m.end()
    parts.append(_inline_fmt(text[last:]))
    return "".join(parts)


def _inline_fmt(text: str) -> str:
    t = html.escape(text)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", t)
    return t


def md_to_html(md: str) -> tuple[str, list[tuple[int, str, str]]]:
    """Convert a small Markdown subset to HTML. Returns (html, toc entries)."""
    lines = md.splitlines()
    out: list[str] = []
    toc: list[tuple[int, str, str]] = []
    i = 0
    in_code = False
    code_lang = ""
    code_buf: list[str] = []

    def flush_para(buf: list[str]):
        if not buf:
            return
        text = " ".join(buf).strip()
        if text:
            out.append(f"<p>{inline(text)}</p>")
        buf.clear()

    para: list[str] = []

    while i < len(lines):
        line = lines[i]

        if in_code:
            if line.startswith("```"):
                out.append(
                    f'<pre><code class="language-{html.escape(code_lang)}">'
                    f'{html.escape(chr(10).join(code_buf))}</code></pre>'
                )
                in_code = False
                code_buf = []
            else:
                code_buf.append(line)
            i += 1
            continue

        if line.startswith("```"):
            flush_para(para)
            in_code = True
            code_lang = line[3:].strip()
            i += 1
            continue

        if line.strip() == ":::needs-checking":
            flush_para(para)
            i += 1
            note: list[str] = []
            while i < len(lines) and lines[i].strip() != ":::":
                note.append(lines[i])
                i += 1
            i += 1  # skip closing :::
            out.append(
                '<div class="needs-checking"><strong>Needs checking:</strong> '
                + inline(" ".join(note))
                + "</div>"
            )
            continue

        if line.strip() == ":::didyouknow":
            flush_para(para)
            i += 1
            block: list[str] = []
            while i < len(lines) and lines[i].strip() != ":::":
                block.append(lines[i])
                i += 1
            i += 1
            inner, _ = md_to_html("\n".join(block))
            # Drop nested h2 from TOC noise — re-parse list-only content
            out.append('<aside class="didyouknow"><h2>Did you know…</h2>' + inner + "</aside>")
            continue

        hm = re.match(r"^(#{1,4})\s+(.+)$", line)
        if hm:
            flush_para(para)
            level = len(hm.group(1))
            title = hm.group(2).strip()
            sid = slugify(title)
            toc.append((level, sid, title))
            out.append(f'<h{level} id="{sid}">{inline(title)}</h{level}>')
            i += 1
            continue

        if line.strip().startswith("|") and "|" in line.strip()[1:]:
            flush_para(para)
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            out.append(_table_html(table_lines))
            continue

        if re.match(r"^[-*]\s+", line):
            flush_para(para)
            items = []
            while i < len(lines) and re.match(r"^[-*]\s+", lines[i]):
                items.append(re.sub(r"^[-*]\s+", "", lines[i]))
                i += 1
            out.append("<ul>" + "".join(f"<li>{inline(it)}</li>" for it in items) + "</ul>")
            continue

        if re.match(r"^\d+\.\s+", line):
            flush_para(para)
            items = []
            while i < len(lines) and re.match(r"^\d+\.\s+", lines[i]):
                items.append(re.sub(r"^\d+\.\s+", "", lines[i]))
                i += 1
            out.append("<ol>" + "".join(f"<li>{inline(it)}</li>" for it in items) + "</ol>")
            continue

        if not line.strip():
            flush_para(para)
            i += 1
            continue

        para.append(line.strip())
        i += 1

    flush_para(para)
    return "\n".join(out), toc


def _table_html(lines: list[str]) -> str:
    rows = []
    for line in lines:
        cells = [c.strip() for c in line.strip("|").split("|")]
        rows.append(cells)
    if len(rows) >= 2 and all(re.match(r"^:?-+:?$", c.replace(" ", "")) for c in rows[1]):
        header, body = rows[0], rows[2:]
    else:
        header, body = None, rows
    html_parts = ["<table>"]
    if header:
        html_parts.append(
            "<thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in header) + "</tr></thead>"
        )
    html_parts.append("<tbody>")
    for row in body:
        html_parts.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>")
    html_parts.append("</tbody></table>")
    return "".join(html_parts)


def render_infobox(meta: dict) -> str:
    rows = meta.get("infobox") or []
    if isinstance(rows, str):
        parsed = []
        for part in rows.split(";"):
            if "|" in part:
                a, b = part.split("|", 1)
                parsed.append({"label": a.strip(), "value": b.strip()})
        rows = parsed
    if not rows and not meta.get("infobox_title"):
        return ""
    title = html.escape(str(meta.get("infobox_title") or meta.get("title") or ""))
    icon = str(meta.get("icon") or "📋")
    # Allow raw emoji or a short HTML/SVG snippet already escaped by authors as plain text
    icon_html = html.escape(icon) if not icon.strip().startswith("<") else icon
    parts = [
        '<aside class="infobox">',
        f'<div class="infobox-title">{title}</div>',
        f'<div class="infobox-icon" aria-hidden="true">{icon_html}</div>',
        "<table>",
    ]
    for row in rows:
        if isinstance(row, dict):
            label, value = row.get("label", ""), row.get("value", "")
        else:
            continue
        parts.append(f"<tr><th>{inline(str(label))}</th><td>{inline(str(value))}</td></tr>")
    parts.append("</table></aside>")
    return "\n".join(parts)


def render_toc(toc: list[tuple[int, str, str]]) -> str:
    entries = [(lvl, sid, title) for lvl, sid, title in toc if lvl in (2, 3)]
    if len(entries) < 2:
        return ""
    parts = ['<nav class="toc" aria-label="Contents"><div class="toc-title">Contents</div><ol>']
    for lvl, sid, title in entries:
        pad = ' style="margin-left:1rem"' if lvl == 3 else ""
        parts.append(f'<li{pad}><a href="#{sid}">{inline(title)}</a></li>')
    parts.append("</ol></nav>")
    return "\n".join(parts)


def render_navboxes(keys: list[str], current: str) -> str:
    parts = ['<div class="navboxes-wrap">']
    for key in keys:
        nb = NAVBOXES.get(key)
        if not nb:
            continue
        icon = nb.get("icon", "")
        open_attr = " open" if key == _primary_nav_for(current, keys) else ""
        parts.append(f"<details class=\"navbox\"{open_attr}>")
        parts.append(
            f'<summary class="navbox-title">'
            f'<span aria-hidden="true">{html.escape(icon)}</span> '
            f'{html.escape(nb["title"])}</summary>'
        )
        for label, links in nb["groups"]:
            parts.append('<div class="navbox-group">')
            parts.append(f'<div class="navbox-label">{html.escape(label)}</div>')
            parts.append('<div class="navbox-list">')
            link_html = []
            for slug, text in links:
                lock = ""
                if key == "admin":
                    lock = (
                        ' <span class="nav-lock" title="Portal sign-in required" '
                        'aria-label="Portal sign-in required">&#128274;</span>'
                    )
                if slug == current:
                    link_html.append(f"<strong>{html.escape(text)}</strong>{lock}")
                else:
                    link_html.append(
                        f'<a href="{slug}.html">{html.escape(text)}{lock}</a>'
                    )
            parts.append(" · ".join(link_html))
            parts.append("</div></div>")
        parts.append("</details>")
    parts.append("</div>")
    return "\n".join(parts)


def _primary_nav_for(current: str, keys: list[str]) -> str:
    """Which navbox should start expanded."""
    for heading, links in SIDEBAR:
        for item in links:
            slug = item[0]
            if slug != current:
                continue
            if "Using" in heading:
                return "using"
            if "Data" in heading:
                return "admin"
            if "Install" in heading:
                return "install"
    if "using" in keys:
        return "using"
    return keys[0] if keys else "using"


def render_sidebar(current: str) -> str:
    parts = [
        '<aside class="wiki-sidebar" id="wikiSidebar">',
        '<div class="brand"><a href="index.html">'
        '<span class="brand-title">Weekly Planning Wiki</span>'
        '<span class="brand-sub">Germany Frankfurt Mission</span>'
        "</a></div>",
        '<div class="flag-accent" aria-hidden="true">'
        '<span class="fk-black"></span><span class="fk-red"></span><span class="fk-gold"></span>'
        "</div>",
        '<div class="search-wrap">'
        '<input type="search" id="wikiSearch" placeholder="Search wiki…" '
        'aria-label="Search wiki" autocomplete="off">'
        '<ul class="search-results" id="wikiSearchResults"></ul></div>',
        "<nav>",
    ]
    for heading, links in SIDEBAR:
        parts.append(f"<h2>{html.escape(heading)}</h2><ul>")
        for item in links:
            slug, label = item[0], item[1]
            icon = item[2] if len(item) > 2 else ""
            cls = ' class="current"' if slug == current else ""
            href = "index.html" if slug == "index" else f"{slug}.html"
            icon_span = (
                f'<span class="nav-icon" aria-hidden="true">{html.escape(icon)}</span>'
                if icon
                else ""
            )
            lock = ""
            if "Data" in heading and "admin" in heading.lower():
                lock = (
                    '<span class="nav-lock" title="Portal sign-in required" '
                    'aria-label="Portal sign-in required">&#128274;</span>'
                )
            parts.append(
                f'<li{cls}><a href="{href}">{icon_span}'
                f"<span>{html.escape(label)}</span>{lock}</a></li>"
            )
        parts.append("</ul>")
    parts.append("</nav></aside>")
    return "\n".join(parts)


def page_template(
    slug: str,
    meta: dict,
    body_html: str,
    toc_html: str,
    infobox_html: str,
    navbox_html: str,
    *,
    private: bool = False,
) -> str:
    title = meta.get("title") or slug
    lead = meta.get("lead") or ""
    stub = meta.get("stub", False)
    status = meta.get("status", "full" if not stub else "stub")
    has_infobox = bool(infobox_html)
    layout_cls = "wiki-layout" if has_infobox else "wiki-layout no-infobox"

    stub_html = ""
    if stub or status == "stub":
        stub_html = (
            '<div class="stub-notice">'
            '<span class="stub-icon" aria-hidden="true">🚲</span>'
            "<strong>This article is still out tracting</strong> — "
            "help it find its way by expanding it with checked facts from the live system. "
            "Sections marked <em>needs checking</em> should be verified before relying on them."
            "</div>"
        )

    lead_html = ""
    if lead:
        lead_html = (
            f'<p class="wiki-lead"><strong class="subject">{html.escape(title)}</strong> '
            f"{inline(lead)}</p>"
        )

    main_col = stub_html + lead_html + toc_html + body_html
    if has_infobox:
        content = f'<div class="{layout_cls}"><div class="wiki-body">{main_col}</div>{infobox_html}</div>'
    else:
        content = f'<div class="{layout_cls}"><div class="wiki-body">{main_col}</div></div>'

    out_href = "index.html" if slug == "index" else f"{html.escape(slug)}.html"
    private_attr = ' data-private="1"' if private else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)} — Weekly Planning Wiki</title>
  <meta name="description" content="{html.escape(str(meta.get('summary') or lead or title))}">
  <link rel="stylesheet" href="assets/wiki.css">
  <script src="assets/wiki.js" defer></script>
</head>
<body data-wiki-base="." data-page="{html.escape(slug)}"{private_attr}>
  <div class="sidebar-backdrop" id="sidebarBackdrop"></div>
  <div class="wiki-shell">
    {render_sidebar(slug)}
    <div class="wiki-main">
      <div class="wiki-topbar">
        <span class="topbar-tagline">Suit up. Plan the week. Serve.</span>
        <div class="topbar-actions">
          <button type="button" class="sidebar-toggle" id="sidebarToggle" aria-expanded="false" aria-controls="wikiSidebar">☰ Menu</button>
          <button type="button" class="theme-toggle" id="themeToggle">Dark mode</button>
        </div>
      </div>
      <article class="wiki-article">
        {ARTICLE_START}
        <nav class="wiki-page-tabs" aria-label="Page actions" data-page-tabs data-slug="{html.escape(slug)}">
          <a class="tab is-active" href="{out_href}" data-tab="read">Read</a>
          <a class="tab tab-edit is-hidden" href="edit.html?page={html.escape(slug)}" data-tab="edit">Edit</a>
          <a class="tab tab-history is-hidden" href="history.html?page={html.escape(slug)}" data-tab="history">History</a>
          <a class="tab tab-create is-hidden" href="edit.html?new=1" data-tab="create">Create new page</a>
        </nav>
        <h1>{html.escape(title)}</h1>
        {content}
        {navbox_html}
        <p class="wiki-footer">
          Plain-language docs for the Germany Frankfurt Mission portal.
          Style only inspired by public wiki layouts — not affiliated with Minecraft or Mojang.
          No church logos or trademarked imagery.
          <span class="footer-tag">Built for companions who plan on phones between appointments.</span>
        </p>
        {ARTICLE_END}
      </article>
    </div>
  </div>
</body>
</html>
"""



def build_private_stub(slug: str, meta: dict, navbox_html: str) -> str:
    """Public HTML for an admin page: chrome + sign-in gate, no article body."""
    title = meta.get("title") or slug
    # Do not put admin summary/lead into the public stub (may contain ops details).
    summary = "Sign in to the portal to read this page."
    out_href = "index.html" if slug == "index" else f"{html.escape(slug)}.html"
    sign_in_href = html.escape(f"/?return=/wiki/{out_href}")
    gate = f"""
        <div class="private-gate" id="wikiPrivateGate" data-private-slug="{html.escape(slug)}">
          <div class="private-gate-icon" aria-hidden="true">&#128274;</div>
          <h2>Sign in to read this page</h2>
          <p>This page is in the <strong>Data and admin</strong> section. Sign in to the
             mission portal to read it. Any portal account works.</p>
          <p><a class="btn btn-primary" href="{sign_in_href}">Sign in to the portal</a></p>
          <p class="muted">Already signed in? This page will load automatically.</p>
        </div>
        <div id="wikiPrivateMount" class="is-hidden" hidden></div>
"""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)} \u2014 Weekly Planning Wiki</title>
  <meta name="description" content="{html.escape(summary)}">
  <meta name="robots" content="noindex">
  <link rel="stylesheet" href="assets/wiki.css">
  <script src="assets/wiki.js" defer></script>
</head>
<body data-wiki-base="." data-page="{html.escape(slug)}" data-private="1">
  <div class="sidebar-backdrop" id="sidebarBackdrop"></div>
  <div class="wiki-shell">
    {render_sidebar(slug)}
    <div class="wiki-main">
      <div class="wiki-topbar">
        <span class="topbar-tagline">Suit up. Plan the week. Serve.</span>
        <div class="topbar-actions">
          <button type="button" class="sidebar-toggle" id="sidebarToggle" aria-expanded="false" aria-controls="wikiSidebar">&#9776; Menu</button>
          <button type="button" class="theme-toggle" id="themeToggle">Dark mode</button>
        </div>
      </div>
      <article class="wiki-article">
        <nav class="wiki-page-tabs" aria-label="Page actions" data-page-tabs data-slug="{html.escape(slug)}">
          <a class="tab is-active" href="{out_href}" data-tab="read">Read</a>
          <a class="tab tab-edit is-hidden" href="edit.html?page={html.escape(slug)}" data-tab="edit">Edit</a>
          <a class="tab tab-history is-hidden" href="history.html?page={html.escape(slug)}" data-tab="history">History</a>
          <a class="tab tab-create is-hidden" href="edit.html?new=1" data-tab="create">Create new page</a>
        </nav>
        <h1>{html.escape(title)}</h1>
        {gate}
        {navbox_html}
        <p class="wiki-footer">
          Plain-language docs for the Germany Frankfurt Mission portal.
          Style only inspired by public wiki layouts \u2014 not affiliated with Minecraft or Mojang.
          No church logos or trademarked imagery.
          <span class="footer-tag">Built for companions who plan on phones between appointments.</span>
        </p>
      </article>
    </div>
  </div>
</body>
</html>
"""


def load_pages() -> list[dict]:
    pages = []
    for path in sorted(PAGES.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(text)
        slug = meta.get("slug") or path.stem
        meta["slug"] = slug
        meta.setdefault("title", slug.replace("-", " ").title())
        pages.append({"path": path, "meta": meta, "body": body})
    return pages


def build_random_page(slugs: list[str]) -> str:
    js_list = json.dumps([s for s in slugs if s not in ("index", "random")])
    tips_js = json.dumps(RANDOM_TIPS, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Random page — Weekly Planning Wiki</title>
  <link rel="stylesheet" href="assets/wiki.css">
  <script>
    var pages = {js_list};
    var tips = {tips_js};
    var tip = tips[Math.floor(Math.random() * tips.length)];
    document.addEventListener("DOMContentLoaded", function () {{
      var el = document.getElementById("randomTip");
      if (el) el.textContent = tip;
    }});
    if (pages.length) {{
      setTimeout(function () {{
        location.replace(pages[Math.floor(Math.random() * pages.length)] + ".html");
      }}, 900);
    }}
  </script>
</head>
<body>
  <div class="wiki-main" style="max-width:40rem;margin:2rem auto;padding:0 1rem">
    <div class="flavour-tip">
      <div class="tip-label">🎲 Random page</div>
      <p>Opening a random article… <a href="index.html">Main page</a></p>
      <p><strong>Mission tip:</strong> <span id="randomTip">…</span></p>
    </div>
  </div>
</body>
</html>
"""


def build_404_page() -> str:
    tips = "".join(f"<li>{html.escape(t)}</li>" for t in RANDOM_TIPS[:4])
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Page not found — Weekly Planning Wiki</title>
  <link rel="stylesheet" href="assets/wiki.css">
  <script src="assets/wiki.js" defer></script>
</head>
<body data-wiki-base="." data-page="404">
  <div class="sidebar-backdrop" id="sidebarBackdrop"></div>
  <div class="wiki-shell">
    {render_sidebar("404")}
    <div class="wiki-main">
      <div class="wiki-topbar">
        <span class="topbar-tagline">Suit up. Plan the week. Serve.</span>
        <div class="topbar-actions">
          <button type="button" class="sidebar-toggle" id="sidebarToggle" aria-expanded="false" aria-controls="wikiSidebar">☰ Menu</button>
          <button type="button" class="theme-toggle" id="themeToggle">Dark mode</button>
        </div>
      </div>
      <article class="wiki-article">
        <h1>404 — This page went out tracting</h1>
        <p class="wiki-lead">We looked on every street in the area book and still could not find that URL.</p>
        <div class="flavour-tip">
          <div class="tip-label">Try these</div>
          <ul>
            <li><a href="index.html">Main page</a></li>
            <li><a href="weekly-planning.html">Weekly Planning</a></li>
            <li><a href="glossary.html">Glossary</a></li>
            <li><a href="random.html">Random page</a></li>
          </ul>
        </div>
        <div class="didyouknow">
          <h2>While you are here…</h2>
          <ul>{tips}</ul>
        </div>
        <p class="wiki-footer">
          Plain-language docs for the Germany Frankfurt Mission portal.
          <span class="footer-tag">Even apostles had to ask for directions sometimes.</span>
        </p>
      </article>
    </div>
  </div>
</body>
</html>
"""


def _shell_chrome(title: str, slug: str, article_inner: str) -> str:
    """Shared chrome for special pages (edit / history)."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)} — Weekly Planning Wiki</title>
  <link rel="stylesheet" href="assets/wiki.css">
  <script src="assets/wiki.js" defer></script>
</head>
<body data-wiki-base="." data-page="{html.escape(slug)}">
  <div class="sidebar-backdrop" id="sidebarBackdrop"></div>
  <div class="wiki-shell">
    {render_sidebar(slug)}
    <div class="wiki-main">
      <div class="wiki-topbar">
        <span class="topbar-tagline">Suit up. Plan the week. Serve.</span>
        <div class="topbar-actions">
          <button type="button" class="sidebar-toggle" id="sidebarToggle" aria-expanded="false" aria-controls="wikiSidebar">☰ Menu</button>
          <button type="button" class="theme-toggle" id="themeToggle">Dark mode</button>
        </div>
      </div>
      <article class="wiki-article">
        {article_inner}
      </article>
    </div>
  </div>
</body>
</html>
"""


def build_edit_page() -> str:
    inner = """
        <nav class="wiki-page-tabs" aria-label="Page actions" data-page-tabs data-slug="" id="editPageTabs">
          <a class="tab" href="index.html" data-tab="read" id="editTabRead">Read</a>
          <a class="tab is-active" href="#" data-tab="edit">Edit</a>
          <a class="tab tab-history is-hidden" href="history.html" data-tab="history" id="editTabHistory">History</a>
          <a class="tab tab-create" href="edit.html?new=1" data-tab="create">Create new page</a>
        </nav>
        <h1 id="editHeading">Edit page</h1>
        <p class="wiki-lead" id="editLead">Change the markdown on the left. The preview on the right uses the same renderer as the published wiki.</p>
        <div id="editAuthGate" class="edit-gate is-hidden">
          <p><strong>Sign in</strong> to the mission portal as an AP, the President, or a Data Analyst to edit.</p>
          <p><a href="/">Open the portal</a></p>
        </div>
        <form id="wikiEditor" class="wiki-editor is-hidden" autocomplete="off">
          <div class="editor-meta">
            <label class="editor-field editor-slug-field is-hidden" id="newSlugField">
              <span>Page name (slug)</span>
              <input type="text" id="editSlug" name="slug" pattern="[a-z0-9]+(-[a-z0-9]+)*" maxlength="80"
                     placeholder="my-new-page" spellcheck="false">
            </label>
            <label class="editor-field editor-summary-field">
              <span>Edit summary</span>
              <input type="text" id="editSummary" name="summary" maxlength="240"
                     placeholder="What did you change?">
            </label>
          </div>
          <div class="editor-panes">
            <label class="editor-pane">
              <span class="pane-label">Markdown source</span>
              <textarea id="editMarkdown" name="markdown" spellcheck="true"></textarea>
            </label>
            <div class="editor-pane">
              <div class="pane-label">Live preview</div>
              <div class="editor-preview wiki-body" id="editPreview"><p class="muted">Preview appears here.</p></div>
            </div>
          </div>
          <div class="editor-actions">
            <button type="submit" class="btn btn-primary" id="editSave">Save</button>
            <button type="button" class="btn" id="editCancel">Cancel</button>
            <span class="editor-status" id="editStatus" role="status" aria-live="polite"></span>
          </div>
        </form>
    """
    return _shell_chrome("Edit page", "edit", inner)


def build_history_page() -> str:
    inner = """
        <nav class="wiki-page-tabs" aria-label="Page actions" data-page-tabs data-slug="" id="historyPageTabs">
          <a class="tab" href="index.html" data-tab="read" id="historyTabRead">Read</a>
          <a class="tab tab-edit is-hidden" href="edit.html" data-tab="edit" id="historyTabEdit">Edit</a>
          <a class="tab is-active" href="#" data-tab="history">History</a>
        </nav>
        <h1 id="historyHeading">Page history</h1>
        <p class="wiki-lead" id="historyLead">Recent edits to this page (who, when, summary).</p>
        <div id="historyAuthGate" class="edit-gate is-hidden">
          <p><strong>Sign in</strong> as an AP, the President, or a Data Analyst to view edit history.</p>
        </div>
        <div id="historyList" class="history-list"></div>
    """
    return _shell_chrome("Page history", "history", inner)




def main() -> None:
    if not PAGES.is_dir():
        raise SystemExit(f"Missing pages folder: {PAGES}")

    if OUT.exists():
        shutil.rmtree(OUT)
    if OUT_PRIVATE.exists():
        shutil.rmtree(OUT_PRIVATE)
    OUT.mkdir(parents=True)
    OUT_PRIVATE.mkdir(parents=True)
    (OUT / "assets").mkdir()
    for f in ASSETS.iterdir():
        if f.is_file():
            shutil.copy2(f, OUT / "assets" / f.name)

    pages = load_pages()
    public_index: list[dict] = []
    private_index: list[dict] = []
    public_slugs: list[str] = []
    private_count = 0

    for page in pages:
        meta = page["meta"]
        slug = meta["slug"]
        body_html, toc = md_to_html(page["body"])
        toc_html = "" if meta.get("hide_toc") else render_toc(toc)
        meta = dict(meta)
        if meta.get("infobox_rows"):
            meta["infobox"] = []
            for item in meta["infobox_rows"]:
                if "|" in item:
                    a, b = item.split("|", 1)
                    meta["infobox"].append({"label": a.strip(), "value": b.strip()})
        infobox_html = render_infobox(meta)

        nav_keys = list(ALL_NAVBOX_KEYS)
        navbox_html = render_navboxes(nav_keys, slug)

        private = is_private_page(meta)
        full_html = page_template(
            slug, meta, body_html, toc_html, infobox_html, navbox_html, private=private
        )
        out_name = "index.html" if slug == "index" else f"{slug}.html"

        entry = {
            "title": meta["title"],
            "href": out_name,
            "summary": meta.get("summary") or meta.get("lead") or "",
            "tags": meta.get("tags") or [],
            "stub": bool(meta.get("stub") or meta.get("status") == "stub"),
            "private": private,
        }
        private_index.append(entry)

        if private:
            private_count += 1
            (OUT_PRIVATE / out_name).write_text(full_html, encoding="utf-8")
            stub_html = build_private_stub(slug, meta, navbox_html)
            (OUT / out_name).write_text(stub_html, encoding="utf-8")
        else:
            public_slugs.append(slug)
            (OUT / out_name).write_text(full_html, encoding="utf-8")
            public_index.append(entry)

    # Random page only walks public articles (admin pages need a session).
    (OUT / "random.html").write_text(build_random_page(public_slugs), encoding="utf-8")
    (OUT / "404.html").write_text(build_404_page(), encoding="utf-8")
    (OUT / "edit.html").write_text(build_edit_page(), encoding="utf-8")
    (OUT / "history.html").write_text(build_history_page(), encoding="utf-8")
    (OUT / "search-index.json").write_text(
        json.dumps(public_index, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (OUT_PRIVATE / "search-index.json").write_text(
        json.dumps(private_index, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"Built {len(pages)} pages ({private_count} private) into {OUT} + {OUT_PRIVATE}")
    for e in private_index:
        flag = " STUB" if e["stub"] else ""
        flag += " PRIVATE" if e["private"] else ""
        print(f"  - {e['href']}{flag}")
    print("  - random.html")
    print("  - 404.html")
    print("  - edit.html")
    print("  - history.html")



if __name__ == "__main__":
    main()
