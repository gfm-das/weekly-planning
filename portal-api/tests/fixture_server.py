"""TEST ONLY: run portal-api against a throwaway database with fixture sign-in.

Used for visible browser tests of the planning pages. The bearer token's `sub`
is trusted without asking Supabase, so this must never point at a real
database: it refuses unless DATABASE_URL names a *test* database and
PEOPLE_TEST_THROWAWAY=yes. Not used by the Dockerfile/compose deployment.
"""
import base64
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse

sys.path.insert(0, '/app')
dbname = urlparse(os.environ.get('DATABASE_URL', '')).path.lstrip('/')
if os.environ.get('PEOPLE_TEST_THROWAWAY') != 'yes' or 'test' not in dbname:
    sys.exit('Refusing to start: fixture sign-in needs a throwaway *test* database.')

import app as api  # noqa: E402


def fixture_identity(url, headers, timeout):
    encoded = headers['Authorization'].split()[1].split('.')[1]
    return SimpleNamespace(status_code=200, json=lambda: {'id': json.loads(base64.urlsafe_b64decode(encoded + '=='))['sub']})


patch.object(api.requests, 'get', side_effect=fixture_identity).start()
api.app.run(host='0.0.0.0', port=8091, threaded=True)
