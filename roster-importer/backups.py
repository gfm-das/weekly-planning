"""Database backups made by DA Management before it deletes something (Delete retired, retire.py).

The step is a small hook, so it can be replaced and tested without Docker or a database:

  maker = backups.current()                 # the backup maker in use (PgDumpBackup unless a test or a setting changed it)
  backup = maker.make("area-bockenheim")    # makes the file; raises BackupError when it did not work
  backup.name                               # gfm-before-delete-area-bockenheim-20261012-231500.dump (named in the batch)

PgDumpBackup runs the command of settings.BACKUP_COMMAND (default: pg_dump, custom format) with {file} replaced by the
file to write in settings.BACKUP_DIR, then checks the file: it exists, it is not empty, and (settings.BACKUP_VERIFY_COMMAND,
default pg_restore --list {file}) PostgreSQL can read its table of contents. The connection comes from DATABASE_URL and
goes to the command through the PG* environment variables, never through its arguments, so the password does not show in a
process list. The command is run without a shell. Anything that does not work raises BackupError and the caller stops
before it changes anything.

To use another way (for example a script that makes the dump on the database computer), set BACKUP_COMMAND to that
program with {file} where the file name goes; it must write a PostgreSQL custom-format dump to that file.
"""
import os
import re
import shlex
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

import settings


class BackupError(RuntimeError):
    """The backup was not made (or could not be checked). The message is plain words for the manager."""


class Backup:
    """A finished backup: its file name (shown in Import history), where it is, and how big it is."""

    def __init__(self, name, path, size, checked):
        self.name, self.path, self.size, self.checked = name, str(path), size, checked

    def as_summary(self):
        """The values written into the batch's summary."""
        return {"backup": self.name, "backup_size_bytes": self.size, "backup_checked": self.checked}


def backup_name(label, when=None):
    """gfm-before-delete-<label>-<yyyymmdd-HHMMSS>.dump with a label made of small letters, digits and dashes."""
    when = when or datetime.now()
    safe = re.sub(r"[^a-z0-9]+", "-", str(label or "").lower()).strip("-")[:40] or "item"
    return f"gfm-before-delete-{safe}-{when:%Y%m%d-%H%M%S}.dump"


def connection_environment(database_url):
    """The PG* environment variables for a postgresql:// address (so no password is put into a command line)."""
    parts = urlsplit(database_url)
    if parts.scheme not in ("postgresql", "postgres") or not parts.hostname:
        raise BackupError("The database address is not a PostgreSQL address.")
    environment = {"PGHOST": parts.hostname, "PGPORT": str(parts.port or 5432),
                   "PGDATABASE": unquote(parts.path.lstrip("/")) or "postgres"}
    if parts.username:
        environment["PGUSER"] = unquote(parts.username)
    if parts.password:
        environment["PGPASSWORD"] = unquote(parts.password)
    return environment


def command_words(template, file):
    """The command as a list of words, with {file} replaced. No shell is involved, so nothing in a file name can run."""
    words = shlex.split(template)
    if not words or not any("{file}" in word for word in words):
        raise BackupError("The backup command must contain {file}.")
    return [word.replace("{file}", str(file)) for word in words]


class PgDumpBackup:
    """Makes a backup with pg_dump (or the program BACKUP_COMMAND names). run: subprocess.run, replaceable in tests."""

    def __init__(self, directory=None, command=None, verify_command=None, database_url=None, run=subprocess.run,
                 clock=datetime.now, timeout=1800):
        self.directory = Path(directory or settings.BACKUP_DIR)
        self.command = command or settings.BACKUP_COMMAND
        self.verify_command = settings.BACKUP_VERIFY_COMMAND if verify_command is None else verify_command
        self.database_url = database_url or settings.DATABASE_URL
        self.run, self.clock, self.timeout = run, clock, timeout

    def make(self, label):
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise BackupError(f"The backups folder cannot be used ({error.__class__.__name__}).") from None
        name = backup_name(label, self.clock())
        path = self.directory / name
        environment = {**os.environ, **connection_environment(self.database_url)}
        self.execute(command_words(self.command, path), environment, "The backup could not be made")
        if not path.is_file() or path.stat().st_size == 0:
            path.unlink(missing_ok=True)
            raise BackupError("The backup command finished but wrote no file.")
        checked = False
        if self.verify_command.strip():
            self.execute(command_words(self.verify_command, path), environment, "The backup could not be read back",
                         quiet=True)
            checked = True
        return Backup(name, path, path.stat().st_size, checked)

    def execute(self, words, environment, failure, quiet=False):
        """Runs one command; raises BackupError with the program's own last line of complaint (never the environment)."""
        try:
            done = self.run(words, env=environment, capture_output=True, text=True, timeout=self.timeout, check=False)
        except FileNotFoundError:
            raise BackupError(f"{failure}: the program {words[0]} is not installed here.") from None
        except subprocess.TimeoutExpired:
            raise BackupError(f"{failure}: it took too long.") from None
        except OSError as error:
            raise BackupError(f"{failure}: {error.__class__.__name__}.") from None
        if done.returncode != 0:
            lines = [line for line in (done.stderr or "").strip().splitlines() if line.strip()]
            raise BackupError(f"{failure}: {scrub(lines[-1], environment) if lines else 'exit code ' + str(done.returncode)}")


def scrub(line, environment):
    """A line of a program's complaint without the password, in case the program repeated it."""
    password = environment.get("PGPASSWORD")
    return line.replace(password, "***")[:300] if password else line[:300]


_maker = None


def current():
    """The backup maker in use: a PgDumpBackup made from the settings, unless set_maker() put another one in its place."""
    global _maker
    if _maker is None:
        _maker = PgDumpBackup()
    return _maker


def set_maker(maker):
    """Replaces the backup maker (the tests use a fake one); set_maker(None) goes back to the settings."""
    global _maker
    _maker = maker
