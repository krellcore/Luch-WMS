"""«Уведомления» — серверная сборка view и действия."""

import sqlite3
import json
from datetime import datetime

from mgmt_protocol import (
    mgmt_page, mgmt_toolbar, mgmt_table, mgmt_form_field,
    mgmt_dialog, heading, text, card, caption, button,
    make_mgmt_document, mgmt_header, group, spacer
)
from mgmt_view_builder import build_sidebar
from i18n import tr
from roles import list_roles


def _role_label(key):
    for r in list_roles():
        if r["key"] == key:
            if r.get("title_key"):
                return tr(r["title_key"], r.get("title") or key)
            return r.get("title") or key
    return key


def _role_options():
    return [
        {"value": r["key"], "label": _role_label(r["key"])}
        for r in list_roles()
    ]


def _type_label(t):
    default = {
        "info": "Информация",
        "urgent": "Срочно",
        "system": "Системное",
    }.get(t or "info", t or "")
    return tr(f"notifications.type.{t or 'info'}", default)


def _type_title(t):
    default = {
        "info": "🔔 Информация",
        "urgent": "🔴 Срочное уведомление",
        "system": "⚙ Системное уведомление",
    }.get(t or "info", "🔔 Уведомление")
    return tr(f"notifications.type.{t or 'info'}_title", default)


def _doc(page, role):
    return make_mgmt_document(
        page, sidebar=build_sidebar(role),
        extra={"role": role})


def _translate_row_msg(msg, payload_raw):
    if not payload_raw:
        return msg
    try:
        payload = json.loads(payload_raw) \
            if isinstance(payload_raw, str) else payload_raw
    except Exception:
        return msg
    if not isinstance(payload, dict):
        return msg

    key = payload.get("key")
    params = payload.get("params") or {}

    if key:
        try:
            new_msg = tr(key, **params) if params else tr(key)
            if new_msg and new_msg != key:
                return new_msg
        except Exception:
            pass

    if "{" in msg and isinstance(params, dict) and params:
        for k, v in params.items():
            msg = msg.replace("{" + str(k) + "}",
                              "" if v is None else str(v))
    return msg


def _list_rows(db_path, search="", show_read=False):
    sql = ("SELECT id, created_at, type, sender_login, "
           "recipient_login, message, read_at, payload "
           "FROM notifications ")
    if not show_read:
        sql += "WHERE (read_at IS NULL OR read_at='') "
    sql += "ORDER BY id DESC LIMIT 500"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = []
        s = (search or "").lower()
        for r in cur.fetchall():
            msg = _translate_row_msg(
                r["message"] or "", r["payload"] or "")
            sender = r["sender_login"] or ""
            if s and s not in msg.lower() \
                    and s not in sender.lower():
                continue
            rows.append({
                "id": r["id"],
                "date": (r["created_at"] or "")[:19],
                "type": _type_label(r["type"]),
                "sender": sender,
                "recipient": (r["recipient_login"] or
                              tr("notifications.system",
                                 "(система)")),
                "message": msg,
                "read": ((r["read_at"] or "")[:19]
                         or tr("common.no", "нет")),
            })
        return rows
    finally:
        conn.close()


def _build_list(db_path, role, search="", show_read=False,
                message=None, error=None, dialog=None):
    header_actions = [
        button(tr("notifications.compose", "+ Написать"),
               "tap", "compose_open", style="primary"),
        button(tr("notifications.mark_all",
                  "Отметить всё прочитанным"),
               "tap", "mark_all"),
    ]
    children = [mgmt_header(
        tr("notifications.title", "Уведомления"), header_actions)]

    if message:
        children.append(card([text(message)], accent="success"))
    if error:
        children.append(card([text(error)], accent="error"))

    filters = [
        mgmt_form_field(
            "search", kind="text",
            label=tr("notifications.filter.search", "Поиск:"),
            label_position="left", stretch=True,
            value=search,
            placeholder=tr("notifications.filter.placeholder",
                           "Фильтр по тексту, отправителю…"),
            on_change="input_submit"),
        mgmt_form_field(
            "show_read", kind="checkbox",
            label=tr("notifications.show_read",
                     "Показывать прочитанные"),
            label_position="left",
            value=show_read,
            on_change="input_submit"),
        button(tr("notifications.btn.refresh", "Обновить"),
               "tap", "refresh"),
    ]
    children.append(group(filters, orientation="horizontal"))

    children.append(mgmt_table(
        columns=[
            {"key": "date",
             "label": tr("notifications.col.date", "Дата"),
             "width": 0.15},
            {"key": "type",
             "label": tr("notifications.col.type", "Тип"),
             "width": 0.1},
            {"key": "sender",
             "label": tr("notifications.col.sender", "От кого"),
             "width": 0.1},
            {"key": "recipient",
             "label": tr("notifications.col.recipient", "Кому"),
             "width": 0.1},
            {"key": "message",
             "label": tr("notifications.col.message", "Текст"),
             "width": 0.45},
            {"key": "read",
             "label": tr("notifications.col.read", "Прочитано"),
             "width": 0.1},
        ],
        rows=_list_rows(db_path, search=search,
                        show_read=show_read),
        on_double_click={
            "action": "tap", "id": "open_panel",
            "value_field": "id"},
        row_key="id",
        field_id="table_0",
        empty_label="",
        searchable=False,
    ))

    if dialog == "compose":
        children.append(_compose_dialog(
            db_path, {}, show_read, search))
    return mgmt_page("notifications",
                     tr("notifications.title", "Уведомления"),
                     children)


def _compose_dialog(db_path, values, show_read, search):
    users = []
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            SELECT login, last_name, first_name, middle_name
            FROM employees ORDER BY last_name COLLATE NOCASE
        """)
        for login_v, last, first, middle in cur.fetchall():
            fio = " ".join(p for p in [last or "", first or "",
                                        middle or ""] if p)
            users.append({"login": login_v,
                          "fio": fio or login_v})
        conn.close()
    except Exception:
        users = []

    kind = values.get("recipient_kind", "all")

    children = [
        mgmt_form_field(
            "recipient_kind", kind="select",
            label=tr("notifications.recipient_label",
                     "Получатель:"),
            value=kind, stretch=True,
            options=[
                {"value": "all",
                 "label": tr("notifications.recipient.all",
                             "Всем сотрудникам")},
                {"value": "role",
                 "label": tr("notifications.recipient.role",
                             "По роли")},
                {"value": "user",
                 "label": tr("notifications.recipient.user",
                             "Конкретному сотруднику")},
            ],
            on_change="input_submit"),
    ]

    if kind == "role":
        children.append(mgmt_form_field(
            "role", kind="select",
            label=tr("notifications.role", "Роль:"),
            value=values.get("role", "picker"), stretch=True,
            options=_role_options()))
    elif kind == "user":
        children.append(mgmt_table(
            columns=[
                {"key": "login",
                 "label": tr("employees.col.login", "Логин")},
                {"key": "fio",
                 "label": tr("employees.col.fio", "ФИО")},
            ],
            rows=users,
            row_key="login",
            field_id="table_0",
            searchable=True,
            search_placeholder=tr("common.search_placeholder",
                                  "Поиск..."),
        ))

    children.extend([
        mgmt_form_field(
            "type", kind="select",
            label=tr("notifications.type_field", "Тип:"),
            value=values.get("type", "info"), stretch=True,
            options=[
                {"value": "info",
                 "label": tr("notifications.type.info",
                             "Информация")},
                {"value": "urgent",
                 "label": tr(
                     "notifications.type.urgent_short",
                     "Срочно (со звуком и вибрацией)")},
            ]),
        mgmt_form_field(
            "message", kind="textarea",
            label=tr("notifications.message", "Текст:"),
            value=values.get("message", ""), stretch=True,
            placeholder=tr("notifications.text_placeholder",
                           "Текст уведомления…")),
    ])

    return mgmt_dialog(
        "compose",
        tr("notifications.compose_title",
           "Новое уведомление"),
        children,
        buttons=[
            button(tr("notifications.btn.send", "Отправить"),
                   "tap", "compose_send", style="primary"),
            button(tr("common.cancel", "Отмена"),
                   "tap", "dialog_cancel"),
        ],
    )


def _build_details(db_path, role, nid):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, created_at, type, sender_login,
                   recipient_login, message, read_at, payload,
                   task_id FROM notifications WHERE id=?
        """, (nid,))
        r = cur.fetchone()
    finally:
        conn.close()
    if not r:
        return mgmt_dialog(
            "details",
            tr("notifications.err.not_found",
               "Уведомление не найдено"),
            [text(tr("notifications.err.not_found",
                     "Уведомление не найдено."))],
            buttons=[button(
                tr("notifications.btn.close", "Закрыть"),
                "tap", "back_to_list")],
        )
    read_at = r["read_at"] or ""

    children = []

    ntype = r["type"] or "info"
    children.append(heading(_type_title(ntype), level=2))

    info_children = [
        text(tr("notifications.dialog.details.type_label",
                "<b>Тип:</b> {type}",
                type=_type_label(ntype))),
        text(tr("notifications.dialog.details.sender_label",
                "<b>Отправитель:</b> {login}",
                login=(r["sender_login"]
                       or tr("notifications.system", "(система)")))),
        text(tr("notifications.dialog.details.recipient_label",
                "<b>Получатель:</b> {login}",
                login=(r["recipient_login"]
                       or tr("notifications.everyone", "(всем)")))),
        text(tr("notifications.dialog.details.created_label",
                "<b>Создано:</b> {date}",
                date=(r["created_at"] or "")[:19])),
        text(tr("notifications.dialog.details.read_label",
                "<b>Прочитано:</b> {date}",
                date=(read_at[:19] if read_at
                      else tr("notifications.dialog.details.unread",
                              "не прочитано")))),
        text(tr("notifications.dialog.details.task_label",
                "<b>Задание:</b> {task_id}",
                task_id=(r["task_id"] if r["task_id"] else "—"))),
    ]
    children.append(card(
        info_children,
        title=tr("notifications.dialog.details.info_title",
                 "Сведения")))

    msg_text = _translate_row_msg(
        r["message"] or "", r["payload"] or "")
    children.append(card(
        [text(msg_text)],
        title=tr("notifications.dialog.details.message_title",
                 "Сообщение")))

    payload = r["payload"] or ""
    if payload:
        try:
            po = json.loads(payload)
            visible = {k: v for k, v in po.items()
                       if k not in ("key", "params")}
            if visible:
                pretty = json.dumps(visible, ensure_ascii=False,
                                     indent=2)
                children.append(card(
                    [text(f"<pre>{pretty}</pre>")],
                    title=tr(
                        "notifications.dialog.details.payload_title",
                        "Дополнительные данные")))
        except Exception:
            pass

    btns = [button(tr("notifications.btn.close", "Закрыть"),
                   "tap", "back_to_list")]
    if not read_at:
        btns.insert(0, button(
            tr("notifications.btn.mark_read",
               "Отметить прочитанным"),
            "tap", "mark_read", value={"id": nid},
            style="primary"))

    return mgmt_dialog(
        "details",
        tr("notifications.dialog.details.title",
           "Просмотр уведомления"),
        children,
        buttons=btns
    )


def build_view(login, role, context):
    return _doc(_build_list(context.db_path, role), role)


def handle_action(action, action_id, value, login, role,
                  context, values=None):
    values = values or {}
    db_path = context.db_path

    search = str(values.get("search") or "")
    show_read = bool(values.get("show_read"))

    if action == "input_submit" and action_id == "recipient_kind":
        doc = _build_list(
            db_path, role, search=search,
            show_read=show_read)
        doc["children"].append(_compose_dialog(
            db_path, values, show_read, search))
        return {"ok": True, "view": _doc(doc, role)}

    if action == "input_submit":
        return {"ok": True, "view": _doc(
            _build_list(db_path, role, search=search,
                        show_read=show_read), role)}

    if action == "tap":
        if action_id == "refresh":
            return {"ok": True, "view": _doc(
                _build_list(db_path, role, search=search,
                            show_read=show_read), role)}
        if action_id == "compose_open":
            return {"ok": True, "view": _doc(
                _build_list(db_path, role, search=search,
                            show_read=show_read,
                            dialog="compose"), role)}
        if action_id == "dialog_cancel":
            return {"ok": True, "view": _doc(
                _build_list(db_path, role, search=search,
                            show_read=show_read), role)}
        if action_id == "compose_send":
            return _compose_send(
                db_path, login, role, values, search, show_read)
        if action_id == "mark_all":
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    "UPDATE notifications SET read_at=? "
                    "WHERE (read_at IS NULL OR read_at='') "
                    "  AND (recipient_login IS NULL "
                    "       OR recipient_login='')",
                    (datetime.now().isoformat(),))
                conn.commit()
            finally:
                conn.close()
            return {"ok": True,
                    "message": tr("notifications.msg.all_marked",
                                  "Все отмечены"),
                    "view": _doc(_build_list(
                        db_path, role, search=search,
                        show_read=show_read), role)}
        if action_id == "open_panel":
            try:
                nid = int(value)
            except (TypeError, ValueError):
                return {"ok": False,
                        "error": tr("common.error", "Ошибка")}
            doc = _build_list(
                db_path, role, search=search,
                show_read=show_read)
            doc["children"].append(_build_details(
                db_path, role, nid))
            return {"ok": True, "view": _doc(doc, role)}

        if action_id == "back_to_list":
            return {"ok": True, "view": _doc(
                _build_list(db_path, role, search=search,
                            show_read=show_read), role)}

        if action_id == "mark_read":
            nid = value.get("id") if isinstance(value, dict) else None
            if not nid:
                return {"ok": False,
                        "error": tr("common.error", "Ошибка")}
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    "UPDATE notifications SET read_at=? "
                    "WHERE id=? AND (recipient_login IS NULL "
                    "               OR recipient_login='')",
                    (datetime.now().isoformat(), nid))
                conn.commit()
            finally:
                conn.close()
            return {"ok": True,
                    "message": tr("notifications.msg.marked_read",
                                  "Прочитано"),
                    "view": _doc(_build_list(
                        db_path, role, search=search,
                        show_read=show_read), role)}

    return {"ok": False,
            "error": tr("notifications.err.unknown_action",
                        "unknown action: {id}", id=action_id)}


def _compose_send(db_path, login, role, values, search, show_read):
    text_v = str(values.get("message") or "").strip()
    if not text_v:
        doc = _build_list(
            db_path, role, search=search,
            show_read=show_read)
        doc["children"].append(_compose_dialog(
            db_path, values, show_read, search))
        return {"ok": True, "view": _doc(doc, role)}

    kind = str(values.get("recipient_kind") or "all")
    ntype = str(values.get("type") or "info")
    now = datetime.now().isoformat()
    targets = []
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        if kind == "all":
            cur.execute("SELECT login FROM employees")
            targets = [r[0] for r in cur.fetchall()]
        elif kind == "role":
            role_v = str(values.get("role") or "picker")
            cur.execute("SELECT login, role, roles FROM employees")
            for lg, r1, roles_txt in cur.fetchall():
                try:
                    rr = json.loads(roles_txt) if roles_txt else []
                except Exception:
                    rr = []
                if not rr:
                    rr = [r1 or "picker"]
                if role_v in rr:
                    targets.append(lg)
        elif kind == "user":
            sel = values.get("table_0_selected", [])
            lg = sel[0].get("login") if sel else ""
            if lg:
                targets = [lg]

        if not targets:
            doc = _build_list(
                db_path, role, search=search,
                show_read=show_read)
            doc["children"].append(_compose_dialog(
                db_path, values, show_read, search))
            return {"ok": True, "view": _doc(doc, role)}

        for lg in targets:
            cur.execute("""
                INSERT INTO notifications
                    (task_id, message, created_at, sender_login,
                     type, recipient_login, read_at, payload)
                VALUES (NULL, ?, ?, ?, ?, ?, '', '')
            """, (text_v, now, login or 'PC', ntype, lg))
        conn.commit()
    finally:
        conn.close()

    return {"ok": True,
            "message": tr("notifications.msg.sent",
                          "Отправлено {count} получателям",
                          count=len(targets)),
            "view": _doc(_build_list(
                db_path, role, search=search,
                show_read=show_read), role)}