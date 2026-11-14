"""Страница «Аудит ячеек» в ПК-клиенте."""

import sqlite3

from mgmt_protocol import (
    mgmt_page, mgmt_table, mgmt_dialog,
    mgmt_header, text, card, caption, button,
)


def _status_label(s):
    return {
        "pending": "Ожидание",
        "in_progress": "Выполняется",
        "action_required": "Требуются действия",
        "done": "Завершено",
    }.get(s or "", s or "")


def _build_page(login, role, context, message=None, error=None,
                dialog=None):
    db = context.db()
    db.row_factory = sqlite3.Row
    rows = []
    try:
        cur = db.cursor()
        cur.execute("""
            SELECT t.id, t.task_number, t.status,
                   t.assignee_login, t.created_at,
                   (SELECT COUNT(*) FROM task_items ti
                    WHERE ti.task_id=t.id
                      AND ti.status='done') AS done_cnt,
                   (SELECT COUNT(*) FROM task_items ti
                    WHERE ti.task_id=t.id) AS total_cnt
            FROM tasks t
            WHERE t.task_type='audit'
            ORDER BY t.id DESC
            LIMIT 100
        """)
        for r in cur.fetchall():
            rows.append({
                "id": r["id"],
                "number": r["task_number"] or "",
                "status": _status_label(r["status"]),
                "assignee": r["assignee_login"] or "—",
                "progress": f'{r["done_cnt"] or 0}/{r["total_cnt"] or 0}',
                "created": (r["created_at"] or "")[:19],
            })
    finally:
        db.close()

    children = [
        mgmt_header(
            context.tr("audit.title"),
            [
                button(context.tr("audit.btn_create"),
                       "tap", "create_open", style="primary"),
                button(context.tr("audit.btn_refresh"),
                       "tap", "refresh"),
            ],
        )
    ]
    if message:
        children.append(card([text(message)], accent="success"))
    if error:
        children.append(card([text(error)], accent="error"))

    children.append(mgmt_table(
        columns=[
            {"key": "number", "label": "№", "width": 0.2},
            {"key": "status", "label": "—", "width": 0.15},
            {"key": "assignee", "label": "—", "width": 0.2},
            {"key": "progress", "label": "%", "width": 0.15},
            {"key": "created", "label": "—", "width": 0.3},
        ],
        rows=rows,
        row_key="id",
        field_id="table_0",
        empty_label=context.tr("audit.empty"),
        searchable=False,
    ))

    if dialog:
        children.append(dialog)

    return mgmt_page("plugin:example_audit:audit",
                     context.tr("audit.title"), children)


def _create_dialog(context):
    db = context.db()
    db.row_factory = sqlite3.Row
    cells = []
    try:
        cur = db.cursor()
        cur.execute(
            "SELECT address, barcode FROM cells "
            "ORDER BY address LIMIT 1000")
        for r in cur.fetchall():
            cells.append({
                "address": r["address"] or "",
                "barcode": r["barcode"] or "",
            })
    finally:
        db.close()

    return mgmt_dialog(
        "create_audit",
        context.tr("audit.dialog_title"),
        [
            caption(context.tr("audit.dialog_caption")),
            mgmt_table(
                columns=[
                    {"key": "address", "label": "Адрес",
                     "width": 0.5},
                    {"key": "barcode", "label": "ШК",
                     "width": 0.5},
                ],
                rows=cells,
                row_key="barcode",
                field_id="table_cells",
                searchable=True,
                search_placeholder="Поиск…",
                empty_label="—",
            ),
        ],
        buttons=[
            button(context.tr("audit.btn_create"), "tap",
                   "create_commit", style="primary"),
            button(context.tr("audit.btn_cancel"), "tap",
                   "dialog_close"),
        ],
    )


def build_view(login, role, context):
    return _build_page(login, role, context)


def handle_action(action, action_id, value, login, role,
                  context, values=None):
    values = values or {}

    if action == "tap" and action_id == "refresh":
        return {"ok": True,
                "view": _build_page(login, role, context)}

    if action == "tap" and action_id == "create_open":
        doc = _build_page(login, role, context,
                          dialog=_create_dialog(context))
        return {"ok": True, "view": doc}

    if action == "tap" and action_id == "dialog_close":
        return {"ok": True,
                "view": _build_page(login, role, context)}

    if action == "tap" and action_id == "create_commit":
        sel = values.get("table_cells_selected", [])
        if not sel:
            return {"ok": True, "view": _build_page(
                login, role, context,
                error="Выберите ячейку.",
                dialog=_create_dialog(context))}
        cell_bc = str(sel[0].get("barcode") or "").strip()
        if not cell_bc:
            return {"ok": True, "view": _build_page(
                login, role, context,
                error="ШК пуст.",
                dialog=_create_dialog(context))}

        db = context.db()
        db.row_factory = sqlite3.Row
        try:
            cur = db.cursor()
            cur.execute(
                "SELECT 1 FROM cells WHERE barcode=?", (cell_bc,))
            if not cur.fetchone():
                return {"ok": True, "view": _build_page(
                    login, role, context,
                    error=f"Ячейки с ШК {cell_bc} нет.",
                    dialog=_create_dialog(context))}

            cur.execute(
                "SELECT COALESCE(MAX(id),0)+1 FROM tasks")
            nid = cur.fetchone()[0]
            number = f"TASK-{nid:06d}"

            cur.execute("""
                INSERT INTO tasks
                    (task_number, task_type, status,
                     assignee_login, target_a, processed_a,
                     target_b, processed_b, barcode,
                     created_at, platform)
                VALUES (?, 'audit', 'pending', NULL, 1, 0, 0, 0,
                        ?, datetime('now'), 'any')
            """, (number, number))
            tid = cur.lastrowid
            cur.execute("""
                INSERT INTO task_items
                    (task_id, cell_barcode, quantity, step_no,
                     status)
                VALUES (?, ?, 1, 1, 'pending')
            """, (tid, cell_bc))
            db.commit()
        finally:
            db.close()

        return {"ok": True,
                "message": f"Аудит {number} создан.",
                "view": _build_page(login, role, context)}

    return {"ok": False,
            "error": f"unknown action: {action_id}"}