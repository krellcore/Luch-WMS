"""HTTP/HTTPS-сервер для клиентов."""

import base64
import json
import os
import socket
import sqlite3
import threading
import time
import traceback
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ui_config import get_versioned
from view_builder import (
    build_step_view, build_container_contents_view,
)
from view_protocol import PROTOCOL_VERSION
from capabilities import (
    registry as cap_registry, ClientCapabilities,
    is_protocol_supported,
)
from plugin_hooks import registry as hook_registry
from db import (
    expire_reservations, refresh_task_reservations,
    release_task, RESERVE_ACTIVE_MINUTES,
    hash_password, verify_password, needs_rehash,
    create_auth_session, verify_auth_session,
    invalidate_session_by_token,
)
from tasks import (
    get_handler, has_handler, list_task_types,
)
from roles import task_types_for_roles
from i18n import (
    set_locale, tr, current_locale, load_locale_for_manager,
    save_locale_for_manager,
)
from tls import (
    make_server_context, has_cert, cert_fingerprint,
    tls_dir as tls_cert_dir,
)

from mgmt_protocol import (
    make_mgmt_document, mgmt_page, mgmt_sidebar, text, heading,
    card, spacer, caption,
)
from mgmt_view_builder import (
    pages_for_role, build_sidebar, placeholder_view,
    build_error_document,
)
from mgmt_pages import (
    get_builder as _mgmt_get_builder,
    get_handler as _mgmt_get_handler,
)
from menu import (
    has as _menu_has, get as _menu_get, build_view as _menu_build_view,
)

_lock = threading.Lock()


# ================================================================
# Метрики сервера
# ================================================================

class _ServerStats:
    def __init__(self):
        self._lock = threading.Lock()
        self.started_at = time.time()
        self.requests_total = 0
        self.bytes_in_total = 0
        self.bytes_out_total = 0

        self._per_sec = deque(maxlen=3600)
        self._cur_sec_ts = int(self.started_at)
        self._cur_sec_req = 0
        self._cur_sec_in = 0
        self._cur_sec_out = 0

        self._per_min = deque(maxlen=1440)
        self._cur_min_ts = int(self.started_at) // 60
        self._cur_min_req = 0
        self._cur_min_in = 0
        self._cur_min_out = 0

        self.clients = {}

    def register_request(self, bytes_in=0, bytes_out=0, client=None):
        with self._lock:
            now = time.time()
            now_sec = int(now)
            now_min = now_sec // 60

            if now_sec != self._cur_sec_ts:
                self._per_sec.append(
                    (self._cur_sec_ts, self._cur_sec_req,
                     self._cur_sec_in, self._cur_sec_out))
                self._cur_sec_ts = now_sec
                self._cur_sec_req = 0
                self._cur_sec_in = 0
                self._cur_sec_out = 0

            if now_min != self._cur_min_ts:
                self._per_min.append(
                    (self._cur_min_ts, self._cur_min_req,
                     self._cur_min_in, self._cur_min_out))
                self._cur_min_ts = now_min
                self._cur_min_req = 0
                self._cur_min_in = 0
                self._cur_min_out = 0

            self._cur_sec_req += 1
            self._cur_sec_in += int(bytes_in or 0)
            self._cur_sec_out += int(bytes_out or 0)
            self._cur_min_req += 1
            self._cur_min_in += int(bytes_in or 0)
            self._cur_min_out += int(bytes_out or 0)
            self.requests_total += 1
            self.bytes_in_total += int(bytes_in or 0)
            self.bytes_out_total += int(bytes_out or 0)

            if client:
                login, kind, device, ip = client
                self.clients[login] = {
                    "kind": kind,
                    "device": device or "unknown",
                    "ip": ip or "",
                    "last_seen": now,
                }

    def snapshot(self):
        with self._lock:
            now = time.time()
            sec_req = self._cur_sec_req
            sec_in = self._cur_sec_in
            sec_out = self._cur_sec_out

            hour_events = list(self._per_sec)
            hour_n = max(1, len(hour_events))
            hour_req = sum(e[1] for e in hour_events)
            hour_in = sum(e[2] for e in hour_events)
            hour_out = sum(e[3] for e in hour_events)
            hour_in_avg = int(hour_in / hour_n) if hour_n else 0
            hour_out_avg = int(hour_out / hour_n) if hour_n else 0

            day_events = list(self._per_min)
            day_n = max(1, len(day_events))
            day_req = sum(e[1] for e in day_events)
            day_in = sum(e[2] for e in day_events)
            day_out = sum(e[3] for e in day_events)
            day_in_avg = int(day_in / day_n) if day_n else 0
            day_out_avg = int(day_out / day_n) if day_n else 0

            admin_total = 0
            workers_total = 0
            by_device = {}
            for login, info in self.clients.items():
                if now - info["last_seen"] > 60:
                    continue
                if info["kind"] == "admin":
                    admin_total += 1
                else:
                    workers_total += 1
                dev = info.get("device") or "unknown"
                by_device[dev] = by_device.get(dev, 0) + 1

            return {
                "ok": True,
                "uptime": int(now - self.started_at),
                "requests": {
                    "total": self.requests_total,
                    "per_sec": sec_req,
                    "per_hour": hour_req,
                    "per_day": day_req,
                },
                "traffic": {
                    "in_total": self.bytes_in_total,
                    "out_total": self.bytes_out_total,
                    "in_per_sec": sec_in,
                    "out_per_sec": sec_out,
                    "in_per_hour": hour_in,
                    "out_per_hour": hour_out,
                    "in_per_day": day_in,
                    "out_per_day": day_out,
                    "in_per_sec_avg_hour": hour_in_avg,
                    "out_per_sec_avg_hour": hour_out_avg,
                    "in_per_min_avg_day": day_in_avg,
                    "out_per_min_avg_day": day_out_avg,
                },
                "clients": {
                    "admin_total": admin_total,
                    "workers_total": workers_total,
                    "by_device": by_device,
                },
                "load": {
                    "threads": threading.active_count(),
                },
            }


_stats = _ServerStats()


# ================================================================
# Rate limit для логинов
# ================================================================

class _RateLimiter:
    def __init__(self, max_attempts=10, window=300, block=900):
        self._lock = threading.Lock()
        self._attempts = {}
        self._blocks = {}
        self.max = max_attempts
        self.window = window
        self.block = block

    def check(self, ip, login):
        """Возвращает (ok: bool, wait_seconds: int)."""
        key = (ip or "", (login or "").lower())
        now = time.time()
        with self._lock:
            until = self._blocks.get(key)
            if until and until > now:
                return False, int(until - now)
            dq = self._attempts.get(key)
            if dq:
                while dq and now - dq[0] > self.window:
                    dq.popleft()
                if len(dq) >= self.max:
                    self._blocks[key] = now + self.block
                    self._attempts[key] = deque()
                    return False, int(self.block)
            return True, 0

    def hit(self, ip, login):
        key = (ip or "", (login or "").lower())
        with self._lock:
            dq = self._attempts.get(key)
            if dq is None:
                dq = deque()
                self._attempts[key] = dq
            dq.append(time.time())

    def reset(self, ip, login):
        key = (ip or "", (login or "").lower())
        with self._lock:
            self._attempts.pop(key, None)
            self._blocks.pop(key, None)


_login_limiter = _RateLimiter()
_MAX_BODY = 2 * 1024 * 1024  # 2 MB


# ================================================================

def _make_item_barcode_png(code, width=600, height=220):
    try:
        import sys
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from barcodes import make_label_image
        return make_label_image("АРТИКУЛ", code, code,
                                width=width, height=height)
    except Exception as e:
        print("_make_item_barcode_png:", e)
        return None


def _all_ipv4():
    ips = []
    seen = set()

    def _add(ip):
        if not ip:
            return
        ip = str(ip).strip()
        if (not ip or ip == "127.0.0.1"
                or ip.startswith("169.254.")
                or ip.startswith("0.")
                or ip in seen):
            return
        seen.add(ip)
        ips.append(ip)

    targets = [
        ("8.8.8.8", 80), ("1.1.1.1", 80),
        ("192.168.1.1", 80), ("192.168.0.1", 80),
        ("10.0.0.1", 80), ("172.16.0.1", 80),
    ]
    for target in targets:
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.3)
            s.connect(target)
            _add(s.getsockname()[0])
        except Exception:
            pass
        finally:
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass
        if ips:
            break

    try:
        hostname = socket.gethostname()
        if hostname:
            for info in socket.getaddrinfo(hostname, None,
                                            socket.AF_INET):
                _add(info[4][0])
    except Exception:
        pass

    try:
        hostname = socket.gethostname()
        if hostname:
            _, _, addrs = socket.gethostbyname_ex(hostname)
            for ip in addrs:
                _add(ip)
    except Exception:
        pass

    return ips


_ipv4_cache = {"ips": [], "ts": 0.0}


def _all_ipv4_cached():
    now = time.time()
    if now - _ipv4_cache["ts"] < 60:
        return list(_ipv4_cache["ips"])
    ips = _all_ipv4()
    _ipv4_cache["ips"] = ips
    _ipv4_cache["ts"] = now
    return list(ips)


def _translate_notification(row):
    payload_raw = row.get("payload") or ""
    if not payload_raw:
        return row
    try:
        payload = json.loads(payload_raw) if isinstance(
            payload_raw, str) else payload_raw
    except Exception:
        return row
    if not isinstance(payload, dict):
        return row

    key = payload.get("key")
    params = payload.get("params") or {}

    if key:
        try:
            new_msg = tr(key, **params) if params else tr(key)
        except Exception as e:
            print("_translate_notification:", e)
            new_msg = None
        if new_msg and new_msg != key:
            row["message"] = new_msg

    msg = row.get("message") or ""
    if "{" in msg and isinstance(params, dict) and params:
        for k, v in params.items():
            msg = msg.replace("{" + str(k) + "}",
                              "" if v is None else str(v))
        row["message"] = msg
    return row


def _valid_mgr_login(login: str) -> bool:
    if not login:
        return False
    for ch in login:
        if not ((ch.isascii() and ch.isalnum()) or ch in "_."):
            return False
    return True


def _check_task_assignee(task, login):
    assignee = (task.get("assignee_login") or "").strip()
    if not assignee:
        return tr("task.err.not_assigned",
                  "Задание не назначено исполнителю.")
    if assignee != login:
        return tr("task.err.foreign_task",
                  "Задание назначено другому исполнителю "
                  "({login}).", login=assignee)
    return None


def _client_ip(handler):
    try:
        if handler.client_address:
            return str(handler.client_address[0])
    except Exception:
        pass
    return ""


class Handler(BaseHTTPRequestHandler):
    db_path = None
    timeout = 15

    def _photo_b64(self, cur, item_code):
        if not item_code:
            return None
        try:
            cur.execute("SELECT mime, data FROM photos "
                        "WHERE item_code=?", (item_code,))
            r = cur.fetchone()
        except sqlite3.Error:
            return None
        if not r or not r[1]:
            return None
        mime = r[0] or "image/png"
        try:
            raw = bytes(r[1])
            return (f"data:{mime};base64,"
                    + base64.b64encode(raw).decode("ascii"))
        except Exception:
            return None

    def _send(self, code, payload):
        if isinstance(payload, dict) and "locale" not in payload:
            try:
                payload["locale"] = current_locale()
            except Exception:
                pass
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._req_out = getattr(self, "_req_out", 0) + len(body)
        self.send_response(code)
        self.send_header("Content-Type",
                         "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_png(self, data):
        self._req_out = getattr(self, "_req_out", 0) + len(data)
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args, **kwargs):
        pass

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except Exception:
            self._req_in = 0
            return None
        if length < 0 or length > _MAX_BODY:
            self._req_in = 0
            return None
        try:
            raw = self.rfile.read(length) if length else b"{}"
            self._req_in = length
            return json.loads(raw.decode("utf-8"))
        except Exception:
            self._req_in = 0
            return None

    def _default_locale(self):
        try:
            conn = self._conn()
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT value FROM settings WHERE key='locale'")
                r = cur.fetchone()
                return (r["value"] if r else "ru") or "ru"
            finally:
                conn.close()
        except Exception:
            return "ru"

    # ---------------- Аутентификация ----------------

    def _auth(self, data):
        login = (data.get("login") or "").strip()
        secret = data.get("secret") or ""
        if not login or not secret:
            return None
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT login, pass_hash FROM employees "
                        "WHERE login=?", (login,))
            r = cur.fetchone()
        finally:
            conn.close()
        if not r or not verify_password(secret, r["pass_hash"] or ""):
            return None
        return login

    def _mgmt_auth(self, data):
        login = (data.get("login") or "").strip()
        secret = data.get("secret") or ""
        if not login or not secret:
            return None
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT login, pass_hash FROM managers WHERE login=?",
                (login,))
            r = cur.fetchone()
        finally:
            conn.close()
        if not r or not verify_password(secret, r["pass_hash"] or ""):
            return None
        return login

    def _auth_token(self, data):
        token = (data.get("token") or "").strip()
        if not token:
            return None
        sess = verify_auth_session(self.db_path, token)
        if not sess or sess.get("kind") != "employee":
            return None
        return sess["login"]

    def _mgmt_auth_token(self, data):
        token = (data.get("token") or "").strip()
        if not token:
            return None
        sess = verify_auth_session(self.db_path, token)
        if not sess or sess.get("kind") != "manager":
            return None
        return {"login": sess["login"],
                "role": sess.get("role") or "operator"}

    def _guess_client(self, parts, data):
        if not parts:
            return None
        token = (data.get("token") or "").strip()
        if not token:
            return None
        sess = verify_auth_session(self.db_path, token)
        if not sess:
            return None
        login = sess["login"]
        top = parts[0]
        if top == "mgmt":
            kind = "admin"
        elif top in ("tasks", "sessions", "notifications",
                     "employees", "capabilities", "menu"):
            kind = "worker"
        else:
            return None
        if kind == "admin":
            device = "pc"
        else:
            d = (data.get("device") or "").strip()
            if d:
                device = d
            else:
                caps = cap_registry.get(login)
                device = getattr(caps, "device", "") or "unknown"
        ip = _client_ip(self)
        return (login, kind, device, ip)

    # ================================================================
    # mgmt
    # ================================================================

    def _mgmt(self, parts, data):
        if len(parts) == 2 and parts[1] == "login":
            return self._mgmt_login(data)
        if len(parts) == 2 and parts[1] == "me":
            return self._mgmt_me(data)
        if len(parts) == 2 and parts[1] == "logout":
            return self._mgmt_logout(data)
        if len(parts) == 2 and parts[1] == "pages":
            return self._mgmt_pages(data)
        if len(parts) == 3 and parts[1] == "page":
            return self._mgmt_page_view(parts[2], data)
        if len(parts) == 4 and parts[1] == "page" \
                and parts[3] == "action":
            return self._mgmt_page_action(parts[2], data)
        self._send(404, {"ok": False,
                         "error": "unknown mgmt route"})

    def _mgmt_login(self, data):
        ip = _client_ip(self)
        login_v = (data.get("login") or "").strip()

        ok, wait = _login_limiter.check(ip, login_v)
        if not ok:
            return self._send(200, {
                "ok": False,
                "error": f"too many attempts, wait {wait}s",
            })

        login = self._mgmt_auth(data)
        if not login:
            _login_limiter.hit(ip, login_v)
            return self._send(200, {
                "ok": False,
                "error": "invalid credentials",
            })
        _login_limiter.reset(ip, login_v)

        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT role, pass_hash FROM managers WHERE login=?",
                (login,))
            r = cur.fetchone()
            if r and needs_rehash(r["pass_hash"] or ""):
                cur.execute(
                    "UPDATE managers SET pass_hash=? WHERE login=?",
                    (hash_password(data.get("secret") or ""), login))
                conn.commit()
        finally:
            conn.close()
        role = (r["role"] if r else "operator") or "operator"

        ctx = _get_plugin_context()
        try:
            allowed = hook_registry.call_filter(
                "on_mgmt_login", True,
                login=login, role=role, context=ctx)
        except Exception:
            traceback.print_exc()
            allowed = True
        if allowed is not True:
            if isinstance(allowed, dict):
                err = allowed.get("error") or "login denied"
            elif allowed is False:
                err = "login denied"
            elif isinstance(allowed, str):
                err = allowed
            else:
                err = "login denied"
            return self._send(200, {"ok": False, "error": err})

        wh_name = os.path.basename(
            os.path.dirname(os.path.abspath(self.db_path)))

        req_locale = data.get("locale")
        user_locale = load_locale_for_manager(self.db_path, login)
        if req_locale in ("ru", "en") and req_locale != user_locale:
            save_locale_for_manager(self.db_path, login, req_locale)
            user_locale = req_locale
        effective_locale = user_locale or self._default_locale()

        token = create_auth_session(
            self.db_path, login, "manager", role=role, ip=ip)

        self._send(200, {
            "ok": True,
            "token": token,
            "login": login,
            "role": role,
            "warehouse": wh_name,
            "protocol": PROTOCOL_VERSION,
            "locale": effective_locale,
            "sidebar": build_sidebar(
                role, extra_pages=_mgmt_extra_pages()),
        })

    def _mgmt_me(self, data):
        m = self._mgmt_auth_token(data)
        if not m:
            return self._send(200, {
                "ok": False, "error": "unauthorized"})
        wh_name = os.path.basename(
            os.path.dirname(os.path.abspath(self.db_path)))
        user_locale = load_locale_for_manager(
            self.db_path, m["login"])
        effective_locale = user_locale or self._default_locale()
        self._send(200, {
            "ok": True,
            "login": m["login"],
            "role": m["role"],
            "warehouse": wh_name,
            "locale": effective_locale,
        })

    def _mgmt_logout(self, data):
        token = (data.get("token") or "").strip()
        if token:
            try:
                invalidate_session_by_token(self.db_path, token)
            except Exception:
                pass
        self._send(200, {"ok": True})

    def _mgmt_pages(self, data):
        m = self._mgmt_auth_token(data)
        if not m:
            return self._send(401, {"ok": False,
                                    "error": "unauthorized"})
        self._send(200, {
            "ok": True,
            "role": m["role"],
            "pages": pages_for_role(
                m["role"], extra_pages=_mgmt_extra_pages()),
        })

    def _mgmt_page_view(self, key, data):
        m = self._mgmt_auth_token(data)
        if not m:
            return self._send(401, {"ok": False,
                                    "error": "unauthorized"})
        available_keys = {p["key"]
                          for p in pages_for_role(
                              m["role"],
                              extra_pages=_mgmt_extra_pages())}
        if key not in available_keys:
            return self._send(200, {
                "ok": False,
                "error": "forbidden",
            })
        ctx = _get_plugin_context(_plugin_name_from_key(key))
        doc = self._mgmt_build_page(key, m["login"], m["role"], ctx)
        try:
            doc = hook_registry.call_filter(
                "on_mgmt_page_build", doc,
                page_key=key, login=m["login"], role=m["role"],
                context=ctx)
        except Exception:
            traceback.print_exc()
        self._send(200, {"ok": True, "view": doc})

    def _mgmt_page_action(self, key, data):
        m = self._mgmt_auth_token(data)
        if not m:
            return self._send(401, {"ok": False,
                                    "error": "unauthorized"})
        available_keys = {p["key"]
                          for p in pages_for_role(
                              m["role"],
                              extra_pages=_mgmt_extra_pages())}
        if key not in available_keys:
            return self._send(200, {
                "ok": False,
                "error": "forbidden",
            })

        action = (data.get("action") or "tap")
        action_id = data.get("id")
        value = data.get("value")
        values = data.get("values") or {}
        ctx = _get_plugin_context(_plugin_name_from_key(key))

        try:
            handled = hook_registry.call_chain(
                "on_mgmt_action",
                page_key=key, action=action, action_id=action_id,
                value=value, values=values,
                login=m["login"], role=m["role"], context=ctx)
        except Exception:
            traceback.print_exc()
            handled = None

        if handled and isinstance(handled, dict) \
                and handled.get("handled"):
            doc = self._mgmt_build_page(
                key, m["login"], m["role"], ctx)
            try:
                doc = hook_registry.call_filter(
                    "on_mgmt_page_build", doc,
                    page_key=key, login=m["login"],
                    role=m["role"], context=ctx)
            except Exception:
                traceback.print_exc()
            return self._send(200, {
                "ok": True,
                "message": handled.get("message", ""),
                "view": doc,
            })

        page_handler = _mgmt_get_handler(key)
        if page_handler:
            try:
                result = page_handler(
                    action=action, action_id=action_id,
                    value=value, values=values,
                    login=m["login"], role=m["role"],
                    context=ctx)
            except Exception as e:
                traceback.print_exc()
                return self._send(500, {
                    "ok": False, "error": str(e)})
            if not isinstance(result, dict):
                result = {"ok": True}
            if not result.get("ok"):
                return self._send(200, result)
            doc = result.get("view")
            if not doc:
                doc = self._mgmt_build_page(
                    key, m["login"], m["role"], ctx)
            try:
                doc = hook_registry.call_filter(
                    "on_mgmt_page_build", doc,
                    page_key=key, login=m["login"],
                    role=m["role"], context=ctx)
            except Exception:
                traceback.print_exc()
            return self._send(200, {
                "ok": True,
                "message": result.get("message", ""),
                "view": doc,
            })

        if key.startswith("plugin:") and _host_ref is not None:
            pages = getattr(_host_ref, "_mgmt_plugin_pages", {}) or {}
            meta = pages.get(key)
            if meta and meta.get("handler"):
                try:
                    result = meta["handler"](
                        action=action, action_id=action_id,
                        value=value, values=values,
                        login=m["login"], role=m["role"],
                        context=ctx)
                except Exception as e:
                    traceback.print_exc()
                    return self._send(500, {
                        "ok": False, "error": str(e)})
                if not isinstance(result, dict):
                    result = {"ok": True}
                if not result.get("ok"):
                    return self._send(200, result)
                doc = result.get("view")
                if not doc:
                    doc = self._mgmt_build_page(
                        key, m["login"], m["role"], ctx)
                try:
                    doc = hook_registry.call_filter(
                        "on_mgmt_page_build", doc,
                        page_key=key, login=m["login"],
                        role=m["role"], context=ctx)
                except Exception:
                    traceback.print_exc()
                return self._send(200, {
                    "ok": True,
                    "message": result.get("message", ""),
                    "view": doc,
                })

        self._send(200, {
            "ok": False,
            "error": ("действия раздела «{key}» пока "
                      "не реализованы").format(key=key),
        })

    def _mgmt_build_page(self, key, login, role, ctx):
        builder = _mgmt_get_builder(key)
        if builder is not None:
            try:
                return builder(login=login, role=role, context=ctx)
            except Exception as e:
                traceback.print_exc()
                return build_error_document(
                    key, role, str(e),
                    extra_pages=_mgmt_extra_pages())

        if key.startswith("plugin:") and _host_ref is not None:
            pages = getattr(_host_ref, "_mgmt_plugin_pages", {}) or {}
            meta = pages.get(key)
            if meta and meta.get("builder"):
                try:
                    page = meta["builder"](
                        login=login, role=role, context=ctx)
                except Exception as e:
                    traceback.print_exc()
                    return build_error_document(
                        key, role, str(e),
                        extra_pages=_mgmt_extra_pages())
                sidebar = build_sidebar(
                    role, extra_pages=_mgmt_extra_pages())
                return make_mgmt_document(
                    page, sidebar=sidebar,
                    extra={"role": role, "plugin": True})

        return placeholder_view(
            key, role, extra_pages=_mgmt_extra_pages())

    # ================================================================
    # menu (тонкие клиенты)
    # ================================================================

    def _menu(self, parts, login, data):
        if len(parts) == 3 and parts[2] == "view":
            return self._menu_view(parts[1], login, data)
        self._send(404, {"ok": False, "error": "unknown menu route"})

    def _menu_view(self, item_id, login, data):
        if not _menu_has(item_id):
            return self._send(200, {
                "ok": False, "error": "menu item not found"})
        roles = self._roles_for_login(login)
        meta = _menu_get(item_id) or {}
        plugin_name = meta.get("plugin_name") or None
        ctx = _get_plugin_context(plugin_name)
        view = _menu_build_view(item_id, login, roles, ctx)
        if view is None:
            return self._send(200, {
                "ok": False, "error": "forbidden"})
        self._send(200, {"ok": True, "view": view})

    # ================================================================
    # status / routing
    # ================================================================

    def _status(self):
        ip = _client_ip(self)
        if ip not in ("127.0.0.1", "::1", ""):
            return self._send(403, {"ok": False,
                                    "error": "forbidden"})
        data = _stats.snapshot()
        data["warehouse"] = os.path.basename(
            os.path.dirname(os.path.abspath(self.db_path)))
        data["tls"] = _tls_enabled
        self._send(200, data)

    def do_POST(self):
        self._req_in = 0
        self._req_out = 0
        data = self._read_json()
        if data is None:
            self._send(400, {"ok": False, "error": "bad json"})
            _stats.register_request(self._req_in, self._req_out)
            return
        try:
            loc = data.get("locale")
            if not loc:
                loc = self._default_locale()
            set_locale(loc)
        except Exception:
            set_locale("ru")
        client = None
        with _lock:
            try:
                parts = [p for p in self.path.split("/") if p]
                client = self._guess_client(parts, data)
                self._route(self.path, data)
            except Exception as e:
                traceback.print_exc()
                self._send(500, {"ok": False, "error": str(e)})
        _stats.register_request(self._req_in, self._req_out,
                                 client=client)

    def do_GET(self):
        self._req_in = 0
        self._req_out = 0
        try:
            set_locale(self._default_locale())
        except Exception:
            set_locale("ru")
        try:
            # GET больше не обслуживает эндпоинты: плагинные
            # эндпоинты требуют авторизации через POST,
            # /barcodes/item/* удалён.
            self._send(405, {"ok": False, "error": "use POST"})
        finally:
            _stats.register_request(self._req_in, self._req_out)

    def _route(self, path, data):
        parts = [p for p in path.split("/") if p]
        if not parts:
            return self._send(404, {"ok": False, "error": "not found"})

        if parts == ["ping"]:
            return self._send(200, {
                "ok": True, "server": "luch",
                "protocol": PROTOCOL_VERSION,
                "tls": _tls_enabled,
                "ts": datetime.now().isoformat(),
            })
        if parts == ["status"]:
            return self._status()
        if parts == ["login"]:
            return self._login(data)
        if parts == ["logout"]:
            return self._logout(data)
        if parts and parts[0] == "mgmt":
            return self._mgmt(parts, data)
        if parts and parts[0] == "ui_config":
            return self._ui_config(parts, data)
        if parts[0] == "plugin":
            return self._plugin_post(parts[1:], data)

        login = self._auth_token(data)
        if not login:
            return self._send(401, {"ok": False,
                                    "error": "unauthorized"})

        if parts == ["employees", "me"]:
            return self._me(login)
        if parts == ["settings"]:
            return self._settings(login)
        if parts == ["capabilities", "hello"]:
            return self._capabilities_hello(login, data)
        if parts and parts[0] == "notifications":
            return self._notifications(parts, login, data)
        if parts and parts[0] == "sessions":
            return self._sessions(parts, login, data)
        if parts and parts[0] == "tasks":
            return self._tasks(parts, login, data)
        if parts and parts[0] == "menu":
            return self._menu(parts, login, data)

        self._send(404, {"ok": False, "error": "not found"})

    def _login(self, data):
        ip = _client_ip(self)
        login_v = (data.get("login") or "").strip()

        ok, wait = _login_limiter.check(ip, login_v)
        if not ok:
            return self._send(200, {
                "ok": False,
                "error": f"too many attempts, wait {wait}s",
            })

        login = self._auth(data)
        if not login:
            _login_limiter.hit(ip, login_v)
            return self._send(200, {"ok": False,
                                    "error": "invalid credentials"})
        _login_limiter.reset(ip, login_v)

        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT pass_hash FROM employees WHERE login=?",
                        (login,))
            r = cur.fetchone()
            if r and needs_rehash(r["pass_hash"] or ""):
                cur.execute(
                    "UPDATE employees SET pass_hash=? WHERE login=?",
                    (hash_password(data.get("secret") or ""), login))
                conn.commit()
        finally:
            conn.close()

        token = create_auth_session(
            self.db_path, login, "employee", ip=ip)
        self._send(200, {
            "ok": True,
            "token": token,
            "protocol": PROTOCOL_VERSION,
        })

    def _logout(self, data):
        token = (data.get("token") or "").strip()
        if token:
            try:
                invalidate_session_by_token(self.db_path, token)
            except Exception:
                pass
        self._send(200, {"ok": True})

    def _ui_config(self, parts, data):
        version, cfg = get_versioned(self.db_path)
        if len(parts) == 2 and parts[1] == "version":
            lv = data.get("version") or ""
            self._send(200, {
                "ok": True, "version": version,
                "changed": lv != version,
            })
            return
        if len(parts) == 1:
            self._send(200, {
                "ok": True, "version": version, "config": cfg,
            })
            return
        self._send(404, {"ok": False, "error": "unknown route"})

    def _me(self, login):
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT first_name, last_name, middle_name,
                       login, role, roles
                FROM employees WHERE login=?
            """, (login,))
            r = cur.fetchone()
        finally:
            conn.close()
        if not r:
            return self._send(200, {"ok": False})
        fio = " ".join(p for p in [r["last_name"], r["first_name"],
                                   r["middle_name"]] if p)
        try:
            roles = json.loads(r["roles"]) if r["roles"] else []
        except Exception:
            roles = []
        self._send(200, {"ok": True, "fio": fio,
                         "login": r["login"],
                         "role": r["role"] or "",
                         "roles": roles})

    def _settings(self, login):
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT key, value FROM settings")
            rows = cur.fetchall()
        finally:
            conn.close()
        result = {r["key"]: r["value"] for r in rows}
        for k in ("locale", "active_plugins", "created_at"):
            result.pop(k, None)
        result = {k: v for k, v in result.items()
                  if not k.startswith("_mgmt_")}
        self._send(200, {"ok": True, "settings": result})

    def _capabilities_hello(self, login, data):
        proto = data.get("protocol") or PROTOCOL_VERSION
        if not is_protocol_supported(proto):
            return self._send(200, {
                "ok": False,
                "error": "protocol not supported",
                "supported": PROTOCOL_VERSION,
            })
        caps = ClientCapabilities.from_dict(data)
        cap_registry.set(login, caps)
        self._send(200, {
            "ok": True, "protocol": PROTOCOL_VERSION,
            "device": caps.device,
            "server_capabilities": {
                "widgets": [
                    "text", "heading", "caption",
                    "card", "group", "divider", "spacer",
                    "progress", "button", "input",
                    "list", "tiles", "image", "barcode",
                    "slot", "webview", "table",
                ],
                "actions": ["scan", "tap", "input_submit",
                            "cancel", "custom"],
                "features": ["assets", "notifications",
                             "heartbeat", "tls"],
            },
        })

    def _notifications(self, parts, login, data):
        if len(parts) == 2 and parts[1] == "inbox":
            return self._notif_inbox(login)
        if len(parts) == 2 and parts[1] == "mark_read":
            return self._notif_mark_read(login, data)
        self._send(404, {"ok": False, "error": "unknown route"})

    def _notif_inbox(self, login):
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, message, created_at, sender_login,
                       type, payload, task_id
                FROM notifications
                WHERE recipient_login=?
                  AND (read_at IS NULL OR read_at='')
                ORDER BY
                    CASE type
                        WHEN 'urgent' THEN 0
                        WHEN 'info' THEN 1
                        ELSE 2
                    END, id ASC
            """, (login,))
            rows = [_translate_notification(dict(r))
                    for r in cur.fetchall()]
        finally:
            conn.close()
        self._send(200, {"ok": True, "notifications": rows})

    def _notif_mark_read(self, login, data):
        ids = data.get("ids") or []
        if not isinstance(ids, list):
            ids = [ids]
        if not ids:
            return self._send(200, {"ok": True, "updated": 0})
        now = datetime.now().isoformat()
        conn = self._conn()
        try:
            cur = conn.cursor()
            placeholders = ",".join(["?"] * len(ids))
            cur.execute(
                f"UPDATE notifications SET read_at=? "
                f"WHERE id IN ({placeholders}) AND recipient_login=?",
                [now] + list(ids) + [login])
            conn.commit()
            n = cur.rowcount
        finally:
            conn.close()
        self._send(200, {"ok": True, "updated": n})

    def _roles_for_login(self, login):
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT role, roles FROM employees "
                        "WHERE login=?", (login,))
            r = cur.fetchone()
        finally:
            conn.close()
        if not r:
            return []
        try:
            roles = json.loads(r["roles"]) if r["roles"] else []
        except Exception:
            roles = []
        return roles

    def _get_roles_for_login(self, cur, login):
        cur.execute("SELECT role, roles FROM employees "
                    "WHERE login=?", (login,))
        r = cur.fetchone()
        if not r:
            return []
        try:
            roles = json.loads(r["roles"]) if r["roles"] else []
        except Exception:
            roles = []
        return roles

    def _sessions(self, parts, login, data):
        if len(parts) == 2 and parts[1] == "list":
            return self._sessions_list(login, data)
        if len(parts) == 3 and parts[2] == "start":
            return self._session_start(parts[1], login, data)
        if len(parts) == 3 and parts[2] == "action":
            return self._session_action(parts[1], login, data)
        if len(parts) == 3 and parts[2] == "close":
            return self._session_close(parts[1], login, data)
        self._send(404, {"ok": False,
                         "error": "unknown session route"})

    def _sessions_list(self, login, data):
        from sessions import list_handlers
        roles = self._roles_for_login(login)
        device = self._device_for(login, data)

        handlers = list_handlers()
        out = []
        for h in handlers:
            try:
                allowed = h.can_start(login, roles)
            except Exception:
                allowed = False
            if not allowed:
                continue
            platforms = getattr(h, "platforms", ("pc",)) or ()
            if platforms and device not in platforms \
                    and "any" not in platforms:
                continue
            out.append({"key": h.key, "title": h.title})
        self._send(200, {"ok": True, "sessions": out})

    def _session_start(self, key, login, data):
        from sessions import get_handler
        sh = get_handler(key)
        if not sh:
            return self._send(404, {"ok": False,
                                    "error": "no handler"})

        device = self._device_for(login, data)
        platforms = getattr(sh, "platforms", ("pc",)) or ()
        if platforms and device not in platforms \
                and "any" not in platforms:
            return self._send(200, {
                "ok": False,
                "error": (f"сессия недоступна на этом "
                          f"устройстве ({device})"),
            })

        conn = self._conn()
        try:
            cur = conn.cursor()
            roles = self._roles_for_login(login)
            can = sh.can_start(login, roles)
            if not can:
                try:
                    state_check = sh.get_state(cur, login)
                    has_open = bool(
                        state_check.get("container_barcode")
                        or state_check.get("task_id")
                        or state_check.get("pending"))
                except Exception:
                    has_open = False
                if not has_open:
                    return self._send(200, {
                        "ok": False,
                        "error": "доступ запрещён",
                    })

            sh.start(cur, login, data.get("payload") or {})
            conn.commit()
            caps = cap_registry.get(login)
            view = sh.get_view(cur, login, {}, caps)
            state = sh.get_state(cur, login)
            payload = {
                "ok": True,
                "view": view,
                "meta": {
                    "session_key": key,
                    "session_title": sh.title,
                    "state": state,
                },
            }
            if hasattr(sh, "_is_role_revoked"):
                try:
                    if sh._is_role_revoked(cur, login):
                        payload["role_revoked"] = True
                except Exception:
                    pass
            self._send(200, payload)
        finally:
            conn.close()

    def _session_action(self, key, login, data):
        from sessions import get_handler
        sh = get_handler(key)
        if not sh:
            return self._send(404, {"ok": False,
                                    "error": "no handler"})

        device = self._device_for(login, data)
        platforms = getattr(sh, "platforms", ("pc",)) or ()
        if platforms and device not in platforms \
                and "any" not in platforms:
            return self._send(200, {
                "ok": False,
                "error": (f"сессия недоступна на этом "
                          f"устройстве ({device})"),
            })

        conn = self._conn()
        try:
            cur = conn.cursor()
            action_id = data.get("id") or ""
            value = data.get("value")
            result = sh.handle_action(cur, login, action_id,
                                       value, {})
            conn.commit()
            if not result.get("ok"):
                return self._send(200, result)
            caps = cap_registry.get(login)
            view = sh.get_view(cur, login, {}, caps)
            state = sh.get_state(cur, login)
            payload = {
                "ok": True,
                "message": result.get("message", ""),
                "view": view,
                "meta": {
                    "session_key": key,
                    "session_title": sh.title,
                    "state": state,
                },
            }
            if result.get("role_revoked"):
                payload["role_revoked"] = True
            elif hasattr(sh, "_is_role_revoked"):
                try:
                    if sh._is_role_revoked(cur, login):
                        payload["role_revoked"] = True
                except Exception:
                    pass
            self._send(200, payload)
        finally:
            conn.close()

    def _session_close(self, key, login, data):
        from sessions import get_handler
        sh = get_handler(key)
        if not sh:
            return self._send(404, {"ok": False,
                                    "error": "no handler"})
        force = bool(data.get("force"))
        conn = self._conn()
        try:
            cur = conn.cursor()
            try:
                result = sh.close(cur, login, force=force)
            except TypeError:
                result = sh.close(cur, login)
            if result is None:
                result = {"ok": True}
            if not result.get("ok"):
                conn.rollback()
                return self._send(200, {
                    "ok": False,
                    "error": result.get("error")
                    or "Не удалось закрыть сессию",
                })
            conn.commit()
            self._send(200, {"ok": True,
                             "message": "Сессия закрыта"})
        finally:
            conn.close()

    def _tasks(self, parts, login, data):
        conn = self._conn()
        try:
            cur = conn.cursor()

            if len(parts) == 2 and parts[1] == "next":
                return self._next_task(cur, conn, login, data)

            if len(parts) >= 2 and parts[1].isdigit():
                task_id = int(parts[1])
                if len(parts) == 3:
                    action = parts[2]
                    if action == "view":
                        return self._task_view(
                            cur, conn, task_id, login, data)
                    if action == "status":
                        return self._task_status(
                            cur, conn, task_id, login)
                    if action == "action":
                        return self._task_action(
                            cur, conn, task_id, login, data)
                    if action == "report":
                        return self._task_report(
                            cur, conn, task_id, login)
                    if action == "finish":
                        return self._task_finish(
                            cur, conn, task_id, login, data)

            return self._send(404, {"ok": False,
                                    "error": "unknown tasks route"})
        finally:
            conn.close()

    def _task_status(self, cur, conn, task_id, login):
        cur.execute("""
            SELECT id, status, assignee_login FROM tasks WHERE id=?
        """, (task_id,))
        r = cur.fetchone()
        if not r:
            return self._send(200, {"ok": True, "exists": False})
        assignee = (r["assignee_login"] or "").strip()
        if assignee and assignee != login:
            return self._send(200, {
                "ok": True, "exists": False,
                "status": "", "assignee_login": "",
            })
        if r["status"] == "in_progress":
            refresh_task_reservations(
                cur, task_id, RESERVE_ACTIVE_MINUTES)
            conn.commit()
        self._send(200, {
            "ok": True, "exists": True,
            "status": r["status"] or "",
            "assignee_login": r["assignee_login"] or "",
        })

    def _load_task_state(self, cur, task_id):
        cur.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        task = cur.fetchone()
        if not task:
            return None, None, None
        cur.execute("""
            SELECT ti.*,
                   ic.name    AS item_name,
                   ic.barcode AS item_barcode,
                   c.address  AS cell_address
            FROM task_items ti
            LEFT JOIN item_characteristics ic
                   ON ic.item_code = ti.item_code
            LEFT JOIN cells c
                   ON c.barcode = ti.cell_barcode
            WHERE ti.task_id=?
            ORDER BY ti.step_no, ti.id
        """, (task_id,))
        items = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT key, value FROM settings")
        settings = {r["key"]: r["value"] for r in cur.fetchall()}
        return dict(task), items, settings

    def _ensure_plan(self, cur, task, items, settings):
        plan = []
        raw = task.get("task_plan") or ""
        if raw:
            try:
                plan = json.loads(raw)
            except Exception:
                plan = []

        if plan and task.get("task_type") == "inventory":
            has_finish = False
            for s in plan:
                if s.get("type") == "confirm" and \
                        (s.get("data") or {}).get("action") == \
                        "finish_task":
                    has_finish = True
                    break
            if not has_finish:
                plan = []

        if plan and task.get("task_type") == "pick":
            has_finish = False
            for s in plan:
                if s.get("type") == "confirm" and \
                        (s.get("data") or {}).get("action") == \
                        "finish_task":
                    has_finish = True
                    break
            if has_finish:
                plan = []

        if not plan:
            handler = get_handler(task["task_type"])
            if not handler:
                return [], 0
            plan = handler.build_steps(task, items, settings)
            cur.execute("UPDATE tasks SET task_plan=? WHERE id=?",
                        (json.dumps(plan, ensure_ascii=False),
                         task["id"]))
            cur_index_old = int(task.get("current_step_no") or 0)
            if cur_index_old >= len(plan):
                cur.execute(
                    "UPDATE tasks SET current_step_no=? WHERE id=?",
                    (max(0, len(plan) - 1), task["id"]))
                task["current_step_no"] = max(0, len(plan) - 1)
        cur_index = int(task.get("current_step_no") or 0)
        return plan, cur_index

    def _task_view(self, cur, conn, task_id, login, data):
        expire_reservations(cur)
        task, items, settings = self._load_task_state(cur, task_id)
        if not task:
            return self._send(200, {"ok": False, "error": "no task"})
        if task.get("task_type") == "receive":
            return self._send(200, {
                "ok": False,
                "error": "Приёмка выполняется через сессию "
                         "приёмки, а не через задание.",
            })
        err = _check_task_assignee(task, login)
        if err:
            return self._send(200, {"ok": False, "error": err})
        if not has_task_handler(task["task_type"]):
            return self._send(200, {
                "ok": False,
                "error": (f"тип задания «{task['task_type']}» "
                          f"не зарегистрирован"),
            })

        plan, cur_index = self._ensure_plan(cur, task, items, settings)
        conn.commit()

        if task.get("status") == "in_progress":
            refresh_task_reservations(
                cur, task_id, RESERVE_ACTIVE_MINUTES)
            conn.commit()

        handler = get_handler(task["task_type"])
        task = handler.enrich_task(cur, task, items, settings)
        step = None
        if 0 <= cur_index < len(plan):
            step = plan[cur_index]
            step = handler.enrich_step(cur, task, step, items, settings)

        caps = cap_registry.get(login)
        ctx = _get_plugin_context()
        view = build_step_view(task, step, items, settings,
                               context=ctx, capabilities=caps)

        batch_id, block_bf, batch_pos, batch_total = \
            self._batch_meta(cur, task)
        pending = (task.get("pending_action") or "").strip()
        finished = (cur_index >= len(plan)) and not pending
        meta = {
            "task_id": task_id,
            "task_type": task["task_type"],
            "task_number": task["task_number"],
            "status": task.get("status", "in_progress"),
            "step_no": cur_index,
            "total_steps": len(plan),
            "finished": finished,
            "pending_action": pending,
            "pending_cell": task.get("pending_cell") or "",
            "batch_id": batch_id,
            "block_bf": block_bf,
            "batch_position": batch_pos,
            "batch_total": batch_total,
            "partial": int(task.get("partial") or 0),
            "progress": self._progress_for(task),
        }
        self._send(200, {"ok": True, "view": view, "meta": meta})

    def _task_action(self, cur, conn, task_id, login, data):
        expire_reservations(cur)
        action = (data.get("action") or "").strip()
        value = data.get("value")
        action_id = data.get("id")
        step_no = data.get("step_no")

        task, items, settings = self._load_task_state(cur, task_id)
        if not task:
            return self._send(200, {"ok": False, "error": "no task"})
        if task.get("task_type") == "receive":
            return self._send(200, {
                "ok": False,
                "error": "Приёмка выполняется через сессию "
                         "приёмки, а не через задание.",
            })
        err = _check_task_assignee(task, login)
        if err:
            return self._send(200, {"ok": False, "error": err})
        handler = get_handler(task["task_type"])
        if not handler:
            return self._send(200, {
                "ok": False, "error": "тип не зарегистрирован",
            })

        if task.get("status") == "in_progress":
            refresh_task_reservations(
                cur, task_id, RESERVE_ACTIVE_MINUTES)

        plan, cur_index = self._ensure_plan(cur, task, items, settings)
        if step_no is not None and int(step_no) != cur_index:
            conn.commit()
            return self._send(200, {
                "ok": False,
                "error": f"несоответствие шага: ждали {cur_index}",
            })

        step = plan[cur_index] if 0 <= cur_index < len(plan) else None
        pending = (task.get("pending_action") or "").strip()

        if not step and not pending:
            return self._send(200, {"ok": False,
                                    "error": "задание уже выполнено"})

        if action == "tap" and action_id == "cancel_pending":
            try:
                ok, err2 = handler.can_cancel_pending(
                    cur, task, task.get("pending_action") or "")
            except Exception:
                ok, err2 = True, None
            if not ok:
                conn.commit()
                return self._send(200, {
                    "ok": False,
                    "error": err2 or "Нельзя отменить это действие",
                })
            cur.execute("""
                UPDATE tasks SET pending_action='', pending_cell='',
                                 drop_status='', drop_pending='',
                                 drop_point_barcode=''
                WHERE id=?
            """, (task_id,))
            conn.commit()
            return self._send_view_after_action(
                conn, task_id, login, message="Отменено")

        if pending:
            if action == "scan":
                return self._handle_pending_scan(
                    cur, conn, task, handler, pending, value,
                    items, settings, plan, cur_index, login)

            if action == "tap" and pending in _CHOICE_PENDINGS:
                result = handler.handle_action(
                    cur, task, step, action_id, value,
                    items, settings)
                return self._apply_result(
                    cur, conn, task, handler, result,
                    items, settings, plan, cur_index, login)

            return self._send(200, {
                "ok": False,
                "error": ("Сначала завершите подтверждение "
                          "или нажмите «Отменить»"),
            })

        if action == "scan":
            result = handler.handle_scan(
                cur, task, step, value, items, settings)
            return self._apply_result(cur, conn, task, handler,
                                       result, items, settings,
                                       plan, cur_index, login)

        if action in ("tap", "cancel", "input_submit") or \
                (isinstance(action, str)
                 and action.startswith("custom:")):
            if action == "cancel":
                container = task.get("container_barcode") or ""
                if container:
                    cur.execute("""
                        SELECT COALESCE(SUM(quantity), 0)
                        FROM placed_instances
                        WHERE cell_or_container_barcode=?
                    """, (container,))
                    qty = cur.fetchone()[0] or 0
                    if qty > 0:
                        return self._send(200, {
                            "ok": False,
                            "error": tr(
                                "task.err.cant_cancel_with_container",
                                "В таре {barcode} остались товары "
                                "({qty} шт). Закройте тару через "
                                "задание или обратитесь "
                                "к руководителю.",
                                barcode=container, qty=qty),
                        })
                    from tasks.utils import set_container_status
                    set_container_status(cur, container, "free")

                cur.execute("""
                    UPDATE tasks SET assignee_login=NULL,
                        status='pending',
                        current_step_no=0,
                        task_plan='',
                        container_barcode='',
                        current_cell_barcode='',
                        pending_action='',
                        pending_cell='',
                        drop_status='',
                        drop_pending='',
                        drop_point_barcode=''
                    WHERE id=?
                """, (task_id,))
                release_task(cur, task_id)
                conn.commit()
                return self._send(200, {
                    "ok": True, "message": "Задание отпущено",
                })

            if isinstance(action, str) and action.startswith("custom:"):
                custom_id = action[len("custom:"):]
                ctx = _get_plugin_context()
                handled = hook_registry.call_chain(
                    "on_custom_action",
                    task=task, step=step, custom_id=custom_id,
                    value=value, login=login, context=ctx)
                if handled and handled.get("handled"):
                    return self._send_view_after_action(
                        conn, task_id, login,
                        message=handled.get("message", ""))
                return self._send(200, {
                    "ok": False,
                    "error": f"custom:{custom_id} не обработан",
                })

            result = handler.handle_action(
                cur, task, step, action_id, value, items, settings)
            return self._apply_result(cur, conn, task, handler,
                                       result, items, settings,
                                       plan, cur_index, login)

        self._send(200, {"ok": False,
                         "error": f"неизвестное действие: {action}"})

    def _handle_pending_scan(self, cur, conn, task, handler, pending,
                             scanned, items, settings, plan,
                             cur_index, login):
        scanned = (scanned or "").strip()
        result = handler.handle_pending_scan(
            cur, task, pending, scanned, items, settings)
        if result is None:
            cur.execute("""
                UPDATE tasks SET pending_action='', pending_cell=''
                WHERE id=?
            """, (task["id"],))
            conn.commit()
            return self._send(200, {
                "ok": False,
                "error": f"неизвестное ожидание: {pending}",
            })
        if not result.get("ok"):
            conn.commit()
            return self._send_view_after_action(
                conn, task["id"], login,
                message=result.get("error", "Ошибка"))
        return self._apply_result(cur, conn, task, handler, result,
                                   items, settings, plan, cur_index,
                                   login)

    def _apply_result(self, cur, conn, task, handler, result,
                      items, settings, plan, cur_index, login):
        if result is None:
            return self._send(200, {
                "ok": False, "error": "handler вернул None",
            })
        if not result.get("ok"):
            conn.commit()
            return self._send(200, result)

        if result.get("view_override") == "container_contents":
            conn.commit()
            return self._send_container_contents_view(
                cur, conn, task, login)

        cur.execute("SELECT pending_action FROM tasks WHERE id=?",
                    (task["id"],))
        row = cur.fetchone()
        pending_now = (row[0] if row else "") or ""

        finished = bool(result.get("finished"))
        if not finished:
            new_index = cur_index
            if not result.get("stay_on_step"):
                new_index = cur_index + 1
                cur.execute(
                    "UPDATE tasks SET current_step_no=? WHERE id=?",
                    (new_index, task["id"]))
            if new_index >= len(plan) and not pending_now:
                finished = True

        if finished and pending_now:
            finished = False

        if finished or (result.get("action") == "finish"
                        and not pending_now):
            handler.on_finalize(cur, task, items, settings)
            cur.execute("""
                UPDATE tasks SET status='done', assignee_login=NULL,
                    processed_a=target_a,
                    pending_action='', pending_cell=''
                WHERE id=?
            """, (task["id"],))
            release_task(cur, task["id"])
            conn.commit()
            hook_registry.call_event(
                "on_task_finish", task=task,
                result={"done": True},
                context=_get_plugin_context())
            return self._send(200, {
                "ok": True, "finished": True,
                "message": result.get("message")
                or "Задание завершено",
            })

        conn.commit()
        extra = None
        if "not_found_result" in result:
            extra = {"not_found_result": result["not_found_result"]}
        return self._send_view_after_action(
            conn, task["id"], login,
            message=result.get("message", ""), extra=extra)

    def _send_container_contents_view(self, cur, conn, task, login):
        container_bc = (task.get("container_barcode") or "").strip()
        if not container_bc:
            return self._send(200, {
                "ok": False, "error": "нет активной тары",
            })
        items_data = self._load_container_contents(
            cur, task["id"], container_bc)
        caps = cap_registry.get(login)
        ctx = _get_plugin_context()
        view = build_container_contents_view(
            task, container_bc, items_data, {}, context=ctx,
            capabilities=caps)
        self._send(200, {
            "ok": True,
            "view": view,
            "meta": {
                "task_id": task["id"],
                "task_type": task["task_type"],
                "task_number": task["task_number"],
                "status": task.get("status", "in_progress"),
                "step_no": int(task.get("current_step_no") or 0),
                "total_steps": 0,
                "finished": False,
                "pending_action": "",
                "pending_cell": "",
                "batch_id": "",
                "block_bf": "",
                "batch_position": 0,
                "batch_total": 0,
                "partial": int(task.get("partial") or 0),
                "progress": self._progress_for(task),
            },
        })

    def _load_container_contents(self, cur, task_id, container_bc):
        cur.execute("""
            SELECT pi.item_code, COALESCE(SUM(pi.quantity), 0) AS qty
            FROM placed_instances pi
            WHERE pi.cell_or_container_barcode=?
            GROUP BY pi.item_code
        """, (container_bc,))
        in_container = {r[0]: r[1] for r in cur.fetchall() if r[0]}

        cur.execute("""
            SELECT ti.item_code,
                   COALESCE(SUM(ti.quantity), 0) AS qty_total
            FROM task_items ti
            WHERE ti.task_id=? AND ti.container_barcode=?
              AND ti.item_code IS NOT NULL
              AND ti.item_code != ''
            GROUP BY ti.item_code
        """, (task_id, container_bc))
        task_qty = {r[0]: r[1] for r in cur.fetchall() if r[0]}

        all_codes = set(list(in_container.keys()) +
                        list(task_qty.keys()))
        all_codes = {c for c in all_codes if c}

        result = []
        for item_code in all_codes:
            cur.execute("""
                SELECT name, barcode FROM item_characteristics
                WHERE item_code=?
            """, (item_code,))
            r = cur.fetchone()
            item_name = r[0] if r else ""
            item_bc = r[1] if r else ""
            photo = self._photo_b64(cur, item_code) or ""
            in_cont = in_container.get(item_code, 0)

            if item_code in task_qty:
                total = task_qty[item_code]
                placed = max(0, total - in_cont)
            else:
                total = in_cont
                placed = 0

            result.append({
                "item_code": item_code,
                "item_name": item_name or item_code,
                "item_barcode": item_bc,
                "photo_b64": photo,
                "qty_total": total,
                "qty_placed": placed,
            })
        return result

    def _progress_for(self, task):
        tt = task.get("task_type")
        if tt == "inventory":
            b_max = 0
        else:
            b_max = task.get("target_b", 0)
        return {
            "a": task.get("processed_a", 0),
            "a_max": task.get("target_a", 0),
            "b": task.get("processed_b", 0),
            "b_max": b_max,
        }

    def _batch_meta(self, cur, task):
        batch_id = (task.get("batch_id") or "").strip()
        block_bf = (task.get("block_bf") or "").strip()
        if not batch_id:
            return "", block_bf, 0, 0
        cur.execute("SELECT COUNT(*) FROM tasks WHERE batch_id=?",
                    (batch_id,))
        total = cur.fetchone()[0] or 0
        cur.execute("""
            SELECT COUNT(*) FROM tasks
            WHERE batch_id=? AND id<=?
        """, (batch_id, task["id"]))
        pos = cur.fetchone()[0] or 0
        return batch_id, block_bf, pos, total

    def _device_for(self, login, data=None):
        if data:
            device = (data.get("device") or "").strip()
            if device:
                return device
        caps = cap_registry.get(login)
        return getattr(caps, "device", "") or "pc"

    def _next_task(self, cur, conn, login, data):
        expire_reservations(cur)

        platform = data.get("platform") or "any"

        cur.execute("""
            SELECT id FROM tasks
            WHERE assignee_login=? AND status='in_progress'
            ORDER BY id DESC LIMIT 1
        """, (login,))
        active = cur.fetchone()
        if active:
            task_id = active["id"]
        else:
            roles = self._get_roles_for_login(cur, login)
            types = task_types_for_roles(roles)
            if not types:
                return self._send(200, {"ok": False,
                                        "error": "no roles"})
            placeholders = ",".join(["?"] * len(types))
            sql = f"""
                SELECT id FROM tasks
                WHERE status='pending' AND assignee_login IS NULL
                  AND task_type IN ({placeholders})
            """
            params = list(types)
            if platform and platform != "any":
                sql += " AND platform IN (?, 'any')"
                params.append(platform)
            sql += " ORDER BY id ASC LIMIT 1"
            cur.execute(sql, params)
            row = cur.fetchone()
            if not row:
                return self._send(200, {"ok": False,
                                        "error": "no tasks"})
            task_id = row["id"]
            cur.execute("""
                UPDATE tasks SET assignee_login=?, status='in_progress'
                WHERE id=? AND assignee_login IS NULL
            """, (login, task_id))
            if cur.rowcount == 0:
                return self._send(200, {"ok": False,
                                        "error": "race"})
            conn.commit()

        refresh_task_reservations(cur, task_id, RESERVE_ACTIVE_MINUTES)
        conn.commit()

        cur.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        t = cur.fetchone()
        if t and t["task_type"] == "receive":
            cur.execute(
                "UPDATE tasks SET status='pending', "
                "assignee_login=NULL WHERE id=?", (task_id,))
            conn.commit()
            return self._send(200, {"ok": False, "error": "no tasks"})

        cur.execute("""
            SELECT ti.*,
                   ic.name    AS item_name,
                   ic.barcode AS item_barcode,
                   c.address  AS cell_address
            FROM task_items ti
            LEFT JOIN item_characteristics ic
                   ON ic.item_code = ti.item_code
            LEFT JOIN cells c
                   ON c.barcode = ti.cell_barcode
            WHERE ti.task_id=?
            ORDER BY ti.step_no, ti.id
        """, (task_id,))
        items = [dict(rr) for rr in cur.fetchall()]

        handler = get_handler(t["task_type"])
        if handler:
            handler.on_enter(cur, dict(t), items, {})

        hook_registry.call_event("on_task_assign",
                                 task=dict(t), login=login)
        self._send(200, {"ok": True, "task": dict(t),
                         "items": items})

    def _task_report(self, cur, conn, task_id, login):
        cur.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        task = cur.fetchone()
        if not task:
            return self._send(200, {"ok": False, "error": "no task"})
        err = _check_task_assignee(dict(task), login)
        if err:
            return self._send(200, {"ok": False, "error": err})
        task_type = task["task_type"]

        cur.execute("""
            SELECT ti.id, ti.item_code, ti.quantity,
                   COALESCE(ti.scanned_qty, 0) AS scanned_qty,
                   ti.status, ti.rejected,
                   ic.name AS item_name, ic.barcode AS item_barcode
            FROM task_items ti
            LEFT JOIN item_characteristics ic
                   ON ic.item_code = ti.item_code
            WHERE ti.task_id=?
            ORDER BY ti.step_no, ti.id
        """, (task_id,))
        rows = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT barcode FROM task_events
            WHERE task_id=? AND event_type='rejected'
            ORDER BY id
        """, (task_id,))
        rejected = [r["barcode"] for r in cur.fetchall()]

        items_out = []
        for r in rows:
            items_out.append({
                "item_code": r["item_code"],
                "item_name": r["item_name"] or "",
                "item_barcode": r["item_barcode"] or "",
                "expected": r["quantity"] or 0,
                "scanned": r["scanned_qty"] or 0,
                "status": r["status"] or "pending",
            })

        self._send(200, {
            "ok": True,
            "task_number": task["task_number"],
            "task_type": task_type,
            "status": task["status"],
            "items": items_out,
            "rejected": rejected,
        })

    def _task_finish(self, cur, conn, task_id, login, data):
        cur.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        task = cur.fetchone()
        if not task:
            return self._send(200, {"ok": False, "error": "no task"})
        if task["task_type"] == "receive":
            return self._send(200, {
                "ok": False,
                "error": "Приёмка выполняется через сессию "
                         "приёмки, а не через задание.",
            })
        err = _check_task_assignee(dict(task), login)
        if err:
            return self._send(200, {"ok": False, "error": err})
        task_dict = dict(task)
        handler = get_handler(task_dict.get("task_type"))
        if handler:
            _, items, settings = self._load_task_state(cur, task_id)
            handler.on_finalize(cur, task_dict, items or [],
                                 settings or {})
        cur.execute("UPDATE tasks SET assignee_login=NULL "
                    "WHERE id=?", (task_id,))
        cur.execute("""
            UPDATE tasks SET status='done',
                pending_action='', pending_cell=''
            WHERE id=?
        """, (task_id,))
        release_task(cur, task_id)
        conn.commit()
        hook_registry.call_event(
            "on_task_done", task=task_dict,
            context=_get_plugin_context())
        self._send(200, {"ok": True})

    def _send_view_after_action(self, conn, task_id, login,
                                message="", extra=None):
        cur = conn.cursor()
        task, items, settings = self._load_task_state(cur, task_id)
        if not task:
            return self._send(200, {"ok": False, "error": "no task"})

        handler = get_handler(task["task_type"])
        if not handler:
            return self._send(200, {
                "ok": False, "error": "тип не зарегистрирован",
            })
        plan, cur_index = self._ensure_plan(cur, task, items, settings)
        task = handler.enrich_task(cur, task, items, settings)
        step = None
        if 0 <= cur_index < len(plan):
            step = handler.enrich_step(
                cur, task, plan[cur_index], items, settings)
        caps = cap_registry.get(login)
        ctx = _get_plugin_context()
        view = build_step_view(task, step, items, settings,
                               context=ctx, capabilities=caps)
        batch_id, block_bf, batch_pos, batch_total = \
            self._batch_meta(cur, task)
        pending = (task.get("pending_action") or "").strip()
        finished = (cur_index >= len(plan)) and not pending
        meta = {
            "task_id": task_id,
            "task_type": task["task_type"],
            "task_number": task["task_number"],
            "status": task.get("status", "in_progress"),
            "step_no": cur_index,
            "total_steps": len(plan),
            "finished": finished,
            "pending_action": pending,
            "pending_cell": task.get("pending_cell") or "",
            "batch_id": batch_id,
            "block_bf": block_bf,
            "batch_position": batch_pos,
            "batch_total": batch_total,
            "partial": int(task.get("partial") or 0),
            "progress": self._progress_for(task),
        }
        payload = {
            "ok": True,
            "message": message,
            "view": view,
            "meta": meta,
        }
        if extra:
            payload.update(extra)
        self._send(200, payload)

    def _plugin_post(self, parts, data):
        if not parts:
            return self._send(404, {"ok": False,
                                    "error": "no plugin path"})
        login = self._auth_token(data)
        if not login:
            return self._send(401, {"ok": False,
                                    "error": "unauthorized"})
        plugin_name = parts[0]
        path = "/plugin/" + plugin_name + "/" + "/".join(parts[1:])
        handler = _find_plugin_endpoint(path, "POST")
        if not handler:
            return self._send(404, {"ok": False,
                                    "error": "no handler"})
        try:
            result = handler({
                "method": "POST", "path": path,
                "data": data, "login": login,
            })
            self._send(200, result if isinstance(result, dict)
                       else {"ok": True, "result": result})
        except Exception as e:
            traceback.print_exc()
            self._send(500, {"ok": False, "error": str(e)})


_CHOICE_PENDINGS = {
    "unknown_item",
}


def has_task_handler(task_type):
    return has_handler(task_type)


_host_ref = None


def set_host(host):
    global _host_ref
    _host_ref = host


def _plugin_name_from_key(key):
    """Извлекает имя плагина из ключа plugin:<name>:<k>."""
    if key and isinstance(key, str) and key.startswith("plugin:"):
        parts = key.split(":", 2)
        if len(parts) >= 2:
            return parts[1]
    return None


def _get_plugin_context(plugin_name=None):
    """Возвращает PublicContext плагина или облегчённый fallback.

    Если имя плагина известно и плагин активирован — возвращаем
    его PublicContext (db(), tr(), query(), notify() и т.д.).
    Иначе — fallback с тем же минимальным API.
    """
    if _host_ref is None:
        return None

    if plugin_name:
        pm = getattr(_host_ref, "plugin_manager", None)
        if pm is not None:
            ctx = pm.contexts.get(plugin_name)
            if ctx is not None:
                return ctx

    class _Ctx:
        def __init__(self):
            self.host = _host_ref
            self.db_path = getattr(_host_ref, "db_path", None)
            self.name = plugin_name or ""

        def db(self):
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            return conn

        def query(self, sql, params=()):
            conn = self.db()
            try:
                cur = conn.cursor()
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]
            finally:
                conn.close()

        def query_one(self, sql, params=()):
            conn = self.db()
            try:
                cur = conn.cursor()
                cur.execute(sql, params)
                r = cur.fetchone()
                return dict(r) if r else None
            finally:
                conn.close()

        def execute(self, sql, params=()):
            conn = self.db()
            try:
                cur = conn.cursor()
                cur.execute(sql, params)
                conn.commit()
                return cur.rowcount, cur.lastrowid
            finally:
                conn.close()

        def tr(self, key, **kwargs):
            return tr(key, **kwargs)

        def tr_in(self, locale, key, **kwargs):
            from i18n import tr_in
            return tr_in(locale, key, **kwargs)

        def log(self, msg):
            print(f"[plugin-ctx:{self.name or '?'}] {msg}")

    return _Ctx()


def _mgmt_extra_pages():
    if _host_ref is None:
        return None
    pages = getattr(_host_ref, "_mgmt_plugin_pages", None) or {}
    if not pages:
        return None
    return {
        k: {"title": v.get("title", k),
            "roles": v.get("roles")}
        for k, v in pages.items()
    }


def _find_plugin_endpoint(path, method):
    if _host_ref is None:
        return None
    eps = getattr(_host_ref, "_plugin_endpoints", None)
    if not eps:
        return None
    for (pname, p_path, handler, methods) in eps:
        if p_path == path and method in methods:
            return handler
    return None


_server = None
_thread = None
_tls_enabled = False
_warehouse_dir = None


def server_url():
    ips = _all_ipv4_cached()
    ip = ips[0] if ips else "127.0.0.1"
    base = f"WMS://{ip}:8765"
    if _tls_enabled and _warehouse_dir:
        fp = cert_fingerprint(_warehouse_dir)
        if fp:
            base += f"#fp={fp}"
    return base


def start_server(db_path, host="0.0.0.0", port=8765, tls=False):
    global _server, _thread, _tls_enabled, _warehouse_dir
    if _server is not None:
        return _server
    Handler.db_path = db_path
    Handler.timeout = 15
    _warehouse_dir = os.path.dirname(os.path.abspath(db_path))

    try:
        conn = sqlite3.connect(db_path)
        for sql in [
            """CREATE TABLE IF NOT EXISTS managers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                login TEXT UNIQUE NOT NULL,
                pass_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'operator',
                created_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER, message TEXT, created_at TEXT,
                sender_login TEXT DEFAULT '',
                type TEXT DEFAULT 'info',
                recipient_login TEXT DEFAULT '',
                read_at TEXT DEFAULT '', payload TEXT DEFAULT '')""",
            """CREATE TABLE IF NOT EXISTS inventory_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER, cell_barcode TEXT, item_code TEXT,
                qty_before INTEGER, qty_after INTEGER,
                created_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS reservations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL, item_code TEXT NOT NULL,
                cell_barcode TEXT NOT NULL, qty INTEGER NOT NULL,
                expires_at TEXT NOT NULL, created_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS drop_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                barcode TEXT UNIQUE NOT NULL, name TEXT,
                created_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                login TEXT NOT NULL,
                session_key TEXT NOT NULL,
                payload TEXT DEFAULT '{}',
                created_at TEXT,
                UNIQUE(login, session_key))""",
            """CREATE TABLE IF NOT EXISTS auth_sessions (
                token_hash TEXT PRIMARY KEY,
                login TEXT NOT NULL,
                kind TEXT NOT NULL,
                role TEXT DEFAULT '',
                created_at TEXT,
                expires_at TEXT,
                last_seen_at TEXT,
                ip TEXT DEFAULT '')""",
        ]:
            conn.execute(sql)
        conn.commit()
        conn.close()
    except Exception as e:
        print("start_server миграция:", e)

    tls_ctx = None
    if tls:
        if not has_cert(_warehouse_dir):
            raise RuntimeError(
                "TLS: сертификат не найден в "
                f"{tls_cert_dir(_warehouse_dir)}. "
                "Перевыпустите сертификат в "
                "«Настройки → Безопасность».")
        tls_ctx = make_server_context(_warehouse_dir)

    try:
        _server = ThreadingHTTPServer((host, port), Handler)
    except OSError as e:
        print(f"[server] НЕ УДАЛОСЬ занять порт {port}: {e}")
        raise

    if tls_ctx is not None:
        try:
            _server.socket = tls_ctx.wrap_socket(
                _server.socket, server_side=True)
            _tls_enabled = True
        except Exception as e:
            print(f"[server] TLS wrap: {e}")
            try:
                _server.server_close()
            except Exception:
                pass
            _server = None
            raise

    _thread = threading.Thread(target=_server.serve_forever,
                               daemon=True)
    _thread.start()

    scheme = "https" if _tls_enabled else "http"
    print("=" * 60)
    print(f"[server] слушаем на {host}:{port} ({scheme.upper()})")
    for ip in _all_ipv4_cached():
        print(f"[server]     {scheme}://{ip}:{port}")
    print(f"[server]     {scheme}://127.0.0.1:{port}")
    if _tls_enabled:
        fp = cert_fingerprint(_warehouse_dir) or ""
        print(f"[server]     fp={fp}")
    print("=" * 60)
    return _server


def stop_server():
    global _server, _tls_enabled
    if _server is not None:
        try:
            _server.shutdown()
        except Exception:
            pass
        try:
            _server.server_close()
        except Exception:
            pass
        _server = None
    _tls_enabled = False