"""«Сотрудники» — серверная сборка view и действия."""

import sqlite3
import json
import secrets
import base64
import os

from PySide6.QtCore import Qt, QBuffer, QIODevice
from PySide6.QtGui import QFont, QPixmap, QImage, QPainter, QColor

from mgmt_protocol import (
    mgmt_page, mgmt_toolbar, mgmt_table, mgmt_form_field,
    heading, text, card, caption, button, spacer,
    mgmt_file_trigger, make_mgmt_document, mgmt_header, group,
    mgmt_image, mgmt_dialog
)
from mgmt_view_builder import build_sidebar
from barcodes import make_qr_pixmap
from i18n import tr
from roles import list_roles
from db import hash_password, invalidate_sessions


BADGE_W, BADGE_H = 900, 600


def _role_label(key):
    for r in list_roles():
        if r["key"] == key:
            if r.get("title_key"):
                return tr(r["title_key"], r.get("title") or key)
            return r.get("title") or key
    return key


def _doc(page, role):
    return make_mgmt_document(
        page, sidebar=build_sidebar(role),
        extra={"role": role})


def _make_placeholder_image(w, h, txt, bg, fg, border=None):
    pm = QPixmap(w, h)
    pm.fill(QColor(bg))
    painter = QPainter(pm)
    if border:
        painter.setPen(QColor(border))
        painter.drawRect(0, 0, w - 1, h - 1)
    if txt:
        font = QFont()
        font.setPointSize(16)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(fg))
        painter.drawText(pm.rect(), Qt.AlignCenter, txt)
    painter.end()
    qb = QBuffer()
    qb.open(QIODevice.WriteOnly)
    pm.save(qb, "PNG")
    raw = bytes(qb.data())
    qb.close()
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def _make_badge(fio, login, payload, photo_bytes):
    img = QImage(BADGE_W, BADGE_H, QImage.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    pen = p.pen()
    pen.setColor(QColor("#2c3e50"))
    pen.setWidth(4)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRect(4, 4, BADGE_W - 8, BADGE_H - 8)

    p.setPen(QColor("#e67e22"))
    f = QFont()
    f.setPointSize(32)
    f.setBold(True)
    p.setFont(f)
    p.drawText(0, 20, BADGE_W, 60, Qt.AlignCenter,
               tr("employees.label.badge", "ПРОПУСК"))

    px, py, pw, ph = 40, 100, 300, 400
    drawn = False
    if photo_bytes:
        pm = QPixmap()
        if pm.loadFromData(photo_bytes) and not pm.isNull():
            pm = pm.scaled(pw, ph, Qt.KeepAspectRatio,
                           Qt.SmoothTransformation)
            p.drawPixmap(px + (pw - pm.width()) // 2,
                         py + (ph - pm.height()) // 2, pm)
            drawn = True
    if not drawn:
        p.setPen(QColor("#95a5a6"))
        f = QFont()
        f.setPointSize(16)
        p.setFont(f)
        p.drawRect(px, py, pw, ph)
        p.drawText(px, py, pw, ph, Qt.AlignCenter,
                   tr("employees.panel.no_photo", "НЕТ ФОТО"))

    p.setPen(QColor("#2c3e50"))
    f = QFont()
    f.setPointSize(22)
    f.setBold(True)
    p.setFont(f)
    p.drawText(370, 120, BADGE_W - 410, 80,
               Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap, fio)

    p.setPen(QColor("#7f8c8d"))
    f = QFont()
    f.setPointSize(14)
    p.setFont(f)
    p.drawText(370, 210, BADGE_W - 410, 40,
               Qt.AlignLeft | Qt.AlignVCenter,
               tr("employees.badge.login", "Логин: {login}",
                  login=login))
    qr = make_qr_pixmap(payload, size=220)
    if qr:
        p.drawPixmap(BADGE_W - 260, BADGE_H - 260, qr)
    p.end()

    qb = QBuffer()
    qb.open(QIODevice.WriteOnly)
    img.save(qb, "PNG")
    data = bytes(qb.data())
    qb.close()
    return data


def _list_rows(db_path, search="", role_filter=""):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, last_name, first_name, middle_name, login,
                   role, roles
            FROM employees ORDER BY last_name COLLATE NOCASE
        """)
        rows = []
        s = (search or "").lower()
        for (eid, last, first, middle, login,
             role, roles_txt) in cur.fetchall():
            try:
                role_list = json.loads(roles_txt) if roles_txt else []
            except Exception:
                role_list = []
            fio = " ".join(p for p in
                           [last or "", first or "", middle or ""]
                           if p)
            if s and s not in fio.lower() \
                    and s not in (login or "").lower():
                continue
            if role_filter == "__none__":
                if role_list:
                    continue
            elif role_filter:
                if role_filter not in role_list:
                    continue
            role_str = ", ".join(_role_label(r) for r in role_list)
            if not role_str:
                role_str = tr("employees.no_roles_short",
                              "Нет ролей")
            rows.append({
                "id": eid,
                "fio": fio,
                "login": login or "",
                "roles": role_str,
            })
        return rows
    finally:
        conn.close()


def _build_list(db_path, role, search="", role_filter="",
                message=None, error=None):
    header_actions = [
        button(tr("employees.btn.add", "+ Добавить"),
               "tap", "add_open", style="primary"),
        button(tr("employees.btn.delete", "Удалить"),
               "tap", "delete"),
    ]
    children = [mgmt_header(
        tr("employees.title", "Сотрудники"), header_actions)]
    if message:
        children.append(card([text(message)], accent="success"))
    if error:
        children.append(card([text(error)], accent="error"))

    role_options = [
        {"value": "", "label": tr("employees.filter.all", "Все")},
    ] + [
        {"value": r["key"], "label": _role_label(r["key"])}
        for r in list_roles()
    ] + [
        {"value": "__none__",
         "label": tr("employees.filter.none", "Нет ролей")},
    ]

    children.append(group([
        mgmt_form_field(
            "search", kind="text",
            label=tr("common.search", "Поиск:"),
            label_position="left", stretch=True,
            value=search,
            placeholder=tr("employees.search_placeholder",
                           "Фильтр по ФИО, логину…"),
            on_change="input_submit"),
        mgmt_form_field(
            "role_filter", kind="select",
            label=tr("employees.filter.role", "Роль:"),
            label_position="left",
            value=role_filter,
            options=role_options,
            on_change="input_submit"),
        button(tr("employees.btn.refresh", "Обновить"),
               "tap", "refresh"),
    ], orientation="horizontal"))

    children.append(mgmt_table(
        columns=[
            {"key": "fio",
             "label": tr("employees.col.fio", "ФИО")},
            {"key": "login",
             "label": tr("employees.col.login", "Логин")},
            {"key": "roles",
             "label": tr("employees.col.roles", "Роли")},
        ],
        rows=_list_rows(db_path, search=search,
                        role_filter=role_filter),
        on_double_click={
            "action": "tap", "id": "open_panel",
            "value_field": "id"},
        row_key="id",
        field_id="table_0",
        empty_label="",
        searchable=False,
    ))
    children.append(caption(
        tr("notifications.double_click_hint",
           "Двойной клик — карточка сотрудника.")))

    return mgmt_page("employees",
                     tr("employees.title", "Сотрудники"),
                     children)


def _build_add(db_path, role, error=None, values=None):
    """Карточка «Новый сотрудник».

    FIX: принимает values. Раньше при загрузке/удалении фото и
    при ошибке валидации карточка перерисовывалась без values —
    все введённые поля сбрасывались. Теперь значения сохраняются.
    """
    values = values or {}
    title = tr("employees.card.new", "Новый сотрудник")

    def gv(k, default=""):
        return values.get(k, default)

    children = [
        mgmt_header(title, [
            button(tr("common.back", "← Назад"),
                   "tap", "back"),
            button(tr("employees.btn.create", "Создать"),
                   "tap", "add_commit", style="primary"),
        ]),
    ]
    if error:
        children.append(card([text(error)], accent="error"))

    photo_blob = _get_temp_photo(db_path)

    left_col = []
    if photo_blob:
        b64 = base64.b64encode(photo_blob).decode("ascii")
        left_col.append(mgmt_image(
            f"data:image/png;base64,{b64}",
            width=300, height=300))
    else:
        ph_b64 = _make_placeholder_image(
            300, 300,
            tr("employees.panel.no_photo", "НЕТ ФОТО"),
            "#34495e", "#95a5a6", "#5d7288")
        left_col.append(mgmt_image(ph_b64, width=300, height=300))

    if photo_blob:
        left_col.append(group([
            mgmt_file_trigger(
                "photo",
                tr("employees.btn.change_photo", "Сменить фото"),
                accept="Images (*.png *.jpg *.jpeg *.bmp)",
                action="upload",
                action_id="photo_upload"),
            button(tr("employees.btn.remove_photo",
                      "Убрать фото"),
                   "tap", "photo_clear"),
        ], orientation="horizontal", spacing=8))
    else:
        left_col.append(mgmt_file_trigger(
            "photo",
            tr("employees.btn.upload_photo", "Загрузить фото"),
            accept="Images (*.png *.jpg *.jpeg *.bmp)",
            action="upload",
            action_id="photo_upload"))

    left_col.append(group([], orientation="vertical", stretch=True))

    right_col = [
        card([
            mgmt_form_field(
                "last_name", kind="text",
                label=tr("employees.dialog.add.last_name",
                         "Фамилия*:"),
                label_position="left", label_width=150,
                stretch=True,
                value=gv("last_name", "")),
            mgmt_form_field(
                "first_name", kind="text",
                label=tr("employees.dialog.add.first_name",
                         "Имя*:"),
                label_position="left", label_width=150,
                stretch=True,
                value=gv("first_name", "")),
            mgmt_form_field(
                "middle_name", kind="text",
                label=tr("employees.dialog.add.middle_name",
                         "Отчество:"),
                label_position="left", label_width=150,
                stretch=True,
                value=gv("middle_name", "")),
            mgmt_form_field(
                "login", kind="text",
                label=tr("employees.dialog.add.login", "Логин*:"),
                label_position="left", label_width=150,
                stretch=True,
                value=gv("login", "")),
        ], title=tr("employees.card.main", "Основное")),
    ]

    role_fields = []
    for r in list_roles():
        checked = values.get(
            f"role_{r['key']}",
            r["key"] == "picker")
        role_fields.append(mgmt_form_field(
            f"role_{r['key']}", kind="checkbox",
            label=_role_label(r["key"]),
            value=bool(checked)))
    right_col.append(card(
        role_fields,
        title=tr("employees.panel.roles_title",
                 "Роли (можно несколько, можно ни одной)")))

    children.append(group([
        group(left_col, orientation="vertical"),
        group(right_col, orientation="vertical", stretch=True),
    ], orientation="horizontal", spacing=20))

    return mgmt_page("employees", title, children)


def _build_panel(db_path, role, eid, message=None, error=None,
                 badge_b64=None):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT first_name, last_name, middle_name, login,
                   pass_hash, photo, role, roles
            FROM employees WHERE id=?
        """, (eid,))
        r = cur.fetchone()
    finally:
        conn.close()
    if not r:
        return _build_list(
            db_path, role,
            error=tr("employees.err.not_found", "не найден"))
    first, last, middle, login, ph, photo, role1, roles_txt = r
    fio = " ".join(p for p in
                   [last or "", first or "", middle or ""] if p)
    try:
        role_list = json.loads(roles_txt) if roles_txt else []
    except Exception:
        role_list = []

    children = []

    header_children = [
        button(tr("employees.btn.back", "← Назад"),
               "tap", "back"),
        heading(tr("employees.panel.header",
                   "Сотрудник: {fio}", fio=fio)),
        {"type": "text", "value": "", "stretch": True},
        button(tr("employees.btn.save_roles",
                  "Сохранить роли"),
               "tap", "save_roles",
               value={"id": eid}, style="primary"),
    ]
    children.append(group(header_children, orientation="horizontal"))

    if message:
        children.append(card([text(message)], accent="success"))
    if error:
        children.append(card([text(error)], accent="error"))

    left_col = []
    if photo:
        b64 = base64.b64encode(bytes(photo)).decode("ascii")
        left_col.append(mgmt_image(
            f"data:image/png;base64,{b64}", width=240, height=300))
    else:
        ph_b64 = _make_placeholder_image(
            240, 300,
            tr("employees.panel.no_photo", "НЕТ ФОТО"),
            "#34495e", "#95a5a6", "#3d566e")
        left_col.append(mgmt_image(ph_b64, width=240, height=300))

    left_col.append(group([], orientation="vertical", stretch=True))

    right_col = []
    info_children = [
        text(tr("employees.panel.fio",
                "<b>ФИО:</b> {fio}", fio=fio or "—")),
        text(tr("employees.panel.login",
                "<b>Логин:</b> {login}", login=login or "—")),
        text(tr("employees.panel.hash",
                "<b>Хэш:</b> {hash}",
                hash=(ph[:24] + "…") if ph and len(ph) > 24
                     else (ph or "—"))),
    ]
    right_card = card(
        info_children,
        title=tr("employees.panel.characteristics",
                 "Характеристики"))
    right_card["stretch"] = True
    right_col.append(right_card)

    children.append(group([
        group(left_col, orientation="vertical"),
        group(right_col, orientation="vertical", stretch=True)
    ], orientation="horizontal", spacing=20))

    role_fields = []
    known_keys = {r["key"] for r in list_roles()}
    for r in list_roles():
        role_fields.append(mgmt_form_field(
            f"role_{r['key']}", kind="checkbox",
            label=_role_label(r["key"]),
            value=(r["key"] in role_list)))
    children.append(card(
        role_fields,
        title=tr("employees.panel.roles_title",
                 "Роли (можно несколько, можно ни одной)")))

    unknown = [r for r in role_list if r not in known_keys]
    if unknown:
        children.append(caption(
            f"Роли вне реестра (сохранятся): "
            f"{', '.join(unknown)}"))

    children.append(mgmt_toolbar([
        button(tr("employees.btn.regen_badge",
                  "Сгенерировать новый пропуск"),
               "tap", "regen_badge", value={"id": eid}),
    ]))

    if badge_b64:
        children.append(card([
            text(tr("employees.panel.new_badge",
                    "Новый пропуск (сохраните PNG):")),
            mgmt_file_trigger(
                "badge",
                tr("employees.btn.download_badge",
                   "Скачать пропуск"),
                action="download",
                download_b64=badge_b64,
                filename=f"{login}_badge.png"),
        ], accent="success"))
    return mgmt_page("employees",
                     tr("employees.title", "Сотрудники"),
                     children)


def build_view(login, role, context):
    return _doc(_build_list(context.db_path, role), role)


def _get_temp_photo(db_path):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT value FROM settings WHERE key='_mgmt_temp_photo'")
        r = cur.fetchone()
        if r and r[0]:
            try:
                return base64.b64decode(r[0])
            except Exception:
                return None
        return None
    finally:
        conn.close()


def _set_temp_photo(db_path, blob_or_none):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM settings WHERE key='_mgmt_temp_photo'")
        val = base64.b64encode(blob_or_none).decode("ascii") \
            if blob_or_none else ""
        if cur.fetchone():
            cur.execute(
                "UPDATE settings SET value=? "
                "WHERE key='_mgmt_temp_photo'", (val,))
        else:
            cur.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)",
                ("_mgmt_temp_photo", val))
        conn.commit()
    finally:
        conn.close()


def _collect_selected_roles(values, existing=None):
    known = {r["key"] for r in list_roles()}
    selected = [r["key"] for r in list_roles()
                if values.get(f"role_{r['key']}")]
    if existing:
        for r in existing:
            if r not in known and r not in selected:
                selected.append(r)
    return selected


def handle_action(action, action_id, value, login, role,
                  context, values=None):
    values = values or {}
    db_path = context.db_path

    if action == "input_submit" and action_id in ("search",
                                                    "role_filter"):
        search = str(values.get("search") or "")
        rf = str(values.get("role_filter") or "")
        return {"ok": True, "view": _doc(_build_list(
            db_path, role, search=search,
            role_filter=rf), role)}

    if action == "upload" and action_id == "photo_upload":
        if isinstance(value, dict) and value.get("b64"):
            try:
                blob = base64.b64decode(value["b64"])
                _set_temp_photo(db_path, blob)
            except Exception:
                pass
        # FIX: передаём values, чтобы поля формы не сбрасывались
        # при загрузке фото.
        return {"ok": True,
                "message": tr("employees.msg.photo_loaded",
                              "Фото загружено"),
                "view": _doc(_build_add(
                    db_path, role, values=values), role)}

    if action == "tap":
        if action_id == "photo_clear":
            _set_temp_photo(db_path, None)
            # FIX: сохраняем значения полей.
            return {"ok": True, "view": _doc(
                _build_add(db_path, role, values=values), role)}

        if action_id == "add_open":
            _set_temp_photo(db_path, None)
            return {"ok": True, "view": _doc(
                _build_add(db_path, role), role)}
        if action_id == "refresh":
            return {"ok": True, "view": _doc(
                _build_list(db_path, role), role)}
        if action_id == "dialog_cancel":
            _set_temp_photo(db_path, None)
            return {"ok": True, "view": _doc(
                _build_list(db_path, role), role)}
        if action_id == "add_commit":
            return _add_commit(db_path, role, values)
        if action_id == "open_panel":
            try:
                eid = int(value)
            except (TypeError, ValueError):
                return {"ok": False,
                        "error": tr("employees.err.bad_id",
                                    "bad id")}
            return {"ok": True, "view": _doc(
                _build_panel(db_path, role, eid), role)}
        if action_id == "back":
            return {"ok": True, "view": _doc(
                _build_list(db_path, role), role)}
        if action_id == "delete":
            sel = values.get("table_0_selected", [])
            if not sel:
                return {"ok": False,
                        "error": tr("employees.err.not_found",
                                    "не найден")}
            eid = sel[0].get("id")
            if not eid:
                return {"ok": False,
                        "error": tr("employees.err.not_found",
                                    "не найден")}
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    "DELETE FROM employees WHERE id=?", (eid,))
                conn.commit()
            finally:
                conn.close()
            return {"ok": True,
                    "message": tr("employees.msg.deleted",
                                  "Удалён"),
                    "view": _doc(_build_list(db_path, role),
                                 role)}
        if action_id == "save_roles":
            eid = value.get("id") if isinstance(value, dict) else None
            if not eid:
                return {"ok": False,
                        "error": tr("employees.err.bad_id",
                                    "bad id")}
            conn = sqlite3.connect(db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT roles FROM employees WHERE id=?", (eid,))
                r = cur.fetchone()
                try:
                    existing = json.loads(r[0]) if r and r[0] else []
                except Exception:
                    existing = []
                selected = _collect_selected_roles(values, existing)
                cur.execute(
                    "UPDATE employees SET role=?, roles=? "
                    "WHERE id=?",
                    (selected[0] if selected else "",
                     json.dumps(selected), eid))
                conn.commit()
            finally:
                conn.close()
            return {"ok": True,
                    "message": tr("employees.msg.roles_saved",
                                  "Роли сохранены"),
                    "view": _doc(_build_panel(
                        db_path, role, eid), role)}
        if action_id == "regen_badge":
            eid = value.get("id") if isinstance(value, dict) else None
            if not eid:
                return {"ok": False,
                        "error": tr("employees.err.bad_id",
                                    "bad id")}
            return _regen_badge(db_path, role, eid)
    return {"ok": False,
            "error": tr("employees.err.unknown_action",
                        "unknown action: {id}", id=action_id)}


def _add_commit(db_path, role, values):
    last = str(values.get("last_name") or "").strip()
    first = str(values.get("first_name") or "").strip()
    middle = str(values.get("middle_name") or "").strip()
    login_v = str(values.get("login") or "").strip()

    def _err(text_):
        # FIX: передаём values, чтобы при ошибке валидации
        # (логин занят / пустые поля) введённые данные не терялись.
        return {"ok": True, "view": _doc(
            _build_add(db_path, role, error=text_,
                       values=values), role)}

    if not last or not first or not login_v:
        return _err(tr("employees.err.fill_required",
                       "фамилия, имя и логин обязательны"))
    for ch in login_v:
        if not ((ch.isascii() and ch.isalnum()) or ch in "_."):
            return _err(tr("managers.err.login_format",
                           "логин: только a-z, 0-9, _ и ."))

    selected = _collect_selected_roles(values, existing=None)

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM employees WHERE login=?",
                    (login_v,))
        if cur.fetchone():
            return _err(tr("employees.err.login_taken",
                           "логин занят"))
        secret = secrets.token_hex(8)
        pass_hash = hash_password(secret)
        fio = " ".join([last, first] +
                       ([middle] if middle else []))
        photo = _get_temp_photo(db_path)
        badge = _make_badge(fio, login_v,
                            f"{login_v}-{secret}", photo)
        cur.execute("""
            INSERT INTO employees (first_name, last_name,
                middle_name, login, pass_hash, photo, role, roles)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (first, last, middle, login_v, pass_hash, photo,
              selected[0] if selected else "",
              json.dumps(selected)))
        conn.commit()
    finally:
        conn.close()

    try:
        wh_dir = os.path.dirname(db_path)
        badges_dir = os.path.join(wh_dir, "badges")
        os.makedirs(badges_dir, exist_ok=True)
        with open(os.path.join(badges_dir,
                                f"{login_v}_badge.png"), "wb") as f:
            f.write(badge)
    except Exception:
        pass

    _set_temp_photo(db_path, None)
    b64 = base64.b64encode(badge).decode("ascii")
    return {"ok": True,
            "message": tr("employees.msg.created",
                          "Сотрудник {login} создан",
                          login=login_v),
            "view": _doc(_build_list(
                db_path, role,
                message=tr(
                    "employees.msg.created_with_badge",
                    "Сотрудник {login} создан. "
                    "Пропуск: badges/{login}_badge.png",
                    login=login_v)), role),
            "badge_b64": b64}


def _regen_badge(db_path, role, eid):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT first_name, last_name, middle_name, login,
                   photo FROM employees WHERE id=?
        """, (eid,))
        r = cur.fetchone()
        if not r:
            return {"ok": True, "view": _doc(
                _build_list(
                    db_path, role,
                    error=tr("employees.err.not_found",
                             "не найден")), role)}
        first, last, middle, login_v, photo = r
        secret = secrets.token_hex(8)
        pass_hash = hash_password(secret)
        cur.execute(
            "UPDATE employees SET pass_hash=? WHERE id=?",
            (pass_hash, eid))
        conn.commit()
    finally:
        conn.close()

    # Инвалидировать активные сессии сотрудника: старый QR
    # (login-secret) больше не действителен.
    try:
        invalidate_sessions(db_path, login_v, "employee")
    except Exception:
        pass

    fio = " ".join(p for p in [last or "", first or "",
                               middle or ""] if p)
    badge = _make_badge(fio, login_v, f"{login_v}-{secret}",
                        photo)
    try:
        wh_dir = os.path.dirname(db_path)
        badges_dir = os.path.join(wh_dir, "badges")
        os.makedirs(badges_dir, exist_ok=True)
        with open(os.path.join(badges_dir,
                                f"{login_v}_badge.png"), "wb") as f:
            f.write(badge)
    except Exception:
        pass
    b64 = base64.b64encode(badge).decode("ascii")
    return {"ok": True,
            "message": tr("employees.msg.badge_regen",
                          "Пропуск перегенерирован"),
            "view": _doc(_build_panel(
                db_path, role, eid,
                badge_b64=b64), role)}