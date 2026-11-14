"""«Задания» — серверная сборка view и действия.

Платформа задания жёстко привязана к типу:
  - receive           → "pc"
  - pick/putaway/inv  → "android"
Пользователь не выбирает платформу в wizard.
"""

import base64
import json
import sqlite3
import secrets
from datetime import datetime

from PySide6.QtCore import QBuffer, QIODevice

from mgmt_protocol import (
    mgmt_page, mgmt_toolbar, mgmt_table, mgmt_form_field,
    mgmt_dialog, heading, text, card, caption, button,
    group, spacer, mgmt_image, mgmt_header, mgmt_file_trigger,
    make_mgmt_document,
)
from mgmt_view_builder import build_sidebar
from barcodes import (
    make_label_image, make_barcode_pixmap, make_qr_pixmap,
)
from i18n import tr


CREATABLE_TASK_TYPES = ("pick", "receive", "putaway", "inventory")
ALL_TASK_TYPES = ("pick", "receive", "putaway", "inventory")
ALL_STATUSES = ("pending", "in_progress",
                "action_required", "done")
PICK_MODES = ("normal", "exact")

# Жёсткая привязка платформы к типу задания.
TASK_PLATFORM = {
    "pick": "android",
    "receive": "pc",
    "putaway": "android",
    "inventory": "android",
}


def _type_label(t):
    default = {
        "pick": "Подбор", "receive": "Приёмка",
        "putaway": "Размещение", "inventory": "Инвентаризация",
    }.get(t or "", t or "")
    return tr(f"task.type.{t}", default)


def _status_label(s):
    default = {
        "pending": "Ожидание",
        "in_progress": "Выполняется",
        "action_required": "Требуются действия",
        "done": "Завершено",
    }.get(s or "", s or "")
    return tr(f"task.status.{s}", default)


def _platform_label(p):
    default = {
        "any": "Любая", "pc": "ПК", "android": "ТСД",
    }.get(p or "any", p or "")
    return tr(f"task.platform.{p or 'any'}", default)


def _pick_mode_label(m):
    default = {
        "normal": "Обычный", "exact": "Определённый",
    }.get(m or "normal", m or "")
    return tr(f"task.pick.{m or 'normal'}", default)


def _task_label(ttype):
    default = {
        "receive": "ГРУЗ К ПРИЁМКЕ",
        "pick": "ЗАДАНИЕ НА ПОДБОР",
        "putaway": "ЗАДАНИЕ НА РАЗМЕЩЕНИЕ",
        "inventory": "ЗАДАНИЕ ИНВЕНТАРИЗАЦИИ",
    }.get(ttype or "", "ЗАДАНИЕ")
    return tr(f"task.label.{ttype}", default)


def _doc(page, role):
    return make_mgmt_document(page, sidebar=build_sidebar(role),
                              extra={"role": role})


def _barcode_preview_b64(code):
    try:
        pix = make_barcode_pixmap(code)
    except Exception:
        return None
    if pix is None or pix.isNull():
        return None
    qb = QBuffer()
    qb.open(QIODevice.WriteOnly)
    pix.save(qb, "PNG")
    raw = bytes(qb.data())
    qb.close()
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def _label_png_b64(title, subtitle, code):
    try:
        png = make_label_image(title, subtitle, code)
        return base64.b64encode(png).decode("ascii")
    except Exception:
        return None


def _server_url_and_qr():
    try:
        from server import server_url as get_server_url
    except Exception:
        def get_server_url():
            return "WMS://127.0.0.1:8765"
    try:
        url = get_server_url()
    except Exception:
        return None, None
    try:
        pm = make_qr_pixmap(url, size=140)
        if pm is None:
            return url, None
        qb = QBuffer()
        qb.open(QIODevice.WriteOnly)
        pm.save(qb, "PNG")
        raw = bytes(qb.data())
        qb.close()
        b64 = base64.b64encode(raw).decode("ascii")
        return url, "data:image/png;base64," + b64
    except Exception as e:
        print("[tasks] qr:", e)
        return url, None


def _wiz_key(login):
    return f"_mgmt_wizard_{login}"


def _load_wizard(db_path, login):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key=?",
                    (_wiz_key(login),))
        r = cur.fetchone()
        if r and r[0]:
            try:
                return json.loads(r[0])
            except Exception:
                return None
        return None
    finally:
        conn.close()


def _save_wizard(db_path, login, state):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM settings WHERE key=?",
                    (_wiz_key(login),))
        val = json.dumps(state, ensure_ascii=False)
        if cur.fetchone():
            cur.execute("UPDATE settings SET value=? WHERE key=?",
                        (val, _wiz_key(login)))
        else:
            cur.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)",
                (_wiz_key(login), val))
        conn.commit()
    finally:
        conn.close()


def _drop_wizard(db_path, login):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DELETE FROM settings WHERE key=?",
                     (_wiz_key(login),))
        conn.commit()
    finally:
        conn.close()


def _fresh_wizard():
    return {
        "type": "pick",
        "platform": TASK_PLATFORM["pick"],
        "pick_mode": "normal",
        "items": [],
        "containers": [],
        "cells": [],
        "dialog": "",
        "error": "",
    }


def _list_rows(db_path, filters):
    where, params = [], []
    if filters.get("type"):
        where.append("task_type=?")
        params.append(filters["type"])
    if filters.get("status"):
        where.append("status=?")
        params.append(filters["status"])
    if filters.get("platform"):
        where.append("platform=?")
        params.append(filters["platform"])
    if filters.get("search"):
        where.append("(LOWER(task_number) LIKE ? "
                     "OR LOWER(COALESCE(assignee_login,'')) LIKE ?)")
        s = "%" + filters["search"].lower() + "%"
        params.extend([s, s])

    if filters.get("partial"):
        where.append("COALESCE(partial,0)=1")
    if filters.get("block"):
        where.append("block_bf LIKE ?")
        params.append(filters["block"] + "%")
    if filters.get("active") and not filters.get("status"):
        where.append(
            "status IN ('pending','in_progress','action_required')")
    if filters.get("date") == "today":
        where.append("DATE(created_at)=DATE('now','localtime')")
    elif filters.get("date") == "week":
        where.append("DATE(created_at)>=DATE('now','localtime','-7 days')")

    sql = """
        SELECT id, task_number, task_type, status,
               assignee_login, target_a, processed_a,
               target_b, processed_b, block_bf, partial, platform
        FROM tasks
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT 500"

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = []
        for (tid, num, ttype, status, assignee, ta, pa,
             tb, pb, bf, partial, platform) in cur.fetchall():
            num_disp = num or ""
            if bf:
                num_disp += f" (B{bf})"
            if partial:
                num_disp += " ⚠"
            if ttype == "putaway":
                prog = f"{pb}/{tb}"
            elif ttype == "inventory":
                prog = tr("tasks.progress.inventory",
                          "ячейки {processed}/{target}",
                          processed=pa, target=ta)
            else:
                prog = f"{pa}/{ta}"
            rows.append({
                "id": tid,
                "number": num_disp,
                "type": _type_label(ttype),
                "platform": _platform_label(platform),
                "progress": prog,
                "assignee": (assignee
                             or tr("tasks.assignee.empty", "—")),
                "status": _status_label(status),
            })
        return rows
    finally:
        conn.close()


def _build_list(db_path, role, filters=None, message=None,
                error=None):
    filters = filters or {}

    header_actions = [
        button(tr("tasks.add", "+ Создать задание"),
               "tap", "wizard_start", style="primary"),
    ]

    children = [mgmt_header(
        tr("tasks.title", "Задания"), header_actions)]

    url, qr_b64 = _server_url_and_qr()
    if url:
        qr_children = []
        if qr_b64:
            qr_children.append(
                mgmt_image(qr_b64, width=140, height=140))

        info_children = [
            text(tr("tasks.server_qr_url", "URL:")),
            text(f"<span style='font-family: Courier New; "
                 f"font-size: 10pt;'>{url}</span>"),
            text(tr("tasks.server_qr_hint",
                    "Отсканируйте этот QR в клиенте,\n"
                    "затем — QR с пропуска сотрудника.")),
        ]

        qr_children.append(
            group(info_children, orientation="vertical",
                  spacing=4, stretch=True))

        children.append(card([
            group(qr_children, orientation="horizontal",
                  spacing=16),
        ], title=tr("tasks.server_qr", "ШК сервера")))

    if message:
        children.append(card([text(message)], accent="success"))
    if error:
        children.append(card([text(error)], accent="error"))

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM blocks ORDER BY name")
        blocks = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()
    blocks_options = [{"value": b, "label": f"Блок {b}"}
                      for b in blocks]

    type_options = [
        {"value": "", "label": tr("tasks.filter.all", "Все")},
    ] + [
        {"value": k, "label": _type_label(k)}
        for k in ALL_TASK_TYPES
    ]
    status_options = [
        {"value": "", "label": tr("tasks.filter.all", "Все")},
    ] + [
        {"value": k, "label": _status_label(k)}
        for k in ALL_STATUSES
    ]
    platform_options = [
        {"value": "", "label": tr("tasks.filter.all", "Все")},
        {"value": "pc", "label": _platform_label("pc")},
        {"value": "android", "label": _platform_label("android")},
    ]

    filters_children = [
        mgmt_form_field(
            "filter_search", kind="text",
            label=tr("common.search", "Поиск:"),
            label_position="left",
            placeholder=tr("tasks.filter.search_placeholder",
                           "Номер, тип…"),
            value=filters.get("search", ""),
            on_change="input_submit", stretch=True),
        mgmt_form_field(
            "filter_type", kind="select",
            label=tr("tasks.filter.type", "Тип:"),
            label_position="left",
            value=filters.get("type", ""),
            options=type_options,
            on_change="input_submit"),
        mgmt_form_field(
            "filter_status", kind="select",
            label=tr("tasks.filter.status", "Статус:"),
            label_position="left",
            value=filters.get("status", ""),
            options=status_options,
            on_change="input_submit"),
        mgmt_form_field(
            "filter_platform", kind="select",
            label=tr("tasks.filter.platform", "Платформа:"),
            label_position="left",
            value=filters.get("platform", ""),
            options=platform_options,
            on_change="input_submit"),
        mgmt_form_field(
            "filter_partial", kind="checkbox",
            label=tr("tasks.filter.partial", "Только частичные"),
            label_position="left",
            value=filters.get("partial", False),
            on_change="input_submit"),
        mgmt_form_field(
            "filter_block", kind="select",
            label=tr("tasks.filter.block", "Блок"),
            label_position="left", width=120,
            value=filters.get("block", ""),
            options=[{"value": "",
                      "label": tr("tasks.filter.all", "Все")}]
                    + blocks_options,
            on_change="input_submit"),
        mgmt_form_field(
            "filter_active", kind="checkbox",
            label=tr("tasks.filter.active", "Только активные"),
            label_position="left",
            value=filters.get("active", True),
            on_change="input_submit"),
        mgmt_form_field(
            "filter_date", kind="select",
            label=tr("tasks.filter.date", "Дата:"),
            label_position="left",
            value=filters.get("date", ""),
            options=[
                {"value": "",
                 "label": tr("tasks.filter.all", "Все")},
                {"value": "today",
                 "label": tr("tasks.filter.date_today",
                             "Сегодня")},
                {"value": "week",
                 "label": tr("tasks.filter.date_week",
                             "За 7 дней")},
            ],
            on_change="input_submit"),
        button(tr("common.refresh", "Обновить"),
               "tap", "refresh")
    ]
    children.append(group(filters_children, orientation="horizontal"))

    children.append(mgmt_table(
        columns=[
            {"key": "number",
             "label": tr("tasks.col.number", "Номер"),
             "width": 0.2},
            {"key": "type",
             "label": tr("tasks.col.type", "Тип"),
             "width": 0.15},
            {"key": "platform",
             "label": tr("tasks.col.platform", "Платформа"),
             "width": 0.1},
            {"key": "progress",
             "label": tr("tasks.col.progress", "Прогресс"),
             "width": 0.15},
            {"key": "assignee",
             "label": tr("tasks.col.assignee", "Исполнитель"),
             "width": 0.15},
            {"key": "status",
             "label": tr("tasks.col.status", "Статус"),
             "width": 0.15},
        ],
        rows=_list_rows(db_path, filters),
        on_double_click={
            "action": "tap", "id": "open_task",
            "value_field": "id"},
        row_key="id",
        empty_label="",
        searchable=False,
    ))
    return mgmt_page("tasks", tr("tasks.title", "Задания"),
                     children)


def _wizard_view(db_path, role, login, values=None):
    values = values or {}
    state = _load_wizard(db_path, login)
    if not state:
        return None

    ttype = state.get("type", "pick")
    if ttype not in CREATABLE_TASK_TYPES:
        ttype = "pick"
        state["type"] = "pick"
        state["platform"] = TASK_PLATFORM["pick"]
        _save_wizard(db_path, login, state)

    # Принудительно синхронизируем platform с типом.
    if state.get("platform") != TASK_PLATFORM[ttype]:
        state["platform"] = TASK_PLATFORM[ttype]
        _save_wizard(db_path, login, state)

    children = [mgmt_header(
        tr("task.wizard.title", "Создание задания"))]

    dialog = state.get("dialog") or ""
    dlg_err = state.get("error") if dialog else None
    if state.get("error") and not dialog:
        children.append(card([text(state["error"])],
                             accent="error"))

    # Только тип задания; платформа выводится из типа.
    children.append(group([
        mgmt_form_field(
            "wizard_type", kind="select",
            label=tr("task.wizard.type", "Тип задания:"),
            label_position="left",
            value=ttype,
            options=[
                {"value": k, "label": _type_label(k)}
                for k in CREATABLE_TASK_TYPES
            ],
            on_change="input_submit"),
        caption(tr(
            "task.wizard.platform_hint",
            "Платформа: {platform}",
            platform=_platform_label(TASK_PLATFORM[ttype]))),
    ], orientation="horizontal"))

    if ttype == "pick":
        children.append(group([
            mgmt_form_field(
                "wizard_pick_mode", kind="select",
                label=tr("task.wizard.pick_type",
                         "Тип подбора:"),
                label_position="left",
                value=state.get("pick_mode", "normal"),
                options=[
                    {"value": k, "label": _pick_mode_label(k)}
                    for k in PICK_MODES
                ],
                on_change="input_submit"),
        ], orientation="horizontal"))

    if ttype in ("pick", "receive"):
        rows = []
        for i, it in enumerate(state.get("items") or []):
            conn = sqlite3.connect(db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT name FROM item_characteristics "
                    "WHERE item_code=?",
                    (it["item_code"],))
                r = cur.fetchone()
                name = r[0] if r else ""
            finally:
                conn.close()
            if ttype == "receive":
                rows.append({
                    "id": i,
                    "idx": i,
                    "code": it["item_code"],
                    "name": name or "",
                    "qty": it["qty"],
                })
            else:
                rows.append({
                    "id": i,
                    "idx": i,
                    "code": it["item_code"],
                    "name": name or "",
                    "cell": (it.get("cell")
                             or tr("common.dash", "—")),
                    "qty": it["qty"],
                })
        if ttype == "pick":
            cols = [
                {"key": "code",
                 "label": tr("task.wizard.col.code", "Артикул")},
                {"key": "name",
                 "label": tr("task.wizard.col.name",
                             "Название")},
                {"key": "cell",
                 "label": tr("task.wizard.col.cell", "Ячейка")},
                {"key": "qty",
                 "label": tr("task.wizard.col.qty",
                             "Количество")},
            ]
        else:
            cols = [
                {"key": "code",
                 "label": tr("task.wizard.col.code", "Артикул")},
                {"key": "name",
                 "label": tr("task.wizard.col.name",
                             "Название")},
                {"key": "qty",
                 "label": tr("task.wizard.col.qty",
                             "Количество")},
            ]
        children.append(mgmt_table(
            columns=cols,
            rows=rows,
            on_double_click={
                "action": "tap", "id": "remove_item",
                "value_field": "idx"},
            row_key="id",
            empty_label="",
            searchable=False,
        ))
        children.append(caption(
            tr("task.wizard.hint.remove_item",
               "Двойной клик по строке — удалить позицию.")))
        children.append(mgmt_toolbar([
            button(tr("task.wizard.add_items",
                      "+ Добавить товары"),
                   "tap", "open_add_item", style="primary"),
        ]))

    elif ttype == "putaway":
        rows = []
        for i, bc in enumerate(state.get("containers") or []):
            rows.append({"id": i, "idx": i, "barcode": bc})
        children.append(mgmt_table(
            columns=[
                {"key": "barcode",
                 "label": tr("task.wizard.col.barcode",
                             "ШК тары")},
            ],
            rows=rows,
            on_double_click={
                "action": "tap", "id": "remove_container",
                "value_field": "idx"},
            row_key="id",
            empty_label="",
            searchable=False,
        ))
        children.append(caption(
            tr("task.wizard.hint.remove_container",
               "Двойной клик по строке — удалить тару.")))
        children.append(mgmt_toolbar([
            button(tr("task.wizard.add_container",
                      "+ Добавить тару"),
                   "tap", "open_add_container",
                   style="primary"),
        ]))

    elif ttype == "inventory":
        rows = []
        for i, c in enumerate(state.get("cells") or []):
            rows.append({
                "id": i,
                "idx": i,
                "barcode": c["barcode"],
                "address": c.get("address") or "",
            })
        children.append(mgmt_table(
            columns=[
                {"key": "address",
                 "label": tr("task.wizard.col.address",
                             "Адрес ячейки")},
                {"key": "barcode",
                 "label": tr("task.wizard.col.cell_barcode",
                             "ШК ячейки")},
            ],
            rows=rows,
            on_double_click={
                "action": "tap", "id": "remove_cell",
                "value_field": "idx"},
            row_key="id",
            empty_label="",
            searchable=False,
        ))
        children.append(caption(
            tr("task.wizard.hint.remove_cell",
               "Двойной клик по строке — удалить ячейку.")))
        children.append(mgmt_toolbar([
            button(tr("task.wizard.add_cells",
                      "+ Добавить ячейки"),
                   "tap", "open_add_cell", style="primary"),
        ]))

    children.append(spacer(12))
    children.append(mgmt_toolbar([
        button(tr("task.wizard.back", "← Назад"),
               "tap", "wizard_cancel"),
        button(tr("task.wizard.create", "Создать задание →"),
               "tap", "wizard_create", style="primary"),
    ]))

    if dialog == "add_item":
        children.append(_add_item_dialog(
            db_path, state, error=dlg_err, values=values))
    elif dialog == "add_container":
        children.append(_add_container_dialog(
            db_path, state, error=dlg_err))
    elif dialog == "add_cell":
        # Передаём db_path, чтобы диалог мог подгрузить
        # таблицу всех ячеек.
        children.append(_add_cell_dialog(
            db_path, state, error=dlg_err, values=values))

    return mgmt_page("tasks",
                     tr("task.wizard.title", "Создание задания"),
                     children)


def _add_item_dialog(db_path, state, error=None, values=None):
    values = values or {}
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT item_code, name, barcode FROM item_characteristics
            ORDER BY name COLLATE NOCASE
        """)
        items = [{"code": c or "", "name": n or "",
                  "barcode": b or ""}
                 for c, n, b in cur.fetchall()]
    finally:
        conn.close()

    children = []
    if error:
        children.append(card([text(error)], accent="error"))

    children.append(mgmt_table(
        columns=[
            {"key": "code",
             "label": tr("task.wizard.col.code", "Артикул")},
            {"key": "name",
             "label": tr("task.wizard.col.name", "Название")},
            {"key": "barcode",
             "label": tr("items.col.barcode", "Штрихкод")},
        ],
        rows=items,
        row_key="code",
        field_id="table_0",
        searchable=True,
        search_placeholder=tr("common.search_placeholder",
                              "Поиск..."),
    ))

    qty_val = values.get("dialog_qty")
    try:
        qty_val = int(qty_val) if qty_val is not None else 1
    except (ValueError, TypeError):
        qty_val = 1
    children.append(mgmt_form_field(
        "dialog_qty", kind="number",
        label=tr("task.wizard.dialog.add_item.qty",
                 "Количество:"),
        value=qty_val, min_value=1, max_value=1000000))

    if state.get("type") == "pick" and \
            state.get("pick_mode") == "exact":
        children.append(mgmt_form_field(
            "dialog_cell", kind="text",
            label=tr("task.wizard.dialog.add_item.cell",
                     "Ячейка (ШК):"),
            value=str(values.get("dialog_cell") or ""),
            placeholder=tr(
                "task.wizard.dialog.add_item.cell_placeholder",
                "ШК ячейки, откуда брать")))

    return mgmt_dialog(
        "add_item",
        tr("task.wizard.dialog.add_item.title",
           "Добавить товар"),
        children,
        panel_kind="dialog",
        buttons=[
            button(tr("task.wizard.dialog.btn_add", "Добавить"),
                   "tap", "dialog_add_item", style="primary"),
            button(tr("task.wizard.dialog.btn_cancel", "Отмена"),
                   "tap", "dialog_close"),
        ],
    )


def _add_container_dialog(db_path, state, error=None):
    """Диалог выбора тары для putaway.

    Таблица: ШК тары + количество товаров в таре (сумма
    placed_instances). Пустые тары скрыты; тары, уже занятые
    в активном putaway, исключены; статус только free/placing.
    """
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT c.barcode,
                   COALESCE((
                       SELECT SUM(quantity) FROM placed_instances
                       WHERE cell_or_container_barcode = c.barcode
                   ), 0) AS qty
            FROM containers c
            WHERE COALESCE(c.status,'free') IN ('free','placing')
              AND c.barcode NOT IN (
                  SELECT ti.container_barcode
                  FROM task_items ti
                  JOIN tasks t ON t.id = ti.task_id
                  WHERE t.task_type='putaway'
                    AND t.status IN ('pending','in_progress')
                    AND ti.container_barcode IS NOT NULL
              )
            ORDER BY c.barcode
        """)
        containers = []
        for bc, qty in cur.fetchall():
            q = int(qty or 0)
            if q > 0:
                containers.append({"barcode": bc, "qty": q})
    finally:
        conn.close()

    children = []
    if error:
        children.append(card([text(error)], accent="error"))

    children.append(mgmt_table(
        columns=[
            {"key": "barcode",
             "label": tr("task.wizard.col.barcode", "ШК тары"),
             "width": 0.6},
            {"key": "qty",
             "label": tr("common.items", "Товаров"),
             "width": 0.4},
        ],
        rows=containers,
        row_key="barcode",
        field_id="table_0",
        searchable=True,
        search_placeholder=tr("common.search_placeholder",
                              "Поиск..."),
        empty_label=tr(
            "task.wizard.dialog.add_container.no_containers",
            "Нет тар с товарами"),
    ))

    return mgmt_dialog(
        "add_container",
        tr("task.wizard.dialog.add_container.title",
           "Добавить тару"),
        children,
        panel_kind="dialog",
        buttons=[
            button(tr("task.wizard.dialog.btn_add", "Добавить"),
                   "tap", "dialog_add_container", style="primary"),
            button(tr("task.wizard.dialog.btn_cancel", "Отмена"),
                   "tap", "dialog_close"),
        ],
    )


def _add_cell_dialog(db_path, state, error=None, values=None):
    """Диалог выбора ячейки для инвентаризации.

    Таблица всех ячеек (адрес + ШК) с поиском. Выбор — клик
    по строке + «Добавить».
    """
    values = values or {}
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT address, barcode FROM cells ORDER BY address")
        cells = [
            {"address": addr or "", "barcode": bc or ""}
            for addr, bc in cur.fetchall()
        ]
    finally:
        conn.close()

    children = []
    if error:
        children.append(card([text(error)], accent="error"))

    children.append(mgmt_table(
        columns=[
            {"key": "address",
             "label": tr("task.wizard.col.address",
                         "Адрес ячейки"),
             "width": 0.5},
            {"key": "barcode",
             "label": tr("task.wizard.col.cell_barcode",
                         "ШК ячейки"),
             "width": 0.5},
        ],
        rows=cells,
        row_key="barcode",
        field_id="table_0",
        searchable=True,
        search_placeholder=tr("common.search_placeholder",
                              "Поиск..."),
        empty_label=tr(
            "task.wizard.dialog.add_cell.no_cells",
            "Ячейки не созданы"),
    ))

    return mgmt_dialog(
        "add_cell",
        tr("task.wizard.dialog.add_cell.title",
           "Добавить ячейку"),
        children,
        panel_kind="dialog",
        buttons=[
            button(tr("task.wizard.dialog.btn_add", "Добавить"),
                   "tap", "dialog_add_cell", style="primary"),
            button(tr("task.wizard.dialog.btn_cancel", "Отмена"),
                   "tap", "dialog_close"),
        ],
    )


def _create_pick(cur, state):
    from db import (
        expire_reservations, available_qty, reserve,
        RESERVE_DEFAULT_MINUTES,
    )
    expire_reservations(cur)
    paths_by_bf = {}
    leftover = []
    for it in state["items"]:
        item_code = it["item_code"]
        need = int(it["qty"] or 0)
        if need <= 0:
            continue
        if state["pick_mode"] == "exact":
            cell = it.get("cell") or ""
            if not cell:
                leftover.append((item_code, need))
                continue
            cur.execute("SELECT 1 FROM cells WHERE barcode=?",
                        (cell,))
            if not cur.fetchone():
                return False, tr("task.err.cell_not_found",
                                 "Ячейки с ШК «{cell}» не существует.",
                                 cell=cell)
            avail = available_qty(cur, item_code, cell)
            if avail < need:
                leftover.append((item_code, need - avail))
                continue
            cur.execute("SELECT address FROM cells WHERE barcode=?",
                        (cell,))
            r = cur.fetchone()
            bf = r[0].split("-", 1)[0] if r and r[0] else ""
            paths_by_bf.setdefault(bf, []).append({
                "item_code": item_code, "cell": cell, "qty": need,
            })
        else:
            cur.execute("""
                SELECT cell_barcode, COALESCE(quantity, 0) AS qty
                FROM placed_instances
                WHERE item_code=? AND quantity > 0
                  AND cell_barcode IS NOT NULL
                  AND cell_barcode != ''
                ORDER BY cell_barcode
            """, (item_code,))
            for r in cur.fetchall():
                if need <= 0:
                    break
                # FIX: курсор без row_factory (см. _wizard_create
                # — теперь с row_factory, но код оставляем
                # совместимым с обоими режимами: tuple[0] и
                # Row["cell_barcode"] дают одно и то же значение).
                cell = r[0]
                avail = available_qty(cur, item_code, cell)
                if avail <= 0:
                    continue
                take = min(need, avail)
                cur.execute(
                    "SELECT address FROM cells WHERE barcode=?",
                    (cell,))
                addr = cur.fetchone()
                bf = (addr[0].split("-", 1)[0]
                      if addr and addr[0] else "")
                paths_by_bf.setdefault(bf, []).append({
                    "item_code": item_code, "cell": cell,
                    "qty": take,
                })
                need -= take
            if need > 0:
                leftover.append((item_code, need))

    if leftover:
        lines = [tr("task.err.leftover_item",
                    "  {code}: не хватает {qty} шт "
                    "(с учётом резервов)",
                    code=code, qty=qty)
                 for code, qty in leftover]
        return False, (tr("task.err.not_enough_stock",
                          "Не хватает товара")
                       + ":\n" + "\n".join(lines))

    if not paths_by_bf:
        return False, tr("task.err.no_available_items",
                         "Нет доступных для подбора товаров.")

    bf_keys = sorted(paths_by_bf.keys())
    batch_id = ""
    if len(bf_keys) > 1:
        batch_id = (f"BATCH-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                    f"-{secrets.token_hex(3)}")

    platform = TASK_PLATFORM["pick"]
    numbers = []
    for bf in bf_keys:
        path = paths_by_bf[bf]
        total_items = sum(p["qty"] for p in path)
        cur.execute("SELECT COALESCE(MAX(id),0)+1 FROM tasks")
        nid = cur.fetchone()[0]
        number = f"TASK-{nid:06d}"
        cur.execute("""
            INSERT INTO tasks
                (task_number, task_type, status,
                 assignee_login, target_a, processed_a,
                 target_b, processed_b, barcode, created_at,
                 batch_id, block_bf, platform)
            VALUES (?, 'pick', 'pending', NULL, ?, 0, 0, 0,
                    ?, ?, ?, ?, ?)
        """, (number, total_items, number,
              datetime.now().isoformat(), batch_id, bf, platform))
        tid = cur.lastrowid
        for step_no, p in enumerate(path, start=1):
            cur.execute("""
                INSERT INTO task_items
                    (task_id, item_code, cell_barcode, quantity,
                     step_no, status)
                VALUES (?, ?, ?, ?, ?, 'pending')
            """, (tid, p["item_code"], p["cell"], p["qty"],
                  step_no))
            reserve(cur, tid, p["item_code"], p["cell"],
                    p["qty"], minutes=RESERVE_DEFAULT_MINUTES)
        numbers.append(number)
    return True, numbers


def _create_receive(cur, state):
    items = [it for it in (state.get("items") or [])
             if int(it.get("qty") or 0) > 0]
    if not items:
        return False, tr("task.err.no_items",
                         "Добавьте позиции.")

    total = sum(int(it["qty"]) for it in items)
    cur.execute("SELECT COALESCE(MAX(id),0)+1 FROM tasks")
    nid = cur.fetchone()[0]
    number = f"TASK-{nid:06d}"
    now = datetime.now().isoformat()
    platform = TASK_PLATFORM["receive"]

    cur.execute("""
        INSERT INTO tasks
            (task_number, task_type, status,
             assignee_login, target_a, processed_a,
             target_b, processed_b, barcode, created_at,
             platform)
        VALUES (?, 'receive', 'pending', NULL, ?, 0, 0, 0,
                ?, ?, ?)
    """, (number, total, number, now, platform))
    tid = cur.lastrowid
    for i, it in enumerate(items, start=1):
        cur.execute("""
            INSERT INTO task_items
                (task_id, item_code, quantity, step_no, status)
            VALUES (?, ?, ?, ?, 'pending')
        """, (tid, it["item_code"], int(it["qty"]), i))
    return True, [number]


def _create_putaway(cur, state):
    bad = []
    for bc in state["containers"]:
        cur.execute(
            "SELECT COALESCE(status,'free') FROM containers "
            "WHERE barcode=?", (bc,))
        r = cur.fetchone()
        st = r[0] if r else "free"
        if st not in ("free", "placing"):
            bad.append((bc, st))
    if bad:
        lines = [f"  {bc}: {st}" for bc, st in bad]
        return False, (tr("task.err.cant_place_containers",
                          "Эти тары нельзя размещать")
                       + ":\n" + "\n".join(lines))

    busy = []
    for bc in state["containers"]:
        cur.execute("""
            SELECT 1 FROM task_items ti
            JOIN tasks t ON t.id = ti.task_id
            WHERE t.task_type='putaway'
              AND t.status IN ('pending','in_progress')
              AND ti.container_barcode = ?
            LIMIT 1
        """, (bc,))
        if cur.fetchone():
            busy.append(bc)
    if busy:
        return False, (tr("task.err.containers_busy",
                          "Эти тары уже в других активных заданиях")
                       + ":\n" + "\n".join(busy))

    total_qty = 0
    for bc in state["containers"]:
        cur.execute(
            "SELECT COALESCE(SUM(quantity), 0) "
            "FROM placed_instances "
            "WHERE cell_or_container_barcode=?", (bc,))
        total_qty += cur.fetchone()[0] or 0

    cur.execute("SELECT COALESCE(MAX(id),0)+1 FROM tasks")
    nid = cur.fetchone()[0]
    number = f"TASK-{nid:06d}"
    platform = TASK_PLATFORM["putaway"]
    cur.execute("""
        INSERT INTO tasks
            (task_number, task_type, status,
             assignee_login, target_a, processed_a,
             target_b, processed_b, barcode, created_at,
             platform)
        VALUES (?, 'putaway', 'pending', NULL, ?, 0, ?, 0,
                ?, ?, ?)
    """, (number, len(state["containers"]), total_qty,
          number, datetime.now().isoformat(), platform))
    tid = cur.lastrowid
    for i, bc in enumerate(state["containers"], start=1):
        cur.execute("""
            INSERT INTO task_items
                (task_id, container_barcode, quantity,
                 step_no, status)
            VALUES (?, ?, 1, ?, 'pending')
        """, (tid, bc, i))
    return True, [number]


def _create_inventory(cur, state):
    cur.execute("SELECT COALESCE(MAX(id),0)+1 FROM tasks")
    nid = cur.fetchone()[0]
    number = f"TASK-{nid:06d}"
    platform = TASK_PLATFORM["inventory"]
    cur.execute("""
        INSERT INTO tasks
            (task_number, task_type, status,
             assignee_login, target_a, processed_a,
             target_b, processed_b, barcode, created_at,
             platform)
        VALUES (?, 'inventory', 'pending', NULL, ?, 0, 0, 0,
                ?, ?, ?)
    """, (number, len(state["cells"]), number,
          datetime.now().isoformat(), platform))
    tid = cur.lastrowid
    for i, c in enumerate(state["cells"], start=1):
        cur.execute("""
            INSERT INTO task_items
                (task_id, cell_barcode, quantity,
                 step_no, status)
            VALUES (?, ?, 1, ?, 'pending')
        """, (tid, c["barcode"], i))
    return True, [number]


def _create_task(cur, state):
    ttype = state["type"]
    if ttype not in CREATABLE_TASK_TYPES:
        return False, tr("task.err.unknown_type",
                         "Неизвестный тип задания.")

    if ttype in ("pick", "receive") and not state["items"]:
        return False, tr("task.err.no_items",
                         "Добавьте позиции.")
    if ttype == "putaway" and not state["containers"]:
        return False, tr("task.err.no_containers",
                         "Добавьте тары.")
    if ttype == "inventory" and not state["cells"]:
        return False, tr("task.err.no_cells",
                         "Выберите ячейки.")

    if ttype == "pick":
        return _create_pick(cur, state)
    if ttype == "receive":
        return _create_receive(cur, state)
    if ttype == "putaway":
        return _create_putaway(cur, state)
    if ttype == "inventory":
        return _create_inventory(cur, state)
    return False, tr("task.err.unknown_type",
                     "Неизвестный тип задания.")


def build_view(login, role, context):
    return _doc(_build_list(context.db_path, role), role)


def handle_action(action, action_id, value, login, role,
                  context, values=None):
    values = values or {}
    db_path = context.db_path

    if action == "input_submit" and action_id and \
            action_id.startswith("filter_"):
        filters = _read_filters(values)
        return {"ok": True, "view": _doc(
            _build_list(db_path, role, filters=filters), role)}

    if action == "input_submit" and action_id in (
            "wizard_type", "wizard_pick_mode"):
        state = _load_wizard(db_path, login) or _fresh_wizard()
        if action_id == "wizard_type":
            new_type = str(value or "pick")
            if new_type not in CREATABLE_TASK_TYPES:
                new_type = "pick"
            if new_type != state["type"]:
                state["type"] = new_type
                state["platform"] = TASK_PLATFORM[new_type]
                state["pick_mode"] = "normal"
                state["items"] = []
                state["containers"] = []
                state["cells"] = []
                state["dialog"] = ""
        elif action_id == "wizard_pick_mode":
            new_mode = str(value or "normal")
            if new_mode != state["pick_mode"]:
                state["pick_mode"] = new_mode
                state["items"] = []
                state["dialog"] = ""
        state["error"] = ""
        _save_wizard(db_path, login, state)
        return {"ok": True, "view": _doc(
            _wizard_view(db_path, role, login, values), role)}

    if action == "tap":
        if action_id == "refresh" or action_id == "back":
            return {"ok": True, "view": _doc(
                _build_list(db_path, role), role)}

        if action_id == "wizard_start":
            _drop_wizard(db_path, login)
            _save_wizard(db_path, login, _fresh_wizard())
            return {"ok": True, "view": _doc(
                _wizard_view(db_path, role, login), role)}
        if action_id == "wizard_cancel":
            _drop_wizard(db_path, login)
            return {"ok": True, "view": _doc(
                _build_list(db_path, role), role)}

        if action_id in ("open_add_item",
                         "open_add_container", "open_add_cell"):
            state = _load_wizard(db_path, login) or _fresh_wizard()
            state["dialog"] = {
                "open_add_item": "add_item",
                "open_add_container": "add_container",
                "open_add_cell": "add_cell",
            }[action_id]
            state["error"] = ""
            _save_wizard(db_path, login, state)
            return {"ok": True, "view": _doc(
                _wizard_view(db_path, role, login), role)}

        if action_id == "dialog_close":
            state = _load_wizard(db_path, login) or _fresh_wizard()
            state["dialog"] = ""
            state["error"] = ""
            _save_wizard(db_path, login, state)
            return {"ok": True, "view": _doc(
                _wizard_view(db_path, role, login), role)}

        if action_id == "dialog_add_item":
            return _dialog_add_item(db_path, role, login, values)
        if action_id == "dialog_add_container":
            return _dialog_add_container(
                db_path, role, login, values)
        if action_id == "dialog_add_cell":
            return _dialog_add_cell(db_path, role, login, values)

        if action_id in ("remove_item", "remove_container",
                         "remove_cell"):
            key = {
                "remove_item": "items",
                "remove_container": "containers",
                "remove_cell": "cells",
            }[action_id]
            return _remove_at(db_path, role, login, key, value)

        if action_id == "wizard_create":
            return _wizard_create(db_path, role, login)

        if action_id == "open_task":
            try:
                tid = int(value)
            except (TypeError, ValueError):
                return {"ok": False,
                        "error": tr("task.err.bad_id",
                                    "bad id")}
            return {"ok": True, "view": _doc(
                _build_panel(db_path, role, tid), role)}
        if action_id == "report":
            tid = (value.get("id")
                   if isinstance(value, dict) else None)
            if not tid:
                return {"ok": False,
                        "error": tr("task.err.bad_id",
                                    "bad id")}
            return {"ok": True, "view": _doc(
                _build_panel(db_path, role, tid,
                             show_report=True), role)}
        if action_id == "finish_early":
            tid = (value.get("id")
                   if isinstance(value, dict) else None)
            if not tid:
                return {"ok": False,
                        "error": tr("task.err.bad_id",
                                    "bad id")}
            return _finish_early(db_path, role, tid)
        if action_id == "delete_task":
            tid = (value.get("id")
                   if isinstance(value, dict) else None)
            if not tid:
                return {"ok": False,
                        "error": tr("task.err.bad_id",
                                    "bad id")}
            return _delete_task(db_path, role, tid)
        if action_id == "close_report":
            tid = (value.get("id")
                   if isinstance(value, dict) else None)
            if not tid:
                return {"ok": True, "view": _doc(
                    _build_list(db_path, role), role)}
            return {"ok": True, "view": _doc(
                _build_panel(db_path, role, tid), role)}
    return {"ok": False,
            "error": tr("task.err.unknown_action",
                        "unknown action: {id}", id=action_id)}


def _dialog_add_item(db_path, role, login, values):
    state = _load_wizard(db_path, login) or _fresh_wizard()
    sel = values.get("table_0_selected", [])
    code = sel[0].get("code") if sel else ""

    if not code:
        state["error"] = tr("task.err.select_item",
                            "Выберите товар.")
        _save_wizard(db_path, login, state)
        return {"ok": True, "view": _doc(
            _wizard_view(db_path, role, login, values), role)}

    try:
        qty = int(values.get("dialog_qty") or 0)
    except (ValueError, TypeError):
        qty = 0
    if qty <= 0:
        state["error"] = tr("task.err.bad_qty",
                            "Некорректное количество.")
        _save_wizard(db_path, login, state)
        return {"ok": True, "view": _doc(
            _wizard_view(db_path, role, login, values), role)}

    cell = ""
    if state["type"] == "pick" and state["pick_mode"] == "exact":
        cell = str(values.get("dialog_cell") or "").strip()
        if not cell:
            state["error"] = tr("task.err.enter_cell",
                                "Укажите ячейку.")
            _save_wizard(db_path, login, state)
            return {"ok": True, "view": _doc(
                _wizard_view(db_path, role, login, values), role)}
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM cells WHERE barcode=?",
                        (cell,))
            if not cur.fetchone():
                state["error"] = tr(
                    "task.err.cell_not_found",
                    "Ячейки с ШК «{cell}» не существует.",
                    cell=cell)
                _save_wizard(db_path, login, state)
                return {"ok": True, "view": _doc(
                    _wizard_view(db_path, role, login, values),
                    role)}
        finally:
            conn.close()

    merged = False
    for it in state["items"]:
        if it["item_code"] == code and \
                (it.get("cell") or "") == cell:
            it["qty"] = int(it["qty"]) + qty
            merged = True
            break
    if not merged:
        state["items"].append({
            "item_code": code, "qty": qty, "cell": cell,
        })
    state["error"] = ""
    state["dialog"] = ""
    _save_wizard(db_path, login, state)
    return {"ok": True, "view": _doc(
        _wizard_view(db_path, role, login), role)}


def _dialog_add_container(db_path, role, login, values):
    state = _load_wizard(db_path, login) or _fresh_wizard()
    sel = values.get("table_0_selected", [])
    bc = sel[0].get("barcode") if sel else ""

    if not bc:
        state["error"] = tr("task.err.no_containers",
                            "Выберите тару.")
        _save_wizard(db_path, login, state)
        return {"ok": True, "view": _doc(
            _wizard_view(db_path, role, login), role)}
    if bc in state["containers"]:
        state["error"] = tr("task.wizard.container_exists",
                            "Такая тара уже добавлена.")
        _save_wizard(db_path, login, state)
        return {"ok": True, "view": _doc(
            _wizard_view(db_path, role, login), role)}
    state["containers"].append(bc)
    state["error"] = ""
    state["dialog"] = ""
    _save_wizard(db_path, login, state)
    return {"ok": True, "view": _doc(
        _wizard_view(db_path, role, login), role)}


def _dialog_add_cell(db_path, role, login, values):
    """Добавить ячейку из таблицы.

    Клиент выбирает строку в таблице cells (field_id='table_0'),
    server получает table_0_selected[0].barcode. Дополнительно
    валидируем, что ячейка действительно существует в БД
    (защита от подделки values).
    """
    state = _load_wizard(db_path, login) or _fresh_wizard()
    sel = values.get("table_0_selected", [])
    cell = str(sel[0].get("barcode") or "").strip() if sel else ""
    if not cell:
        state["error"] = tr("task.err.select_cell",
                            "Выберите ячейку из таблицы.")
        _save_wizard(db_path, login, state)
        return {"ok": True, "view": _doc(
            _wizard_view(db_path, role, login, values), role)}

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT address FROM cells WHERE barcode=?",
                    (cell,))
        r = cur.fetchone()
        if not r:
            state["error"] = tr(
                "task.err.cell_not_found",
                "Ячейки с ШК «{cell}» не существует.",
                cell=cell)
            _save_wizard(db_path, login, state)
            return {"ok": True, "view": _doc(
                _wizard_view(db_path, role, login, values), role)}
        addr = r[0] or ""
    finally:
        conn.close()

    for c in state["cells"]:
        if c["barcode"] == cell:
            state["error"] = tr("task.wizard.cell_exists",
                                "Такая ячейка уже добавлена.")
            _save_wizard(db_path, login, state)
            return {"ok": True, "view": _doc(
                _wizard_view(db_path, role, login), role)}
    state["cells"].append({"barcode": cell, "address": addr})
    state["error"] = ""
    state["dialog"] = ""
    _save_wizard(db_path, login, state)
    return {"ok": True, "view": _doc(
        _wizard_view(db_path, role, login), role)}


def _remove_at(db_path, role, login, key, value):
    state = _load_wizard(db_path, login) or _fresh_wizard()
    try:
        idx = int(value)
    except (TypeError, ValueError):
        return {"ok": True, "view": _doc(
            _wizard_view(db_path, role, login), role)}
    lst = state.get(key) or []
    if 0 <= idx < len(lst):
        del lst[idx]
        state[key] = lst
        state["error"] = ""
        _save_wizard(db_path, login, state)
    return {"ok": True, "view": _doc(
        _wizard_view(db_path, role, login), role)}


def _wizard_create(db_path, role, login):
    state = _load_wizard(db_path, login) or _fresh_wizard()
    conn = sqlite3.connect(db_path)
    # FIX: row_factory, чтобы r["..."] в _create_* не падал
    # с "tuple indices must be integers or slices, not str".
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        ok, result = _create_task(cur, state)
        if not ok:
            conn.rollback()
            state["error"] = str(result)
            state["dialog"] = ""
            _save_wizard(db_path, login, state)
            return {"ok": True, "view": _doc(
                _wizard_view(db_path, role, login), role)}
        conn.commit()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        state["error"] = tr("task.err.cant_create",
                            "Нельзя создать задание:") + f" {e}"
        state["dialog"] = ""
        _save_wizard(db_path, login, state)
        return {"ok": True, "view": _doc(
            _wizard_view(db_path, role, login), role)}
    finally:
        conn.close()

    _drop_wizard(db_path, login)
    numbers = result if isinstance(result, list) else [result]
    if len(numbers) == 1:
        msg = tr("task.msg.created_one",
                 "Создано задание: {number}",
                 number=numbers[0])
    else:
        msg = tr("task.msg.created_many",
                 "Создано {count} заданий:\n{numbers}",
                 count=len(numbers),
                 numbers="\n".join(numbers))
    return {"ok": True, "message": msg,
            "view": _doc(_build_list(db_path, role), role)}


def _build_panel(db_path, role, task_id, message=None, error=None,
                 show_report=False):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT task_number, task_type, status, assignee_login,
                   target_a, processed_a, target_b, processed_b,
                   batch_id, block_bf, partial, platform
            FROM tasks WHERE id=?
        """, (task_id,))
        r = cur.fetchone()
        if not r:
            return _build_list(
                db_path, role,
                error=tr("task.err.not_found",
                         "Задание не найдено"))
        (num, ttype, status, assignee, ta, pa, tb, pb,
         batch, bf, partial, platform) = r

        cur.execute("""
            SELECT ti.item_code, ti.quantity, ti.processed,
                   COALESCE(ti.scanned_qty, 0) AS scanned_qty,
                   ic.name, ti.cell_barcode, ti.container_barcode
            FROM task_items ti
            LEFT JOIN item_characteristics ic
                   ON ic.item_code = ti.item_code
            WHERE ti.task_id=?
            ORDER BY ti.step_no, ti.id
        """, (task_id,))
        items = []
        for row in cur.fetchall():
            (code, qty, proc, scanned_qty,
             name, cell, cont) = row
            items.append({
                "id": code or "",
                "code": code or "",
                "name": name or "",
                "cell": cell or "",
                "container": cont or "",
                "qty": qty or 0,
                "processed": scanned_qty or proc or 0,
            })
    finally:
        conn.close()

    preview = _barcode_preview_b64(num)
    label_b64 = _label_png_b64(_task_label(ttype), num, num)

    header_children = [
        button(tr("common.back", "← Назад"),
               "tap", "back"),
        heading(tr("task.panel.title_num",
                   "Задание {num}", num=num)),
        {"type": "text", "value": "", "stretch": True},
    ]
    if label_b64:
        header_children.append(mgmt_file_trigger(
            "task_barcode",
            tr("task.btn.download_barcode",
               "Скачать ШК задания"),
            action="download",
            download_b64=label_b64,
            filename=f"{num}.png",
            style="primary",
        ))
    children = [group(header_children, orientation="horizontal")]

    if message:
        children.append(card([text(message)], accent="success"))
    if error:
        children.append(card([text(error)], accent="error"))

    left_col = []
    if preview:
        left_col.append(mgmt_image(preview, width=380, height=100))
    left_col.append(text(f"<b>{num}</b>", size=15, align="center"))

    info_children = [
        text(tr("task.panel.number_label",
                "<b>Номер:</b> {number}", number=num)),
        text(tr("task.panel.type_label",
                "<b>Тип:</b> {type}",
                type=_type_label(ttype))),
        text(tr("task.panel.platform_label",
                "<b>Платформа:</b> {platform}",
                platform=_platform_label(platform))),
        text(tr("task.panel.status_label",
                "<b>Статус:</b> {status}",
                status=_status_label(status))),
        text(tr("task.panel.assignee_label",
                "<b>Исполнитель:</b> {assignee}",
                assignee=(assignee
                          or tr("common.dash", "—")))),
        text(tr("task.panel.partial_label",
                "<b>Частичное:</b> {partial}",
                partial=(tr("task.panel.partial_yes", "⚠ Да")
                         if partial
                         else tr("task.panel.partial_no", "Нет")))),
        text(tr("task.panel.block_label",
                "<b>Блок:</b> {block}",
                block=(bf or tr("common.dash", "—")))),
    ]
    info_card = card(info_children,
                     title=tr("task.panel.info", "Сведения"))
    info_card["stretch"] = True

    children.append(group([
        group(left_col, orientation="vertical", spacing=8),
        info_card,
    ], orientation="horizontal", spacing=20))

    if items:
        children.append(mgmt_table(
            columns=[
                {"key": "code",
                 "label": tr("task.panel.col.code", "Артикул")},
                {"key": "name",
                 "label": tr("task.panel.col.name", "Название")},
                {"key": "cell",
                 "label": tr("task.panel.col.cell", "Ячейка")},
                {"key": "container",
                 "label": tr("task.panel.col.container", "Тара")},
                {"key": "qty",
                 "label": tr("task.panel.col.qty", "Кол-во")},
                {"key": "processed",
                 "label": tr("task.panel.col.processed",
                             "Обработано")},
            ],
            rows=items,
            row_key="id",
            empty_label="",
            searchable=False,
        ))
    else:
        children.append(caption(tr("task.panel.empty",
                                   "Состав пуст.")))

    actions = [
        button(tr("task.btn.report", "Отчёт"),
               "tap", "report", value={"id": task_id}),
    ]
    if status != "done":
        actions.append(button(
            tr("task.btn.finish_early", "Завершить досрочно"),
            "tap", "finish_early", value={"id": task_id}))
        actions.append(button(
            tr("task.btn.delete", "Удалить задание"),
            "tap", "delete_task", value={"id": task_id},
            style="danger"))
    children.append(mgmt_toolbar(actions))

    if show_report:
        children.append(_report_dialog(db_path, task_id))
    return mgmt_page("tasks",
                     tr("task.panel.title_num",
                        "Задание {num}", num=num),
                     children)


def _report_dialog(db_path, task_id):
    """Отчёт по заданию. Для каждого типа — своя таблица.

    - pick:      артикул | название | ШК | ячейка | ожидалось
                 | принято | статус (pending/done/not_found)
    - receive:   артикул | название | ШК | ожидалось | принято
                 | статус (pending/done/extra)
    - putaway:   тара | статус | остаток в таре
    - inventory: ячейка | артикул | было | стало
                 + строка «Тары с неизвестными ШК»

    Для pick/receive дополнительно — блок «Отложенные
    (неизвестные) товары» из task_events (event_type='rejected').
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT task_number, task_type, status "
            "FROM tasks WHERE id=?", (task_id,))
        trow = cur.fetchone()
        if not trow:
            return mgmt_dialog(
                "report",
                tr("task.report.title", "Отчёт по заданию"),
                [text(tr("task.err.not_found",
                         "Задание не найдено"))],
                buttons=[button(
                    tr("task.btn.close_report", "Закрыть"),
                    "tap", "close_report",
                    value={"id": task_id})],
            )
        task_number = trow["task_number"] or ""
        task_type = trow["task_type"] or ""
        task_status = trow["status"] or ""

        header = tr(
            "task.report.header",
            "Отчёт: {title} ({status})",
            title=task_number,
            status=_status_label(task_status))

        children = [heading(header, level=2)]

        if task_type == "pick":
            children.append(_report_pick(cur, task_id))
        elif task_type == "receive":
            children.append(_report_receive(cur, task_id))
        elif task_type == "putaway":
            children.append(_report_putaway(cur, task_id))
        elif task_type == "inventory":
            children.append(_report_inventory(cur, task_id))
        else:
            children.append(card(
                [text(tr("task.report.empty",
                         "Нет данных по заданию."))],
                accent="warning"))

        if task_type in ("pick", "receive"):
            rej = _report_rejected(cur, task_id)
            if rej is not None:
                children.append(spacer(8))
                children.append(rej)
    finally:
        conn.close()

    return mgmt_dialog(
        "report",
        tr("task.report.title", "Отчёт по заданию"),
        children,
        buttons=[button(tr("task.btn.close_report", "Закрыть"),
                        "tap", "close_report",
                        value={"id": task_id})],
    )


def _report_pick(cur, task_id):
    cur.execute("""
        SELECT ti.item_code, ti.quantity,
               COALESCE(ti.scanned_qty, 0) AS scanned_qty,
               ti.status,
               ic.name, ic.barcode,
               c.address AS cell_address
        FROM task_items ti
        LEFT JOIN item_characteristics ic
               ON ic.item_code = ti.item_code
        LEFT JOIN cells c
               ON c.barcode = ti.cell_barcode
        WHERE ti.task_id=?
        ORDER BY ti.step_no, ti.id
    """, (task_id,))
    rows = []
    for r in cur.fetchall():
        st = r["status"] or "pending"
        status_label = {
            "pending": tr("task.report.status.pending",
                          "ожидает"),
            "done": tr("task.report.status.done", "готово"),
            "not_found": tr("task.report.status.not_found",
                            "не найден"),
        }.get(st, st)
        rows.append({
            "id": f'{r["item_code"] or ""}|{r["cell_address"] or ""}',
            "code": r["item_code"] or "",
            "name": r["name"] or "",
            "barcode": r["barcode"] or "",
            "cell": r["cell_address"] or "",
            "expected": r["quantity"] or 0,
            "scanned": r["scanned_qty"] or 0,
            "status": status_label,
        })
    return mgmt_table(
        columns=[
            {"key": "code",
             "label": tr("task.report.col.item_code",
                         "Артикул")},
            {"key": "name",
             "label": tr("task.report.col.name", "Название")},
            {"key": "barcode",
             "label": tr("task.report.col.barcode", "ШК")},
            {"key": "cell",
             "label": tr("task.report.col.cell", "Ячейка")},
            {"key": "expected",
             "label": tr("task.report.col.expected",
                         "Ожидалось")},
            {"key": "scanned",
             "label": tr("task.report.col.scanned",
                         "Принято")},
            {"key": "status",
             "label": tr("task.report.col.status", "Статус")},
        ],
        rows=rows,
        row_key="id",
        empty_label="",
        searchable=False,
    )


def _report_receive(cur, task_id):
    cur.execute("""
        SELECT ti.item_code, ti.quantity,
               COALESCE(ti.scanned_qty, 0) AS scanned_qty,
               ti.status,
               ic.name, ic.barcode
        FROM task_items ti
        LEFT JOIN item_characteristics ic
               ON ic.item_code = ti.item_code
        WHERE ti.task_id=?
        ORDER BY ti.step_no, ti.id
    """, (task_id,))
    rows = []
    for r in cur.fetchall():
        st = r["status"] or "pending"
        if st == "extra":
            status_label = tr("task.report.status.extra",
                              "сверх плана")
        elif st == "done":
            status_label = tr("task.report.status.done",
                              "готово")
        else:
            status_label = tr("task.report.status.pending",
                              "ожидает")
        rows.append({
            "id": f'{r["item_code"] or ""}|{st}|{r["quantity"] or 0}',
            "code": r["item_code"] or "",
            "name": r["name"] or "",
            "barcode": r["barcode"] or "",
            "expected": r["quantity"] or 0,
            "scanned": r["scanned_qty"] or 0,
            "status": status_label,
        })
    return mgmt_table(
        columns=[
            {"key": "code",
             "label": tr("task.report.col.item_code",
                         "Артикул")},
            {"key": "name",
             "label": tr("task.report.col.name", "Название")},
            {"key": "barcode",
             "label": tr("task.report.col.barcode", "ШК")},
            {"key": "expected",
             "label": tr("task.report.col.expected",
                         "Ожидалось")},
            {"key": "scanned",
             "label": tr("task.report.col.scanned",
                         "Принято")},
            {"key": "status",
             "label": tr("task.report.col.status", "Статус")},
        ],
        rows=rows,
        row_key="id",
        empty_label="",
        searchable=False,
    )


def _report_putaway(cur, task_id):
    # Для putaway в task_items — тары. item_code NULL,
    # quantity=1. Показываем: ШК тары | статус | остаток.
    cur.execute("""
        SELECT ti.container_barcode, ti.status
        FROM task_items ti
        WHERE ti.task_id=?
        ORDER BY ti.step_no, ti.id
    """, (task_id,))
    rows = []
    for r in cur.fetchall():
        bc = r["container_barcode"] or ""
        st = r["status"] or "pending"
        status_label = {
            "pending": tr("task.report.status.pending",
                          "ожидает"),
            "scanned": tr("task.report.status.scanned",
                          "отсканирована"),
            "in_use": tr("task.report.status.in_use",
                         "в работе"),
            "done": tr("task.report.status.done", "готово"),
        }.get(st, st)
        cur.execute("""
            SELECT COALESCE(SUM(quantity), 0)
            FROM placed_instances
            WHERE cell_or_container_barcode=?
        """, (bc,))
        left = cur.fetchone()[0] or 0
        rows.append({
            "id": bc,
            "barcode": bc,
            "status": status_label,
            "left": left,
        })
    return mgmt_table(
        columns=[
            {"key": "barcode",
             "label": tr("task.report.col.container", "Тара")},
            {"key": "status",
             "label": tr("task.report.col.status", "Статус")},
            {"key": "left",
             "label": tr("task.report.col.left",
                         "Остаток в таре")},
        ],
        rows=rows,
        row_key="id",
        empty_label="",
        searchable=False,
    )


def _report_inventory(cur, task_id):
    # Результаты — из inventory_reports (было/стало).
    cur.execute("""
        SELECT r.cell_barcode, r.item_code,
               r.qty_before, r.qty_after,
               ic.name, c.address AS cell_address
        FROM inventory_reports r
        LEFT JOIN item_characteristics ic
               ON ic.item_code = r.item_code
        LEFT JOIN cells c
               ON c.barcode = r.cell_barcode
        WHERE r.task_id=?
        ORDER BY r.cell_barcode, ic.name COLLATE NOCASE
    """, (task_id,))
    diff_rows = []
    for r in cur.fetchall():
        diff_rows.append({
            "id": f'{r["cell_barcode"] or ""}|{r["item_code"] or ""}',
            "cell": r["cell_address"] or r["cell_barcode"] or "",
            "code": r["item_code"] or "",
            "name": r["name"] or "",
            "before": r["qty_before"] or 0,
            "after": r["qty_after"] or 0,
        })

    # Контейнеры с неизвестными ШК — из task_items (status='unknown').
    cur.execute("""
        SELECT DISTINCT ti.container_barcode
        FROM task_items ti
        JOIN containers c ON c.barcode = ti.container_barcode
        WHERE ti.task_id=? AND c.status = 'unknown_scan'
    """, (task_id,))
    unknown = [r["container_barcode"] for r in cur.fetchall()]

    parts = []
    if diff_rows:
        parts.append(mgmt_table(
            columns=[
                {"key": "cell",
                 "label": tr("task.report.col.cell", "Ячейка")},
                {"key": "code",
                 "label": tr("task.report.col.item_code",
                             "Артикул")},
                {"key": "name",
                 "label": tr("task.report.col.name", "Название")},
                {"key": "before",
                 "label": tr("task.report.col.qty_before",
                             "Было")},
                {"key": "after",
                 "label": tr("task.report.col.qty_after",
                             "Стало")},
            ],
            rows=diff_rows,
            row_key="id",
            empty_label="",
            searchable=False,
        ))
    else:
        parts.append(caption(tr(
            "task.report.empty",
            "Нет данных по заданию.")))

    if unknown:
        parts.append(spacer(8))
        parts.append(caption(tr(
            "task.report.unknown_containers",
            "Тары с неизвестными ШК: {list}",
            list=", ".join(unknown))))

    return group(parts, orientation="vertical", spacing=8)


def _report_rejected(cur, task_id):
    """Блок «Отложенные (неизвестные) товары» из task_events.

    Возвращает готовый mgmt-узел (card + таблица) или None,
    если отложенных нет.
    """
    cur.execute("""
        SELECT barcode, created_at
        FROM task_events
        WHERE task_id=? AND event_type='rejected'
        ORDER BY id
    """, (task_id,))
    events = cur.fetchall()
    if not events:
        return None

    rows = []
    for i, r in enumerate(events):
        rows.append({
            "id": f"rej-{i}",
            "barcode": r["barcode"] or "",
            "date": (r["created_at"] or "")[:19],
        })

    return card([
        caption(tr("task.report.rejected",
                   "Отложенные (неизвестные) товары:")),
        mgmt_table(
            columns=[
                {"key": "barcode",
                 "label": tr("task.report.col.barcode", "ШК"),
                 "width": 0.6},
                {"key": "date",
                 "label": tr("task.report.col.date", "Когда"),
                 "width": 0.4},
            ],
            rows=rows,
            row_key="id",
            empty_label="",
            searchable=False,
        ),
    ], accent="warning")


def _finish_early(db_path, role, tid):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT task_type FROM tasks WHERE id=?",
                    (tid,))
        r = cur.fetchone()
        if r and r[0] == "receive":
            return {"ok": False,
                    "error": tr(
                        "task.err.receive_only_session",
                        "Приёмку завершайте через сессию "
                        "приёмки (ПК-терминал).")}
        try:
            from tasks import get_handler
            from server import _load_task_state as _load_state
            handler = get_handler(r[0] if r else "")
            if handler is not None:
                task, items, settings = _load_state(cur, tid)
                if task:
                    handler.on_finalize(cur, task,
                                        items or [], settings or {})
        except Exception:
            pass
        cur.execute("""
            UPDATE tasks SET status='done',
                assignee_login=NULL,
                pending_action='', pending_cell=''
            WHERE id=?
        """, (tid,))
        cur.execute("DELETE FROM reservations WHERE task_id=?",
                    (tid,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True,
            "message": tr("task.msg.finished",
                          "Задание завершено"),
            "view": _doc(_build_list(db_path, role), role)}


def _delete_task(db_path, role, tid):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT container_barcode FROM tasks WHERE id=?",
            (tid,))
        r = cur.fetchone()
        main_container = (r[0] if r else "") or ""
        containers = set()
        if main_container:
            containers.add(main_container)
        cur.execute("""
            SELECT DISTINCT container_barcode FROM task_items
            WHERE task_id=? AND container_barcode IS NOT NULL
              AND container_barcode != ''
        """, (tid,))
        for row in cur.fetchall():
            containers.add(row[0])
        for bc in containers:
            cur.execute(
                "SELECT COALESCE(SUM(quantity), 0) "
                "FROM placed_instances "
                "WHERE cell_or_container_barcode=?", (bc,))
            qty = cur.fetchone()[0] or 0
            new_status = "placing" if qty > 0 else "free"
            cur.execute(
                "UPDATE containers SET status=? WHERE barcode=?",
                (new_status, bc))
        cur.execute("DELETE FROM task_events WHERE task_id=?",
                    (tid,))
        cur.execute("DELETE FROM task_items WHERE task_id=?",
                    (tid,))
        cur.execute("DELETE FROM tasks WHERE id=?", (tid,))
        cur.execute("DELETE FROM reservations WHERE task_id=?",
                    (tid,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True,
            "message": tr("task.msg.deleted",
                          "Задание удалено"),
            "view": _doc(_build_list(db_path, role), role)}


def _read_filters(values):
    return {
        "type": str(values.get("filter_type") or ""),
        "status": str(values.get("filter_status") or ""),
        "platform": str(values.get("filter_platform") or ""),
        "search": str(values.get("filter_search") or ""),
        "partial": bool(values.get("filter_partial")),
        "block": str(values.get("filter_block") or ""),
        "active": bool(values.get("filter_active", True)),
        "date": str(values.get("filter_date") or ""),
    }