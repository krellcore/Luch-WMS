"""«Просмотр склада» — серверная сборка view."""

import sqlite3
import base64
import json

from PySide6.QtCore import QBuffer, QIODevice

from mgmt_protocol import (
    mgmt_page, mgmt_toolbar, mgmt_table, mgmt_form_field,
    mgmt_breadcrumb, heading, text, card, button, group,
    mgmt_file_trigger, mgmt_image, make_mgmt_document, mgmt_header,
    mgmt_dialog, spacer
)
from mgmt_view_builder import build_sidebar
from barcodes import make_label_image, make_barcode_pixmap
from i18n import tr


PICKABLE_CONTAINER_STATUSES = ("free", "waiting", "placing")


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


def _get_cell_info(db_path, address):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT address, barcode, cell_type FROM cells "
            "WHERE address=?", (address,))
        r = cur.fetchone()
        if not r:
            return None
        return {"address": r[0], "barcode": r[1], "cell_type": r[2]}
    finally:
        conn.close()


def _list_rows(db_path):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT address, barcode, cell_type "
                    "FROM cells ORDER BY address")
        rows = []
        for addr, bc, ct in cur.fetchall():
            cur.execute("""
                SELECT COALESCE(SUM(quantity), 0)
                FROM placed_instances WHERE cell_barcode=?
            """, (bc,))
            qty = cur.fetchone()[0] or 0
            rows.append({
                "id": addr,
                "address": addr or "",
                "qty": qty,
                "barcode": bc or "",
                "type": ct or "",
            })
        return rows
    finally:
        conn.close()


def _build_list(db_path, role, search=""):
    rows = _list_rows(db_path)
    if search:
        s = search.lower()
        rows = [r for r in rows
                if s in (r["address"] or "").lower()
                or s in (r["barcode"] or "").lower()
                or s in (r["type"] or "").lower()]

    children = [
        mgmt_header(
            tr("viewer.title", "Просмотр склада"),
            [mgmt_breadcrumb([{
                "label": tr("viewer.breadcrumb.home",
                            "Главная")}])]),
        group([
            mgmt_form_field(
                "search", kind="text",
                label=tr("common.search", "Поиск:"),
                label_position="left",
                value=search,
                placeholder=tr("viewer.search_placeholder",
                               "Фильтр по адресу, ШК, типу..."),
                on_change="input_submit", stretch=True),
            button(tr("viewer.btn.refresh", "Обновить"),
                   "tap", "refresh")
        ], orientation="horizontal"),
        mgmt_table(
            columns=[
                {"key": "address",
                 "label": tr("viewer.col.address", "Ячейки")},
                {"key": "qty",
                 "label": tr("viewer.col.qty",
                             "Кол-во товаров")},
                {"key": "barcode",
                 "label": tr("viewer.col.barcode",
                             "Штрихкод ячейки")},
                {"key": "type",
                 "label": tr("viewer.col.type", "Тип")},
            ],
            rows=rows,
            on_double_click={
                "action": "tap", "id": "open_cell",
                "value_field": "id"},
            row_key="id",
            empty_label="",
            searchable=False,
        ),
    ]
    return mgmt_page("viewer",
                     tr("viewer.title", "Просмотр склада"),
                     children)


def _alert_dialog(title, msg, addr):
    return mgmt_dialog(
        "alert_dialog", title,
        [text(msg)],
        buttons=[button(tr("common.ok", "ОК"), "tap",
                        "close_dialog",
                        value={"address": addr},
                        style="primary")]
    )


def _clear_inv_draft(db_path, login):
    draft_key = f"_mgmt_inv_draft_{login}"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DELETE FROM settings WHERE key=?",
                     (draft_key,))
        conn.commit()
    finally:
        conn.close()


def _build_cell(db_path, role, address, dialog=None, search=""):
    info = _get_cell_info(db_path, address)
    if not info:
        return (_build_list(db_path, role),
                tr("viewer.err.cell_not_found",
                   "Ячейка не найдена"))

    addr = info["address"]
    bc = info["barcode"]
    ct = info["cell_type"]

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT ic.item_code, ic.name, ic.barcode,
                   COALESCE(SUM(pi.quantity), 0)
            FROM placed_instances pi
            LEFT JOIN item_characteristics ic
                ON ic.item_code = pi.item_code
            WHERE pi.cell_barcode=?
            GROUP BY ic.item_code, ic.name, ic.barcode
        """, (bc,))
        contents = []
        total = 0
        for code, name, ibc, qty in cur.fetchall():
            contents.append({
                "id": code or "",
                "code": code or "",
                "name": name or "",
                "barcode": ibc or "",
                "qty": qty or 0,
            })
            total += qty or 0
    finally:
        conn.close()

    if search:
        s = search.lower()
        contents = [c for c in contents
                    if s in c["code"].lower()
                    or s in c["name"].lower()
                    or s in c["barcode"].lower()]

    preview = _barcode_preview_b64(bc)
    label_b64 = _label_png_b64(
        tr("viewer.label.cell", "ЯЧЕЙКА"), addr or "", bc or "")

    children = [
        mgmt_header(
            tr("viewer.title", "Просмотр склада"),
            [mgmt_breadcrumb([
                {"label": tr("viewer.breadcrumb.home",
                             "Главная"),
                 "value": "home"},
                {"label": addr or ""},
            ])]
        ),
    ]

    left_col = []
    if preview:
        left_col.append(mgmt_image(preview, width=380, height=100))
    left_col.append(text(f"<b>{bc}</b>", size=15, align="center"))
    if label_b64:
        left_col.append(mgmt_file_trigger(
            "download_bc",
            tr("viewer.btn.download_barcode",
               "Скачать стилизованный ШК"),
            action="download",
            download_b64=label_b64,
            filename=f"{bc}.png"
        ))

    info_card = card([
        text(tr("viewer.panel.address_label",
                "<b>Адрес:</b> {address}", address=addr)),
        text(tr("viewer.panel.type_label",
                "<b>Тип:</b> {type}",
                type=(ct or tr("common.dash", "—")))),
        text(tr("viewer.panel.total_label",
                "<b>Всего:</b> {total}", total=total)),
    ], title=tr("viewer.characteristics",
                "Характеристики ячейки"))
    info_card["stretch"] = True

    children.append(group([
        group(left_col, orientation="vertical", spacing=8),
        info_card
    ], orientation="horizontal", spacing=20))

    bottom_row = [
        mgmt_form_field(
            f"cell_search:{addr}", kind="text",
            label=tr("common.search", "Поиск:"),
            label_position="left",
            value=search,
            placeholder=tr(
                "viewer.cell_search_placeholder",
                "Фильтр по артикулу, названию, ШК…"),
            on_change="input_submit", stretch=True),
        button(tr("viewer.btn.pick", "Подбор"),
               "tap", "pick", value={"address": addr},
               style="primary"),
        button(tr("viewer.btn.putaway", "Размещение"),
               "tap", "putaway", value={"address": addr},
               style="primary"),
        button(tr("viewer.btn.inventory", "Инвентаризация"),
               "tap", "inventory", value={"address": addr},
               style="primary")
    ]
    children.append(group(bottom_row, orientation="horizontal",
                          spacing=20))

    children.append(mgmt_table(
        columns=[
            {"key": "code",
             "label": tr("viewer.col.item_code", "Артикул")},
            {"key": "name",
             "label": tr("viewer.col.item_name", "Название")},
            {"key": "barcode",
             "label": tr("viewer.col.item_barcode",
                         "Штрихкод")},
            {"key": "qty",
             "label": tr("viewer.col.item_qty", "Количество")},
        ],
        rows=contents,
        row_key="id",
        empty_label="",
        searchable=False,
    ))

    if dialog:
        children.append(dialog)

    return (mgmt_page("viewer",
                      tr("viewer.cell_label", "Ячейка:")
                      + f" {addr}",
                      children),
            None)


def _move_qty(cur, src_bc, src_kind, dst_bc, dst_kind,
              item_code, qty):
    src_fld = ("cell_barcode" if src_kind == "cell"
               else "cell_or_container_barcode")
    dst_fld = ("cell_barcode" if dst_kind == "cell"
               else "cell_or_container_barcode")

    cur.execute(
        f"SELECT id, quantity FROM placed_instances "
        f"WHERE {src_fld}=? AND item_code=?",
        (src_bc, item_code))
    row = cur.fetchone()
    if not row or row[1] < qty:
        raise ValueError(
            tr("viewer.err_not_enough_raw",
               "Недостаточно товара {code}",
               code=item_code))

    src_id, src_qty = row
    if src_qty == qty:
        cur.execute("DELETE FROM placed_instances WHERE id=?",
                    (src_id,))
    else:
        cur.execute(
            "UPDATE placed_instances SET quantity=quantity-? "
            "WHERE id=?", (qty, src_id))

    cur.execute(
        f"SELECT id FROM placed_instances "
        f"WHERE {dst_fld}=? AND item_code=?",
        (dst_bc, item_code))
    dst_row = cur.fetchone()
    if dst_row:
        cur.execute(
            "UPDATE placed_instances SET quantity=quantity+? "
            "WHERE id=?", (qty, dst_row[0]))
    else:
        cur.execute(
            f"INSERT INTO placed_instances "
            f"(item_code, {dst_fld}, quantity) "
            f"VALUES (?, ?, ?)",
            (item_code, dst_bc, qty))


def _sync_container_status_after_pick(cur, container, prev_status):
    if prev_status not in PICKABLE_CONTAINER_STATUSES:
        return
    cur.execute(
        "SELECT COALESCE(SUM(quantity), 0) "
        "FROM placed_instances "
        "WHERE cell_or_container_barcode=?", (container,))
    qty = cur.fetchone()[0] or 0
    if qty == 0:
        return
    if prev_status == "free":
        cur.execute(
            "UPDATE containers SET status='waiting' "
            "WHERE barcode=?", (container,))


def _sync_container_status_after_putaway(cur, container):
    if not container:
        return
    cur.execute(
        "SELECT COALESCE(SUM(quantity), 0) "
        "FROM placed_instances "
        "WHERE cell_or_container_barcode=?", (container,))
    qty = cur.fetchone()[0] or 0
    if qty == 0:
        cur.execute(
            "UPDATE containers SET status='free', placed_in='' "
            "WHERE barcode=?", (container,))


def _cancel_putaway_for_container(cur, container):
    cur.execute("""
        SELECT DISTINCT t.id, t.task_number
        FROM tasks t
        JOIN task_items ti ON ti.task_id = t.id
        WHERE t.task_type = 'putaway'
          AND t.status IN ('pending', 'in_progress')
          AND ti.container_barcode = ?
    """, (container,))
    tasks = cur.fetchall()
    for task_id, task_number in tasks:
        cur.execute(
            "DELETE FROM task_items WHERE task_id = ? "
            "AND container_barcode = ?",
            (task_id, container))
        cur.execute(
            "SELECT COUNT(*) FROM task_items WHERE task_id = ?",
            (task_id,))
        left = cur.fetchone()[0] or 0
        if left == 0:
            cur.execute(
                "UPDATE tasks SET status = 'cancelled', "
                "assignee_login = NULL, pending_action = '', "
                "pending_cell = '' WHERE id = ?", (task_id,))
            msg = tr("viewer.putaway.task_cancelled",
                     "Задание {num} автоматически отменено: "
                     "тара {bc} размещена вручную",
                     num=task_number, bc=container)
            payload = {
                "key": "viewer.putaway.task_cancelled",
                "params": {"num": task_number,
                           "bc": container},
            }
            cur.execute("""
                INSERT INTO notifications
                    (task_id, message, created_at, sender_login,
                     type, recipient_login, read_at, payload)
                VALUES (?, ?, datetime('now'), 'PC', 'system',
                        '', '', ?)
            """, (task_id, msg, json.dumps(payload)))
        else:
            cur.execute(
                "UPDATE tasks SET target_a = "
                "(SELECT COUNT(*) FROM task_items "
                "WHERE task_id = ?) WHERE id = ?",
                (task_id, task_id))
            msg = tr("viewer.putaway.task_updated",
                     "Из задания {num} удалена тара {bc}: "
                     "размещена вручную",
                     num=task_number, bc=container)
            payload = {
                "key": "viewer.putaway.task_updated",
                "params": {"num": task_number,
                           "bc": container},
            }
            cur.execute("""
                INSERT INTO notifications
                    (task_id, message, created_at, sender_login,
                     type, recipient_login, read_at, payload)
                VALUES (?, ?, datetime('now'), 'PC', 'system',
                        '', '', ?)
            """, (task_id, msg, json.dumps(payload)))


def _set_qty(cur, cell_bc, item_code, qty):
    cur.execute(
        "SELECT id FROM placed_instances "
        "WHERE cell_barcode=? AND item_code=?",
        (cell_bc, item_code))
    r = cur.fetchone()
    if r:
        if qty > 0:
            cur.execute(
                "UPDATE placed_instances SET quantity=? "
                "WHERE id=?", (qty, r[0]))
        else:
            cur.execute(
                "DELETE FROM placed_instances WHERE id=?", (r[0],))
    elif qty > 0:
        cur.execute("""
            INSERT INTO placed_instances
                (item_code, cell_barcode,
                 cell_or_container_barcode, quantity)
            VALUES (?, ?, '', ?)
        """, (item_code, cell_bc, qty))


def _get_selected(values, fid="table_0"):
    return values.get(fid + "_selected", [])


def build_view(login, role, context):
    return _doc(_build_list(context.db_path, role), role)


def handle_action(action, action_id, value, login, role,
                  context, values=None):
    values = values or {}
    db_path = context.db_path

    table_rows = values.get("table_0", [])

    if action == "input_submit" and action_id and \
            action_id.startswith("cell_search:"):
        addr = action_id[len("cell_search:"):]
        search_v = (str(values.get(action_id) or value or ""))
        page, err = _build_cell(db_path, role, addr,
                                search=search_v)
        if err:
            return {"ok": True, "message": err,
                    "view": _doc(page, role)}
        return {"ok": True, "view": _doc(page, role)}

    if action == "input_submit" and action_id == "search":
        return {"ok": True, "view": _doc(
            _build_list(db_path, role,
                        search=str(value or "")), role)}

    if action == "tap":
        if action_id == "refresh" or action_id == "back_list":
            _clear_inv_draft(db_path, login)
            return {"ok": True, "view": _doc(
                _build_list(db_path, role), role)}
        if action_id == "navigate":
            target = str(value or "")
            if target == "home" or target == "":
                _clear_inv_draft(db_path, login)
                return {"ok": True, "view": _doc(
                    _build_list(db_path, role), role)}
            page, err = _build_cell(db_path, role, target)
            if err:
                return {"ok": True, "message": err,
                        "view": _doc(page, role)}
            return {"ok": True, "view": _doc(page, role)}
        if action_id == "open_cell":
            page, err = _build_cell(db_path, role, str(value or ""))
            if err:
                return {"ok": True, "message": err,
                        "view": _doc(page, role)}
            return {"ok": True, "view": _doc(page, role)}

        if action_id == "close_dialog":
            _clear_inv_draft(db_path, login)
            addr = (value.get("address")
                    if isinstance(value, dict) else None)
            if not addr:
                return {"ok": True, "view": _doc(
                    _build_list(db_path, role), role)}
            return {"ok": True, "view": _doc(
                _build_cell(db_path, role, addr)[0], role)}

        # ------- ПОДБОР -------
        if action_id == "pick":
            addr = value.get("address")
            if not _get_cell_info(db_path, addr):
                return {"ok": False,
                        "error": tr("viewer.err.cell_not_found",
                                    "Ячейка не найдена")}

            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute(
                "SELECT barcode, type, COALESCE(status,'free'), "
                "(SELECT COALESCE(SUM(quantity),0) "
                " FROM placed_instances "
                " WHERE cell_or_container_barcode=containers.barcode) "
                "FROM containers "
                "WHERE status IN ('free', 'waiting', 'placing') "
                "ORDER BY barcode")
            containers = []
            for bc, t, st, qty in cur.fetchall():
                containers.append({
                    "barcode": bc, "type": t,
                    "status": st, "qty": qty})
            conn.close()

            if not containers:
                return {"ok": True, "view": _doc(
                    _build_cell(
                        db_path, role, addr,
                        dialog=_alert_dialog(
                            tr("common.warning", "Внимание"),
                            tr("viewer.err.no_containers_available",
                               "Нет доступных тар для подбора."),
                            addr))[0], role)}

            table = mgmt_table(
                columns=[
                    {"key": "barcode",
                     "label": tr("containers.col.barcode",
                                 "ШК тары")},
                    {"key": "type",
                     "label": tr("containers.col.type", "Тип")},
                    {"key": "status",
                     "label": tr("containers.col.status",
                                 "Статус")},
                    {"key": "qty",
                     "label": tr("containers.col.contents",
                                 "Содержимое")},
                ],
                rows=containers,
                field_id="table_0",
                searchable=True,
                search_placeholder=tr("common.search_placeholder",
                                      "Поиск..."),
            )

            dialog = mgmt_dialog(
                "select_container",
                tr("viewer.dialog.pick.title", "Подбор"),
                [text(tr("viewer.picker.hint",
                         "Выберите рабочую тару:")), table],
                buttons=[
                    button(tr("viewer.btn.select", "Выбрать"),
                           "tap", "pick_enter_qty",
                           value={"address": addr},
                           style="primary"),
                    button(tr("common.cancel", "Отмена"),
                           "tap", "close_dialog",
                           value={"address": addr}),
                ]
            )
            return {"ok": True, "view": _doc(
                _build_cell(db_path, role, addr,
                            dialog=dialog)[0], role)}

        if action_id == "pick_enter_qty":
            addr = value.get("address")
            sel = _get_selected(values, "table_0")
            if not sel:
                return {"ok": True, "view": _doc(
                    _build_cell(
                        db_path, role, addr,
                        dialog=_alert_dialog(
                            tr("common.warning", "Внимание"),
                            tr("viewer.dialog.pick.select_hint",
                               "Выберите тару из списка."),
                            addr))[0], role)}

            container_bc = sel[0]["barcode"]
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cell_bc = _get_cell_info(db_path, addr)["barcode"]
            cur.execute(
                "SELECT ti.item_code, ic.name, "
                "COALESCE(SUM(ti.quantity),0) "
                "FROM placed_instances ti "
                "LEFT JOIN item_characteristics ic "
                "ON ic.item_code = ti.item_code "
                "WHERE ti.cell_barcode=? "
                "GROUP BY ti.item_code, ic.name",
                (cell_bc,))
            rows = [{"code": c, "name": n or c, "qty": q}
                    for c, n, q in cur.fetchall()]
            conn.close()

            if not rows:
                return {"ok": True, "view": _doc(
                    _build_cell(
                        db_path, role, addr,
                        dialog=_alert_dialog(
                            tr("common.warning", "Внимание"),
                            tr("viewer.dialog.pick.empty_cell",
                               "Ячейка пуста."),
                            addr))[0], role)}

            table = mgmt_table(
                columns=[
                    {"key": "code",
                     "label": tr("viewer.col.item_code",
                                 "Артикул")},
                    {"key": "name",
                     "label": tr("viewer.col.item_name",
                                 "Название")},
                    {"key": "qty",
                     "label": tr("viewer.col.item_qty",
                                 "Количество")},
                ],
                rows=rows,
                editable=True,
                field_id="table_0",
                searchable=True,
                search_placeholder=tr("common.search_placeholder",
                                      "Поиск..."),
            )
            dialog = mgmt_dialog(
                "pick_qty",
                tr("viewer.dialog.pick.title", "Подбор"),
                [
                    text(tr("viewer.dialog.pick.source",
                            "Источник: {src}  →  Цель: {dst}",
                            src=cell_bc, dst=container_bc)),
                    text(tr("viewer.hint_edit",
                            "Дважды кликните на количество, "
                            "чтобы изменить."),
                         color="#7f8c8d"),
                    table,
                ],
                buttons=[
                    button(tr("viewer.btn.execute", "Выполнить"),
                           "tap", "pick_commit",
                           value={"address": addr,
                                  "container": container_bc},
                           style="primary"),
                    button(tr("common.cancel", "Отмена"),
                           "tap", "close_dialog",
                           value={"address": addr}),
                ]
            )
            return {"ok": True, "view": _doc(
                _build_cell(db_path, role, addr,
                            dialog=dialog)[0], role)}

        if action_id == "pick_commit":
            addr = value.get("address")
            container_bc = value.get("container")
            cell_bc = _get_cell_info(db_path, addr)["barcode"]

            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute(
                "SELECT COALESCE(status,'free') FROM containers "
                "WHERE barcode=?", (container_bc,))
            prev_status = cur.fetchone()[0]
            try:
                for row in table_rows:
                    code = row.get("code")
                    qty_to_move = int(row.get("qty") or 0)
                    if code and qty_to_move > 0:
                        _move_qty(cur, cell_bc, "cell",
                                  container_bc, "container",
                                  code, qty_to_move)
                _sync_container_status_after_pick(
                    cur, container_bc, prev_status)
                conn.commit()
            except Exception as e:
                conn.rollback()
                conn.close()
                return {"ok": True, "view": _doc(
                    _build_cell(
                        db_path, role, addr,
                        dialog=_alert_dialog(
                            tr("common.error", "Ошибка"),
                            str(e), addr))[0], role)}
            conn.close()
            return {"ok": True,
                    "message": tr("viewer.msg.pick_done",
                                  "Подбор выполнен"),
                    "view": _doc(_build_cell(
                        db_path, role, addr)[0], role)}

        # ------- РАЗМЕЩЕНИЕ -------
        if action_id == "putaway":
            addr = value.get("address")
            if not _get_cell_info(db_path, addr):
                return {"ok": False,
                        "error": tr("viewer.err.cell_not_found",
                                    "Ячейка не найдена")}

            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            # FIX: исключаем контейнеры, занятые в других задачах
            # (picking/accepting/unknown_scan). Ручное размещение
            # такого контейнера ранее «увозило» товар из активного
            # pick-задания, оставляя саму задачу невыполнимой.
            cur.execute(
                "SELECT barcode, type, COALESCE(status,'free'), "
                "(SELECT COALESCE(SUM(quantity),0) "
                " FROM placed_instances "
                " WHERE cell_or_container_barcode=containers.barcode) "
                "FROM containers "
                "WHERE barcode IN ("
                "  SELECT cell_or_container_barcode "
                "  FROM placed_instances WHERE quantity>0) "
                "  AND COALESCE(status,'free') NOT IN "
                "      ('picking','accepting','unknown_scan') "
                "ORDER BY barcode")
            containers = []
            for bc, t, st, qty in cur.fetchall():
                containers.append({
                    "barcode": bc, "type": t,
                    "status": st, "qty": qty})
            conn.close()

            table = mgmt_table(
                columns=[
                    {"key": "barcode",
                     "label": tr("containers.col.barcode",
                                 "ШК тары")},
                    {"key": "type",
                     "label": tr("containers.col.type", "Тип")},
                    {"key": "status",
                     "label": tr("containers.col.status",
                                 "Статус")},
                    {"key": "qty",
                     "label": tr("containers.col.contents",
                                 "Содержимое")},
                ],
                rows=containers,
                field_id="table_0",
                empty_label=tr(
                    "viewer.dialog.putaway.no_containers",
                    "Нет тар с товарами"),
                searchable=True,
                search_placeholder=tr("common.search_placeholder",
                                      "Поиск..."),
            )

            dialog = mgmt_dialog(
                "select_container",
                tr("viewer.dialog.putaway.title", "Размещение"),
                [text(tr("viewer.picker.hint",
                         "Выберите рабочую тару:")), table],
                buttons=[
                    button(tr("viewer.btn.select", "Выбрать"),
                           "tap", "putaway_enter_qty",
                           value={"address": addr},
                           style="primary"),
                    button(tr("common.cancel", "Отмена"),
                           "tap", "close_dialog",
                           value={"address": addr}),
                ]
            )
            return {"ok": True, "view": _doc(
                _build_cell(db_path, role, addr,
                            dialog=dialog)[0], role)}

        if action_id == "putaway_enter_qty":
            addr = value.get("address")
            sel = _get_selected(values, "table_0")
            if not sel:
                return {"ok": True, "view": _doc(
                    _build_cell(
                        db_path, role, addr,
                        dialog=_alert_dialog(
                            tr("common.warning", "Внимание"),
                            tr("viewer.dialog.pick.select_hint",
                               "Выберите тару из списка."),
                            addr))[0], role)}

            container_bc = sel[0]["barcode"]
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cell_bc = _get_cell_info(db_path, addr)["barcode"]
            cur.execute(
                "SELECT pi.item_code, ic.name, "
                "COALESCE(SUM(pi.quantity),0) "
                "FROM placed_instances pi "
                "LEFT JOIN item_characteristics ic "
                "ON ic.item_code = pi.item_code "
                "WHERE pi.cell_or_container_barcode=? "
                "GROUP BY pi.item_code, ic.name",
                (container_bc,))
            rows = [{"code": c, "name": n or c, "qty": q}
                    for c, n, q in cur.fetchall()]
            conn.close()

            if not rows:
                return {"ok": True, "view": _doc(
                    _build_cell(
                        db_path, role, addr,
                        dialog=_alert_dialog(
                            tr("common.warning", "Внимание"),
                            tr("viewer.dialog.putaway.empty_container",
                               "Тара пуста."),
                            addr))[0], role)}

            table = mgmt_table(
                columns=[
                    {"key": "code",
                     "label": tr("viewer.col.item_code",
                                 "Артикул")},
                    {"key": "name",
                     "label": tr("viewer.col.item_name",
                                 "Название")},
                    {"key": "qty",
                     "label": tr("viewer.col.item_qty",
                                 "Количество")},
                ],
                rows=rows,
                editable=True,
                field_id="table_0",
                searchable=True,
                search_placeholder=tr("common.search_placeholder",
                                      "Поиск..."),
            )
            dialog = mgmt_dialog(
                "putaway_qty",
                tr("viewer.dialog.putaway.title", "Размещение"),
                [
                    text(tr("viewer.dialog.pick.source",
                            "Источник: {src}  →  Цель: {dst}",
                            src=container_bc, dst=cell_bc)),
                    text(tr("viewer.hint_edit",
                            "Дважды кликните на количество, "
                            "чтобы изменить."),
                         color="#7f8c8d"),
                    table,
                ],
                buttons=[
                    button(tr("viewer.btn.execute", "Выполнить"),
                           "tap", "putaway_commit",
                           value={"address": addr,
                                  "container": container_bc},
                           style="primary"),
                    button(tr("common.cancel", "Отмена"),
                           "tap", "close_dialog",
                           value={"address": addr}),
                ]
            )
            return {"ok": True, "view": _doc(
                _build_cell(db_path, role, addr,
                            dialog=dialog)[0], role)}

        if action_id == "putaway_commit":
            addr = value.get("address")
            container_bc = value.get("container")
            cell_bc = _get_cell_info(db_path, addr)["barcode"]

            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            try:
                for row in table_rows:
                    code = row.get("code")
                    qty_to_move = int(row.get("qty") or 0)
                    if code and qty_to_move > 0:
                        _move_qty(cur, container_bc, "container",
                                  cell_bc, "cell",
                                  code, qty_to_move)
                _cancel_putaway_for_container(cur, container_bc)
                _sync_container_status_after_putaway(
                    cur, container_bc)
                conn.commit()
            except Exception as e:
                conn.rollback()
                conn.close()
                return {"ok": True, "view": _doc(
                    _build_cell(
                        db_path, role, addr,
                        dialog=_alert_dialog(
                            tr("common.error", "Ошибка"),
                            str(e), addr))[0], role)}
            conn.close()
            return {"ok": True,
                    "message": tr("viewer.msg.putaway_done",
                                  "Размещение выполнено"),
                    "view": _doc(_build_cell(
                        db_path, role, addr)[0], role)}

        # ------- ИНВЕНТАРИЗАЦИЯ -------
        if action_id == "inventory":
            addr = value.get("address")
            cell = _get_cell_info(db_path, addr)
            if not cell:
                return {"ok": False,
                        "error": tr("viewer.err.cell_not_found",
                                    "Ячейка не найдена")}

            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute(
                "SELECT ti.item_code, ic.name, "
                "COALESCE(SUM(ti.quantity),0) "
                "FROM placed_instances ti "
                "LEFT JOIN item_characteristics ic "
                "ON ic.item_code = ti.item_code "
                "WHERE ti.cell_barcode=? "
                "GROUP BY ti.item_code, ic.name",
                (cell["barcode"],))
            rows = [{"code": c, "name": n or c, "qty": q}
                    for c, n, q in cur.fetchall()]
            conn.close()

            table = mgmt_table(
                columns=[
                    {"key": "code",
                     "label": tr("viewer.col.item_code",
                                 "Артикул")},
                    {"key": "name",
                     "label": tr("viewer.col.item_name",
                                 "Название")},
                    {"key": "qty",
                     "label": tr("viewer.col.item_qty",
                                 "Количество")},
                ],
                rows=rows,
                editable=True,
                field_id="table_0",
                searchable=True,
                search_placeholder=tr("common.search_placeholder",
                                      "Поиск..."),
            )

            dialog = mgmt_dialog(
                "inv_qty",
                tr("viewer.dialog.inventory.title",
                   "Инвентаризация"),
                [
                    text(tr("viewer.dialog.inventory.source",
                            "Источник: {barcode}",
                            barcode=cell["barcode"])),
                    text(tr("viewer.hint_edit",
                            "Дважды кликните на количество, "
                            "чтобы изменить."),
                         color="#7f8c8d"),
                    table,
                ],
                buttons=[
                    button(tr("viewer.inventory.add_item",
                              "+ Добавить артикул"),
                           "tap", "add_inv_item",
                           value={"address": addr}, align="left"),
                    button(tr("viewer.btn.execute", "Выполнить"),
                           "tap", "inventory_commit",
                           value={"address": addr},
                           style="primary"),
                    button(tr("common.cancel", "Отмена"),
                           "tap", "close_dialog",
                           value={"address": addr}),
                ]
            )
            return {"ok": True, "view": _doc(
                _build_cell(db_path, role, addr,
                            dialog=dialog)[0], role)}

        if action_id == "inventory_commit":
            addr = value.get("address")
            cell_bc = _get_cell_info(db_path, addr)["barcode"]

            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            try:
                for row in table_rows:
                    code = row.get("code")
                    new_qty = int(row.get("qty") or 0)
                    if code:
                        _set_qty(cur, cell_bc, code, new_qty)
                conn.commit()
            except Exception as e:
                conn.rollback()
                conn.close()
                return {"ok": True, "view": _doc(
                    _build_cell(
                        db_path, role, addr,
                        dialog=_alert_dialog(
                            tr("common.error", "Ошибка"),
                            str(e), addr))[0], role)}
            conn.close()
            _clear_inv_draft(db_path, login)
            return {"ok": True,
                    "message": tr("viewer.msg.inventory_done",
                                  "Инвентаризация завершена"),
                    "view": _doc(_build_cell(
                        db_path, role, addr)[0], role)}

        if action_id == "add_inv_item":
            addr = value.get("address")
            draft_key = f"_mgmt_inv_draft_{login}"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute("DELETE FROM settings WHERE key=?",
                             (draft_key,))
                conn.execute(
                    "INSERT INTO settings (key, value) "
                    "VALUES (?, ?)",
                    (draft_key, json.dumps(table_rows)))
                conn.commit()
            finally:
                conn.close()

            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute(
                "SELECT item_code, name, barcode "
                "FROM item_characteristics "
                "ORDER BY name COLLATE NOCASE")
            items = [{"code": c, "name": n, "barcode": b}
                     for c, n, b in cur.fetchall()]
            conn.close()

            table = mgmt_table(
                columns=[
                    {"key": "code",
                     "label": tr("viewer.col.item_code",
                                 "Артикул")},
                    {"key": "name",
                     "label": tr("viewer.col.item_name",
                                 "Название")},
                    {"key": "barcode",
                     "label": tr("viewer.col.item_barcode",
                                 "ШК")},
                ],
                rows=items,
                field_id="table_0",
                searchable=True,
                search_placeholder=tr("common.search_placeholder",
                                      "Поиск..."),
            )
            dialog = mgmt_dialog(
                "inv_add_item",
                tr("viewer.dialog.inventory.add_item_title",
                   "Выбор артикула"),
                [table],
                buttons=[
                    button(tr("viewer.btn.add_item_short",
                              "Добавить"),
                           "tap", "add_inv_item_commit",
                           value={"address": addr},
                           style="primary"),
                    button(tr("common.cancel", "Отмена"),
                           "tap", "cancel_inv_add_item",
                           value={"address": addr}),
                ]
            )
            return {"ok": True, "view": _doc(
                _build_cell(db_path, role, addr,
                            dialog=dialog)[0], role)}

        if action_id == "add_inv_item_commit":
            addr = value.get("address")
            sel = _get_selected(values, "table_0")
            if not sel:
                return {"ok": True, "view": _doc(
                    _build_cell(
                        db_path, role, addr,
                        dialog=_alert_dialog(
                            tr("common.warning", "Внимание"),
                            tr("viewer.dialog.inventory"
                                ".no_item_selected",
                               "Артикул не выбран."),
                            addr))[0], role)}

            draft_key = f"_mgmt_inv_draft_{login}"
            conn = sqlite3.connect(db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT value FROM settings WHERE key=?",
                    (draft_key,))
                r = cur.fetchone()
                draft_rows = json.loads(r[0]) if r else []
                cur.execute("DELETE FROM settings WHERE key=?",
                            (draft_key,))
                conn.commit()
            finally:
                conn.close()

            code = sel[0]["code"]
            if not any(row.get("code") == code
                       for row in draft_rows):
                draft_rows.append({
                    "code": code,
                    "name": sel[0]["name"],
                    "qty": 0,
                })

            cell = _get_cell_info(db_path, addr)
            table = mgmt_table(
                columns=[
                    {"key": "code",
                     "label": tr("viewer.col.item_code",
                                 "Артикул")},
                    {"key": "name",
                     "label": tr("viewer.col.item_name",
                                 "Название")},
                    {"key": "qty",
                     "label": tr("viewer.col.item_qty",
                                 "Количество")},
                ],
                rows=draft_rows,
                editable=True,
                field_id="table_0",
                searchable=True,
                search_placeholder=tr("common.search_placeholder",
                                      "Поиск..."),
            )
            dialog = mgmt_dialog(
                "inv_qty",
                tr("viewer.dialog.inventory.title",
                   "Инвентаризация"),
                [
                    text(tr("viewer.dialog.inventory.source",
                            "Источник: {barcode}",
                            barcode=cell["barcode"])),
                    text(tr("viewer.hint_edit",
                            "Дважды кликните на количество, "
                            "чтобы изменить."),
                         color="#7f8c8d"),
                    table,
                ],
                buttons=[
                    button(tr("viewer.inventory.add_item",
                              "+ Добавить артикул"),
                           "tap", "add_inv_item",
                           value={"address": addr}, align="left"),
                    button(tr("viewer.btn.execute", "Выполнить"),
                           "tap", "inventory_commit",
                           value={"address": addr},
                           style="primary"),
                    button(tr("common.cancel", "Отмена"),
                           "tap", "close_dialog",
                           value={"address": addr}),
                ]
            )
            return {"ok": True, "view": _doc(
                _build_cell(db_path, role, addr,
                            dialog=dialog)[0], role)}

        if action_id == "cancel_inv_add_item":
            addr = value.get("address")
            draft_key = f"_mgmt_inv_draft_{login}"
            conn = sqlite3.connect(db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT value FROM settings WHERE key=?",
                    (draft_key,))
                r = cur.fetchone()
                draft_rows = json.loads(r[0]) if r else []
                cur.execute("DELETE FROM settings WHERE key=?",
                            (draft_key,))
                conn.commit()
            finally:
                conn.close()

            cell = _get_cell_info(db_path, addr)
            table = mgmt_table(
                columns=[
                    {"key": "code",
                     "label": tr("viewer.col.item_code",
                                 "Артикул")},
                    {"key": "name",
                     "label": tr("viewer.col.item_name",
                                 "Название")},
                    {"key": "qty",
                     "label": tr("viewer.col.item_qty",
                                 "Количество")},
                ],
                rows=draft_rows,
                editable=True,
                field_id="table_0",
                searchable=True,
                search_placeholder=tr("common.search_placeholder",
                                      "Поиск..."),
            )
            dialog = mgmt_dialog(
                "inv_qty",
                tr("viewer.dialog.inventory.title",
                   "Инвентаризация"),
                [
                    text(tr("viewer.dialog.inventory.source",
                            "Источник: {barcode}",
                            barcode=cell["barcode"])),
                    text(tr("viewer.hint_edit",
                            "Дважды кликните на количество, "
                            "чтобы изменить."),
                         color="#7f8c8d"),
                    table,
                ],
                buttons=[
                    button(tr("viewer.inventory.add_item",
                              "+ Добавить артикул"),
                           "tap", "add_inv_item",
                           value={"address": addr}, align="left"),
                    button(tr("viewer.btn.execute", "Выполнить"),
                           "tap", "inventory_commit",
                           value={"address": addr},
                           style="primary"),
                    button(tr("common.cancel", "Отмена"),
                           "tap", "close_dialog",
                           value={"address": addr}),
                ]
            )
            return {"ok": True, "view": _doc(
                _build_cell(db_path, role, addr,
                            dialog=dialog)[0], role)}

    return {"ok": False,
            "error": tr("viewer.err.unknown_action",
                        "unknown action: {id}", id=action_id)}