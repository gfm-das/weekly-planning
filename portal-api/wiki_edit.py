"""Wiki page editing for the Weekly Planning docs (wiki/).

What it is: /api/wiki routes to read markdown sources, preview with the same renderer as wiki/build.py,
save pages (rebuild static HTML), and list recent edits.
Who uses it: managers (AP, President, Data Analyst) from the wiki's Edit tab in the browser.
How it fits: pages live under WIKI_DIR (default /data/wiki — mount wiki/ into the portal-api container).
Saves write wiki/pages/<slug>.md, run build.py, and append to wiki/edit-log.jsonl. Optional git commit when
WIKI_GIT_COMMIT=1 (off by default). Syncing edits back to GitHub is a separate ops step (see wiki/README.md).

    GET  /api/wiki/me                      {can_edit, role_label, display_name}
    GET  /api/wiki/pages                   {pages: [{slug, title}, ...]}
    GET  /api/wiki/pages/<slug>            {slug, markdown, title, exists}
    PUT  /api/wiki/pages/<slug>            {markdown, summary?} → save + rebuild
    POST /api/wiki/pages                   {slug, markdown, summary?} → create + rebuild
    POST /api/wiki/preview                 {markdown} → {html} (body fragment, same as build.py)
    GET  /api/wiki/pages/<slug>/history    {edits: [{when, who, summary, ...}, ...]}
    GET  /api/wiki/private/<slug>          {slug, title, html}  (any signed-in user; admin pages)
    GET  /api/wiki/private/search-index    {pages: [...]}       (any signed-in user)
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, abort, g, jsonify, request

import roles

wiki_bp = Blueprint('wiki_edit', __name__)

SLUG_RE = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
SLUG_MAX = 80
MARKDOWN_MAX = 200_000  # characters
SUMMARY_MAX = 240
RESERVED_SLUGS = frozenset({
    'random', 'edit', 'history', '404', 'assets', 'search-index', 'index',
})
NOT_EDITOR = 'Editing the wiki is for the APs, the President and the Data Analysts.'
BAD_SLUG = 'Use a page name of lowercase letters, numbers and hyphens only (for example weekly-planning).'
TOO_LARGE = f'Keep the page under {MARKDOWN_MAX // 1000} KB of text.'
MISSING_PAGE = 'That wiki page does not exist yet.'
EXISTS = 'A page with that name already exists. Open it to edit, or choose another name.'
NO_WIKI = 'The wiki folder is not mounted on this server (set WIKI_DIR).'


def _app():
    import app
    return app


def wiki_root() -> Path:
    return Path(os.environ.get('WIKI_DIR') or '/data/wiki').resolve()


def pages_dir() -> Path:
    return wiki_root() / 'pages'


def edit_log_path() -> Path:
    return wiki_root() / 'edit-log.jsonl'


def require_editor():
    if not roles.can_edit_wiki(g.context):
        abort(403, NOT_EDITOR)


def validate_slug(slug: str, *, allow_index: bool = False, for_create: bool = False) -> str:
    """Lowercase slug [a-z0-9-]. index may be edited; create refuses reserved names including index."""
    slug = (slug or '').strip().lower()
    if not slug or len(slug) > SLUG_MAX or not SLUG_RE.match(slug):
        abort(400, BAD_SLUG)
    reserved = set(RESERVED_SLUGS)
    if allow_index and not for_create:
        reserved.discard('index')
    if slug in reserved:
        abort(400, BAD_SLUG)
    return slug


def validate_markdown(text) -> str:
    if text is None or not isinstance(text, str):
        abort(400, 'Send the page as markdown text.')
    if len(text) > MARKDOWN_MAX:
        abort(400, TOO_LARGE)
    return text


def validate_summary(value) -> str:
    if value is None:
        return ''
    if not isinstance(value, str):
        abort(400, 'Edit summary must be text.')
    text = value.strip()
    if len(text) > SUMMARY_MAX:
        abort(400, f'Keep the edit summary to {SUMMARY_MAX} characters or fewer.')
    return text


def load_wiki_build():
    """Import wiki/build.py from WIKI_DIR (stdlib renderer shared with the static site)."""
    root = wiki_root()
    path = root / 'build.py'
    if not path.is_file():
        abort(503, NO_WIKI)
    spec = importlib.util.spec_from_file_location('gfm_wiki_build', path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    if hasattr(mod, 'set_paths'):
        mod.set_paths(root)
    return mod


def page_path(slug: str) -> Path:
    return pages_dir() / f'{slug}.md'


def parse_title(markdown: str, slug: str) -> str:
    build = load_wiki_build()
    meta, _ = build.parse_frontmatter(markdown)
    return str(meta.get('title') or slug.replace('-', ' ').title())


def actor_label(c) -> str:
    name = (c.get('display_name') or c.get('full_name') or '').strip()
    if name:
        return name
    return roles.describe(c)


def append_edit_log(entry: dict) -> None:
    path = edit_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + '\n')


def read_history(slug: str, limit: int = 50) -> list[dict]:
    path = edit_log_path()
    if not path.is_file():
        return []
    matched = []
    with path.open(encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get('slug') == slug:
                matched.append(row)
    matched.reverse()
    return matched[:limit]


def rebuild_wiki() -> None:
    build = load_wiki_build()
    build.main()


def maybe_git_commit(slug: str, summary: str, who: str) -> str | None:
    if os.environ.get('WIKI_GIT_COMMIT', '').strip() not in ('1', 'true', 'yes'):
        return None
    root = wiki_root()
    # Prefer the git repo that contains the wiki (repo root one level up if wiki/ is a subfolder).
    repo = root.parent if (root.parent / '.git').exists() else root
    if not (repo / '.git').exists():
        return None
    message = f'wiki({slug}): {summary or "edit"} — {who}'
    try:
        subprocess.run(['git', '-C', str(repo), 'add', '--', str(page_path(slug).relative_to(repo)),
                        str(edit_log_path().relative_to(repo))],
                       check=False, capture_output=True, timeout=30)
        # Also stage out/ if present under the repo
        out_dir = root / 'out'
        if out_dir.is_dir():
            subprocess.run(['git', '-C', str(repo), 'add', '--', str(out_dir.relative_to(repo))],
                           check=False, capture_output=True, timeout=60)
        priv_dir = root / 'out-private'
        if priv_dir.is_dir():
            subprocess.run(['git', '-C', str(repo), 'add', '--', str(priv_dir.relative_to(repo))],
                           check=False, capture_output=True, timeout=60)
        result = subprocess.run(
            ['git', '-C', str(repo), 'commit', '-m', message],
            check=False, capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            return None
        head = subprocess.run(['git', '-C', str(repo), 'rev-parse', '--short', 'HEAD'],
                              check=False, capture_output=True, text=True, timeout=15)
        return (head.stdout or '').strip() or 'ok'
    except (OSError, subprocess.TimeoutExpired):
        return None


@wiki_bp.get('/api/wiki/me')
def wiki_me():
    """Whether this person may edit the wiki (plus a short label for the UI)."""
    c = g.context
    return jsonify(
        can_edit=roles.can_edit_wiki(c),
        role_label=roles.describe(c),
        display_name=(c.get('display_name') or '').strip() or None,
        capabilities=roles.capabilities(c),
    )


@wiki_bp.get('/api/wiki/pages')
def list_pages():
    require_editor()
    folder = pages_dir()
    if not folder.is_dir():
        abort(503, NO_WIKI)
    pages = []
    for path in sorted(folder.glob('*.md')):
        text = path.read_text(encoding='utf-8')
        slug = path.stem
        try:
            title = parse_title(text, slug)
        except Exception:
            title = slug
        pages.append({'slug': slug, 'title': title})
    return jsonify(pages=pages)


@wiki_bp.get('/api/wiki/pages/<slug>')
def get_page(slug):
    require_editor()
    slug = validate_slug(slug, allow_index=True)
    path = page_path(slug)
    if not path.is_file():
        abort(404, MISSING_PAGE)
    markdown = path.read_text(encoding='utf-8')
    return jsonify(slug=slug, markdown=markdown, title=parse_title(markdown, slug), exists=True)


@wiki_bp.put('/api/wiki/pages/<slug>')
def save_page(slug):
    require_editor()
    slug = validate_slug(slug, allow_index=True)
    body = request.get_json(silent=True) or {}
    markdown = validate_markdown(body.get('markdown'))
    summary = validate_summary(body.get('summary'))
    path = page_path(slug)
    if not path.is_file():
        abort(404, MISSING_PAGE)
    if not pages_dir().is_dir():
        abort(503, NO_WIKI)
    path.write_text(markdown, encoding='utf-8')
    rebuild_wiki()
    c = g.context
    when = datetime.now(timezone.utc).isoformat()
    who = actor_label(c)
    entry = {
        'slug': slug,
        'when': when,
        'who': who,
        'user_id': str(c.get('user_id') or ''),
        'summary': summary or 'Updated page',
        'action': 'edit',
        'bytes': len(markdown.encode('utf-8')),
    }
    append_edit_log(entry)
    commit = maybe_git_commit(slug, summary or 'Updated page', who)
    if commit:
        entry['git'] = commit
    return jsonify(ok=True, slug=slug, title=parse_title(markdown, slug), edit=entry, git=commit)


@wiki_bp.post('/api/wiki/pages')
def create_page():
    require_editor()
    body = request.get_json(silent=True) or {}
    slug = validate_slug(body.get('slug') or '', for_create=True)
    markdown = validate_markdown(body.get('markdown'))
    summary = validate_summary(body.get('summary'))
    if not pages_dir().is_dir():
        abort(503, NO_WIKI)
    path = page_path(slug)
    if path.is_file():
        abort(409, EXISTS)
    # Ensure front matter has matching slug when authors omit it
    if not markdown.lstrip().startswith('---'):
        title = slug.replace('-', ' ').title()
        markdown = (
            f'---\ntitle: {title}\nslug: {slug}\nlead: needs a short lead clause.\n'
            f'summary: Stub.\nstatus: stub\nstub: true\nnavboxes: [admin]\n'
            f'infobox_title: {title}\nicon: "📄"\ninfobox_rows: ["Status|Stub"]\ntags: []\n---\n\n'
            f'## Usage\n\n{markdown.strip()}\n'
        )
    path.write_text(markdown, encoding='utf-8')
    rebuild_wiki()
    c = g.context
    when = datetime.now(timezone.utc).isoformat()
    who = actor_label(c)
    entry = {
        'slug': slug,
        'when': when,
        'who': who,
        'user_id': str(c.get('user_id') or ''),
        'summary': summary or 'Created page',
        'action': 'create',
        'bytes': len(markdown.encode('utf-8')),
    }
    append_edit_log(entry)
    commit = maybe_git_commit(slug, summary or 'Created page', who)
    if commit:
        entry['git'] = commit
    return jsonify(ok=True, slug=slug, title=parse_title(markdown, slug), edit=entry, git=commit), 201


@wiki_bp.post('/api/wiki/preview')
def preview():
    require_editor()
    body = request.get_json(silent=True) or {}
    markdown = validate_markdown(body.get('markdown'))
    build = load_wiki_build()
    # Preview the body only (strip front matter so authors see article content)
    _, md_body = build.parse_frontmatter(markdown)
    html_out, _toc = build.md_to_html(md_body)
    return jsonify(html=html_out)


@wiki_bp.get('/api/wiki/pages/<slug>/history')
def history(slug):
    require_editor()
    slug = validate_slug(slug, allow_index=True)
    try:
        limit = min(100, max(1, int(request.args.get('limit') or 50)))
    except (TypeError, ValueError):
        limit = 50
    return jsonify(slug=slug, edits=read_history(slug, limit=limit))


def private_dir() -> Path:
    return wiki_root() / 'out-private'


def extract_article_html(full_html: str) -> str:
    """Return the inject-able article body between build.py markers."""
    build = load_wiki_build()
    start = getattr(build, 'ARTICLE_START', '<!--wiki-article-start-->')
    end = getattr(build, 'ARTICLE_END', '<!--wiki-article-end-->')
    a = full_html.find(start)
    b = full_html.find(end)
    if a >= 0 and b > a:
        return full_html[a + len(start):b].strip()
    import re
    m = re.search(r'<article class="wiki-article">(.*)</article>', full_html, re.S)
    return (m.group(1).strip() if m else full_html)


@wiki_bp.get('/api/wiki/private/search-index')
def private_search_index():
    """Full search index including admin pages. Any signed-in portal user."""
    path = private_dir() / 'search-index.json'
    if not path.is_file():
        abort(503, NO_WIKI)
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        abort(503, 'Private wiki search index is unreadable.')
    return jsonify(pages=data)


@wiki_bp.get('/api/wiki/private/<slug>')
def private_page(slug):
    """Rendered admin article HTML for any signed-in portal user."""
    slug = validate_slug(slug, allow_index=True)
    out_name = 'index.html' if slug == 'index' else f'{slug}.html'
    path = private_dir() / out_name
    if not path.is_file():
        abort(404, MISSING_PAGE)
    full = path.read_text(encoding='utf-8')
    article = extract_article_html(full)
    md_path = page_path(slug)
    if md_path.is_file():
        page_title = parse_title(md_path.read_text(encoding='utf-8'), slug)
    else:
        page_title = slug.replace('-', ' ').title()
    return jsonify(slug=slug, title=page_title, html=article)
