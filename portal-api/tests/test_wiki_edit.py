"""Unit checks for wiki_edit.py: role gate, slug validation, preview, save+build roundtrip in a temp dir.

Run:
  python -m pytest portal-api/tests/test_wiki_edit.py
  # or without pytest:
  python portal-api/tests/test_wiki_edit.py
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('SUPABASE_URL', 'http://supabase.invalid')
os.environ.setdefault('SUPABASE_SERVICE_ROLE_KEY', 'unit-test-only')

import app as api  # noqa: E402
import roles  # noqa: E402
import wiki_edit as wiki  # noqa: E402

REPO_WIKI = Path(__file__).resolve().parents[2] / 'wiki'

CONTEXTS = {
    'ap': {'user_id': '00000000-0000-0000-0000-00000000000a', 'app_role': 'MISSIONARY', 'leadership_role': 'AP',
           'mission_id': 1, 'display_name': 'Elder AP'},
    'president': {'user_id': '00000000-0000-0000-0000-00000000000b', 'app_role': 'PRESIDENT', 'mission_id': 1,
                  'display_name': 'President'},
    'analyst': {'user_id': '00000000-0000-0000-0000-00000000000c', 'app_role': 'DATA_ADMIN', 'mission_id': 1,
                'display_name': 'Data Analyst'},
    'dl_da': {'user_id': '00000000-0000-0000-0000-0000000000d1', 'app_role': 'MISSIONARY', 'leadership_role': 'DL',
              'additional_roles': ['DATA_ADMIN'], 'mission_id': 1, 'display_name': 'DL Analyst'},
    'dl': {'user_id': '00000000-0000-0000-0000-00000000000d', 'app_role': 'MISSIONARY', 'leadership_role': 'DL',
           'mission_id': 1},
    'office': {'user_id': '00000000-0000-0000-0000-000000000010', 'app_role': 'OFFICE', 'mission_id': 1},
    'missionary': {'user_id': '00000000-0000-0000-0000-000000000011', 'app_role': 'MISSIONARY', 'mission_id': 1},
}


class SlugAndSize(unittest.TestCase):
    def test_good_slugs(self):
        for value in ('overview', 'weekly-planning', 'a', 'x1', 'editing-the-wiki'):
            self.assertEqual(wiki.validate_slug(value, allow_index=True), value)

    def test_index_edit_ok_create_refused(self):
        self.assertEqual(wiki.validate_slug('index', allow_index=True), 'index')
        with self.assertRaises(Exception):
            wiki.validate_slug('index', for_create=True)

    def test_bad_slugs_refused(self):
        from werkzeug.exceptions import HTTPException
        for value in ('', 'has space', 'under_score', '../x', 'a/b', 'edit', 'random', '-leading', 'trailing-', 'x' * 81):
            with self.assertRaises(HTTPException) as caught:
                wiki.validate_slug(value, allow_index=True)
            self.assertEqual(caught.exception.code, 400)
        # Mixed case is normalized to lowercase (still valid shape).
        self.assertEqual(wiki.validate_slug('Overview', allow_index=True), 'overview')

    def test_markdown_size_limit(self):
        from werkzeug.exceptions import HTTPException
        wiki.validate_markdown('ok')
        with self.assertRaises(HTTPException) as caught:
            wiki.validate_markdown('x' * (wiki.MARKDOWN_MAX + 1))
        self.assertEqual(caught.exception.code, 400)


class RoleHelpers(unittest.TestCase):
    def test_can_edit_wiki_matches_managers(self):
        self.assertTrue(roles.can_edit_wiki(CONTEXTS['ap']))
        self.assertTrue(roles.can_edit_wiki(CONTEXTS['president']))
        self.assertTrue(roles.can_edit_wiki(CONTEXTS['analyst']))
        self.assertTrue(roles.can_edit_wiki(CONTEXTS['dl_da']))
        self.assertFalse(roles.can_edit_wiki(CONTEXTS['dl']))
        self.assertFalse(roles.can_edit_wiki(CONTEXTS['office']))
        self.assertFalse(roles.can_edit_wiki(CONTEXTS['missionary']))
        self.assertTrue(roles.capabilities(CONTEXTS['analyst'])['wiki_edit'])
        self.assertFalse(roles.capabilities(CONTEXTS['missionary'])['wiki_edit'])


class Routes(unittest.TestCase):
    def setUp(self):
        self.client = api.app.test_client()
        self.who = 'analyst'
        self.wiki_dir = Path(tempfile.mkdtemp(prefix='gfm-wiki-test-'))
        self.addCleanup(lambda: shutil.rmtree(self.wiki_dir, ignore_errors=True))

        # Minimal wiki tree: copy build.py + assets + one page
        (self.wiki_dir / 'pages').mkdir()
        (self.wiki_dir / 'assets').mkdir()
        shutil.copy2(REPO_WIKI / 'build.py', self.wiki_dir / 'build.py')
        for name in ('wiki.css', 'wiki.js'):
            src = REPO_WIKI / 'assets' / name
            if src.is_file():
                shutil.copy2(src, self.wiki_dir / 'assets' / name)
        sample = '''---
title: Overview
slug: overview
lead: is a test page.
summary: Test.
status: full
navboxes: [using]
infobox_title: Overview
icon: "🏠"
infobox_rows: ["Who|Everyone"]
tags: [test]
---

## Usage

Hello **wiki**.

## See also

- [Main page](index.html)
'''
        (self.wiki_dir / 'pages' / 'overview.md').write_text(sample, encoding='utf-8')

        def context_for(conn, user_id):
            c = dict(CONTEXTS[self.who])
            c['is_manager'] = roles.is_manager(c)
            return c

        @contextmanager
        def fake_db():
            yield None

        self._env = patch.dict(os.environ, {'WIKI_DIR': str(self.wiki_dir), 'WIKI_GIT_COMMIT': '0'})
        self._env.start()
        self.addCleanup(self._env.stop)

        patches = [
            patch.object(api.requests, 'get',
                         return_value=SimpleNamespace(status_code=200,
                                                      json=lambda: {'id': CONTEXTS[self.who]['user_id']})),
            patch.object(api, 'context_for', side_effect=context_for),
            patch.object(api, 'db', side_effect=fake_db),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def call(self, who, method, path, body=None):
        self.who = who
        claims = base64.urlsafe_b64encode(json.dumps({'sub': CONTEXTS[who]['user_id']}).encode()).decode().rstrip('=')
        response = self.client.open(
            path, method=method, json=body,
            headers={'Authorization': f'Bearer x.{claims}.y'},
        )
        return response.status_code, response.get_json(silent=True)

    def test_role_denied_for_non_managers(self):
        for who in ('dl', 'office', 'missionary'):
            for method, path, body in (
                ('GET', '/api/wiki/pages/overview', None),
                ('POST', '/api/wiki/preview', {'markdown': '# Hi'}),
                ('PUT', '/api/wiki/pages/overview', {'markdown': '# x', 'summary': 'no'}),
                ('GET', '/api/wiki/pages/overview/history', None),
            ):
                status, answer = self.call(who, method, path, body)
                self.assertEqual(status, 403, f'{who} {method} {path}')
                self.assertIn('Data Analyst', answer['error'])

    def test_me_reports_can_edit(self):
        status, answer = self.call('missionary', 'GET', '/api/wiki/me', None)
        self.assertEqual(status, 200)
        self.assertFalse(answer['can_edit'])
        status, answer = self.call('analyst', 'GET', '/api/wiki/me', None)
        self.assertEqual(status, 200)
        self.assertTrue(answer['can_edit'])

    def test_bad_slug_on_get(self):
        status, answer = self.call('analyst', 'GET', '/api/wiki/pages/Not_Valid', None)
        self.assertEqual(status, 400)
        status, answer = self.call('analyst', 'GET', '/api/wiki/pages/edit', None)
        self.assertEqual(status, 400)

    def test_preview_uses_build_renderer(self):
        status, answer = self.call('analyst', 'POST', '/api/wiki/preview', {
            'markdown': '---\ntitle: T\nslug: t\n---\n\n## Hello\n\n**Bold** and a [link](a.html).\n'
        })
        self.assertEqual(status, 200)
        self.assertIn('<h2 id="hello">Hello</h2>', answer['html'])
        self.assertIn('<strong>Bold</strong>', answer['html'])
        self.assertIn('<a href="a.html">link</a>', answer['html'])

    def test_save_and_build_roundtrip(self):
        new_md = (self.wiki_dir / 'pages' / 'overview.md').read_text(encoding='utf-8')
        new_md = new_md.replace('Hello **wiki**.', 'Hello **updated wiki**.')
        status, answer = self.call('analyst', 'PUT', '/api/wiki/pages/overview', {
            'markdown': new_md, 'summary': 'Unit test edit',
        })
        self.assertEqual(status, 200, answer)
        self.assertTrue(answer['ok'])
        saved = (self.wiki_dir / 'pages' / 'overview.md').read_text(encoding='utf-8')
        self.assertIn('updated wiki', saved)
        out = self.wiki_dir / 'out' / 'overview.html'
        self.assertTrue(out.is_file(), 'build should write overview.html')
        html = out.read_text(encoding='utf-8')
        self.assertIn('updated wiki', html)
        self.assertIn('wiki-page-tabs', html)
        log = (self.wiki_dir / 'edit-log.jsonl').read_text(encoding='utf-8').strip().splitlines()
        self.assertEqual(len(log), 1)
        entry = json.loads(log[0])
        self.assertEqual(entry['slug'], 'overview')
        self.assertEqual(entry['summary'], 'Unit test edit')
        self.assertEqual(entry['who'], 'Data Analyst')

        status, hist = self.call('analyst', 'GET', '/api/wiki/pages/overview/history', None)
        self.assertEqual(status, 200)
        self.assertEqual(len(hist['edits']), 1)
        self.assertEqual(hist['edits'][0]['summary'], 'Unit test edit')

    def test_create_page(self):
        status, answer = self.call('ap', 'POST', '/api/wiki/pages', {
            'slug': 'unit-test-page',
            'markdown': '## Usage\n\nFresh page.\n',
            'summary': 'Created in test',
        })
        self.assertEqual(status, 201, answer)
        self.assertTrue((self.wiki_dir / 'pages' / 'unit-test-page.md').is_file())
        self.assertTrue((self.wiki_dir / 'out' / 'unit-test-page.html').is_file())



class PrivatePages(unittest.TestCase):
    def setUp(self):
        self.client = api.app.test_client()
        self.who = 'missionary'
        self.wiki_dir = Path(tempfile.mkdtemp(prefix='gfm-wiki-priv-'))
        self.addCleanup(lambda: shutil.rmtree(self.wiki_dir, ignore_errors=True))
        (self.wiki_dir / 'pages').mkdir()
        (self.wiki_dir / 'assets').mkdir()
        shutil.copy2(REPO_WIKI / 'build.py', self.wiki_dir / 'build.py')
        for name in ('wiki.css', 'wiki.js'):
            src = REPO_WIKI / 'assets' / name
            if src.is_file():
                shutil.copy2(src, self.wiki_dir / 'assets' / name)
        admin = (
            '---\n'
            'title: DBeaver access\n'
            'slug: dbeaver-access\n'
            'lead: is a test admin page.\n'
            'summary: Admin test with port 54322 and pg_dump mention.\n'
            'status: full\n'
            'navboxes: [admin]\n'
            'infobox_title: DBeaver\n'
            'icon: "DB"\n'
            'infobox_rows: ["Port|54322"]\n'
            'tags: [admin]\n'
            '---\n\n'
            '## Usage\n\n'
            'Connect on port **54322**. Operators may run `pg_dump` for backups.\n'
        )
        public = (
            '---\n'
            'title: Overview\n'
            'slug: overview\n'
            'lead: is public.\n'
            'summary: Public page.\n'
            'status: full\n'
            'navboxes: [using]\n'
            'infobox_title: Overview\n'
            'icon: "O"\n'
            'infobox_rows: ["Who|Everyone"]\n'
            'tags: [users]\n'
            '---\n\n'
            '## Usage\n\n'
            'Hello public wiki.\n'
        )
        (self.wiki_dir / 'pages' / 'dbeaver-access.md').write_text(admin, encoding='utf-8')
        (self.wiki_dir / 'pages' / 'overview.md').write_text(public, encoding='utf-8')

        def context_for(conn, user_id):
            c = dict(CONTEXTS[self.who])
            c['is_manager'] = roles.is_manager(c)
            return c

        @contextmanager
        def fake_db():
            yield None

        self._env = patch.dict(os.environ, {'WIKI_DIR': str(self.wiki_dir), 'WIKI_GIT_COMMIT': '0'})
        self._env.start()
        self.addCleanup(self._env.stop)
        patches = [
            patch.object(api.requests, 'get',
                         return_value=SimpleNamespace(status_code=200,
                                                      json=lambda: {'id': CONTEXTS[self.who]['user_id']})),
            patch.object(api, 'context_for', side_effect=context_for),
            patch.object(api, 'db', side_effect=fake_db),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        import wiki_edit as wmod
        wmod.rebuild_wiki()

    def call(self, who, method, path, body=None, auth=True):
        self.who = who
        headers = {}
        if auth:
            claims = base64.urlsafe_b64encode(json.dumps({'sub': CONTEXTS[who]['user_id']}).encode()).decode().rstrip('=')
            headers['Authorization'] = f'Bearer x.{claims}.y'
        response = self.client.open(path, method=method, json=body, headers=headers)
        return response.status_code, response.get_json(silent=True)

    def test_private_endpoint_401_without_token(self):
        status, answer = self.call('missionary', 'GET', '/api/wiki/private/dbeaver-access', auth=False)
        self.assertEqual(status, 401)

    def test_private_endpoint_ok_for_any_signed_in_user(self):
        status, answer = self.call('missionary', 'GET', '/api/wiki/private/dbeaver-access')
        self.assertEqual(status, 200, answer)
        self.assertIn('54322', answer['html'])
        self.assertIn('pg_dump', answer['html'])
        status, answer = self.call('analyst', 'GET', '/api/wiki/private/search-index')
        self.assertEqual(status, 200, answer)
        titles = [p['title'] for p in answer['pages']]
        self.assertIn('DBeaver access', titles)

    def test_public_out_excludes_admin_secrets(self):
        out = self.wiki_dir / 'out'
        blob = '\n'.join(p.read_text(encoding='utf-8') for p in out.rglob('*') if p.is_file())
        self.assertNotIn('54322', blob)
        self.assertNotIn('pg_dump', blob)
        stub = (out / 'dbeaver-access.html').read_text(encoding='utf-8')
        self.assertIn('Sign in to read this page', stub)
        priv = (self.wiki_dir / 'out-private' / 'dbeaver-access.html').read_text(encoding='utf-8')
        self.assertIn('54322', priv)

    def test_save_rebuilds_private_output(self):
        md = (self.wiki_dir / 'pages' / 'dbeaver-access.md').read_text(encoding='utf-8')
        md = md.replace('Connect on port', 'Connect again on port')
        status, answer = self.call('analyst', 'PUT', '/api/wiki/pages/dbeaver-access', {
            'markdown': md, 'summary': 'Private rebuild check',
        })
        self.assertEqual(status, 200, answer)
        priv = (self.wiki_dir / 'out-private' / 'dbeaver-access.html').read_text(encoding='utf-8')
        self.assertIn('Connect again on port', priv)
        pub = (self.wiki_dir / 'out' / 'dbeaver-access.html').read_text(encoding='utf-8')
        self.assertNotIn('Connect again on port', pub)
        self.assertIn('Sign in to read this page', pub)


if __name__ == '__main__':
    unittest.main(verbosity=2)
