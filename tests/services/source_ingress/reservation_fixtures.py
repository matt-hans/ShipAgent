"""Disposable SQLite exclusion, never a production authentication adapter."""

import math
import sqlite3
import time
from contextlib import closing
from urllib.parse import quote

from src.services.source_ingress.reservation_contracts import ResolvedSourceAuthority


class SQLiteSourceAuthority:
    def __init__(self, path, *, expires_at=None, create=True):
        self.path = path
        self.events = []
        if not create:
            assert path.is_file()
            return
        with closing(sqlite3.connect(path)) as db:
            db.execute("""CREATE TABLE principals (
                principal TEXT PRIMARY KEY, account TEXT, connection TEXT,
                epoch TEXT, target TEXT, fingerprint TEXT, purpose TEXT,
                expires INTEGER, enabled INTEGER)""")
            db.execute(
                "INSERT INTO principals VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    "operator-a",
                    "account-a",
                    "connection-a",
                    "epoch-a",
                    "target-a",
                    "fingerprint-a",
                    "operator_source_setup",
                    expires_at if expires_at is not None else int(time.time()) + 300,
                    1,
                ),
            )
            db.commit()
        path.chmod(0o600)

    def mutate(self, **changes):
        allowed = {
            "account",
            "connection",
            "epoch",
            "target",
            "fingerprint",
            "purpose",
            "expires",
            "enabled",
        }
        assert changes.keys() <= allowed
        with closing(sqlite3.connect(self.path, timeout=2, isolation_level=None)) as db:
            db.execute("BEGIN IMMEDIATE")
            for name, value in changes.items():
                db.execute(f"UPDATE principals SET {name}=?", (value,))
            db.commit()

    def fence(
        self, context, *, provider_connection_id, purpose, monotonic=time.monotonic
    ):
        return SQLiteAuthorityFence(
            self, context, provider_connection_id, purpose, monotonic
        )


class SQLiteAuthorityFence:
    def __init__(self, authority, context, connection, purpose, monotonic):
        self.authority = authority
        self.context = context
        self.connection = connection
        self.purpose = purpose
        self.monotonic = monotonic
        self.db = None
        self.deadline = 0.0
        self.attempted = False
        self.active = False
        self.retired = False
        self.rolled_back = False
        self.resolved = None

    def _remaining(self):
        now = self.monotonic()
        if (
            type(now) not in (int, float)
            or not math.isfinite(now)
            or now >= self.deadline
        ):
            raise RuntimeError("Synthetic authority is unavailable.")
        return self.deadline - now

    def _execute(self, sql, parameters=()):
        self.db.execute(f"PRAGMA busy_timeout={int(self._remaining() * 1000)}")
        result = self.db.execute(sql, parameters)
        self._remaining()
        return result

    def acquire(self, *, deadline):
        if self.attempted or self.retired:
            raise RuntimeError("Synthetic authority is unavailable.")
        self.attempted = True
        self.deadline = deadline
        self.db = sqlite3.connect(
            f"file:{quote(str(self.authority.path))}?mode=rw",
            uri=True,
            timeout=self._remaining(),
            isolation_level=None,
        )
        self._execute("BEGIN IMMEDIATE")
        self.active = True
        self.authority.events.append("acquired")

    def resolve(self):
        if not self.active or self.retired or not self.db.in_transaction:
            raise RuntimeError("Synthetic authority is unavailable.")
        row = self._execute(
            """SELECT account,connection,epoch,target,fingerprint,purpose,expires
            FROM principals WHERE principal=? AND connection=? AND purpose=? AND enabled=1""",
            (self.context.principal_reference, self.connection, self.purpose),
        ).fetchone()
        if row is None:
            raise RuntimeError("Synthetic authority is unavailable.")
        value = ResolvedSourceAuthority(*row)
        if self.resolved is not None and self.resolved != value:
            raise RuntimeError("Synthetic authority is unavailable.")
        self.resolved = value
        self.authority.events.append("resolved")
        return value

    def require_current(self, *, now):
        value = self.resolve()
        if (
            type(now) not in (int, float)
            or not math.isfinite(now)
            or now >= value.authorization_expires_at
        ):
            raise RuntimeError("Synthetic authority is unavailable.")

    def retire(self):
        self.active = False
        if self.retired:
            return
        if self.db is not None:
            if not self.rolled_back:
                self.db.rollback()
                self.rolled_back = True
            self.db.close()
            self.db = None
        self.retired = True
        self.authority.events.append("retired")
