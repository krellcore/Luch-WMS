"""«Точки сброса» — серверная сборка view и действия."""

import sqlite3
import base64

from PySide6.QtCore import QBuffer, QIODevice

from mgmt_protocol import (
    mgmt_page, mgmt_toolbar, mgmt_table, mgmt_form_field,
    mgmt_dialog, heading, text, card, caption, button,
    mgmt_file_trigger, mgmt_image, make_mgmt_document, mgmt_header,
    group, spacer,
)
from mgmt_view_builder import build_sidebar
from barcodes import make_label_image, make_barcode_pixmap
from i18n import tr


def _status_label(st):
    key = f"containers.status.{st or 'free'}"
    default = {
        "free": "свободна", "accepting": "приёмка",
        "placing": "к размещению", "picking": "подбор",
        "waiting": "ожидает", "closed": "закрыта",
        "dropped": "сброшена",
        "unknown_scan": "неизвестные ШК",
    }.get(st or "free", st or "")
    return tr(key, default)


def _doc(page, role):
    return make_mgmt_document(
        page, sidebar=build_sidebar(role),
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


def _list_rows(db_path, search=""):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT dp.barcode, dp.name,
                   (SELECT COUNT(*) FROM containers
                    WHERE placed_in = dp.barcode) AS cnt
            FROM drop_points dp ORDER BY dp.id
        """)
        rows = []
        s = (search or "").lower()
        for bc, name, cnt in cur.fetchall():
            if s and s not in (bc or "").lower() \
                    and s not in (name or "").lower():
                continue
            rows.append({
                "id": bc,
                "barcode": bc or "",
                "name": name or "",
                "count": cnt or 0,
            })
        return rows
    finally:
        conn.close()


def _build_list(db_path, role, search="", message=None,
                error=None, dialog=None):
    header_actions = [
        button(tr("drop_points.btn.add", "+ Создать точку"),
               "tap", "add_open", style="primary"),
        button(tr("drop_points.btn.delete", "Удалить"),
               "tap", "delete"),
    ]
    children = [mgmt_header(
        tr("drop_points.title", "Точки сброса"), header_actions)]
    if message:
        children.append(card([text(message)], accent="success"))
    if error:
        children.append(card([text(error)], accent="error"))

    children.append(group([
        mgmt_form_field(
            "search", kind="text",
            label=tr("drop_points.filter.search", "Поиск:"),
            label_position="left", stretch=True,
            value=search,
            placeholder=tr("drop_points.filter.placeholder",
                           "ШК или название…"),
            on_change="input_submit"),
        button(tr("drop_points.btn.refresh", "Обновить"),
               "tap", "refresh"),
    ], orientation="horizontal"))

    children.append(mgmt_table(
        columns=[
            {"key": "barcode",
             "label": tr("drop_points.col.barcode", "ШК точки")},
            {"key": "name",
             "label": tr("drop_points.col.name", "Название")},
            {"key": "count",
             "label": tr("drop_points.col.count",
                         "Тар на точке")},
        ],
        rows=_list_rows(db_path, search=search),
        on_double_click={
            "action": "tap", "id": "open_point",
            "value_field": "barcode"},
        row_key="barcode",
        empty_label="",
        searchable=False,
    ))

    children.append(caption(tr(
        "drop_points.caption.hint",
        "Двойной клик по точке — список тар, которые на ней "
        "лежат, и кнопка «Скачать ШК точки».")))

    if dialog == "add":
        children.append(_add_dialog())
    return mgmt_page(tr("drop_points.title", "Точки сброса"),
                     tr("drop_points.title", "Точки сброса"),
                     children)


def _add_dialog():
    return mgmt_dialog(
        "add",
        tr("drop_points.dialog.add.title", "Новая точка сброса"),
        [
            mgmt_form_field(
                "barcode", kind="text",
                label=tr("drop_points.dialog.add.barcode",
                         "ШК точки:"),
                placeholder=tr(
                    "drop_points.dialog.add.barcode_placeholder",
                    "Например, DROP-1"),
                stretch=True),
            mgmt_form_field(
                "name", kind="text",
                label=tr("drop_points.dialog.add.name",
                         "Название:"),
                placeholder=tr(
                    "drop_points.dialog.add.name_placeholder",
                    "Например, «Сброс у лифта B»"),
                stretch=True),
        ],
        buttons=[
            button(tr("drop_points.btn.create", "Создать"),
                   "tap", "add_commit", style="primary"),
            button(tr("drop_points.btn.cancel", "Отмена"),
                   "tap", "dialog_cancel"),
        ],
    )


def _build_panel(db_path, role, point_barcode, message=None,
                 error=None):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT barcode, name FROM drop_points WHERE barcode=?",
            (point_barcode,))
        r = cur.fetchone()
        if not r:
            return _build_list(
                db_path, role,
                error=tr("drop_points.err.not_found",
                         "точка не найдена"))
        pb, pname = r
        cur.execute("""
            SELECT c.barcode, COALESCE(c.status,'free'),
                   COALESCE((SELECT SUM(pi.quantity)
                     FROM placed_instances pi
                     WHERE pi.cell_or_container_barcode=c.barcode),
                     0) AS qty
            FROM containers c
            WHERE c.placed_in = ?
            ORDER BY c.barcode
        """, (point_barcode,))
        containers = []
        for bc, st, qty in cur.fetchall():
            containers.append({
                "id": bc,
                "barcode": bc or "",
                "status": _status_label(st),
                "qty": qty or 0,
            })
    finally:
        conn.close()

    preview = _barcode_preview_b64(pb)
    label_b64 = _label_png_b64(
        tr("drop_points.label.point", "ТОЧКА СБРОСА"),
        pname or pb, pb)

    children = []
    
    header_children = [
        button(tr("drop_points.btn.back", "← Назад"),
               "tap", "back"),
        heading(tr("drop_points.panel.title",
                   "Точка сброса: {name}", name=pname or pb)),
        {"type": "text", "value": "", "stretch": True},
    ]
    if label_b64:
        header_children.append(mgmt_file_trigger(
            "point_barcode",
            tr("drop_points.btn.download", "Скачать ШК точки"),
            action="download",
            download_b64=label_b64,
            filename=f"{pb}.png",
            style="primary"
        ))
    children.append(group(header_children, orientation="horizontal"))

    if message:
        children.append(card([text(message)], accent="success"))
    if error:
        children.append(card([text(error)], accent="error"))

    left_col = []
    if preview:
        left_col.append(mgmt_image(preview, width=380, height=100))
    left_col.append(text(f"<b>{pb}</b>", size=15, align="center"))
    
    info_card = card([
        text(tr("drop_points.panel.barcode",
                "<b>ШК:</b> {barcode}", barcode=pb)),
        text(tr("drop_points.panel.name",
                "<b>Название:</b> {name}",
                name=pname or tr("drop_points.panel.no_name",
                                 "(без названия)"))),
        text(tr("drop_points.panel.count",
                "<b>Тар на точке:</b> {count}",
                count=len(containers))),
    ], title=tr("drop_points.panel.characteristics",
                "Характеристики"))
    info_card["stretch"] = True

    children.append(group([
        group(left_col, orientation="vertical", spacing=8),
        info_card
    ], orientation="horizontal", spacing=20))

    children.append(text(
        tr("drop_points.panel.containers_title",
           "Тары на этой точке:"), bold=True))
    children.append(mgmt_table(
        columns=[
            {"key": "barcode",
             "label": tr("drop_points.col.container_barcode",
                         "ШК тары")},
            {"key": "status",
             "label": tr("drop_points.col.container_status",
                         "Статус")},
            {"key": "qty",
             "label": tr("drop_points.col.container_qty",
                         "Содержимое")},
        ],
        rows=containers,
        row_key="id",
        field_id="table_0",
        on_double_click={
            "action": "tap", "id": "open_container",
            "value_field": "id"},
        empty_label="",
    ))

    children.append(group([
        {"type": "text", "value": "", "stretch": True},
        button(tr("drop_points.btn.free", "Освободить тару"),
               "tap", "free_container"),
    ], orientation="horizontal"))
    
    children.append(caption(tr(
        "drop_points.caption.details",
        "Двойной клик по таре — посмотреть содержимое. "
        "«Освободить тару» очищает содержимое и возвращает "
        "тару в оборот.")))

    return mgmt_page(tr("drop_points.title", "Точки сброса"),
                     tr("drop_points.title", "Точки сброса"),
                     children)


def _container_contents_dialog(db_path, barcode):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT pi.item_code, pi.quantity,
                   ic.name, ic.barcode
            FROM placed_instances pi
            LEFT JOIN item_characteristics ic
                   ON ic.item_code = pi.item_code
            WHERE pi.cell_or_container_barcode=?
            ORDER BY pi.item_code
        """, (barcode,))
        rows = []
        for code, qty, name, bc in cur.fetchall():
            rows.append({
                "code": code or "",
                "name": name or "",
                "barcode": bc or "",
                "qty": qty or 0,
            })
    finally:
        conn.close()

    return mgmt_dialog(
        "container_contents",
        tr("drop_points.dialog.contents.title",
           "Содержимое тары {barcode}", barcode=barcode),
        [mgmt_table(
            columns=[
                {"key": "code",
                 "label": tr(
                     "drop_points.dialog.contents.col.code",
                     "Артикул")},
                {"key": "name",
                 "label": tr(
                     "drop_points.dialog.contents.col.name",
                     "Название")},
                {"key": "barcode",
                 "label": tr(
                     "drop_points.dialog.contents.col.barcode",
                     "ШК")},
                {"key": "qty",
                 "label": tr(
                     "drop_points.dialog.contents.col.qty",
                     "Количество")},
            ],
            rows=rows,
            row_key="code",
            empty_label="",
        )],
        buttons=[button(tr("drop_points.btn.close", "Закрыть"),
                        "tap", "close_dialog")]
    )


def build_view(login, role, context):
    return _doc(_build_list(context.db_path, role), role)


def handle_action(action, action_id, value, login, role,
                  context, values=None):
    values = values or {}
    db_path = context.db_path

    if action == "input_submit" and action_id == "search":
        return {"ok": True, "view": _doc(
            _build_list(db_path, role,
                        search=str(values.get("search") or "")),
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
        if action_id == "open_point":
            return {"ok": True, "view": _doc(
                _build_panel(db_path, role, str(value or "")),
                role)}
        if action_id == "back":
            return {"ok": True, "view": _doc(
                _build_list(db_path, role), role)}
        if action_id == "delete":
            bc = value if isinstance(value, str) else \
                (value.get("id") if isinstance(value, dict)
                 else None)
            if not bc:
                return {"ok": False,
                        "error": tr("drop_points.err.not_found",
                                    "точка не найдена")}
            return _delete(db_path, role, str(bc))
            
        if action_id == "open_container":
            bc = value if isinstance(value, str) else \
                (value.get("id") if isinstance(value, dict) else None)
            if not bc:
                return {"ok": False,
                        "error": tr(
                            "drop_points.err.container_not_found",
                            "тара не найдена")}
            pt_bc = _find_point_for_container(db_path, str(bc))
            if not pt_bc:
                return {"ok": False,
                        "error": tr(
                            "drop_points.err.point_not_found",
                            "точка не найдена")}
                
            doc = _build_panel(db_path, role, pt_bc)
            doc["children"].append(
                _container_contents_dialog(db_path, str(bc)))
            return {"ok": True, "view": _doc(doc, role)}
            
        if action_id == "free_container":
            return _free_container(db_path, role, values)
            
        if action_id == "close_dialog":
            pt_bc = (value.get("point_barcode")
                     if isinstance(value, dict) else None)
            if pt_bc:
                return {"ok": True, "view": _doc(
                    _build_panel(db_path, role, pt_bc), role)}
            return {"ok": True, "view": _doc(
                _build_list(db_path, role), role)}
            
    return {"ok": False,
            "error": tr("drop_points.err.unknown_action",
                        "unknown action: {id}", id=action_id)}


def _find_point_for_container(db_path, container_bc):
    if not container_bc:
        return None
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT placed_in FROM containers WHERE barcode=?",
            (container_bc,))
        r = cur.fetchone()
        return r[0] if r else None
    finally:
        conn.close()


def _free_container(db_path, role, values):
    sel = _get_selected(values, "table_0")
    if not sel:
        return {"ok": False,
                "error": tr(
                    "drop_points.err.no_container_selected",
                    "выберите тару в таблице")}
    
    barcode = sel[0].get("barcode")
    if not barcode:
        return {"ok": False,
                "error": tr(
                    "drop_points.err.container_not_found",
                    "тара не найдена")}
        
    pt_bc = _find_point_for_container(db_path, barcode)
    
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM placed_instances
            WHERE cell_or_container_barcode=?
        """, (barcode,))
        cur.execute("""
            UPDATE containers SET status='free', placed_in=''
            WHERE barcode=?
        """, (barcode,))
        conn.commit()
    finally:
        conn.close()
        
    msg = tr("drop_points.msg.freed",
             "Тара {barcode} освобождена", barcode=barcode)
    if pt_bc:
        return {"ok": True, "message": msg,
                "view": _doc(_build_panel(
                    db_path, role, pt_bc), role)}
    return {"ok": True, "message": msg,
            "view": _doc(_build_list(db_path, role), role)}


def _get_selected(values, fid="table_0"):
    return values.get(fid + "_selected", [])


def _add_commit(db_path, role, values):
    bc = str(values.get("barcode") or "").strip()
    name = (str(values.get("name") or "").strip()
            or tr("drop_points.title", "Точки сброса"))
    if not bc:
        return {"ok": True, "view": _doc(_build_list(
            db_path, role,
            error=tr("drop_points.err.barcode_empty",
                     "введите ШК"),
            dialog="add"), role)}
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM drop_points WHERE barcode=?", (bc,))
        if cur.fetchone():
            return {"ok": True, "view": _doc(_build_list(
                db_path, role,
                error=tr("drop_points.err.exists",
                         "ШК уже существует"),
                dialog="add"), role)}
        cur.execute("""
            INSERT INTO drop_points (barcode, name, created_at)
            VALUES (?, ?, datetime('now'))
        """, (bc, name))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True,
            "message": tr("drop_points.msg.created",
                          "Создана точка {barcode}", barcode=bc),
            "view": _doc(_build_list(db_path, role), role)}


def _delete(db_path, role, bc):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM containers WHERE placed_in=?
        """, (bc,))
        cnt = cur.fetchone()[0] or 0
        if cnt > 0:
            return {"ok": True, "view": _doc(_build_list(
                db_path, role,
                error=tr("drop_points.err.not_empty",
                         "на точке {barcode} лежит тар: {count}. "
                         "Сначала освободите их.",
                         barcode=bc, count=cnt)), role)}
        cur.execute(
            "DELETE FROM drop_points WHERE barcode=?", (bc,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True,
            "message": tr("drop_points.msg.deleted", "Удалена"),
            "view": _doc(_build_list(db_path, role), role)}