"""Базовый класс тонкой mgmt-страницы ПК-клиента управления.

Реальный HTTP-клиент: по PAGE_KEY шлёт POST на /mgmt/page/{key}
и рендерит ответ через MgmtRenderer. Один экземпляр на страницу.

Пример:
    page = MgmtPageBase(db_path, host, page_key="viewer")
"""

import json
import traceback
import urllib.request
import urllib.error

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QScrollArea, QFrame,
)

from mgmt_render import MgmtRenderer


class MgmtPageBase(QWidget):
    PAGE_KEY = ""

    def __init__(self, db_path, parent=None, page_key=None):
        super().__init__(parent)
        self.db_path = db_path
        self.host = parent
        if page_key:
            self.PAGE_KEY = page_key
        self._loaded = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)

        v = QVBoxLayout(content)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(10)

        self.status = QLabel("Загрузка…")
        self.status.setStyleSheet("color:#7f8c8d;")
        self.status.setWordWrap(True)
        v.addWidget(self.status)

        self.renderer = MgmtRenderer()
        self.renderer.action_clicked.connect(self._on_action)
        v.addWidget(self.renderer, 1)

    def on_show(self):
        if not self._loaded:
            self._load()

    def _server_url(self):
        url = getattr(self.host, "manager_server_url", None)
        if not url:
            url = "http://127.0.0.1:8765"
        return url.rstrip("/")

    def _token(self):
        return getattr(self.host, "manager_token", None)

    def _locale(self):
        if self.host is not None:
            return getattr(self.host, "locale", "ru") or "ru"
        return "ru"

    def _apply_locale_from(self, r):
        if not isinstance(r, dict) or self.host is None:
            return
        new_loc = r.get("locale")
        if not new_loc:
            return
        if new_loc == self._locale():
            return
        try:
            self.host.locale = new_loc
        except Exception:
            pass
        try:
            from i18n import set_locale
            set_locale(new_loc)
        except Exception:
            pass
        try:
            cb = getattr(self.host, "_on_locale_changed", None)
            if callable(cb):
                cb(new_loc)
        except Exception:
            pass

    def _post(self, path, payload):
        payload = dict(payload or {})
        payload["token"] = self._token()
        payload["locale"] = self._locale()
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._server_url() + path,
            data=data,
            headers={"Content-Type":
                     "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _handle_http_error(self, e):
        """Пытаемся вытащить осмысленную ошибку из тела
        ответа сервера (JSON с полем error). Иначе — str(e)."""
        msg = str(e)
        try:
            body = e.read().decode("utf-8")
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                msg = parsed.get("error") or msg
        except Exception:
            pass
        self.status.setText(f"Ошибка: {msg}")
        self.status.setVisible(True)

    def _load(self):
        token = self._token()
        if not token:
            self.status.setText(
                "Нет токена — запустите склад с логином "
                "руководителя.")
            self.status.setVisible(True)
            return

        try:
            r = self._post("/mgmt/page/" + self.PAGE_KEY, {})
        except urllib.error.HTTPError as e:
            # HTTPError — подкласс URLError, ловим первым!
            self._handle_http_error(e)
            return
        except urllib.error.URLError as e:
            self.status.setText(
                f"Сервер недоступен: {getattr(e, 'reason', e)}")
            self.status.setVisible(True)
            return
        except Exception as e:
            traceback.print_exc()
            self.status.setText(f"Ошибка загрузки: {e}")
            self.status.setVisible(True)
            return

        self._apply_locale_from(r)

        if not r.get("ok"):
            self.status.setText(
                str(r.get("error") or "Не удалось загрузить раздел."))
            self.status.setVisible(True)
            return

        view = r.get("view") or {}
        self.renderer.set_document(view)
        self.status.setVisible(False)
        self._loaded = True

    def _on_action(self, action, action_id, value, values):
        token = self._token()
        if not token:
            return
        payload = {
            "action": action,
            "id": action_id,
            "value": value,
            "values": values or {},
        }
        try:
            r = self._post(
                "/mgmt/page/" + self.PAGE_KEY + "/action", payload)
        except urllib.error.HTTPError as e:
            self._handle_http_error(e)
            return
        except urllib.error.URLError as e:
            self.status.setText(
                f"Сервер недоступен: {getattr(e, 'reason', e)}")
            self.status.setVisible(True)
            return
        except Exception as e:
            traceback.print_exc()
            self.status.setText(f"Ошибка: {e}")
            self.status.setVisible(True)
            return

        self._apply_locale_from(r)

        if not r.get("ok"):
            self.status.setText(
                str(r.get("error") or "Ошибка действия."))
            self.status.setVisible(True)
            return

        msg = r.get("message") or ""
        if msg:
            self.status.setText(msg)
            self.status.setVisible(True)
        else:
            self.status.setVisible(False)

        view = r.get("view")
        if view:
            self.renderer.set_document(view)