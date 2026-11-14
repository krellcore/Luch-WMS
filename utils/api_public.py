"""Публичный фасад для плагинов."""

import json
import sqlite3
import traceback
from datetime import datetime

from plugin_hooks import registry, KNOWN_HOOKS


API_VERSION = "1.0"


class PublicContext:
    def __init__(self, name, db_path, host, info=None):
        self.name = name
        self.db_path = db_path
        self.host = host
        self.info = info or {}
        self.api_version = API_VERSION

        self._barcode_buttons = []
        self._pages = []
        self._endpoints = []
        self._step_handlers = []
        self._mgmt_pages = []
        self._mgmt_endpoints = []
        self._menu_items = []

    def log(self, msg):
        print(f"[plugin:{self.name}] {msg}")

    def tr(self, key, **kwargs):
        from i18n import tr_fallback
        return tr_fallback(
            [f"plugin.{self.name}.{key}", key], **kwargs)

    def tr_in(self, locale, key, **kwargs):
        try:
            from i18n import tr_in, _resolve as _res
            scoped = f"plugin.{self.name}.{key}"
            if _res(locale, scoped) is not None:
                return tr_in(locale, scoped, **kwargs)
            return tr_in(locale, key, **kwargs)
        except Exception:
            return key

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

    def get_setting(self, key, default=None):
        r = self.query_one(
            "SELECT value FROM settings WHERE key=?", (key,))
        if r is None:
            return default
        return r["value"]

    def set_setting(self, key, value):
        conn = self.db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM settings WHERE key=?", (key,))
            if cur.fetchone():
                cur.execute("UPDATE settings SET value=? WHERE key=?",
                            (str(value), key))
            else:
                cur.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?)",
                    (key, str(value)))
            conn.commit()
        finally:
            conn.close()

    def hook(self, name, priority=0):
        def _decorator(func):
            registry.register(self.name, name, func, priority=priority)
            self.log(f"hook '{name}' зарегистрирован "
                     f"(priority={priority})")
            return func
        return _decorator

    def get_task(self, task_id):
        return self.query_one(
            "SELECT * FROM tasks WHERE id=?", (task_id,))

    def get_items(self, task_id):
        return self.query(
            "SELECT * FROM task_items WHERE task_id=? "
            "ORDER BY step_no, id", (task_id,))

    def get_cell(self, barcode):
        return self.query_one(
            "SELECT * FROM cells WHERE barcode=?", (barcode,))

    def get_item(self, item_code):
        return self.query_one(
            "SELECT * FROM item_characteristics WHERE item_code=?",
            (item_code,))

    def find_cells_with_item(self, item_code, exclude_cell=None):
        sql = ("SELECT cell_barcode, SUM(quantity) AS qty "
               "FROM placed_instances WHERE item_code=? "
               "AND cell_barcode IS NOT NULL AND cell_barcode != '' ")
        params = [item_code]
        if exclude_cell:
            sql += "AND cell_barcode != ? "
            params.append(exclude_cell)
        sql += "GROUP BY cell_barcode HAVING qty > 0"
        return self.query(sql, params)

    def notify(self, message, type="info", recipient_login="",
               recipient_role="", task_id=None, payload=None):
        now = datetime.now().isoformat()
        payload_txt = json.dumps(payload or {}, ensure_ascii=False)

        conn = self.db()
        try:
            cur = conn.cursor()
            if recipient_role:
                cur.execute("SELECT login, role, roles FROM employees")
                logins = []
                for row in cur.fetchall():
                    try:
                        roles = json.loads(row["roles"] or "[]") \
                            if "roles" in row.keys() else []
                    except Exception:
                        roles = []
                    if not roles:
                        role = row["role"] if "role" in row.keys() \
                            else None
                        roles = [role] if role else []
                    if recipient_role in roles:
                        logins.append(row["login"])
                for lg in logins:
                    cur.execute("""
                        INSERT INTO notifications
                            (task_id, message, created_at, sender_login,
                             type, recipient_login, read_at, payload)
                        VALUES (?, ?, ?, ?, ?, ?, '', ?)
                    """, (task_id, message, now, self.name, type, lg,
                          payload_txt))
            else:
                cur.execute("""
                    INSERT INTO notifications
                        (task_id, message, created_at, sender_login,
                         type, recipient_login, read_at, payload)
                    VALUES (?, ?, ?, ?, ?, ?, '', ?)
                """, (task_id, message, now, self.name, type,
                      recipient_login or "", payload_txt))
            conn.commit()
        finally:
            conn.close()

        registry.call_event(
            "on_notification_sent",
            sender=self.name, message=message, type=type,
            recipient_login=recipient_login,
            recipient_role=recipient_role,
        )

    def add_barcode_button(self, label, callback, panel_filter=None):
        self._barcode_buttons.append((panel_filter, label, callback))

    def register_page(self, key, title, widget_class):
        self._pages.append((key, title, widget_class))
        if hasattr(self.host, "_register_plugin_page"):
            self.host._register_plugin_page(self.name, key, title,
                                            widget_class)

    def register_task_handler(self, handler_instance):
        try:
            from tasks import register_instance
            register_instance(handler_instance)
            self.log(f"handler зарегистрирован: "
                     f"{handler_instance.task_type}")
        except Exception as e:
            traceback.print_exc()
            self.log(f"register_task_handler: {e}")

    def register_session(self, session_instance):
        try:
            from sessions import register_instance as reg_sess
            reg_sess(session_instance)
            self.log(f"сессия зарегистрирована: "
                     f"{session_instance.key}")
        except ImportError:
            self.log("sessions пока не реализованы")
        except Exception as e:
            traceback.print_exc()
            self.log(f"register_session: {e}")

    def register_step_handler(self, step_type, handler, priority=0):
        self._step_handlers.append((step_type, handler, priority))
        if hasattr(self.host, "_register_step_handler"):
            self.host._register_step_handler(self.name, step_type,
                                             handler, priority)

    def register_endpoint(self, path, handler, methods=("POST",)):
        self._endpoints.append((path, handler, methods))
        if hasattr(self.host, "_register_plugin_endpoint"):
            self.host._register_plugin_endpoint(self.name, path,
                                                handler, methods)

    def register_role(self, key, title_key=None, title=None,
                      task_types=()):
        try:
            from roles import register as _reg_role
        except Exception as e:
            self.log(f"register_role: {e}")
            return
        prefixed = (f"plugin.{self.name}.{title_key}"
                    if title_key else None)
        _reg_role(
            key,
            title_key=prefixed,
            title=title or key,
            task_types=tuple(task_types or ()),
            plugin_name=self.name,
        )
        self.log(f"role registered: {key}")

    def register_mgmt_page(self, key, title, builder,
                           handler=None, roles=None):
        item = (key, title, builder, handler, roles)
        self._mgmt_pages.append(item)
        if hasattr(self.host, "_register_mgmt_page"):
            try:
                self.host._register_mgmt_page(
                    self.name, key, title, builder, handler, roles)
            except Exception as e:
                self.log(f"register_mgmt_page({key}): {e}")

    def register_mgmt_endpoint(self, path, handler,
                                methods=("POST",)):
        self._mgmt_endpoints.append((path, handler, tuple(methods)))
        if hasattr(self.host, "_register_mgmt_endpoint"):
            try:
                self.host._register_mgmt_endpoint(
                    self.name, path, handler, tuple(methods))
            except Exception as e:
                self.log(f"register_mgmt_endpoint({path}): {e}")

    def register_menu_item(self, item_id, title, builder, roles=None):
        self._menu_items.append((item_id, title, builder, roles))
        try:
            from menu import register as _reg
            _reg(item_id, title=title, builder=builder,
                 roles=roles, plugin_name=self.name)
            self.log(f"menu item registered: {item_id}")
        except Exception as e:
            traceback.print_exc()
            self.log(f"register_menu_item({item_id}): {e}")