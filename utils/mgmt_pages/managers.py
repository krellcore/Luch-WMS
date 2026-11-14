"""«Руководители» — серверная сборка view и действия."""

import sqlite3
import hashlib
import secrets

from mgmt_protocol import (
    mgmt_page, mgmt_toolbar, mgmt_table, mgmt_form_field,
    mgmt_dialog, heading, text, card, caption, button,
    make_mgmt_document, mgmt_header, group,
)
from mgmt_view_builder import build_sidebar
from i18n import tr


MANAGEABLE_ROLES = ("admin", "operator")


def _role_label(role):
    key = f"managers.role.{role or 'operator'}"
    default = {
        "owner": "Владелец",
        "admin": "Администратор",
        "operator": "Оператор",
    }.get(role or "operator", role or "")
    return tr(key, default)


def _hash(pwd):
    return hashlib.sha256(pwd.encode("utf-8")).hexdigest()


def _doc(page, role):
    return make_mgmt_document(
        page, sidebar=build_sidebar(role),
        extra={"role": role})


def _list_rows(db_path, search="", role_filter=""):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, login, role, created_at
            FROM managers ORDER BY login COLLATE NOCASE
        """)
        rows = []
        s = (search or "").lower()
        for mid, login, role, created_at in cur.fetchall():
            if s and s not in (login or "").lower():
                continue
            if role_filter and role != role_filter:
                continue
            rows.append({
                "id": mid,
                "login": login or "",
                "role": _role_label(role),
                "role_key": role or "operator",
                "created": (created_at or "")[:19],
            })
        return rows
    finally:
        conn.close()


def _build_list(db_path, role, search="", role_filter="",
                message=None, error=None, dialog=None):
    header_actions = [
        button(tr("managers.btn.add", "+ Добавить"),
               "tap", "add_open", style="primary"),
        button(tr("managers.btn.delete", "Удалить"),
               "tap", "delete"),
    ]
    children = [mgmt_header(
        tr("managers.title", "Руководители"), header_actions)]
    if message:
        children.append(card([text(message)], accent="success"))
    if error:
        children.append(card([text(error)], accent="error"))

    role_options = [
        {"value": "", "label": tr("managers.filter.all", "Все")},
    ] + [
        {"value": r, "label": _role_label(r)}
        for r in ("owner", "admin", "operator")
    ]

    children.append(group([
        mgmt_form_field(
            "search", kind="text",
            label=tr("managers.filter.search", "Поиск:"),
            label_position="left", stretch=True,
            value=search,
            placeholder=tr("managers.filter.placeholder",
                           "Фильтр по логину…"),
            on_change="input_submit"),
        mgmt_form_field(
            "role_filter", kind="select",
            label=tr("managers.filter.role", "Роль:"),
            label_position="left",
            value=role_filter,
            options=role_options,
            on_change="input_submit"),
        button(tr("managers.btn.refresh", "Обновить"),
               "tap", "refresh"),
    ], orientation="horizontal"))

    children.append(mgmt_table(
        columns=[
            {"key": "login",
             "label": tr("managers.col.login", "Логин")},
            {"key": "role",
             "label": tr("managers.col.role", "Роль")},
            {"key": "created",
             "label": tr("managers.col.created", "Создан")},
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
        tr("task.wizard.hint.remove_item",
           "Двойной клик — карточка руководителя.")))
    return mgmt_page("managers",
                     tr("managers.title", "Руководители"),
                     children)


def _add_dialog():
    return mgmt_dialog(
        "add",
        tr("managers.dialog.add.title", "Новый руководитель"),
        [
            mgmt_form_field(
                "login", kind="text",
                label=tr("managers.dialog.add.login",
                         "Логин*:"),
                stretch=True,
                placeholder=tr(
                    "managers.dialog.add.login_placeholder",
                    "a-z, 0-9, _, .")),
            mgmt_form_field(
                "password", kind="password",
                label=tr("managers.dialog.add.password",
                         "Пароль*:"),
                stretch=True),
            mgmt_form_field(
                "password2", kind="password",
                label=tr("managers.dialog.add.password2",
                         "Повтор*:"),
                stretch=True),
            mgmt_form_field(
                "role", kind="select",
                label=tr("managers.dialog.add.role", "Роль*:"),
                value="operator", stretch=True,
                options=[
                    {"value": r, "label": _role_label(r)}
                    for r in MANAGEABLE_ROLES
                ]),
        ],
        buttons=[
            button(tr("managers.btn.create", "Создать"),
                   "tap", "add_commit", style="primary"),
            button(tr("managers.btn.cancel", "Отмена"),
                   "tap", "dialog_cancel"),
        ],
    )


def _build_panel(db_path, role, mid, message=None, error=None):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT login, role, created_at FROM managers WHERE id=?
        """, (mid,))
        r = cur.fetchone()
    finally:
        conn.close()
    if not r:
        return _build_list(
            db_path, role,
            error=tr("managers.err.not_found", "не найден"))
    login, mrole, created = r
    is_owner = (mrole == "owner")

    children = [
        mgmt_header(
            tr("managers.panel.header",
               "Руководитель: {login}", login=login),
            [button(tr("managers.btn.back", "← Назад"),
                    "tap", "back")],
        ),
    ]
    if message:
        children.append(card([text(message)], accent="success"))
    if error:
        children.append(card([text(error)], accent="error"))

    children.append(card([
        text(tr("managers.panel.login",
                "<b>Логин:</b> {login}", login=login)),
        text(tr("managers.panel.role",
                "<b>Роль:</b> {role}",
                role=_role_label(mrole))),
        text(tr("managers.panel.created",
                "<b>Создан:</b> {date}",
                date=(created or "")[:19])),
    ], title=tr("managers.panel.info_title", "Сведения")))

    if is_owner:
        children.append(caption(tr(
            "managers.panel.owner_hint",
            "Роль владельца назначается только при создании "
            "склада и не может быть изменена.")))
    else:
        children.append(card([
            mgmt_form_field(
                "role", kind="select",
                label=tr("managers.panel.role_title", "Роль"),
                value=mrole, stretch=True,
                options=[
                    {"value": r, "label": _role_label(r)}
                    for r in MANAGEABLE_ROLES
                ]),
        ], title=tr("managers.panel.role_title", "Роль")))
        children.append(mgmt_toolbar([
            button(tr("managers.btn.save_role",
                      "Сохранить роль"),
                   "tap", "save_role", value={"id": mid},
                   style="primary"),
            button(tr("managers.btn.reset_password",
                      "Сбросить пароль"),
                   "tap", "reset_password", value={"id": mid}),
        ]))

    return mgmt_page("managers",
                     tr("managers.title", "Руководители"),
                     children)


def build_view(login, role, context):
    return _doc(_build_list(context.db_path, role), role)


def handle_action(action, action_id, value, login, role,
                  context, values=None):
    values = values or {}
    db_path = context.db_path

    if action == "input_submit" and action_id in ("search",
                                                    "role_filter"):
        return {"ok": True, "view": _doc(_build_list(
            db_path, role,
            search=str(values.get("search") or ""),
            role_filter=str(values.get("role_filter") or "")),
            role)}

    if action == "tap":
        if action_id == "add_open":
            return {"ok": True, "view": _doc(
                _build_list(db_path, role, dialog="add"), role)}
        if action_id == "refresh":
            return {"ok": True, "view": _doc(
                _build_list(db_path, role), role)}
        if action_id == "dialog_cancel":
            return {"ok": True, "view": _doc(
                _build_list(db_path, role), role)}
        if action_id == "add_commit":
            return _add_commit(db_path, role, values)
        if action_id == "open_panel":
            mid = value
            try:
                mid = int(mid)
            except (TypeError, ValueError):
                return {"ok": False,
                        "error": tr("managers.err.bad_id",
                                    "bad id")}
            return {"ok": True, "view": _doc(
                _build_panel(db_path, role, mid), role)}
        if action_id == "back":
            return {"ok": True, "view": _doc(
                _build_list(db_path, role), role)}
        if action_id == "save_role":
            mid = value.get("id") if isinstance(value, dict) else None
            if mid is None:
                return {"ok": False,
                        "error": tr("managers.err.bad_id",
                                    "bad id")}
            new_role = str(values.get("role") or "operator")
            if new_role not in MANAGEABLE_ROLES:
                return {"ok": False,
                        "error": tr(
                            "managers.err.role_invalid",
                            "недопустимая роль")}
            conn = sqlite3.connect(db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT role FROM managers WHERE id=?", (mid,))
                r = cur.fetchone()
                if not r:
                    return {"ok": True, "view": _doc(
                        _build_list(
                            db_path, role,
                            error=tr("managers.err.not_found",
                                     "не найден")), role)}
                if r[0] == "owner":
                    return {"ok": True, "view": _doc(
                        _build_panel(
                            db_path, role, mid,
                            error=tr(
                                "managers.err.owner_protected",
                                "владельца менять нельзя")), role)}
                cur.execute(
                    "UPDATE managers SET role=? WHERE id=?",
                    (new_role, mid))
                conn.commit()
            finally:
                conn.close()
            return {"ok": True,
                    "message": tr("managers.msg.role_saved",
                                  "Роль сохранена"),
                    "view": _doc(_build_panel(
                        db_path, role, mid), role)}
        if action_id == "reset_password":
            mid = value.get("id") if isinstance(value, dict) else None
            if mid is None:
                return {"ok": False,
                        "error": tr("managers.err.bad_id",
                                    "bad id")}
            new_password = secrets.token_urlsafe(8)
            conn = sqlite3.connect(db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT 1 FROM managers WHERE id=?", (mid,))
                if not cur.fetchone():
                    return {"ok": True, "view": _doc(
                        _build_list(
                            db_path, role,
                            error=tr("managers.err.not_found",
                                     "не найден")), role)}
                cur.execute(
                    "UPDATE managers SET pass_hash=? WHERE id=?",
                    (_hash(new_password), mid))
                conn.commit()
            finally:
                conn.close()
            return {"ok": True,
                    "message": tr("managers.msg.new_password",
                                  "Новый пароль: {password}",
                                  password=new_password),
                    "view": _doc(_build_panel(
                        db_path, role, mid), role)}
        if action_id == "delete":
            sel = values.get("table_0_selected", [])
            if not sel:
                return {"ok": False,
                        "error": tr("managers.err.not_found",
                                    "не найден")}
            mid = sel[0].get("id")
            if mid is None:
                return {"ok": False,
                        "error": tr("managers.err.not_found",
                                    "не найден")}
            return _delete(db_path, role, mid)
    return {"ok": False,
            "error": tr("managers.err.unknown_action",
                        "unknown action: {id}", id=action_id)}


def _add_commit(db_path, role, values):
    login_v = str(values.get("login") or "").strip()
    pwd = str(values.get("password") or "")
    pwd2 = str(values.get("password2") or "")
    new_role = str(values.get("role") or "operator")

    def _err(text_):
        return {"ok": True, "view": _doc(
            _build_list(db_path, role, error=text_,
                        dialog="add"), role)}

    if not login_v:
        return _err(tr("managers.err.login_required",
                       "введите логин"))
    for ch in login_v:
        if not ((ch.isascii() and ch.isalnum()) or ch in "_."):
            return _err(tr("managers.err.login_format",
                           "логин: только a-z, 0-9, _ и ."))
    if len(pwd) < 4:
        return _err(tr("managers.err.password_short",
                       "пароль — минимум 4 символа"))
    if pwd != pwd2:
        return _err(tr("managers.err.password_mismatch",
                       "пароли не совпадают"))
    if new_role not in MANAGEABLE_ROLES:
        return _err(tr("managers.err.role_invalid",
                       "недопустимая роль"))

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM managers WHERE login=?",
                    (login_v,))
        if cur.fetchone():
            return _err(tr("managers.err.login_taken",
                           "логин уже занят"))
        cur.execute("""
            INSERT INTO managers (login, pass_hash, role, created_at)
            VALUES (?, ?, ?, datetime('now'))
        """, (login_v, _hash(pwd), new_role))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True,
            "message": tr("managers.msg.created",
                          "Создан {login}", login=login_v),
            "view": _doc(_build_list(db_path, role), role)}


def _delete(db_path, role, mid):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT role FROM managers WHERE id=?", (mid,))
        r = cur.fetchone()
        if not r:
            return {"ok": True, "view": _doc(
                _build_list(
                    db_path, role,
                    error=tr("managers.err.not_found",
                             "не найден")), role)}
        if r[0] == "owner":
            return {"ok": True, "view": _doc(
                _build_list(
                    db_path, role,
                    error=tr("managers.err.owner_delete",
                             "владельца удалить нельзя")), role)}
        cur.execute("DELETE FROM managers WHERE id=?", (mid,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True,
            "message": tr("managers.msg.deleted", "Удалён"),
            "view": _doc(_build_list(db_path, role), role)}