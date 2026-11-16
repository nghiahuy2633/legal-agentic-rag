"""Kho phiên RAM dùng chung, có khóa và giới hạn LRU."""
from collections import OrderedDict
from threading import RLock
from legal_rag.knowledge.facts import empty_facts


def new_session():
    return dict(messages=[], facts=empty_facts(), form={}, evidence={}, changes=[],
                answers={}, checks={}, report=None, facts_version=0, report_facts_version=None,
                description="", statement="", prepared=False, group_status={}, banned_status=None,
                mode="legacy")


class SessionStore:
    def __init__(self, max_sessions=200):
        if type(max_sessions) is not int or max_sessions < 1:
            raise ValueError("Giới hạn phiên phải là số nguyên dương.")
        self.max_sessions = max_sessions
        self.lock = RLock()
        self.sessions = OrderedDict()

    def get(self, session_id, create=False):
        with self.lock:
            if session_id not in self.sessions:
                if not create:
                    return None
                self.put(session_id, new_session())
            self.sessions.move_to_end(session_id)
            return self.sessions[session_id]

    def put(self, session_id, session):
        with self.lock:
            self.sessions[session_id] = session
            self.sessions.move_to_end(session_id)
            while len(self.sessions) > self.max_sessions:
                self.sessions.popitem(last=False)


def stale(session):
    return bool(session["report"] is not None and
                session["facts_version"] != session["report_facts_version"])
