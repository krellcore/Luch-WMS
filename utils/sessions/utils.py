"""Общие утилиты для сессий."""

import json
from datetime import datetime


def load_session(cur, login, key):
    cur.execute("""
        SELECT payload FROM sessions
        WHERE login=? AND session_key=?
    """, (login, key))
    r = cur.fetchone()
    if not r:
        return None
    try:
        return json.loads(r[0] or "{}")
    except Exception:
        return {}


def save_session(cur, login, key, payload):
    txt = json.dumps(payload, ensure_ascii=False)
    cur.execute("""
        SELECT 1 FROM sessions WHERE login=? AND session_key=?
    """, (login, key))
    if cur.fetchone():
        cur.execute("""
            UPDATE sessions SET payload=?
            WHERE login=? AND session_key=?
        """, (txt, login, key))
    else:
        cur.execute("""
            INSERT INTO sessions
                (login, session_key, payload, created_at)
            VALUES (?, ?, ?, ?)
        """, (login, key, txt, datetime.now().isoformat()))


def drop_session(cur, login, key):
    cur.execute("""
        DELETE FROM sessions WHERE login=? AND session_key=?
    """, (login, key))