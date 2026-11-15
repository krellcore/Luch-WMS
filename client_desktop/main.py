"""ПК-клиент WMS — универсальный терминал."""

import base64
import json
import sys
import os
import re
import time

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QStackedWidget, QMessageBox, QFrame,
    QScrollArea, QGridLayout, QProgressBar, QLineEdit, QComboBox,
    QDialog, QDialogButtonBox, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QHeaderView, QListWidget, QListWidgetItem,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import (
    QFont, QPixmap, QPalette, QColor, QIcon,
)

from api import (
    Api, ApiError, ViewMeta, SessionMeta, NotificationItem,
    SessionInfo, parse_view_node, humanize_error, _parse_locales,
)
from scanner import ScannerBridge
from config import (
    load_config, save_config,
    get_ui_cache, set_ui_cache,
    get_settings_cache, set_settings_cache,
    get_tls_cache,
)


def _find_asset(name):
    here = os.path.dirname(os.path.abspath(__file__))
    for base in (here, os.path.dirname(here)):
        path = os.path.join(base, name)
        if os.path.exists(path):
            return path
    return None


# ================================================================
# Встроенные fallback-переводы (ru/en) — без изменений.
# ================================================================
_T = {
    "ru": {
        "title": "Луч — терминал",
        "login_server_prompt": "Отсканируйте QR-код сервера",
        "login_server_hint": "(QR находится в разделе «Задания» в панели «ШК сервера»)",
        "login_emp_prompt": "Отсканируйте QR с пропуска",
        "login_emp_hint": "Поднесите QR сотрудника к сканеру",
        "user": "Пользователь: {fio}",
        "logout": "Выйти",
        "logout_blocked_tooltip": "Сначала закройте задание/сессию",
        "sessions": "Сессии",
        "get_task": "Получить задание",
        "sessions_hint": "Сессии — это длинные процессы (например, приёмка). Задания берутся кнопкой выше.",
        "session_title": "Сессия",
        "close_session": "Закрыть сессию",
        "task_title": "Задание {num}",
        "loading": "Загрузка задания…",
        "refresh": "Обновить",
        "task_done": "Задание выполнено",
        "to_modes": "К режимам",
        "no_connection": "Нет связи с сервером",
        "work_blocked": "Работа заблокирована. Ожидание связи…",
        "last_contact": "Последний контакт: {sec} сек назад",
        "attempt": "Попытка: {n}",
        "reconnecting": "Переподключение…",
        "notif_title": "Уведомление",
        "notif_urgent": "🔴 СРОЧНО",
        "notif_read": "Прочитано",
        "not_found_relocated": "Найдено рядом",
        "not_found_split": "Найдено частично",
        "not_found_lost": "Товар утерян",
        "not_found_result": "Результат",
        "not_found_cell": "Ячейка: {cell}",
        "not_found_task": "Новое задание: {task}",
        "ok": "ОК",
        "batch_block": "Блок {bf}",
        "batch_part": "Часть {pos} из {total}",
        "no_tasks": "Нет доступных заданий",
        "no_roles": "Нет назначенных ролей, обратитесь к руководителю",
        "race": "Кто-то уже забрал это задание",
        "error_start": "Не удалось получить задание",
        "role_picker": "Подбор",
        "role_receiver": "Приёмка",
        "role_putaway": "Размещение",
        "role_inventory": "Инвентаризация",
        "cancel": "Отмена",
        "confirm": "Подтверждение",
        "are_you_sure": "Вы уверены?",
        "yes": "Да",
        "no": "Нет",
        "language": "Язык",
        "server": "Сервер:",
        "submit": "Отправить",
        "empty": "(пусто)",
        "empty_table": "(пустая таблица)",
        "webview_unavailable": "[webview недоступен]",
        "no_photo": "Нет фото",
        "role_revoked_title": "Роль отозвана",
        "role_revoked_text": (
            "Ваша роль приёмки отозвана руководителем.\n\n"
            "Завершите текущую работу: закройте грузоместо "
            "(кнопка «Закончить грузоместо») и рабочую тару "
            "(кнопка «Закрыть рабочую тару»).\n\n"
            "После закрытия тары сессия автоматически завершится."
        ),
        "role_revoked_closed": (
            "Текущая работа завершена. Сессия закрыта. "
            "Обратитесь к руководителю."
        ),
        "err_server_unavailable": (
            "Сервер недоступен. Проверьте, что сервер включён "
            "и сеть работает."),
        "err_server_timeout": (
            "Сервер не отвечает. Проверьте соединение."),
        "err_not_server_qr": "Это не QR-код сервера:\n{code}",
        "err_not_employee_qr": "Это не QR сотрудника",
        "err_denied": "Доступ запрещён: {err}",
        "err_tls_cert": "Ошибка сертификата: {err}",
        "common_error": "Ошибка",
        "sidebar_brand": "ЛУЧ",
        "sidebar_unauthorized": "Не авторизован",
        "sidebar_menu_language": "🌐  Язык",
        "sidebar_menu_logout": "🚪  Выйти",
        "sidebar_menu_about": "ℹ  О программе",
        "about_text": "Луч — WMS для адресного хранения.",
        "tls_badge": "🔒 HTTPS",
        "http_badge": "⚠ HTTP (без шифрования)",
    },
    "en": {
        "title": "Luch — Terminal",
        "login_server_prompt": "Scan server QR code",
        "login_server_hint": "(QR code is in «Tasks» section under «Server barcode»)",
        "login_emp_prompt": "Scan employee badge QR",
        "login_emp_hint": "Present employee QR to scanner",
        "user": "User: {fio}",
        "logout": "Logout",
        "logout_blocked_tooltip": "Close the task/session first",
        "sessions": "Sessions",
        "get_task": "Get task",
        "sessions_hint": "Sessions are long processes (e.g. receiving). Tasks are obtained via the button above.",
        "session_title": "Session",
        "close_session": "Close session",
        "task_title": "Task {num}",
        "loading": "Loading task…",
        "refresh": "Refresh",
        "task_done": "Task completed",
        "to_modes": "To modes",
        "no_connection": "No connection to server",
        "work_blocked": "Work blocked. Waiting for connection…",
        "last_contact": "Last contact: {sec} sec ago",
        "attempt": "Attempt: {n}",
        "reconnecting": "Reconnecting…",
        "notif_title": "Notification",
        "notif_urgent": "🔴 URGENT",
        "notif_read": "Read",
        "not_found_relocated": "Found nearby",
        "not_found_split": "Partially found",
        "not_found_lost": "Item lost",
        "not_found_result": "Result",
        "not_found_cell": "Cell: {cell}",
        "not_found_task": "New task: {task}",
        "ok": "OK",
        "batch_block": "Block {bf}",
        "batch_part": "Part {pos} of {total}",
        "no_tasks": "No available tasks",
        "no_roles": "No assigned roles, contact your supervisor",
        "race": "Someone already took this task",
        "error_start": "Failed to get task",
        "role_picker": "Picker",
        "role_receiver": "Receiver",
        "role_putaway": "Putaway",
        "role_inventory": "Inventory",
        "cancel": "Cancel",
        "confirm": "Confirmation",
        "are_you_sure": "Are you sure?",
        "yes": "Yes",
        "no": "No",
        "language": "Language",
        "server": "Server:",
        "submit": "Submit",
        "empty": "(empty)",
        "empty_table": "(empty table)",
        "webview_unavailable": "[webview unavailable]",
        "no_photo": "No photo",
        "role_revoked_title": "Role revoked",
        "role_revoked_text": (
            "Your receiving role has been revoked by the supervisor.\n\n"
            "Finish the current work: close the cargo "
            "(«Finish cargo») and working container "
            "(«Close working container»).\n\n"
            "The session will close automatically after "
            "the container is closed."
        ),
        "role_revoked_closed": (
            "Current work is finished. Session closed. "
            "Contact your supervisor."
        ),
        "err_server_unavailable": (
            "Server is unreachable. Check that the server is "
            "running and the network works."),
        "err_server_timeout": (
            "Server is not responding. Check the connection."),
        "err_not_server_qr": "Not a server QR:\n{code}",
        "err_not_employee_qr": "Not an employee QR",
        "err_denied": "Denied: {err}",
        "err_tls_cert": "Certificate error: {err}",
        "common_error": "Error",
        "sidebar_brand": "LUCH",
        "sidebar_unauthorized": "Not logged in",
        "sidebar_menu_language": "🌐  Language",
        "sidebar_menu_logout": "🚪  Logout",
        "sidebar_menu_about": "ℹ  About",
        "about_text": "Luch — WMS for address storage.",
        "tls_badge": "🔒 HTTPS",
        "http_badge": "⚠ HTTP (insecure)",
    }
}


_META = {}
_loaded = False
_DEFAULT = "ru"


def _read_cached_locales_all():
    cfg = load_config()
    out = {}
    ui_cache = cfg.get("ui_cache") or {}
    for entry in ui_cache.values():
        if not isinstance(entry, dict):
            continue
        config = entry.get("config") or {}
        locales = _parse_locales(config)
        for code, data in locales.items():
            if code not in out:
                out[code] = data
            else:
                merged = dict(out[code].get("data") or {})
                merged.update(data.get("data") or {})
                out[code] = {
                    "name": data.get("name") or out[code].get("name"),
                    "rtl": bool(data.get("rtl")),
                    "fallback": data.get("fallback")
                                or out[code].get("fallback"),
                    "data": merged,
                }
    legacy = cfg.get("locales_cache") or {}
    if isinstance(legacy, dict):
        for code, entry in legacy.items():
            if not isinstance(entry, dict):
                continue
            data = entry.get("data") or {}
            if not isinstance(data, dict):
                continue
            if code not in out:
                out[code] = {
                    "name": entry.get("name") or code.upper(),
                    "rtl": bool(entry.get("rtl")),
                    "fallback": entry.get("fallback"),
                    "data": data,
                }
    return out


def _apply_locales(server_locales):
    global _loaded
    for code, entry in server_locales.items():
        data = entry.get("data") or {}
        base = dict(_T.get(code, {}))
        for k, v in data.items():
            if not isinstance(k, str):
                continue
            if k.startswith("client."):
                base[k[len("client."):]] = v
            else:
                base[k] = v
        _T[code] = base
        _META[code] = {
            "name": entry.get("name") or code.upper(),
            "rtl": bool(entry.get("rtl")),
            "fallback": entry.get("fallback"),
        }
    _loaded = True


def _init_locales():
    global _loaded
    if _loaded:
        return
    cached = _read_cached_locales_all()
    if cached:
        _apply_locales(cached)
    _loaded = True


def available_locales():
    _init_locales()
    return list(_T.keys())


def locale_display_name(code):
    _init_locales()
    meta = _META.get(code) or {}
    name = (meta.get("name") or "").strip()
    if name:
        return name
    builtin = {
        "ru": "Русский", "en": "English", "de": "Deutsch",
        "fr": "Français", "es": "Español", "it": "Italiano",
        "pt": "Português", "pl": "Polski", "uk": "Українська",
        "kk": "Қазақша", "tr": "Türkçe", "zh": "中文",
        "ja": "日本語", "ko": "한국어", "ar": "العربية",
        "he": "עברית",
    }
    return builtin.get(code, code.upper())


def tr(key, **kwargs):
    _init_locales()
    loc = "ru"
    if hasattr(tr, 'api') and tr.api:
        loc = tr.api.locale
    if loc not in _T:
        loc = "ru"
    val = _T.get(loc, {}).get(key)
    if val is None:
        fb = (_META.get(loc) or {}).get("fallback")
        if fb and fb in _T:
            val = _T[fb].get(key)
        if val is None:
            val = _T.get("ru", {}).get(key)
        if val is None:
            val = _T.get("en", {}).get(key)
        if val is None:
            if key.startswith("role_"):
                rest = key[len("role_"):]
                val = (rest.replace("_", " ").capitalize()
                       if rest else key)
            else:
                val = key
    if kwargs:
        try:
            val = val.format(**kwargs)
        except Exception:
            pass
    return val


def humanize_locale(err_text):
    raw = humanize_error(err_text)
    if raw == "__HUMAN_NETWORK_UNAVAILABLE__":
        return tr("err_server_unavailable")
    if raw == "__HUMAN_NETWORK_TIMEOUT__":
        return tr("err_server_timeout")
    return raw or tr("err_server_unavailable")


def load_pixmap_from_data(data_str):
    if not data_str:
        return None
    pm = QPixmap()
    if data_str.startswith("data:"):
        try:
            _, _, b64 = data_str.partition(",")
            raw = base64.b64decode(b64)
            if pm.loadFromData(raw):
                return pm
        except Exception:
            return None
        return None
    return None


# ================================================================
# View-рендерер — без изменений
# ================================================================

class ViewRenderer(QWidget):
    def __init__(self, on_action, parent=None):
        super().__init__(parent)
        self._on_action = on_action
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)

    def set_nodes(self, nodes):
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for node in nodes or []:
            w = self._render_node(node)
            if w is not None:
                self._layout.addWidget(w)

    def _render_node(self, node):
        if not isinstance(node, dict):
            return None
        t = node.get("type", "text")
        try:
            if t == "text":       return self._node_text(node)
            if t == "heading":    return self._node_heading(node)
            if t == "caption":    return self._node_caption(node)
            if t == "card":       return self._node_card(node)
            if t == "group":      return self._node_group(node)
            if t == "divider":    return self._node_divider()
            if t == "spacer":     return self._node_spacer(node)
            if t == "progress":   return self._node_progress(node)
            if t == "button":     return self._node_button(node)
            if t == "input":      return self._node_input(node)
            if t == "list":       return self._node_list(node)
            if t == "tiles":      return self._node_tiles(node)
            if t == "table":      return self._node_table(node)
            if t == "image":      return self._node_image(node)
            if t == "barcode":    return self._node_barcode(node)
            if t == "slot":       return self._node_group(node)
            if t == "webview":
                return QLabel(tr("webview_unavailable"))
        except Exception as e:
            print("ViewRenderer:", t, e)
        return QLabel(f"[{t}]")

    def _node_text(self, n):
        lbl = QLabel(n.get("value", ""))
        lbl.setWordWrap(True)
        style = n.get("style") or {}
        f = QFont("Arial")
        if style.get("bold"):
            f.setBold(True)
        if int(style.get("size") or 0) > 0:
            f.setPointSize(int(style["size"]))
        lbl.setFont(f)
        if style.get("color"):
            lbl.setStyleSheet(f"color:{style['color']};")
        return lbl

    def _node_heading(self, n):
        lbl = QLabel(n.get("value", ""))
        lbl.setWordWrap(True)
        level = int(n.get("level") or 1)
        size = 20 if level == 1 else 17 if level == 2 else 15
        f = QFont("Arial", size)
        f.setBold(True)
        lbl.setFont(f)
        return lbl

    def _node_caption(self, n):
        lbl = QLabel(n.get("value", ""))
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color:#7f8c8d; font-size:11px;")
        return lbl

    def _node_card(self, n):
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        accent = n.get("accent") or ""
        bg = {
            "success": "#e8f5e9",
            "warning": "#fff8e1",
            "error":   "#ffebee",
            "primary": "#e3f2fd",
        }.get(accent, "#ffffff")
        frame.setStyleSheet(
            f"QFrame {{ background:{bg}; border:1px solid #dcdcdc; "
            f"border-radius:8px; }}"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)
        title = n.get("title")
        if title:
            t = QLabel(title)
            t.setFont(QFont("Arial", 10, QFont.Bold))
            layout.addWidget(t)
        for c in n.get("children", []):
            w = self._render_node(c)
            if w is not None:
                layout.addWidget(w)
        return frame

    def _node_group(self, n):
        w = QWidget()
        layout = (QHBoxLayout(w)
                  if n.get("orientation") == "horizontal"
                  else QVBoxLayout(w))
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(int(n.get("spacing") or 8))
        for c in n.get("children", []):
            cw = self._render_node(c)
            if cw is not None:
                layout.addWidget(cw)
        return w

    def _node_divider(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color:#dcdcdc;")
        return line

    def _node_spacer(self, n):
        w = QWidget()
        w.setFixedHeight(int(n.get("size") or 8))
        return w

    def _node_progress(self, n):
        pb = QProgressBar()
        mx = int(n.get("max") or 0) or 100
        pb.setRange(0, mx)
        pb.setValue(int(n.get("value") or 0))
        label = n.get("label")
        if label:
            pb.setFormat(label)
        pb.setTextVisible(bool(label))
        return pb

    def _node_button(self, n):
        btn = QPushButton(n.get("label") or "OK")
        btn.setEnabled(bool(n.get("enabled", True)))
        style = n.get("style") or "default"
        if style == "primary":
            btn.setStyleSheet(
                "QPushButton { background:#27ae60; color:white; "
                "border:none; border-radius:6px; padding:8px 14px; "
                "font-weight:bold; }"
                "QPushButton:hover { background:#2ecc71; }")
        elif style == "danger":
            btn.setStyleSheet(
                "QPushButton { background:#e74c3c; color:white; "
                "border:none; border-radius:6px; padding:8px 14px; "
                "font-weight:bold; }")
        action = n.get("action") or "tap"
        action_id = n.get("id")
        value = n.get("value")

        def _on_click():
            if value == "ask":
                r = QMessageBox.question(
                    self, tr("confirm"), tr("are_you_sure"),
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No)
                if r != QMessageBox.Yes:
                    return
                self._on_action(action, action_id, None)
            else:
                self._on_action(action, action_id, value)

        btn.clicked.connect(_on_click)
        return btn

    def _node_input(self, n):
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        if n.get("label"):
            v.addWidget(QLabel(n["label"]))
        field_id = n.get("id") or "input"
        initial = n.get("value") or ""
        options = n.get("options") or []
        if n.get("input_type") == "select" and options:
            combo = QComboBox()
            for opt in options:
                combo.addItem(str(opt))
            if initial and initial in options:
                combo.setCurrentText(initial)
            v.addWidget(combo)
            btn = QPushButton(tr("submit"))
            btn.clicked.connect(
                lambda: self._on_action(
                    "input_submit", field_id, combo.currentText()))
            v.addWidget(btn)
            return wrap
        edit = QLineEdit(str(initial))
        v.addWidget(edit)
        btn = QPushButton(tr("submit"))
        btn.clicked.connect(
            lambda: self._on_action(
                "input_submit", field_id, edit.text()))
        v.addWidget(btn)
        return wrap

    def _node_list(self, n):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        for c in n.get("children", []):
            cw = self._render_node(c)
            if cw is not None:
                v.addWidget(cw)
        return w

    def _node_tiles(self, n):
        items = n.get("items") or []
        if not items:
            return QLabel(tr("empty"))
        w = QWidget()
        grid = QGridLayout(w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)
        for i, item in enumerate(items):
            label = item.get("label") or item.get("barcode") or ""
            lbl = QLabel(str(label))
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setWordWrap(True)
            lbl.setMinimumHeight(56)
            accent = item.get("accent") or "default"
            bg = {
                "success": "#4caf50", "warning": "#ffa726",
                "primary": "#2196f3", "error":   "#e53935",
            }.get(accent, "#e0e0e0")
            fg = "#333" if accent in ("", "default") else "#fff"
            lbl.setStyleSheet(
                f"background:{bg}; color:{fg}; "
                f"border-radius:6px; font-weight:bold; padding:6px;")
            grid.addWidget(lbl, i // 2, i % 2)
        return w

    def _node_table(self, n):
        cols = n.get("columns") or []
        rows = n.get("rows") or []
        if not cols:
            return QLabel(tr("empty_table"))

        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        title = n.get("title")
        if title:
            t = QLabel(str(title))
            t.setFont(QFont("Arial", 10, QFont.Bold))
            v.addWidget(t)

        table = QTableWidget()
        table.setColumnCount(len(cols))
        table.setHorizontalHeaderLabels(
            [c.get("label") or c.get("key") or "" for c in cols])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.verticalHeader().setVisible(False)
        table.setStyleSheet(
            "QTableWidget { background:#fff; border:1px solid #dcdcdc; "
            "gridline-color: #eaeaea; }"
            "QHeaderView::section { background:#f5f5f5; "
            "font-weight:bold; padding:4px; border:none; "
            "border-bottom:1px solid #dcdcdc; }"
        )
        header = table.horizontalHeader()
        for i, c in enumerate(cols):
            w = c.get("width")
            if isinstance(w, (int, float)) and w > 0:
                header.setSectionResizeMode(i, QHeaderView.Fixed)
                table.setColumnWidth(i, int(w * 600))
            else:
                header.setSectionResizeMode(i, QHeaderView.Stretch)

        table.setRowCount(len(rows))
        for r_idx, row in enumerate(rows):
            for c_idx, c in enumerate(cols):
                key = c.get("key") or ""
                ctype = c.get("type") or "text"
                val = row.get(key, "")
                if ctype == "image":
                    pm = load_pixmap_from_data(str(val))
                    if pm and not pm.isNull():
                        lbl = QLabel()
                        lbl.setPixmap(pm.scaled(
                            40, 40, Qt.KeepAspectRatio,
                            Qt.SmoothTransformation))
                        lbl.setAlignment(Qt.AlignCenter)
                        table.setCellWidget(r_idx, c_idx, lbl)
                        it = QTableWidgetItem("")
                    else:
                        it = QTableWidgetItem("—")
                else:
                    it = QTableWidgetItem(str(val))
                    if ctype == "number":
                        it.setTextAlignment(
                            Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(r_idx, c_idx, it)

        table.resizeRowsToContents()
        table.setMinimumHeight(min(300, 30 * (len(rows) + 1)))
        v.addWidget(table)
        return wrap

    def _node_image(self, n):
        lbl = QLabel(tr("no_photo"))
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setMinimumHeight(120)
        lbl.setMinimumWidth(120)
        lbl.setStyleSheet(
            "background:#ecf0f1; color:#7f8c8d; "
            "border:1px dashed #bdc3c7; border-radius:6px; "
            "font-size:11px;")
        src = n.get("url") or n.get("value") or ""
        pm = load_pixmap_from_data(src)
        if pm and not pm.isNull():
            lbl.setPixmap(pm.scaled(180, 180, Qt.KeepAspectRatio,
                                    Qt.SmoothTransformation))
            lbl.setText("")
        return lbl

    def _node_barcode(self, n):
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        if n.get("label"):
            v.addWidget(QLabel(n["label"]))
        code = QLabel(n.get("value") or "")
        f = QFont("Courier New", 14)
        f.setBold(True)
        code.setFont(f)
        code.setStyleSheet("color:#2c3e50;")
        v.addWidget(code)
        return wrap


class NotificationDialog(QDialog):
    def __init__(self, item: NotificationItem, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("notif_title"))
        self.setMinimumWidth(420)
        v = QVBoxLayout(self)
        title = tr("notif_urgent") if item.type == "urgent" \
            else tr("notif_title")
        t = QLabel(title)
        t.setFont(QFont("Arial", 12, QFont.Bold))
        if item.type == "urgent":
            t.setStyleSheet("color:#c0392b;")
        v.addWidget(t)
        if item.sender_login:
            v.addWidget(QLabel(f"From: {item.sender_login}"))
        if item.created_at:
            lbl = QLabel(item.created_at[:19])
            lbl.setStyleSheet("color:#95a5a6; font-size:10px;")
            v.addWidget(lbl)
        msg = QLabel(item.message)
        msg.setWordWrap(True)
        msg.setFont(QFont("Arial", 11))
        v.addWidget(msg)
        btns = QDialogButtonBox(QDialogButtonBox.Ok)
        btns.button(QDialogButtonBox.Ok).setText(tr("notif_read"))
        btns.accepted.connect(self.accept)
        v.addWidget(btns)


class LanguageDialog(QDialog):
    def __init__(self, current_code: str, on_pick, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("language"))
        self.setMinimumWidth(360)
        self._on_pick = on_pick
        self._current = current_code

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(8)

        self.list = QListWidget()
        self.list.setStyleSheet(
            "QListWidget { border:1px solid #dcdcdc; "
            "border-radius:6px; padding:4px; font-size:13px; }"
            "QListWidget::item { padding:8px 6px; }"
            "QListWidget::item:selected { background:#27ae60; "
            "color:white; }"
        )
        for code in available_locales():
            name = locale_display_name(code)
            item = QListWidgetItem(f"{name}  ({code})")
            item.setData(Qt.UserRole, code)
            self.list.addItem(item)
            if code == current_code:
                self.list.setCurrentItem(item)
        self.list.itemDoubleClicked.connect(self._pick_current)
        v.addWidget(self.list, 1)

        btns = QHBoxLayout()
        btns.addStretch()
        ok_btn = QPushButton(tr("ok"))
        ok_btn.setObjectName("primary_btn")
        ok_btn.clicked.connect(self._pick_current)
        cancel_btn = QPushButton(tr("cancel"))
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        v.addLayout(btns)

    def _pick_current(self, *_args):
        it = self.list.currentItem()
        if it is None:
            return
        code = it.data(Qt.UserRole)
        if code:
            self._on_pick(code)
        self.accept()


_QR_RE = re.compile(
    r"^WMS://([^/:]+)(?::(\d+))?/?(\#fp=([^&\s]+))?$",
    re.IGNORECASE)


class LoginServerScreen(QWidget):
    done = Signal()

    def __init__(self, api: Api, parent=None):
        super().__init__(parent)
        self.api = api
        v = QVBoxLayout(self)
        v.addStretch()

        self.logo_label = QLabel()
        self.logo_label.setAlignment(Qt.AlignCenter)
        logo_path = _find_asset("logo_horizontal.png")
        if logo_path:
            pix = QPixmap(logo_path)
            self.logo_label.setPixmap(pix.scaledToWidth(
                450, Qt.SmoothTransformation))
        else:
            self.logo_label.setText("Луч — терминал")
            self.logo_label.setFont(QFont("Arial", 22, QFont.Bold))
        v.addWidget(self.logo_label)

        self.prompt = QLabel(tr("login_server_prompt"))
        self.prompt.setFont(QFont("Arial", 16))
        self.prompt.setAlignment(Qt.AlignCenter)
        self.prompt.setStyleSheet("color:#27ae60;")
        v.addWidget(self.prompt)

        self.tls_badge = QLabel("")
        self.tls_badge.setAlignment(Qt.AlignCenter)
        self.tls_badge.setStyleSheet(
            "color:#7f8c8d; font-size:11px;")
        v.addWidget(self.tls_badge)

        self.hint_label = QLabel(tr("login_server_hint"))
        self.hint_label.setStyleSheet("color:#7f8c8d;")
        self.hint_label.setAlignment(Qt.AlignCenter)
        v.addWidget(self.hint_label)

        v.addStretch()

    def retranslate(self):
        if self.api.base:
            self.prompt.setText(f"{tr('server')} {self.api.base}")
        else:
            self.prompt.setText(tr("login_server_prompt"))
        self.hint_label.setText(tr("login_server_hint"))
        self._update_tls_badge()

    def _update_tls_badge(self):
        if self.api.base.startswith("https://"):
            self.tls_badge.setText(tr("tls_badge"))
            self.tls_badge.setStyleSheet(
                "color:#27ae60; font-size:11px; font-weight:bold;")
        elif self.api.base.startswith("http://"):
            self.tls_badge.setText(tr("http_badge"))
            self.tls_badge.setStyleSheet(
                "color:#e67e22; font-size:11px; font-weight:bold;")
        else:
            self.tls_badge.setText("")

    def handle_scan(self, code: str):
        m = _QR_RE.match(code.strip())
        if not m:
            QMessageBox.warning(
                self, tr("common_error"),
                tr("err_not_server_qr", code=code))
            return

        host = m.group(1)
        port = m.group(2) or "8765"
        fp = m.group(4)

        cfg = load_config()
        https_url = f"https://{host}:{port}"
        http_url = f"http://{host}:{port}"

        if fp:
            url = https_url
        else:
            if get_tls_cache(cfg, https_url):
                url = https_url
            else:
                url = http_url

        try:
            self.api.set_base(url, fp=fp)
        except ApiError as e:
            QMessageBox.warning(
                self, tr("common_error"),
                tr("err_tls_cert", err=str(e)))
            return
        except Exception as e:
            QMessageBox.warning(
                self, tr("common_error"), str(e))
            return

        cfg["server"] = url
        save_config(cfg)
        self.prompt.setText(f"{tr('server')} {url}")
        self._update_tls_badge()
        self.done.emit()

    def reset(self):
        self.retranslate()


class LoginEmployeeScreen(QWidget):
    done = Signal()

    def __init__(self, api: Api, parent=None):
        super().__init__(parent)
        self.api = api
        v = QVBoxLayout(self)
        v.addStretch()

        self.prompt_label = QLabel(tr("login_emp_prompt"))
        self.prompt_label.setFont(QFont("Arial", 18))
        self.prompt_label.setAlignment(Qt.AlignCenter)
        self.prompt_label.setStyleSheet("color:#27ae60;")
        v.addWidget(self.prompt_label)

        self.status = QLabel("")
        self.status.setStyleSheet("color:#e74c3c;")
        self.status.setAlignment(Qt.AlignCenter)
        v.addWidget(self.status)

        self.hint_label = QLabel(tr("login_emp_hint"))
        self.hint_label.setStyleSheet("color:#7f8c8d;")
        self.hint_label.setAlignment(Qt.AlignCenter)
        v.addWidget(self.hint_label)
        v.addStretch()

    def retranslate(self):
        self.prompt_label.setText(tr("login_emp_prompt"))
        self.hint_label.setText(tr("login_emp_hint"))

    def handle_scan(self, code: str):
        code = code.strip()
        if "-" not in code:
            self.status.setText(tr("err_not_employee_qr"))
            return
        login, secret = code.split("-", 1)
        try:
            ok, err = self.api.login_user(login, secret)
        except ApiError as e:
            self.status.setText(humanize_locale(str(e)))
            return
        if not ok:
            self.status.setText(tr("err_denied", err=err))
            return
        self.status.setText("")
        self.done.emit()


class ModesScreen(QWidget):
    session_started = Signal(str, str)
    task_requested = Signal()
    logout_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fio = "—"
        self._roles = []

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(12)

        top = QHBoxLayout()
        self.user_label = QLabel(tr("user", fio="—"))
        self.user_label.setFont(QFont("Arial", 12, QFont.Bold))
        top.addWidget(self.user_label)
        top.addStretch()
        self.logout_btn = QPushButton(tr("logout"))
        self.logout_btn.clicked.connect(self.logout_requested.emit)
        top.addWidget(self.logout_btn)
        v.addLayout(top)

        self.roles_label = QLabel("")
        self.roles_label.setStyleSheet("color:#7f8c8d;")
        v.addWidget(self.roles_label)

        v.addSpacing(20)

        self.sessions_label = QLabel(tr("sessions"))
        self.sessions_label.setFont(QFont("Arial", 13, QFont.Bold))
        v.addWidget(self.sessions_label)

        self.sessions_container = QWidget()
        self.sessions_layout = QVBoxLayout(self.sessions_container)
        self.sessions_layout.setContentsMargins(0, 0, 0, 0)
        self.sessions_layout.setSpacing(6)
        v.addWidget(self.sessions_container)

        v.addSpacing(20)

        self.get_task_btn = QPushButton(tr("get_task"))
        self.get_task_btn.setObjectName("primary_btn")
        self.get_task_btn.setMinimumHeight(56)
        self.get_task_btn.clicked.connect(self.task_requested.emit)
        v.addWidget(self.get_task_btn)

        v.addStretch()

        self.hint_label = QLabel(tr("sessions_hint"))
        self.hint_label.setStyleSheet("color:#95a5a6; font-size:11px;")
        self.hint_label.setWordWrap(True)
        self.hint_label.setAlignment(Qt.AlignCenter)
        v.addWidget(self.hint_label)

    def retranslate(self):
        self.user_label.setText(tr("user", fio=self._fio))
        if self._roles:
            role_txt = ", ".join(tr(f"role_{r}") for r in self._roles)
            self.roles_label.setText(role_txt)
            self.roles_label.setStyleSheet("color:#7f8c8d;")
        else:
            self.roles_label.setText(tr("no_roles"))
            self.roles_label.setStyleSheet("color:#c0392b;")
        self.logout_btn.setText(tr("logout"))
        self.sessions_label.setText(tr("sessions"))
        self.get_task_btn.setText(tr("get_task"))
        self.hint_label.setText(tr("sessions_hint"))

    def set_user(self, fio, roles):
        self._fio = fio or "—"
        self._roles = list(roles or [])
        self.retranslate()

    def set_sessions(self, sessions):
        while self.sessions_layout.count():
            item = self.sessions_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not sessions:
            self.sessions_label.setVisible(False)
            return
        self.sessions_label.setVisible(True)
        for s in sessions:
            btn = QPushButton(f"▶  {s.title}")
            btn.setMinimumHeight(52)
            btn.setStyleSheet(
                "QPushButton { text-align:left; padding:12px 16px; "
                "font-size:14px; font-weight:bold; }")
            btn.clicked.connect(
                lambda _=False, k=s.key, t=s.title:
                self.session_started.emit(k, t))
            self.sessions_layout.addWidget(btn)

    def set_busy(self, busy):
        self.get_task_btn.setEnabled(not busy)


class SessionViewScreen(QWidget):
    closed = Signal()
    connection_lost = Signal()

    def __init__(self, api: Api, parent=None):
        super().__init__(parent)
        self.api = api
        self.session_key = ""
        self.session_title = ""
        self._role_revoked_shown = False

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(8)

        top = QHBoxLayout()
        self.title_label = QLabel(tr("session_title"))
        self.title_label.setFont(QFont("Arial", 14, QFont.Bold))
        top.addWidget(self.title_label)
        top.addStretch()
        self.close_btn = QPushButton(tr("close_session"))
        self.close_btn.clicked.connect(self._on_close)
        top.addWidget(self.close_btn)
        v.addLayout(top)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.content_host = QWidget()
        self.content_layout = QVBoxLayout(self.content_host)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(self.content_host)
        v.addWidget(scroll, 1)

        self.renderer = ViewRenderer(self._on_action)
        self.content_layout.addWidget(self.renderer)
        self.content_layout.addStretch()

    def retranslate(self):
        self.close_btn.setText(tr("close_session"))

    def start(self, key, title):
        self.session_key = key
        self.session_title = title
        self._role_revoked_shown = False
        self.title_label.setText(title)
        self.retranslate()

    def apply(self, nodes):
        self.renderer.set_nodes(nodes)

    def _apply_env(self, env):
        if env.get("message"):
            self._show_msg(env["message"])
        if env.get("role_revoked"):
            self._show_role_revoked()
            meta = env.get("meta")
            state = meta.state if meta else {}
            container = state.get("container_barcode") or ""
            task_id = int(state.get("task_id") or 0)
            if not container and task_id == 0:
                QTimer.singleShot(300, self._auto_close)
        self.renderer.set_nodes(env.get("nodes") or [])

    def _show_role_revoked(self):
        if self._role_revoked_shown:
            return
        self._role_revoked_shown = True
        QMessageBox.warning(
            self,
            tr("role_revoked_title"),
            tr("role_revoked_text"))

    def _auto_close(self):
        QMessageBox.information(
            self,
            tr("role_revoked_title"),
            tr("role_revoked_closed"))
        try:
            self.api.sessions_close(self.session_key, force=True)
        except Exception:
            pass
        self.session_key = ""
        self.closed.emit()

    def handle_scan(self, code: str):
        if not self.session_key:
            return
        try:
            env = self.api.sessions_action(
                self.session_key, "_scan_", code)
        except ApiError as e:
            if getattr(e, "is_network", False):
                self.connection_lost.emit()
                self._show_msg(humanize_locale(str(e)))
                return
            if getattr(e, "role_revoked", False):
                self._show_role_revoked()
            else:
                self._show_msg(str(e))
            return
        self._apply_env(env)

    def _on_action(self, action, action_id, value):
        if not self.session_key:
            return
        self._do_session_action(action_id, value)

    def _do_session_action(self, action_id, value):
        try:
            env = self.api.sessions_action(
                self.session_key, action_id, value)
        except ApiError as e:
            if getattr(e, "is_network", False):
                self.connection_lost.emit()
                self._show_msg(humanize_locale(str(e)))
                return
            if getattr(e, "role_revoked", False):
                self._show_role_revoked()
            else:
                self._show_msg(str(e))
            return
        self._apply_env(env)

    def _on_close(self):
        try:
            self.api.sessions_close(self.session_key)
        except ApiError as e:
            self._show_msg(str(e))
            return
        except Exception:
            pass
        self.session_key = ""
        self.closed.emit()

    def _show_msg(self, text):
        if not text:
            return
        mw = self.window()
        if hasattr(mw, "show_snackbar"):
            mw.show_snackbar(text)


class TaskExecScreen(QWidget):
    closed = Signal()
    connection_lost = Signal()

    def __init__(self, api: Api, parent=None):
        super().__init__(parent)
        self.api = api
        self.task_id = 0
        self.current_meta = None
        self.current_nodes = []

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(8)

        top = QHBoxLayout()
        self.title_label = QLabel(tr("task_title", num=""))
        self.title_label.setFont(QFont("Arial", 14, QFont.Bold))
        top.addWidget(self.title_label)
        top.addStretch()
        self.close_btn = QPushButton(tr("logout"))
        self.close_btn.clicked.connect(self._on_close)
        top.addWidget(self.close_btn)
        v.addLayout(top)

        self.batch_label = QLabel("")
        self.batch_label.setStyleSheet(
            "background:#27ae60; color:white; padding:6px 12px; "
            "border-radius:4px; font-weight:bold;")
        self.batch_label.setVisible(False)
        v.addWidget(self.batch_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.content_host = QWidget()
        self.content_layout = QVBoxLayout(self.content_host)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(self.content_host)
        v.addWidget(scroll, 1)

        self.renderer = ViewRenderer(self._on_action)
        self.content_layout.addWidget(self.renderer)
        self.content_layout.addStretch()

    def retranslate(self):
        self.close_btn.setText(tr("logout"))

    def load_task(self, task, items):
        self.task_id = task.get("id") or 0
        self.title_label.setText(
            tr("task_title", num=task.get('task_number') or ''))
        self.batch_label.setVisible(False)
        self._refresh_view()

    def _refresh_view(self):
        if not self.task_id:
            return
        try:
            env = self.api.task_view(self.task_id)
        except ApiError as e:
            if getattr(e, "is_network", False):
                self.connection_lost.emit()
                self._show_msg(humanize_locale(str(e)))
                return
            self._show_msg(str(e))
            return
        self._apply(env)

    def _apply(self, env):
        self.current_meta = env.get("meta")
        self.current_nodes = env.get("nodes") or []

        m = self.current_meta
        if m:
            parts = []
            if m.block_bf:
                parts.append(tr("batch_block", bf=m.block_bf))
            if m.batch_position > 0 and m.batch_total > 1:
                parts.append(
                    tr("batch_part", pos=m.batch_position,
                       total=m.batch_total))
            if parts:
                self.batch_label.setText("  ·  ".join(parts))
                self.batch_label.setVisible(True)
            else:
                self.batch_label.setVisible(False)

        self.renderer.set_nodes(self.current_nodes)

        if m and m.finished:
            self._show_msg(tr("task_done"))
            self.task_id = 0
            self.closed.emit()
            return

        if env.get("message"):
            self._show_msg(env["message"])

        if env.get("not_found_result"):
            nf = env["not_found_result"]
            title_map = {
                "relocated": tr("not_found_relocated"),
                "split": tr("not_found_split"),
                "lost": tr("not_found_lost"),
            }
            title = title_map.get(nf.result, tr("not_found_result"))
            msg = nf.message
            if nf.new_cell:
                msg += "\n" + tr("not_found_cell", cell=nf.new_cell)
            if nf.new_task_number:
                msg += "\n" + tr("not_found_task",
                                 task=nf.new_task_number)
            QMessageBox.information(self, title, msg)

    def handle_scan(self, code: str):
        if not self.task_id or not self.current_meta:
            return
        try:
            env = self.api.task_action(
                self.task_id, "scan", None, code,
                self.current_meta.step_no)
        except ApiError as e:
            if getattr(e, "is_network", False):
                self.connection_lost.emit()
                self._show_msg(humanize_locale(str(e)))
                return
            self._show_msg(str(e))
            return
        self._apply(env)

    def _on_action(self, action, action_id, value):
        if not self.task_id or not self.current_meta:
            return
        try:
            env = self.api.task_action(
                self.task_id, action, action_id, value,
                self.current_meta.step_no)
        except ApiError as e:
            if getattr(e, "is_network", False):
                self.connection_lost.emit()
                self._show_msg(humanize_locale(str(e)))
                return
            self._show_msg(str(e))
            return
        self._apply(env)

    def _on_close(self):
        if self.task_id:
            try:
                self.api.task_action(
                    self.task_id, "cancel", None, None,
                    self.current_meta.step_no
                    if self.current_meta else None)
            except Exception:
                pass
        self.task_id = 0
        self.current_meta = None
        self.current_nodes = []
        self.closed.emit()

    def _show_msg(self, text):
        if not text:
            return
        mw = self.window()
        if hasattr(mw, "show_snackbar"):
            mw.show_snackbar(text)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(tr("title"))
        self.setMinimumSize(950, 680)

        icon_path = _find_asset("icon.png")
        if icon_path:
            self.setWindowIcon(QIcon(icon_path))

        self.api = Api()
        tr.api = self.api

        self.online = True
        self._ping_failures = 0
        self._last_contact = 0
        self._notif_queue = []
        self._notif_showing = False
        self._fio = "—"
        self._roles = []

        self._ui_version = ""
        self._ui_data = {}
        self._ui_applied = False
        self._ui_applied_for = ""

        self.hidden_input = QLineEdit(self)
        self.hidden_input.setFixedSize(1, 1)
        self.hidden_input.move(0, 0)
        self.hidden_input.setStyleSheet(
            "QLineEdit { background: transparent; border: none; "
            "color: transparent; }")
        self.hidden_input.setAttribute(
            Qt.WA_TransparentForMouseEvents, True)
        self.hidden_input.setFocusPolicy(Qt.StrongFocus)
        self.hidden_input.setVisible(True)
        self.hidden_input.setFocus(Qt.OtherFocusReason)

        central = QWidget()
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.sidebar = self._build_sidebar()
        outer.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)

        self.login_server = LoginServerScreen(self.api)
        self.login_employee = LoginEmployeeScreen(self.api)
        self.modes = ModesScreen()
        self.session_view = SessionViewScreen(self.api)
        self.task_exec = TaskExecScreen(self.api)

        self.stack.addWidget(self.login_server)
        self.stack.addWidget(self.login_employee)
        self.stack.addWidget(self.modes)
        self.stack.addWidget(self.session_view)
        self.stack.addWidget(self.task_exec)

        self.login_server.done.connect(self._go_employee)
        self.login_employee.done.connect(self._go_modes)
        self.modes.session_started.connect(self._open_session)
        self.modes.task_requested.connect(self._get_task)
        self.modes.logout_requested.connect(self._logout)
        self.session_view.closed.connect(self._back_to_modes)
        self.session_view.connection_lost.connect(self._force_offline)
        self.task_exec.closed.connect(self._back_to_modes)
        self.task_exec.connection_lost.connect(self._force_offline)

        # FIX: обновляем состояние кнопки «Выйти» в сайдбаре
        # при каждом переключении экрана. Пока открыто задание
        # или сессия — кнопка заблокирована.
        self.stack.currentChanged.connect(self._update_logout_state)

        self.scanner = ScannerBridge(self, self.hidden_input)
        self.scanner.scanned.connect(self._dispatch_scan)

        self.snackbar = QLabel(self)
        self.snackbar.setStyleSheet(
            "background:#2c3e50; color:white; padding:10px 16px; "
            "border-radius:6px; font-size:12px;")
        self.snackbar.setVisible(False)
        self._snackbar_timer = QTimer(self)
        self._snackbar_timer.setSingleShot(True)
        self._snackbar_timer.timeout.connect(
            lambda: self.snackbar.setVisible(False))

        self.offline_overlay = QWidget(self)
        self.offline_overlay.setStyleSheet(
            "background: rgba(0,0,0,0.75);")
        ov = QVBoxLayout(self.offline_overlay)
        ov.setAlignment(Qt.AlignCenter)
        card = QFrame()
        card.setStyleSheet(
            "background:#b71c1c; color:white; border-radius:10px; "
            "padding:24px;")
        cv = QVBoxLayout(card)
        t = QLabel(tr("no_connection"))
        t.setFont(QFont("Arial", 18, QFont.Bold))
        t.setAlignment(Qt.AlignCenter)
        cv.addWidget(t)
        self.offline_info = QLabel("")
        self.offline_info.setAlignment(Qt.AlignCenter)
        cv.addWidget(self.offline_info)
        self.offline_reconnect = QLabel(tr("reconnecting"))
        self.offline_reconnect.setAlignment(Qt.AlignCenter)
        self.offline_reconnect.setStyleSheet(
            "color:#ffd54f; font-size:12px; margin-top:10px;")
        cv.addWidget(self.offline_reconnect)
        ov.addWidget(card)
        self.offline_overlay.setVisible(False)

        self.heartbeat = QTimer(self)
        self.heartbeat.setInterval(5000)
        self.heartbeat.timeout.connect(self._ping)
        self.heartbeat.start()

        self.notif_poller = QTimer(self)
        self.notif_poller.setInterval(5000)
        self.notif_poller.timeout.connect(self._poll_notifications)
        self.notif_poller.start()

        cfg = load_config()
        if cfg.get("server"):
            saved_url = cfg["server"]
            fp = None
            try:
                cached = get_tls_cache(cfg, saved_url)
                if cached:
                    fp = cached.get("fp") or None
                self.api.set_base(saved_url, fp=fp)
            except Exception as e:
                print(f"[startup] set_base: {e}")
            self.login_server.prompt.setText(
                f"{tr('server')} {self.api.base}")
            self.login_server._update_tls_badge()

        self.stack.setCurrentIndex(0)
        self._apply_styles()
        self._refresh_sidebar_user()
        self._update_logout_state()

        self._apply_cached_ui()
        if self.api.base:
            QTimer.singleShot(200, self._sync_ui_config)

    def _update_logout_state(self, _index=None):
        """Блокирует «Выйти» в сайдбаре, пока открыто задание
        или сессия.

        Чтобы выйти, пользователь сначала закрывает задание
        (кнопка «Выйти» на экране задания — отпускает задание)
        или сессию (кнопка «Закрыть сессию»), а потом выходит.
        """
        if not hasattr(self, "sidebar_logout_btn"):
            return
        active_task = bool(getattr(self.task_exec, "task_id", 0))
        active_session = bool(
            getattr(self.session_view, "session_key", ""))
        blocked = active_task or active_session
        self.sidebar_logout_btn.setEnabled(not blocked)
        if blocked:
            self.sidebar_logout_btn.setToolTip(
                tr("logout_blocked_tooltip"))
        else:
            self.sidebar_logout_btn.setToolTip("")

    def _apply_cached_ui(self):
        if not self.api.base:
            return
        if self._ui_applied and self._ui_applied_for == self.api.base:
            return
        cfg = load_config()
        ver, config = get_ui_cache(cfg, self.api.base)
        if config:
            self._ui_version = ver or ""
            self._apply_ui_config(config)
            return
        cached = _read_cached_locales_all()
        if cached:
            _apply_locales(cached)
        self._ui_applied = True
        self._ui_applied_for = self.api.base

    def _apply_ui_config(self, config):
        self._ui_data = config or {}
        locales = _parse_locales(self._ui_data)
        if locales:
            _apply_locales(locales)
        self._ui_applied = True
        self._ui_applied_for = self.api.base

    def _sync_ui_config(self):
        if not self.api.base:
            return
        current_base = self.api.base
        local_version = self._ui_version or ""
        try:
            version, changed = self.api.ui_config_version(
                local_version, timeout=3)
        except Exception as e:
            print(f"[ui_config] version: {e}")
            self._apply_cached_ui()
            return
        if version is None:
            self._apply_cached_ui()
            return
        if self.api.base != current_base:
            return
        if not changed:
            if not self._ui_applied \
                    or self._ui_applied_for != current_base:
                self._apply_cached_ui()
            return
        try:
            ver, config = self.api.ui_config(timeout=5)
        except Exception as e:
            print(f"[ui_config] fetch: {e}")
            self._apply_cached_ui()
            return
        if not config:
            self._apply_cached_ui()
            return
        if self.api.base != current_base:
            return
        self._ui_version = ver or ""
        self._apply_ui_config(config)
        _cfg = load_config()
        set_ui_cache(_cfg, current_base, self._ui_version, config)
        save_config(_cfg)

    def _build_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(10, 15, 10, 15)
        layout.setSpacing(4)

        title = QLabel()
        title.setAlignment(Qt.AlignCenter)
        logo_path = _find_asset("logo_horizontal.png")
        if logo_path:
            pix = QPixmap(logo_path)
            title.setPixmap(pix.scaledToWidth(
                180, Qt.SmoothTransformation))
        else:
            title.setText(tr("sidebar_brand"))
            title.setObjectName("sidebar_title")
            title.setFont(QFont("Arial", 20, QFont.Bold))
        layout.addWidget(title)

        layout.addSpacing(20)

        self.sidebar_user = QLabel(tr("sidebar_unauthorized"))
        self.sidebar_user.setAlignment(Qt.AlignCenter)
        self.sidebar_user.setWordWrap(True)
        self.sidebar_user.setStyleSheet(
            "color:#ecf0f1; font-size:11px; "
            "background:#34495e; border-radius:4px; "
            "padding:6px 8px;")
        layout.addWidget(self.sidebar_user)

        self.sidebar_roles = QLabel("")
        self.sidebar_roles.setAlignment(Qt.AlignCenter)
        self.sidebar_roles.setWordWrap(True)
        self.sidebar_roles.setStyleSheet(
            "color:#95a5a6; font-size:10px; padding:2px;")
        layout.addWidget(self.sidebar_roles)

        layout.addSpacing(20)

        self.sidebar_lang_btn = QPushButton(
            tr("sidebar_menu_language"))
        self.sidebar_lang_btn.setObjectName("sidebar_btn")
        self.sidebar_lang_btn.setCursor(Qt.PointingHandCursor)
        self.sidebar_lang_btn.clicked.connect(self._open_language_dialog)
        layout.addWidget(self.sidebar_lang_btn)

        self.sidebar_logout_btn = QPushButton(
            tr("sidebar_menu_logout"))
        self.sidebar_logout_btn.setObjectName("sidebar_btn")
        self.sidebar_logout_btn.setCursor(Qt.PointingHandCursor)
        self.sidebar_logout_btn.clicked.connect(self._logout)
        self.sidebar_logout_btn.setVisible(False)
        layout.addWidget(self.sidebar_logout_btn)

        layout.addStretch()

        return sidebar

    def _refresh_sidebar_user(self):
        if self.api.token:
            self.sidebar_user.setText(self._fio or "—")
            if self._roles:
                self.sidebar_roles.setText(
                    ", ".join(tr(f"role_{r}") for r in self._roles))
            else:
                self.sidebar_roles.setText(tr("no_roles"))
            self.sidebar_logout_btn.setVisible(True)
        else:
            self.sidebar_user.setText(tr("sidebar_unauthorized"))
            self.sidebar_roles.setText("")
            self.sidebar_logout_btn.setVisible(False)

    def _retranslate_sidebar(self):
        self.sidebar_lang_btn.setText(
            tr("sidebar_menu_language"))
        self.sidebar_logout_btn.setText(
            tr("sidebar_menu_logout"))
        self._refresh_sidebar_user()
        self._update_logout_state()

    def _open_language_dialog(self):
        current = self.api.locale
        dlg = LanguageDialog(current, self._set_locale, self)
        dlg.exec()

    def _set_locale(self, code):
        if code not in available_locales():
            return
        self.api.set_locale(code)
        self._retranslate_all()
        self._retranslate_sidebar()

    def _retranslate_all(self):
        self.login_server.retranslate()
        self.login_employee.retranslate()
        self.modes.retranslate()
        self.session_view.retranslate()
        self.task_exec.retranslate()

    def _force_offline(self):
        if not self.online:
            return
        self.online = False
        self._ping_failures = 3
        self._last_contact = 0
        self.heartbeat.setInterval(1000)
        self._set_offline(True, tr("no_connection"))

    def _go_employee(self):
        self._sync_ui_config()
        self._retranslate_all()
        self._retranslate_sidebar()
        self.stack.setCurrentIndex(1)

    def _go_modes(self):
        try:
            me = self.api.me()
        except ApiError:
            me = {"ok": False, "fio": "—", "roles": []}
        roles = me.get("roles") or []
        if not roles:
            QMessageBox.warning(
                self, tr("title"), tr("no_roles"))
            self._logout()
            return
        try:
            self.api.capabilities_hello(
                protocol="1.0",
                widgets=[
                    "text", "heading", "caption", "card",
                    "group", "divider", "spacer", "progress",
                    "button", "input", "list", "tiles",
                    "image", "barcode", "slot", "table",
                ],
                actions=["scan", "tap", "input_submit",
                         "cancel", "custom"],
                features=["hardware_scan", "notifications"],
                device="pc",
            )
        except Exception:
            pass
        self._fio = me.get("fio", "—")
        self._roles = list(roles or [])
        self.modes.set_user(self._fio, self._roles)
        self._refresh_sidebar_user()

        self._load_settings_with_cache()

        self._refresh_sessions()
        self.stack.setCurrentWidget(self.modes)

    def _load_settings_with_cache(self):
        login = self.api.login or ""
        try:
            ok = self.api.load_settings()
        except Exception:
            ok = False
        cfg = load_config()
        if ok:
            set_settings_cache(
                cfg, self.api.base, login, self.api.settings)
            save_config(cfg)
            return
        cached = get_settings_cache(cfg, self.api.base, login)
        if cached:
            self.api.settings = dict(cached)

    def _refresh_sessions(self):
        try:
            sessions = self.api.sessions_list()
        except ApiError:
            sessions = []
        self.modes.set_sessions(sessions)

    def _open_session(self, key, title):
        try:
            env = self.api.sessions_start(key)
        except ApiError as e:
            if getattr(e, "is_network", False):
                self._force_offline()
            QMessageBox.warning(self, tr("title"),
                                humanize_locale(str(e)))
            return
        self.session_view.start(key, title)
        self.session_view.apply(env.get("nodes") or [])
        if env.get("role_revoked"):
            self.session_view._show_role_revoked()
        if env.get("message"):
            self.show_snackbar(env["message"])
        self.stack.setCurrentWidget(self.session_view)

    def _get_task(self):
        if not self.online:
            return
        self.modes.set_busy(True)
        QApplication.processEvents()
        try:
            data, err = self.api.task_next(platform="pc")
        except ApiError as e:
            self.modes.set_busy(False)
            if getattr(e, "is_network", False):
                self._force_offline()
            QMessageBox.information(self, tr("title"),
                                    humanize_locale(str(e)))
            return
        finally:
            self.modes.set_busy(False)

        if not data:
            msg = {
                "no tasks": tr("no_tasks"),
                "no roles": tr("no_roles"),
                "race": tr("race"),
            }.get(err, err or tr("error_start"))
            QMessageBox.information(self, tr("title"), msg)
            return

        self.task_exec.load_task(data["task"], data["items"])
        self.stack.setCurrentWidget(self.task_exec)

    def _back_to_modes(self):
        self._refresh_sessions()
        self.stack.setCurrentWidget(self.modes)

    def _logout(self):
        # FIX: страховка. Если logout вызван при активном
        # задании/сессии (например, программно или из modes при
        # гонке) — сначала отпускаем задание и закрываем сессию,
        # иначе задание зависнет в in_progress.
        if getattr(self.task_exec, "task_id", 0):
            try:
                self.api.task_action(
                    self.task_exec.task_id, "cancel", None, None,
                    self.task_exec.current_meta.step_no
                    if self.task_exec.current_meta else None)
            except Exception:
                pass
            self.task_exec.task_id = 0
            self.task_exec.current_meta = None
            self.task_exec.current_nodes = []

        if getattr(self.session_view, "session_key", ""):
            try:
                self.api.sessions_close(
                    self.session_view.session_key, force=True)
            except Exception:
                pass
            self.session_view.session_key = ""

        try:
            sessions = self.api.sessions_list()
            for s in sessions:
                try:
                    self.api.sessions_close(s.key, force=True)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self.api.logout()
        except Exception:
            pass
        self.api.token = None
        self.api.login = ""
        self._fio = "—"
        self._roles = []
        self._ping_failures = 0
        self.online = True
        self.heartbeat.setInterval(5000)
        self._set_offline(False)
        self.login_server.reset()
        self._refresh_sidebar_user()
        self._update_logout_state()
        self.stack.setCurrentIndex(0)

    def _dispatch_scan(self, code):
        if not self.online:
            return
        w = self.stack.currentWidget()
        if w is self.login_server:
            self.login_server.handle_scan(code)
            self._ui_applied = False
            self._ui_applied_for = ""
            self._ui_version = ""
            self._apply_cached_ui()
        elif w is self.login_employee:
            self.login_employee.handle_scan(code)
        elif w is self.session_view:
            self.session_view.handle_scan(code)
        elif w is self.task_exec:
            self.task_exec.handle_scan(code)

    def show_snackbar(self, text: str):
        if not text:
            return
        self.snackbar.setText(text)
        self.snackbar.adjustSize()
        self.snackbar.setVisible(True)
        self._place_snackbar()
        self._snackbar_timer.start(3500)

    def _place_snackbar(self):
        w = self.width()
        h = self.height()
        sw = self.snackbar.width()
        sh = self.snackbar.height()
        self.snackbar.move((w - sw) // 2, h - sh - 30)
        self.snackbar.raise_()

    def _set_offline(self, is_offline: bool, reason: str = ""):
        self.offline_overlay.setGeometry(0, 0, self.width(),
                                         self.height())
        if is_offline:
            info = []
            if self._ping_failures:
                info.append(tr("attempt", n=self._ping_failures))
            if self._last_contact:
                ago = int(time.time() - self._last_contact)
                info.append(tr("last_contact", sec=ago))
            if reason:
                info.append(reason)
            self.offline_info.setText("\n".join(info))
            self.offline_overlay.setVisible(True)
            self.offline_overlay.raise_()
        else:
            self.offline_overlay.setVisible(False)

    def _ping(self):
        if not self.api.base or not self.api.token:
            return
        ok = self.api.ping()
        if ok:
            self._last_contact = time.time()
            if not self.online:
                self.online = True
                self._ping_failures = 0
                self.heartbeat.setInterval(5000)
                self._set_offline(False)
                if self.stack.currentWidget() is self.session_view:
                    try:
                        env = self.api.sessions_start(
                            self.session_view.session_key)
                        self.session_view._apply_env(env)
                    except Exception:
                        pass
                elif self.stack.currentWidget() is self.task_exec:
                    self.task_exec._refresh_view()
            else:
                self._ping_failures = 0
        else:
            self._ping_failures += 1
            if self.online and self._ping_failures >= 3:
                self.online = False
                self.heartbeat.setInterval(1000)
                self._set_offline(True, tr("no_connection"))
            elif not self.online:
                self._set_offline(True, tr("no_connection"))

    def _poll_notifications(self):
        if not self.api.token or not self.online:
            return
        try:
            items = self.api.notifications_inbox()
        except ApiError as e:
            if getattr(e, "is_network", False):
                self._force_offline()
            return
        except Exception:
            return
        if not items:
            return
        self._notif_queue.extend(items)
        self._show_next_notification()

    def _show_next_notification(self):
        if self._notif_showing or not self._notif_queue:
            return
        self._notif_showing = True
        item = self._notif_queue.pop(0)
        dlg = NotificationDialog(item, self)
        dlg.exec()
        try:
            self.api.notifications_mark_read([item.id])
        except Exception:
            pass
        self._notif_showing = False
        QTimer.singleShot(300, self._show_next_notification)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_snackbar()
        self.offline_overlay.setGeometry(0, 0, self.width(),
                                         self.height())
        self.hidden_input.move(0, 0)

    def _apply_styles(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #f0f0f0; }
            QWidget {
                background-color: #f0f0f0;
                color: #2c3e50;
            }
            QFrame#sidebar { background-color: #2c3e50; }
            QLabel {
                background: transparent; color: #2c3e50;
            }
            QFrame#sidebar QLabel { color: #ecf0f1; }
            QLabel#sidebar_title {
                color: #ecf0f1; padding: 8px 0 4px 0;
            }
            QPushButton {
                background-color: #ffffff; color: #2c3e50;
                border: 1px solid #bdc3c7; border-radius: 6px;
                padding: 8px 14px; font-size: 13px;
            }
            QPushButton:hover { background-color: #ecf0f1; }
            QPushButton:pressed { background-color: #d5dbdb; }
            QPushButton:disabled {
                background-color: #ecf0f1; color: #95a5a6;
                border-color: #d5dbdb;
            }
            QPushButton#sidebar_btn {
                background: transparent; color: #bdc3c7;
                border: none; border-radius: 6px;
                padding: 12px 14px; text-align: left;
                font-size: 14px;
            }
            QPushButton#sidebar_btn:hover {
                background-color: #34495e; color: #ecf0f1;
            }
            QPushButton#sidebar_btn:pressed {
                background-color: #1a252f;
            }
            QPushButton#sidebar_btn:disabled {
                background: transparent;
                color: #6b7a85;
            }
            QPushButton#primary_btn {
                background-color: #27ae60; color: white;
                border: none; border-radius: 6px;
                padding: 10px 16px; font-weight: bold;
            }
            QPushButton#primary_btn:hover { background-color: #2ecc71; }
            QPushButton#primary_btn:pressed { background-color: #1e8449; }
            QPushButton#primary_btn:disabled {
                background-color: #bdc3c7; color: #ecf0f1;
            }
            QLineEdit {
                background: #ffffff; color: #2c3e50;
                border: 1px solid #bdc3c7; border-radius: 4px;
                padding: 6px 8px;
            }
            QLineEdit:focus { border-color: #27ae60; }
            QScrollArea { background: #f0f0f0; border: none; }
            QProgressBar {
                background: #ecf0f1; border: 1px solid #bdc3c7;
                border-radius: 4px; text-align: center;
                color: #2c3e50;
            }
            QProgressBar::chunk {
                background-color: #27ae60; border-radius: 3px;
            }
        """)


def main():
    QApplication.setStyle("Fusion")
    app = QApplication(sys.argv)

    icon_path = _find_asset("icon.png")
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#f0f0f0"))
    palette.setColor(QPalette.WindowText, QColor("#2c3e50"))
    palette.setColor(QPalette.Base, QColor("#ffffff"))
    palette.setColor(QPalette.AlternateBase, QColor("#ecf0f1"))
    palette.setColor(QPalette.Text, QColor("#2c3e50"))
    palette.setColor(QPalette.Button, QColor("#ffffff"))
    palette.setColor(QPalette.ButtonText, QColor("#2c3e50"))
    palette.setColor(QPalette.Highlight, QColor("#27ae60"))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText,
                     QColor("#95a5a6"))
    palette.setColor(QPalette.Disabled, QPalette.WindowText,
                     QColor("#95a5a6"))
    app.setPalette(palette)

    cli_locale = None
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--locale" and i + 1 < len(args):
            cli_locale = args[i + 1]
            i += 2
            continue
        i += 1

    _init_locales()

    if cli_locale and cli_locale in available_locales():
        chosen = cli_locale
    else:
        cfg = load_config()
        candidate = cfg.get("locale", "ru")
        chosen = candidate if candidate in available_locales() else "ru"

    class _BootstrapApi:
        locale = chosen
    tr.api = _BootstrapApi()

    w = MainWindow()
    w.api.set_locale(chosen)
    tr.api = w.api
    w._retranslate_all()
    w._retranslate_sidebar()

    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()