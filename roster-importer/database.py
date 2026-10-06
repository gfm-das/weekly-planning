"""Opening the mission database.

Use it like this:

    with database.connect() as conn:
        with database.cursor(conn) as cur:
            cur.execute("select ...")
            rows = cur.fetchall()

When the `with database.connect()` block ends, everything is saved (commit), or nothing is saved if an error
happened (rollback), and the connection is given back.

A few pages need more control (an import writes many tables and must save all or nothing): they call
conn.commit() or conn.rollback() themselves and give the connection back with conn.close() in a `finally:` block.

Kept connections: opening a new connection takes longer than most pages need for all their questions together
(measured in round 9: 20 to 40 ms to open it, and the first question on a new connection is slow too, while the
database fills its caches for it). So a connection that is given back is not closed but kept, and lent to the next
database.connect() (at most KEEP are kept per program). Before it is lent again it is reset with DISCARD ALL, so
nothing an earlier page did stays on it, and that also shows whether it still works: one that does not, or that
waited longer than MAX_WAIT_SECONDS, is closed and a new one is opened. A connection is only ever lent to one
database.connect() at a time.
"""
import threading
import time

import psycopg2
import psycopg2.extensions
import psycopg2.extras

import settings

KEEP = 4                # connections kept per program (gunicorn runs 2 programs with 4 threads each)
MAX_WAIT_SECONDS = 300  # a kept connection that waited longer than this is closed instead of lent again

_kept = []  # the kept connections: [(database address, connection, when it was given back)], the newest last
_kept_lock = threading.Lock()


class Connection:
    """A lent database connection. It works like a psycopg2 connection (cursor(), commit(), rollback(), `with`);
    close() and the end of a `with` block give it back."""

    def __init__(self, raw, address):
        self._raw = raw
        self._address = address

    def __getattr__(self, name):
        """Everything else is the psycopg2 connection's own (cursor, commit, rollback, ...)."""
        if self._raw is None:
            raise psycopg2.InterfaceError("connection already given back")
        return getattr(self._raw, name)

    @property
    def closed(self):
        return 1 if self._raw is None else self._raw.closed

    def __enter__(self):
        self._raw.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if self._raw is not None:
                self._raw.__exit__(exc_type, exc, tb)  # commit, or rollback after an error
        finally:
            self.close()

    def close(self):
        """Gives the connection back (the first time; after that it does nothing)."""
        raw, self._raw = self._raw, None
        if raw is not None:
            give_back(raw, self._address)


def connect():
    """A connection to the mission database, only yours until you give it back (see the top of this file)."""
    address = settings.DATABASE_URL
    while True:
        kept = take_kept(address)
        if kept is None:
            return Connection(psycopg2.connect(address), address)
        raw, given_back_at = kept
        if time.monotonic() - given_back_at < MAX_WAIT_SECONDS and reset(raw):
            return Connection(raw, address)
        raw.close()  # too old or broken: try the next kept one, or open a new one


def take_kept(address):
    """(connection, when it was given back): the newest kept connection to this database, taken off the list. None
    when there is none."""
    with _kept_lock:
        for index in range(len(_kept) - 1, -1, -1):
            if _kept[index][0] == address:
                _, raw, given_back_at = _kept.pop(index)
                return raw, given_back_at
    return None


def reset(raw):
    """Makes a kept connection like new (DISCARD ALL). False when it no longer works (for example after the database
    restarted)."""
    try:
        raw.autocommit = True  # DISCARD ALL cannot run inside a transaction
        with raw.cursor() as cur:
            cur.execute("discard all")
        raw.autocommit = False
        return True
    except psycopg2.Error:
        return False


def give_back(raw, address):
    """Keeps a given-back connection for the next database.connect(), or closes it: when it is broken, when the page
    switched it to autocommit, or when KEEP connections are kept already. A transaction still open is rolled back
    first (nothing of it is saved, just as when a connection is closed)."""
    try:
        if not raw.closed and raw.status != psycopg2.extensions.STATUS_READY:
            raw.rollback()
        keep = not raw.closed and raw.status == psycopg2.extensions.STATUS_READY and not raw.autocommit
    except psycopg2.Error:
        keep = False
    if keep:
        with _kept_lock:
            if len(_kept) < KEEP:
                _kept.append((address, raw, time.monotonic()))
                return
    raw.close()


def cursor(conn):
    """A cursor whose rows are dicts, so a column is read by its name: row["display_name"]."""
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
