"""HTTP/HTTPS-клиент для ПК-терминала."""

import requests

from config import (
    load_config, save_config,
    get_tls_cache, set_tls_cache,
)
from tls_client import (
    fingerprint_of_pem, fetch_peer_cert,
    write_cert_file, split_host_port,
    cert_file_path,
)


class ApiError(Exception):
    def __init__(self, message, is_network=False,
                 role_revoked=False):
        super().__init__(message)
        self.is_network = is_network
        self.role_revoked = role_revoked


def humanize_error(err_text):
    if not err_text:
        return err_text
    low = str(err_text).lower()
    network_markers = (
        "connection refused", "connectionerror",
        "failed to establish", "no route to host",
        "getaddrinfo", "name or service not known",
        "network is unreachable", "connection aborted",
        "connection reset", "connection timed out",
        "max retries exceeded", "certificate",
    )
    if any(m in low for m in network_markers):
        return "__HUMAN_NETWORK_UNAVAILABLE__"
    if "timeout" in low or "timed out" in low:
        return "__HUMAN_NETWORK_TIMEOUT__"
    return err_text


class ViewMeta:
    def __init__(self, **kw):
        self.task_id = kw.get("task_id", 0)
        self.task_type = kw.get("task_type", "")
        self.task_number = kw.get("task_number", "")
        self.status = kw.get("status", "in_progress")
        self.step_no = kw.get("step_no", 0)
        self.total_steps = kw.get("total_steps", 0)
        self.finished = bool(kw.get("finished", False))
        self.pending_action = kw.get("pending_action", "")
        self.pending_cell = kw.get("pending_cell", "")
        self.batch_id = kw.get("batch_id", "")
        self.block_bf = kw.get("block_bf", "")
        self.batch_position = kw.get("batch_position", 0)
        self.batch_total = kw.get("batch_total", 0)
        self.partial = int(kw.get("partial", 0))
        self.progress_a = kw.get("progress_a", 0)
        self.progress_a_max = kw.get("progress_a_max", 0)
        self.progress_b = kw.get("progress_b", 0)
        self.progress_b_max = kw.get("progress_b_max", 0)


class SessionMeta:
    def __init__(self, **kw):
        self.session_key = kw.get("session_key", "")
        self.session_title = kw.get("session_title", "")
        self.state = kw.get("state") or {}


class NotFoundResult:
    def __init__(self, **kw):
        self.result = kw.get("result", "")
        self.message = kw.get("message", "")
        self.new_cell = kw.get("new_cell", "")
        self.new_task_number = kw.get("new_task_number", "")


class NotificationItem:
    def __init__(self, **kw):
        self.id = kw.get("id", 0)
        self.message = kw.get("message", "")
        self.type = kw.get("type", "info")
        self.created_at = kw.get("created_at", "")
        self.sender_login = kw.get("sender_login", "")
        self.task_id = kw.get("task_id", 0)


class SessionInfo:
    def __init__(self, key="", title=""):
        self.key = key
        self.title = title


def parse_view_node(raw):
    if not isinstance(raw, dict):
        return None
    node = dict(raw)
    children_raw = raw.get("children") or []
    node["children"] = [
        parse_view_node(c) for c in children_raw
        if isinstance(c, dict)
    ]
    return node


class Api:
    def __init__(self, base_url=""):
        self.base = base_url.rstrip("/")
        self.token = None
        self.login = ""
        self.settings = {}
        self.locale = "ru"
        self.client = requests.Session()
        self.client.headers.update({
            "Content-Type": "application/json; charset=utf-8",
        })
        cfg = load_config()
        self.locale = cfg.get("locale", "ru")

    def has_saved_cert(self, url):
        cfg = load_config()
        return get_tls_cache(cfg, url) is not None

    def set_base(self, url, fp=None):
        """Устанавливает базовый URL.

        Для HTTPS:
          - если серт уже сохранён и fp в QR не передан
            или совпадает — используем сохранённый;
          - если серт сохранён, но fp другой — TOFU
            (перевыпуск);
          - если серта нет, но fp передан — TOFU;
          - если серта нет и fp нет — ошибка.

        Для HTTP — TLS отключается.
        """
        url = (url or "").rstrip("/")
        if url.startswith("https://"):
            self._apply_https(url, fp)
        else:
            self._disable_tls()

        self.base = url
        self.settings = {}

    def _apply_https(self, url, qr_fp):
        cfg = load_config()
        cached = get_tls_cache(cfg, url)

        if cached:
            pem = cached.get("pem") or ""
            saved_fp = cached.get("fp") or ""
            if not pem:
                raise ApiError(
                    "TLS: сохранённый сертификат пуст. "
                    "Удалите config.json и отсканируйте QR заново.")
            try:
                actual_fp = fingerprint_of_pem(pem)
            except Exception as e:
                raise ApiError(
                    f"TLS: повреждён сохранённый сертификат: {e}")
            if actual_fp != saved_fp:
                raise ApiError(
                    "TLS: локальный сертификат повреждён "
                    "(fp не совпадает). Удалите config.json "
                    "и отсканируйте QR заново.")

            if qr_fp and qr_fp != saved_fp:
                # Сервер перевыпустил серт — TOFU заново.
                self._tofu(url, qr_fp, cfg)
                return

            write_cert_file(url, pem)
            p = cert_file_path(url)
            if not p:
                raise ApiError(
                    "TLS: не удалось сохранить сертификат "
                    "(нет доступа к папке .certs).")
            self.client.verify = p
            return

        # Сохранённого серта нет.
        if not qr_fp:
            raise ApiError(
                "TLS: сервер использует HTTPS, но в QR нет "
                "fingerprint. Отсканируйте QR со страницы "
                "«Задания» в ПК-клиенте управления.")
        self._tofu(url, qr_fp, cfg)

    def _tofu(self, url, expected_fp, cfg):
        host, port = split_host_port(url)
        try:
            pem = fetch_peer_cert(host, port, timeout=5)
        except Exception as e:
            raise ApiError(
                f"Не удалось получить сертификат сервера: {e}")
        if not pem:
            raise ApiError(
                "Сервер не вернул сертификат (TLS handshake).")
        try:
            actual_fp = fingerprint_of_pem(pem)
        except Exception as e:
            raise ApiError(f"Некорректный сертификат: {e}")
        if actual_fp != expected_fp:
            raise ApiError(
                "Сертификат сервера не совпадает с QR. "
                "Возможна MITM-атака. Не подключайтесь. "
                "Если сервер действительно перевыпустил "
                "сертификат — отсканируйте новый QR.")
        set_tls_cache(cfg, url, actual_fp, pem)
        save_config(cfg)
        write_cert_file(url, pem)
        p = cert_file_path(url)
        if not p:
            raise ApiError(
                "TLS: не удалось сохранить сертификат "
                "(нет доступа к папке .certs).")
        self.client.verify = p

    def _disable_tls(self):
        # HTTP — обычная проверка системных CA не мешает.
        self.client.verify = True

    def _post(self, path, payload, timeout=15):
        payload["locale"] = self.locale
        try:
            r = self.client.post(
                self.base + path, json=payload, timeout=timeout)
        except requests.exceptions.SSLError as e:
            raise ApiError(
                "Сертификат сервера не соответствует "
                "сохранённому. Если сервер перевыпущен — "
                "отсканируйте новый QR.", is_network=True)
        except requests.ConnectionError as e:
            raise ApiError(str(e), is_network=True)
        except requests.Timeout as e:
            raise ApiError(str(e), is_network=True)
        except requests.RequestException as e:
            raise ApiError(str(e), is_network=True)

        if r.status_code >= 400:
            try:
                data = r.json()
                if isinstance(data, dict) and data.get("error"):
                    raise ApiError(str(data["error"]),
                                   is_network=False)
            except ValueError:
                pass
            raise ApiError(f"HTTP {r.status_code}",
                           is_network=False)

        try:
            return r.json()
        except ValueError as e:
            raise ApiError(f"invalid JSON: {e}",
                           is_network=False)

    def set_locale(self, locale):
        self.locale = locale
        cfg = load_config()
        cfg["locale"] = locale
        save_config(cfg)

    def _with_token(self, **extra):
        d = {"token": self.token}
        d.update(extra)
        return d

    def ping(self):
        try:
            r = self._post("/ping", {})
            return r.get("ok") is True
        except Exception:
            return False

    def login_user(self, login, secret):
        r = self._post("/login",
                       {"login": login, "secret": secret})
        if r.get("ok") is True:
            self.token = r.get("token")
            self.login = login
            return True, None
        return False, r.get("error") or "invalid"

    def logout(self):
        try:
            if self.token:
                self._post("/logout", {"token": self.token},
                           timeout=5)
        except Exception:
            pass
        self.token = None
        self.login = ""

    def me(self):
        r = self._post("/employees/me", self._with_token())
        if r.get("ok") is not True:
            return {"ok": False, "fio": "—",
                    "login": "", "roles": []}
        return {
            "ok": True,
            "fio": r.get("fio") or "—",
            "login": r.get("login") or "",
            "roles": r.get("roles") or [],
        }

    def load_settings(self):
        try:
            r = self._post("/settings", self._with_token(),
                           timeout=8)
        except ApiError:
            return False
        if r.get("ok") is True:
            self.settings = r.get("settings") or {}
            return True
        return False

    def capabilities_hello(self, protocol="1.0", widgets=None,
                           actions=None, features=None,
                           device="pc"):
        r = self._post("/capabilities/hello", {
            "protocol": protocol,
            "widgets": widgets or [],
            "actions": actions or [],
            "features": features or [],
            "device": device,
        })
        return r.get("ok") is True

    def ui_config_version(self, local_version="", timeout=3):
        try:
            r = self._post(
                "/ui_config/version",
                {"version": local_version},
                timeout=timeout)
        except ApiError:
            return None, False
        if r.get("ok") is not True:
            return None, False
        return r.get("version") or "", bool(r.get("changed"))

    def ui_config(self, timeout=5):
        try:
            r = self._post("/ui_config", {}, timeout=timeout)
        except ApiError:
            return None, None
        if r.get("ok") is not True:
            return None, None
        return r.get("version") or "", r.get("config") or {}

    def sessions_list(self):
        r = self._post("/sessions/list",
                       self._with_token(device="pc"))
        if r.get("ok") is not True:
            return []
        items = r.get("sessions") or []
        return [SessionInfo(
            key=n.get("key") or "",
            title=n.get("title") or "",
        ) for n in items if n.get("key")]

    def sessions_start(self, key, payload=None):
        body = self._with_token(payload=payload or {},
                                device="pc")
        r = self._post(f"/sessions/{key}/start", body)
        return self._parse_session_envelope(r)

    def sessions_action(self, key, action_id, value=None):
        body = {"token": self.token, "id": action_id,
                "device": "pc"}
        if value is not None:
            body["value"] = value
        r = self._post(f"/sessions/{key}/action", body)
        return self._parse_session_envelope(r)

    def sessions_close(self, key, force=False):
        body = self._with_token(device="pc")
        if force:
            body["force"] = True
        r = self._post(f"/sessions/{key}/close", body)
        if r.get("ok") is not True:
            raise ApiError(
                r.get("error") or "Не удалось закрыть сессию")
        return True

    def task_next(self, platform="pc"):
        r = self._post("/tasks/next",
                       self._with_token(platform=platform))
        if r.get("ok") is not True:
            err = r.get("error") or "Ошибка"
            return None, err
        task = r.get("task") or {}
        items = r.get("items") or []
        return {"task": task, "items": items}, None

    def task_view(self, task_id):
        r = self._post(f"/tasks/{task_id}/view",
                       self._with_token())
        return self._parse_envelope(r)

    def task_status(self, task_id):
        try:
            r = self._post(f"/tasks/{task_id}/status",
                           self._with_token())
        except ApiError:
            return {"exists": True, "status": "",
                    "assignee_login": ""}
        if r.get("ok") is not True:
            return {"exists": True, "status": "",
                    "assignee_login": ""}
        return {
            "exists": r.get("exists"),
            "status": r.get("status") or "",
            "assignee_login": r.get("assignee_login") or "",
        }

    def task_action(self, task_id, action, action_id=None,
                    value=None, step_no=None):
        body = {"token": self.token, "action": action}
        if action_id is not None:
            body["id"] = action_id
        if value is not None:
            body["value"] = value
        if step_no is not None:
            body["step_no"] = step_no
        r = self._post(f"/tasks/{task_id}/action", body)
        return self._parse_envelope(r)

    def task_report(self, task_id):
        return self._post(f"/tasks/{task_id}/report",
                          self._with_token())

    def notifications_inbox(self):
        r = self._post("/notifications/inbox", self._with_token())
        if r.get("ok") is not True:
            return []
        items = r.get("notifications") or []
        return [NotificationItem(
            id=n.get("id", 0),
            message=n.get("message") or "",
            type=n.get("type") or "info",
            created_at=n.get("created_at") or "",
            sender_login=n.get("sender_login") or "",
            task_id=n.get("task_id") or 0,
        ) for n in items]

    def notifications_mark_read(self, ids):
        if not ids:
            return True
        r = self._post("/notifications/mark_read",
                       self._with_token(ids=list(ids)))
        return r.get("ok") is True

    def _parse_common(self, r):
        view = r.get("view") or {}
        children = view.get("children") or []
        nodes = [parse_view_node(c) for c in children
                 if isinstance(c, dict)]
        nf = None
        nf_raw = r.get("not_found_result")
        if isinstance(nf_raw, dict):
            nf = NotFoundResult(**nf_raw)
        return nodes, r.get("message") or "", nf

    def _parse_envelope(self, r):
        if r.get("ok") is not True:
            err = r.get("error") or "Ошибка"
            raise ApiError(err)
        nodes, message, nf = self._parse_common(r)
        meta_raw = r.get("meta") or {}
        prog = meta_raw.get("progress") or {}
        meta = ViewMeta(
            task_id=meta_raw.get("task_id", 0),
            task_type=meta_raw.get("task_type", ""),
            task_number=meta_raw.get("task_number", ""),
            status=meta_raw.get("status", "in_progress"),
            step_no=meta_raw.get("step_no", 0),
            total_steps=meta_raw.get("total_steps", 0),
            finished=meta_raw.get("finished", False),
            pending_action=meta_raw.get("pending_action", ""),
            pending_cell=meta_raw.get("pending_cell", ""),
            batch_id=meta_raw.get("batch_id", ""),
            block_bf=meta_raw.get("block_bf", ""),
            batch_position=meta_raw.get("batch_position", 0),
            batch_total=meta_raw.get("batch_total", 0),
            partial=meta_raw.get("partial", 0),
            progress_a=prog.get("a", 0),
            progress_a_max=prog.get("a_max", 0),
            progress_b=prog.get("b", 0),
            progress_b_max=prog.get("b_max", 0),
        )
        return {
            "ok": True,
            "nodes": nodes,
            "meta": meta,
            "message": message,
            "not_found_result": nf,
        }

    def _parse_session_envelope(self, r):
        if r.get("ok") is not True:
            raise ApiError(
                r.get("error") or "Ошибка",
                role_revoked=bool(r.get("role_revoked")))
        nodes, message, _ = self._parse_common(r)
        meta_raw = r.get("meta") or {}
        meta = SessionMeta(
            session_key=meta_raw.get("session_key", ""),
            session_title=meta_raw.get("session_title", ""),
            state=meta_raw.get("state") or {},
        )
        return {
            "ok": True,
            "nodes": nodes,
            "meta": meta,
            "message": message,
            "role_revoked": bool(r.get("role_revoked")),
        }


def _parse_locales(cfg):
    loc = (cfg or {}).get("locales") or {}
    available = loc.get("available") or []
    data = loc.get("data") or {}
    out = {}
    for info in available:
        if not isinstance(info, dict):
            continue
        code = info.get("code")
        if not code:
            continue
        out[code] = {
            "name": info.get("name") or code.upper(),
            "rtl": bool(info.get("rtl")),
            "fallback": info.get("fallback"),
            "data": data.get(code) or {},
        }
    return out