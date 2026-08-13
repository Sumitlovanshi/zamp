"""Ephemeral in-memory store: privacy as an architecture, not a policy.

Nothing a visitor uploads ever touches disk, a database, or object
storage.  A session is a random cookie mapped to an in-process dict;
documents expire with the session TTL and disappear on process restart.
The moment we never store a stranger's receipt, we never become a
custodian of it — the cheapest correct answer to running a public
upload endpoint.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field

SESSION_TTL_S = 60 * 60  # one hour, stated in the UI
MAX_DOCS_PER_SESSION = 40
MAX_SESSIONS = 500  # global memory guard; oldest evicted first


@dataclass
class DocRecord:
    doc_id: str
    name: str
    ledger: dict
    certificate: dict
    image: bytes
    media_type: str
    created: float = field(default_factory=time.time)


@dataclass
class Session:
    sid: str
    docs: dict[str, DocRecord] = field(default_factory=dict)
    created: float = field(default_factory=time.time)
    touched: float = field(default_factory=time.time)


class Store:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def _sweep(self) -> None:
        now = time.time()
        dead = [k for k, s in self._sessions.items() if now - s.touched > SESSION_TTL_S]
        for k in dead:
            del self._sessions[k]
        while len(self._sessions) > MAX_SESSIONS:
            oldest = min(self._sessions.values(), key=lambda s: s.touched)
            del self._sessions[oldest.sid]

    def session(self, sid: str | None) -> Session:
        self._sweep()
        if sid and sid in self._sessions:
            s = self._sessions[sid]
            s.touched = time.time()
            return s
        # NOT persisted until it owns a document (see add) — otherwise a
        # cookieless GET flood would churn the session cap and evict real
        # users' documents long before their advertised TTL
        return Session(sid=secrets.token_urlsafe(16))

    def peek(self, sid: str | None) -> Session | None:
        """Read-only lookup: no session minting, no touch, no sweep."""
        return self._sessions.get(sid) if sid else None

    def add(self, s: Session, rec: DocRecord) -> None:
        if len(s.docs) >= MAX_DOCS_PER_SESSION:
            oldest = min(s.docs.values(), key=lambda d: d.created)
            del s.docs[oldest.doc_id]
        s.docs[rec.doc_id] = rec
        s.touched = time.time()
        self._sessions[s.sid] = s  # a session occupies a cap slot only once it holds data

    def stats(self) -> dict:
        self._sweep()
        return {
            "sessions": len(self._sessions),
            "documents": sum(len(s.docs) for s in self._sessions.values()),
            "ttl_seconds": SESSION_TTL_S,
        }


STORE = Store()
