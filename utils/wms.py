import sys
import os
import json
import sqlite3
import ssl
import urllib.request
import urllib.error

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QStackedWidget, QFrame, QButtonGroup,
    QProgressDialog, QDialog, QLineEdit, QFormLayout, QMessageBox
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QIcon, QPixmap

from db import run_all_migrations
from i18n import (
    set_locale, tr, load_locale_from_db,
    available_locales, locale_display_name,
)
from plugins import PluginManager
from mgmt_client_base import MgmtPageBase

try:
    from server import (
        set_host as server_set_host,
        start_server, stop_server,
    )
except Exception:
    def server_set_host(host):
        pass

    def start_server(db_path, host="0.0.0.0", port=8765, tls=False):
        raise RuntimeError("server module unavailable")

    def stop_server():
        pass


PAGES = [
    ("viewer",        "side.viewer"),
    ("tasks",         "side.tasks"),
    ("items",         "side.items"),
    ("containers",    "side.containers"),
    ("drop_points",   "side.drop_points"),
    ("notifications", "side.notifications"),
    ("settings",      "side.settings"),
    ("employees",     "side.employees"),
    ("managers",      "side.managers"),
    ("plugins",       "side.plugins"),
    ("about",         "side.about"),
]


PAGE_ROLES = {
    "settings":  ("owner", "admin"),
    "employees": ("owner", "admin"),
    "managers":  ("owner",),
    "plugins":   ("owner", "admin"),
}


def _configure_stdio():
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _config_path():
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config.json")


def _load_locale_for(db_path):
    if db_path:
        code = load_locale_from_db(db_path)
        if code:
            return code
    try:
        with open(_config_path(), encoding="utf-8") as f:
            return json.load(f).get("locale", "ru")
    except Exception:
        return "ru"


def _save_last_server(url):
    path = _config_path()
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    cfg["last_server"] = url
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("save last_server:", e)


def _client_ssl_ctx(cert_path):
    """SSLContext для HTTPS-клиента (только указанный серт).

    Возвращает None, если cert_path не задан — тогда
    используется HTTP.
    """
    if not cert_path or not os.path.isfile(cert_path):
        return None
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.load_verify_locations(cafile=cert_path)
        return ctx
    except Exception as e:
        print(f"[wms] ssl ctx: {e}")
        return None


def _mgmt_post(server_url, path, payload, locale="ru",
               timeout=10, cert_path=None):
    payload = dict(payload or {})
    payload["locale"] = locale
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        server_url.rstrip("/") + path,
        data=data,
        headers={
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    ctx = _client_ssl_ctx(cert_path)
    if ctx is not None:
        with urllib.request.urlopen(
                req, timeout=timeout, context=ctx) as resp:
            raw = resp.read().decode("utf-8")
    else:
        with urllib.request.urlopen(
                req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    return json.loads(raw)


class ManagerLoginDialog(QDialog):
    def __init__(self, default_server="http://127.0.0.1:8765",
                 default_locale="ru", parent=None,
                 cert_path=None):
        super().__init__(parent)
        self.setWindowTitle(tr("login.dialog.title",
                               "Луч — Вход в управление складом"))
        self.setMinimumWidth(460)
        self.setModal(True)

        self.token = None
        self.manager_login = None
        self.manager_role = None
        self.warehouse_name = ""
        self.server_url = default_server
        self.locale = default_locale or "ru"
        self.cert_path = cert_path

        base_dir = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        icon_path = os.path.join(base_dir, "icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(12)

        title = QLabel(tr("login.dialog.heading",
                          "Управление складом"))
        title.setFont(QFont("Arial", 16, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        v.addWidget(title)

        hint = QLabel(tr(
            "login.dialog.hint",
            "Войдите как руководитель склада.\n"
            "Учётные записи руководителей создаются владельцем "
            "(owner) в разделе «Руководители»."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#7f8c8d;")
        hint.setAlignment(Qt.AlignCenter)
        v.addWidget(hint)

        form = QFormLayout()
        self.server_edit = QLineEdit(default_server)
        self.login_edit = QLineEdit()
        self.login_edit.setPlaceholderText(
            tr("login.dialog.login_placeholder",
               "Логин руководителя"))
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText(
            tr("login.dialog.password_placeholder", "Пароль"))
        self.password_edit.returnPressed.connect(self._do_login)
        form.addRow(tr("login.dialog.server", "Сервер:"),
                    self.server_edit)
        form.addRow(tr("login.dialog.login", "Логин:"),
                    self.login_edit)
        form.addRow(tr("login.dialog.password", "Пароль:"),
                    self.password_edit)
        v.addLayout(form)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color:#c0392b;")
        self.error_label.setWordWrap(True)
        self.error_label.setAlignment(Qt.AlignCenter)
        v.addWidget(self.error_label)

        btns = QHBoxLayout()
        btns.addStretch()
        self.btn_login = QPushButton(
            tr("login.dialog.enter", "Войти"))
        self.btn_login.setObjectName("primary_btn")
        self.btn_login.clicked.connect(self._do_login)
        self.btn_login.setDefault(True)
        self.btn_cancel = QPushButton(
            tr("login.dialog.cancel", "Отмена"))
        self.btn_cancel.clicked.connect(self.reject)
        btns.addWidget(self.btn_login)
        btns.addWidget(self.btn_cancel)
        v.addLayout(btns)

        self.setStyleSheet("""
            QLineEdit {
                padding: 6px 8px;
                border-radius: 4px;
            }
            QPushButton {
                border-radius: 6px;
                padding: 8px 14px; font-size: 13px;
            }
            QPushButton#primary_btn {
                background-color: #27ae60; color: white;
                border: none; border-radius: 6px;
                padding: 8px 14px; font-weight: bold;
            }
            QPushButton#primary_btn:hover {
                background-color: #2ecc71;
            }
        """)

    def _do_login(self):
        self.error_label.setText("")
        server = self.server_edit.text().strip().rstrip("/")
        login = self.login_edit.text().strip()
        pwd = self.password_edit.text()
        if not server or not login or not pwd:
            self.error_label.setText(tr(
                "login.dialog.fill_all",
                "Заполните все поля."))
            return

        try:
            r = _mgmt_post(server, "/mgmt/login",
                           {"login": login, "secret": pwd},
                           locale=self.locale,
                           cert_path=self.cert_path)
        except urllib.error.URLError as e:
            self.error_label.setText(tr(
                "login.dialog.server_unavailable",
                "Сервер недоступен: {error}",
                error=str(getattr(e, "reason", e))))
            return
        except Exception as e:
            self.error_label.setText(tr(
                "login.dialog.network_error",
                "Ошибка: {error}", error=str(e)))
            return

        if not r.get("ok"):
            err = r.get("error") or "invalid credentials"
            if err == "invalid credentials":
                self.error_label.setText(tr(
                    "login.dialog.invalid_credentials",
                    "Неверный логин или пароль."))
            else:
                self.error_label.setText(str(err))
            return

        token = r.get("token")
        if not token:
            self.error_label.setText(tr(
                "login.dialog.token_missing",
                "Сервер не выдал токен."))
            return

        try:
            me = _mgmt_post(server, "/mgmt/me",
                            {"token": token},
                            locale=self.locale,
                            cert_path=self.cert_path)
        except Exception as e:
            self.error_label.setText(tr(
                "login.dialog.profile_error",
                "Ошибка профиля: {error}", error=str(e)))
            return

        if not me.get("ok"):
            self.error_label.setText(
                me.get("error") or tr(
                    "login.dialog.profile_failed",
                    "Не удалось получить профиль."))
            return

        self.token = token
        self.manager_login = me.get("login") or login
        self.manager_role = me.get("role") or "operator"
        self.warehouse_name = r.get("warehouse") or ""
        self.server_url = server
        self.locale = (r.get("locale") or me.get("locale")
                       or self.locale or "ru")
        self.accept()


class WarehouseApp(QMainWindow):
    def __init__(self, db_path, safe_mode=False,
                 manager_login=None, manager_role=None,
                 manager_token=None, manager_server_url=None,
                 warehouse_name=None,
                 remote_mode=False,
                 locale="ru",
                 tls_enabled=False,
                 cert_path=None):
        super().__init__()
        self.db_path = db_path
        self.safe_mode = safe_mode
        self.manager_login = manager_login
        self.manager_role = manager_role
        self.manager_token = manager_token
        self.manager_server_url = manager_server_url or (
            "" if remote_mode else "http://127.0.0.1:8765")
        self.remote_mode = remote_mode
        self.locale = locale or "ru"
        self._warehouse_name = warehouse_name
        self._tls_enabled = bool(tls_enabled)
        self._cert_path = cert_path

        if not remote_mode and db_path:
            run_all_migrations(db_path)

        if not remote_mode and db_path:
            try:
                start_server(db_path, tls=self._tls_enabled)
            except Exception as e:
                print(f"[wms] сервер не запущен: {e}")

        self.setMinimumSize(900, 600)

        base_dir = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        icon_path = os.path.join(base_dir, "icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = self._build_sidebar()
        layout.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        self.pages = {}
        self.page_buttons = {}
        self.page_button_label_keys = {}
        self.btn_group = QButtonGroup(self)
        self.btn_group.setExclusive(True)

        self._plugin_barcode_callbacks = []
        self._plugin_pages = {}
        self._plugin_step_handlers = []
        self._plugin_endpoints = []
        self._mgmt_plugin_pages = {}
        self._mgmt_plugin_endpoints = []

        if not remote_mode and db_path:
            self.plugin_manager = PluginManager(
                base_dir, db_path, self)
        else:
            self.plugin_manager = None

        if not remote_mode:
            try:
                server_set_host(self)
            except Exception as e:
                print(f"[wms] set_host: {e}")

        progress = QProgressDialog(
            tr("launcher.loading_sections",
               "Загрузка разделов..."),
            None, 0, len(PAGES), self)
        progress.setWindowTitle(
            tr("launcher.loading_title", "Загрузка склада"))
        progress.setWindowModality(Qt.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setCancelButton(None)
        progress.show()
        QApplication.processEvents()

        for i, (key, label_key) in enumerate(PAGES):
            progress.setValue(i)
            progress.setLabelText(
                tr("launcher.loading_prefix", "Загрузка: {name}",
                   name=tr(label_key, key)))
            QApplication.processEvents()
            self._try_register(key, tr(label_key),
                               label_key=label_key)

        progress.setValue(len(PAGES))
        progress.close()

        if self.pages:
            first = next(iter(self.pages))
            self.show_page(first)

        self._apply_styles()
        self._update_window_title()

        if not remote_mode and self.plugin_manager is not None:
            if safe_mode:
                print("[wms] SAFE MODE: плагины не активируются")
            else:
                try:
                    self.plugin_manager.activate_all()
                except Exception as e:
                    print(f"[wms] плагины: {e}")

        QTimer.singleShot(0, self._refresh_pages_from_server)

        self._badge_timer = QTimer(self)
        self._badge_timer.setInterval(10000)
        self._badge_timer.timeout.connect(self._refresh_notif_badge)
        self._badge_timer.start()
        self._refresh_notif_badge()

    def _update_window_title(self):
        if self.remote_mode:
            wh_display = self._warehouse_name or "—"
            title = tr("launcher.client_title_remote",
                       "Луч — {name} [удалённый]",
                       name=wh_display)
            title += f"  {self.manager_server_url}"
        elif self.db_path:
            wh_display = self._warehouse_name or os.path.basename(
                os.path.dirname(os.path.abspath(self.db_path)))
            title = tr("launcher.client_title",
                       "Луч — {name}", name=wh_display)
        else:
            title = tr("launcher.client_title_bare", "Луч")
        if self.manager_login:
            title += f"  [{self.manager_login} / {self.manager_role}]"
        if self.safe_mode:
            title += "  [SAFE MODE]"
        if self._tls_enabled and not self.remote_mode:
            title += "  [TLS]"
        self.setWindowTitle(title)

    def _retranslate_sidebar(self):
        for key, btn in self.page_buttons.items():
            label_key = self.page_button_label_keys.get(key)
            if not label_key:
                continue
            try:
                btn.setText(tr(label_key))
            except Exception:
                pass
        try:
            self._refresh_notif_badge()
        except Exception:
            pass
        try:
            self._update_window_title()
        except Exception:
            pass

    def _on_locale_changed(self, new_locale):
        if not new_locale:
            return
        self.locale = new_locale
        try:
            set_locale(new_locale)
        except Exception:
            pass
        current = self.stack.currentWidget()
        for key, page in self.pages.items():
            if page is current:
                continue
            if hasattr(page, "_loaded"):
                try:
                    page._loaded = False
                except Exception:
                    pass
        self._retranslate_sidebar()

    def _build_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(10, 15, 10, 15)
        layout.setSpacing(4)

        title = QLabel()
        title.setAlignment(Qt.AlignCenter)
        base_dir = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        logo_path = os.path.join(base_dir, "logo_horizontal.png")

        if os.path.exists(logo_path):
            pix = QPixmap(logo_path)
            title.setPixmap(pix.scaledToWidth(
                180, Qt.SmoothTransformation))
        else:
            title.setText(tr("launcher.brand", "ЛУЧ"))
            title.setObjectName("sidebar_title")
            title.setFont(QFont("Arial", 20, QFont.Bold))

        layout.addWidget(title)

        if self.safe_mode:
            safe_badge = QLabel("SAFE MODE")
            safe_badge.setAlignment(Qt.AlignCenter)
            safe_badge.setStyleSheet(
                "background:#f39c12; color:#fff; border-radius:4px; "
                "padding:4px 6px; font-size:10px; font-weight:bold;")
            layout.addWidget(safe_badge)

        if self.remote_mode:
            remote_badge = QLabel(
                f"{tr('launcher.remote_badge', 'REMOTE')}\n"
                f"{self.manager_server_url}")
            remote_badge.setAlignment(Qt.AlignCenter)
            remote_badge.setStyleSheet(
                "background:#2980b9; color:#fff; border-radius:4px; "
                "padding:4px 6px; font-size:10px;")
            layout.addWidget(remote_badge)

        if self.manager_login:
            who = QLabel(f"{self.manager_login}\n{self.manager_role}")
            who.setAlignment(Qt.AlignCenter)
            who.setStyleSheet(
                "color:#ecf0f1; font-size:11px; "
                "background:#34495e; border-radius:4px; "
                "padding:4px 6px;")
            layout.addWidget(who)

        layout.addSpacing(20)
        layout.addStretch()

        self.sidebar_layout = layout
        return sidebar

    def _try_register(self, key, title, label_key=None):
        if key in self.pages:
            return
        required = PAGE_ROLES.get(key)
        if required is not None:
            allowed = required if isinstance(required, tuple) \
                else (required,)
            if self.manager_role not in allowed:
                print(f"[wms] страница {key} недоступна для роли "
                      f"{self.manager_role or '—'}")
                return

        try:
            page = MgmtPageBase(self.db_path, self,
                                page_key=key,
                                cert_path=self._cert_path)
        except Exception as e:
            import traceback
            print(f"[wms] не удалось создать страницу {key}: {e}")
            traceback.print_exc()
            return

        self.pages[key] = page
        self.stack.addWidget(page)

        btn = QPushButton(title)
        btn.setObjectName("sidebar_btn")
        btn.setCheckable(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda _=False, k=key: self.show_page(k))
        self.btn_group.addButton(btn)

        self.sidebar_layout.insertWidget(
            self.sidebar_layout.count() - 1, btn)
        self.page_buttons[key] = btn
        if label_key:
            self.page_button_label_keys[key] = label_key

    def _unregister_page(self, key):
        page = self.pages.pop(key, None)
        btn = self.page_buttons.pop(key, None)
        self.page_button_label_keys.pop(key, None)
        if btn is not None:
            try:
                self.btn_group.removeButton(btn)
                self.sidebar_layout.removeWidget(btn)
                btn.deleteLater()
            except Exception:
                pass
        if page is not None:
            try:
                self.stack.removeWidget(page)
                page.deleteLater()
            except Exception:
                pass

    def _refresh_pages_from_server(self):
        if not self.manager_server_url or not self.manager_token:
            return
        try:
            r = _mgmt_post(
                self.manager_server_url, "/mgmt/pages",
                {"token": self.manager_token}, locale=self.locale,
                cert_path=self._cert_path)
        except Exception as e:
            print(f"[wms] refresh pages: {e}")
            return
        if not r.get("ok"):
            return
        known_keys = {k for k, _ in PAGES}
        for p in r.get("pages") or []:
            key = p.get("key")
            if not key:
                continue
            title = p.get("title") or key
            if key in self.pages:
                continue
            if key in known_keys:
                continue
            self._try_register(key, title)

    def show_page(self, key):
        page = self.pages.get(key)
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        btn = self.page_buttons.get(key)
        if btn:
            btn.setChecked(True)
        if hasattr(page, "on_show"):
            try:
                page.on_show()
            except Exception as e:
                import traceback
                print(f"[wms] on_show({key}): {e}")
                traceback.print_exc()

    def _refresh_notif_badge(self):
        if not self.db_path:
            return
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("""
                SELECT COUNT(*) FROM notifications
                WHERE read_at IS NULL OR read_at=''
            """)
            n = cur.fetchone()[0] or 0
            conn.close()
        except Exception:
            n = 0
        self.update_notif_badge(n)

    def update_notif_badge(self, count):
        key = "notifications"
        btn = self.page_buttons.get(key)
        if not btn:
            return
        base = tr("side.notifications", "🔔  Уведомления")
        if count > 0:
            btn.setText(f"{base}  ({count})")
        else:
            btn.setText(base)

    def _apply_plugin_barcode_buttons(self):
        self._plugin_barcode_callbacks = []
        if self.plugin_manager is None:
            return
        for name, ctx in self.plugin_manager.contexts.items():
            for flt, label, cb in ctx._barcode_buttons:
                self._plugin_barcode_callbacks.append(
                    (name, flt, label, cb))

    def barcode_buttons_for(self, kind):
        result = []
        for name, flt, label, cb in getattr(
                self, "_plugin_barcode_callbacks", []):
            if flt is None or (callable(flt) and flt(kind)):
                result.append((label, cb, kind))
        return result

    def _register_plugin_page(self, plugin_name, key, title,
                              widget_class):
        try:
            page = widget_class(self.db_path, self)
        except Exception as e:
            print(f"[plugins] не создать страницу {key}: {e}")
            return
        full_key = f"plugin:{plugin_name}:{key}"
        self.pages[full_key] = page
        self.stack.addWidget(page)

        btn = QPushButton(title)
        btn.setObjectName("sidebar_btn")
        btn.setCheckable(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(
            lambda _=False, k=full_key: self.show_page(k))
        self.btn_group.addButton(btn)
        self.sidebar_layout.insertWidget(
            self.sidebar_layout.count() - 1, btn)
        self.page_buttons[full_key] = btn
        self._plugin_pages.setdefault(plugin_name, []).append(
            (full_key, btn, page))

    def _remove_plugin_page(self, plugin_name):
        for full_key, btn, page in self._plugin_pages.pop(
                plugin_name, []):
            self.btn_group.removeButton(btn)
            self.sidebar_layout.removeWidget(btn)
            btn.deleteLater()
            self.stack.removeWidget(page)
            page.deleteLater()
            self.pages.pop(full_key, None)
            self.page_buttons.pop(full_key, None)
            self.page_button_label_keys.pop(full_key, None)

    def _register_step_handler(self, plugin_name, step_type,
                               handler, priority):
        self._plugin_step_handlers.append(
            (plugin_name, step_type, handler, priority))

    def _remove_step_handlers(self, plugin_name):
        self._plugin_step_handlers = [
            t for t in self._plugin_step_handlers
            if t[0] != plugin_name
        ]

    def _register_plugin_endpoint(self, plugin_name, path,
                                  handler, methods):
        self._plugin_endpoints.append(
            (plugin_name, path, handler, tuple(methods)))

    def _remove_plugin_endpoints(self, plugin_name):
        self._plugin_endpoints = [
            t for t in self._plugin_endpoints
            if t[0] != plugin_name
        ]

    def _register_mgmt_page(self, plugin_name, key, title,
                            builder, handler=None, roles=None):
        full_key = f"plugin:{plugin_name}:{key}"
        self._mgmt_plugin_pages[full_key] = {
            "title": title,
            "roles": tuple(roles) if roles else None,
            "builder": builder,
            "handler": handler,
            "plugin": plugin_name,
        }
        if self.manager_role is None:
            return
        if roles:
            allowed = roles if isinstance(roles, tuple) else (roles,)
            if self.manager_role not in allowed:
                print(f"[wms] mgmt-страница {full_key} не добавлена "
                      f"в сайдбар: роль {self.manager_role} "
                      f"не в {allowed}")
                return
        self._try_register(full_key, title)

    def _remove_mgmt_page(self, plugin_name):
        to_remove = [k for k, v in self._mgmt_plugin_pages.items()
                     if v.get("plugin") == plugin_name]
        for k in to_remove:
            self._mgmt_plugin_pages.pop(k, None)
            self._unregister_page(k)

    def _register_mgmt_endpoint(self, plugin_name, path,
                                handler, methods):
        self._mgmt_plugin_endpoints.append(
            (plugin_name, path, handler, tuple(methods)))

    def _remove_mgmt_endpoints(self, plugin_name):
        self._mgmt_plugin_endpoints = [
            t for t in self._mgmt_plugin_endpoints
            if t[0] != plugin_name
        ]

    def _apply_styles(self):
        self.setStyleSheet("""
            QFrame#sidebar { background-color: #2c3e50; }
            QLabel#sidebar_title {
                color: #ecf0f1; padding: 8px 0 4px 0;
            }
            QPushButton#sidebar_btn {
                background: transparent; color: #bdc3c7;
                border: none; border-radius: 6px;
                padding: 12px 14px; text-align: left; font-size: 14px;
            }
            QPushButton#sidebar_btn:hover {
                background-color: #34495e; color: #ecf0f1;
            }
            QPushButton#sidebar_btn:checked {
                background-color: #27ae60; color: white;
                font-weight: bold;
            }
            QPushButton#primary_btn {
                background-color: #27ae60; color: white;
                border: none; border-radius: 6px;
                padding: 8px 14px; font-weight: bold;
            }
            QPushButton#primary_btn:hover { background-color: #2ecc71; }
            QPushButton#primary_btn:pressed { background-color: #1e8449; }
            QPushButton#primary_btn:disabled {
                background-color: #bdc3c7; color: #ecf0f1;
            }
            QGroupBox {
                border: 1px solid #dcdcdc; border-radius: 6px;
                margin-top: 12px; padding-top: 8px; font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 10px;
                padding: 0 4px; color: #2c3e50;
            }
            QLineEdit, QTextEdit {
                padding: 6px 8px; border: 1px solid #ccc;
                border-radius: 4px;
            }
            QLineEdit:focus, QTextEdit:focus { border-color: #27ae60; }

            QTableWidget {
                gridline-color: #eaeaea;
                selection-background-color: #27ae60;
                selection-color: white;
                outline: 0;
            }
            QTableView { outline: 0; }
            QTableView::item {
                padding: 0px; margin: 0px;
                border: none;
                background: transparent;
            }
            QTableView::item:focus {
                border: none;
                outline: none;
                background: transparent;
            }
            QTableView::item:selected:active {
                background-color: #27ae60;
                color: white;
            }
            QTableView::item:selected:!active {
                background-color: #27ae60;
                color: white;
            }
            QHeaderView::section {
                background-color: #e67e22; color: white;
                padding: 6px; border: none;
                border-right: 1px solid #d35400;
                border-bottom: 1px solid #d35400;
                font-weight: bold;
            }
            QTableCornerButton::section {
                background-color: #e67e22; border: none;
                border-right: 1px solid #d35400;
                border-bottom: 1px solid #d35400;
            }
        """)


def main():
    _configure_stdio()

    app = QApplication(sys.argv)

    base_dir = os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))
    icon_path = os.path.join(base_dir, "icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    args = sys.argv[1:]

    server_url = None
    wh_path = None
    safe_mode = "--safe" in args
    force_tls = "--tls" in args
    cli_locale = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--server" and i + 1 < len(args):
            server_url = args[i + 1]
            i += 2
            continue
        if a == "--locale" and i + 1 < len(args):
            cli_locale = args[i + 1]
            i += 2
            continue
        if not a.startswith("-") and wh_path is None:
            wh_path = a
        i += 1

    def _pick_locale(db_path):
        if cli_locale and cli_locale in available_locales():
            return cli_locale
        return _load_locale_for(db_path)

    def _resolve_tls(wh_path_, force):
        if not wh_path_:
            return False
        db_path_ = os.path.join(wh_path_, "warehouse.db")
        if not os.path.isfile(db_path_):
            return False
        if force:
            enabled = True
        else:
            try:
                conn = sqlite3.connect(db_path_)
                cur = conn.cursor()
                cur.execute(
                    "SELECT value FROM settings "
                    "WHERE key='tls_enabled'")
                r = cur.fetchone()
                conn.close()
                enabled = bool(r) and str(r[0]) == "1"
            except Exception:
                enabled = False
        if not enabled:
            return False
        cert = os.path.join(wh_path_, "tls", "cert.pem")
        if not os.path.isfile(cert):
            try:
                from tls import generate_cert
                print("[wms] TLS: сертификат не найден — генерирую")
                generate_cert(wh_path_)
            except Exception as e:
                print(f"[wms] TLS: {e}. Стартуем без TLS")
                return False
        return True

    if server_url:
        db_path = None
        if wh_path:
            candidate = os.path.join(wh_path, "warehouse.db")
            if os.path.isfile(candidate):
                db_path = candidate

        loc = _pick_locale(db_path)
        set_locale(loc)

        tls_enabled = _resolve_tls(wh_path, force_tls) \
            if wh_path else server_url.startswith("https://")
        cert_path = None
        if tls_enabled and wh_path:
            cert_path = os.path.join(wh_path, "tls", "cert.pem")

        if tls_enabled and not server_url.startswith("https://"):
            # URL пришёл http://, но --tls — принудительно https.
            server_url = server_url.replace("http://", "https://", 1)

        dlg = ManagerLoginDialog(default_server=server_url,
                                 default_locale=loc,
                                 cert_path=cert_path)
        if dlg.exec() != QDialog.Accepted:
            sys.exit(0)

        _save_last_server(dlg.server_url)
        set_locale(dlg.locale)

        window = WarehouseApp(
            db_path, safe_mode=False,
            manager_login=dlg.manager_login,
            manager_role=dlg.manager_role,
            manager_token=dlg.token,
            manager_server_url=dlg.server_url,
            warehouse_name=dlg.warehouse_name,
            remote_mode=True,
            locale=dlg.locale,
            tls_enabled=tls_enabled,
            cert_path=cert_path,
        )
        window.show()
        sys.exit(app.exec())

    if not wh_path:
        print("Использование: wms.py <папка_склада> [--safe] "
              "[--tls] [--locale <code>]")
        print("              wms.py --server URL [<папка_склада>] "
              "[--locale <code>] [--tls]")
        sys.exit(1)
    if not os.path.isdir(wh_path):
        print(f"Папка склада не найдена: {wh_path}")
        sys.exit(1)
    db_path = os.path.join(wh_path, "warehouse.db")
    if not os.path.isfile(db_path):
        print(f"Файл warehouse.db не найден в папке: {wh_path}")
        sys.exit(1)

    loc = _pick_locale(db_path)
    set_locale(loc)
    run_all_migrations(db_path)

    tls_enabled = _resolve_tls(wh_path, force_tls)
    cert_path = None
    if tls_enabled:
        cert_path = os.path.join(wh_path, "tls", "cert.pem")

    manager_login = None
    manager_role = None
    manager_token = None
    if tls_enabled:
        manager_server_url = "https://127.0.0.1:8765"
    else:
        manager_server_url = "http://127.0.0.1:8765"

    try:
        start_server(db_path, tls=tls_enabled)
    except Exception as e:
        QMessageBox.critical(
            None, tr("launcher.error", "Ошибка"),
            tr("launcher.error.server_start",
               "Не удалось запустить встроенный сервер:\n{error}",
               error=str(e)))
        sys.exit(1)

    dlg = ManagerLoginDialog(default_server=manager_server_url,
                             default_locale=loc,
                             cert_path=cert_path)
    if dlg.exec() != QDialog.Accepted:
        try:
            stop_server()
        except Exception:
            pass
        sys.exit(0)
    manager_login = dlg.manager_login
    manager_role = dlg.manager_role
    manager_token = dlg.token
    manager_server_url = dlg.server_url
    set_locale(dlg.locale)

    wh_name = os.path.basename(wh_path)

    window = WarehouseApp(
        db_path, safe_mode=safe_mode,
        manager_login=manager_login,
        manager_role=manager_role,
        manager_token=manager_token,
        manager_server_url=manager_server_url,
        warehouse_name=wh_name,
        remote_mode=False,
        locale=dlg.locale,
        tls_enabled=tls_enabled,
        cert_path=cert_path,
    )
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()