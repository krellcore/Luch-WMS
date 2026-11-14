"""Общие утилиты для handler'ов заданий."""

import json
from datetime import datetime

from db import (
    available_qty, reserve,
    RESERVE_DEFAULT_MINUTES,
)
from i18n import tr


def set_container_status(cur, barcode, status):
    if not barcode:
        return
    cur.execute("SELECT 1 FROM containers WHERE barcode=?",
                (barcode,))
    if not cur.fetchone():
        cur.execute(
            "INSERT OR IGNORE INTO containers "
            "(barcode, type, placed_in, status) "
            "VALUES (?, 'standart', '', ?)",
            (barcode, status))
    cur.execute("UPDATE containers SET status=? WHERE barcode=?",
                (status, barcode))


def add_to_container(cur, item_code, container, qty=1):
    if not (item_code and container and qty):
        return
    cur.execute("""
        SELECT id FROM placed_instances
        WHERE item_code=? AND cell_or_container_barcode=?
    """, (item_code, container))
    r = cur.fetchone()
    if r:
        cur.execute("UPDATE placed_instances "
                    "SET quantity=quantity+? WHERE id=?",
                    (qty, r[0]))
    else:
        cur.execute("""
            INSERT INTO placed_instances
                (item_code, cell_or_container_barcode, quantity)
            VALUES (?, ?, ?)
        """, (item_code, container, qty))


def move_one(cur, item_code, src_barcode, dst_barcode):
    if not (item_code and src_barcode and dst_barcode):
        return False

    cur.execute("""
        SELECT id, COALESCE(quantity, 0) FROM placed_instances
        WHERE item_code=? AND cell_barcode=?
    """, (item_code, src_barcode))
    src = cur.fetchone()
    if not src:
        cur.execute("""
            SELECT id, COALESCE(quantity, 0) FROM placed_instances
            WHERE item_code=? AND cell_or_container_barcode=?
        """, (item_code, src_barcode))
        src = cur.fetchone()
    if not src:
        return False
    if (src[1] or 0) <= 0:
        return False

    if src[1] > 1:
        cur.execute("UPDATE placed_instances "
                    "SET quantity=quantity-1 WHERE id=?",
                    (src[0],))
    else:
        cur.execute("DELETE FROM placed_instances WHERE id=?",
                    (src[0],))

    cur.execute("""
        SELECT id FROM placed_instances
        WHERE item_code=? AND cell_or_container_barcode=?
    """, (item_code, dst_barcode))
    dst = cur.fetchone()
    if dst:
        cur.execute("UPDATE placed_instances "
                    "SET quantity=quantity+1 WHERE id=?",
                    (dst[0],))
    else:
        cur.execute("""
            INSERT INTO placed_instances
                (item_code, cell_or_container_barcode, quantity)
            VALUES (?, ?, 1)
        """, (item_code, dst_barcode))
    return True


def short_addr(addr):
    if not addr:
        return ""
    parts = addr.split("-")
    if len(parts) == 4:
        return "-".join(parts[1:])
    return addr


def add_task_event(cur, task_id, step_no, event_type, barcode,
                   payload=None):
    cur.execute("""
        INSERT INTO task_events
            (task_id, step_no, event_type, barcode,
             payload, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (task_id, step_no, event_type, barcode,
          json.dumps(payload or {}),
          datetime.now().isoformat()))


def photo_b64(cur, item_code):
    if not item_code:
        return None
    try:
        cur.execute("SELECT mime, data FROM photos "
                    "WHERE item_code=?", (item_code,))
        r = cur.fetchone()
    except Exception:
        return None
    if not r or not r[1]:
        return None
    import base64
    mime = r[0] or "image/png"
    try:
        raw = bytes(r[1])
        return (f"data:{mime};base64,"
                + base64.b64encode(raw).decode("ascii"))
    except Exception:
        return None


def find_items_in_bf(cur, item_code, bf_prefix,
                     exclude_cell=None, limit=999):
    if not bf_prefix:
        return []
    sql = """
        SELECT pi.cell_barcode, SUM(pi.quantity) AS qty
        FROM placed_instances pi
        JOIN cells c ON c.barcode = pi.cell_barcode
        WHERE pi.item_code = ?
          AND c.address LIKE ?
          AND pi.quantity > 0
    """
    params = [item_code, bf_prefix + "-%"]
    if exclude_cell:
        sql += " AND pi.cell_barcode != ?"
        params.append(exclude_cell)
    sql += " GROUP BY pi.cell_barcode ORDER BY c.address"
    cur.execute(sql, params)
    rows = []
    acc = 0
    for r in cur.fetchall():
        if acc >= limit:
            break
        avail = available_qty(cur, item_code, r[0])
        if avail <= 0:
            continue
        take = min(avail, limit - acc)
        rows.append({"cell_barcode": r[0], "qty": take})
        acc += take
    return rows


def find_items_anywhere(cur, item_code, exclude_cells=None,
                        limit=999):
    sql = """
        SELECT pi.cell_barcode, SUM(pi.quantity) AS qty
        FROM placed_instances pi
        WHERE pi.item_code = ?
          AND pi.quantity > 0
          AND pi.cell_barcode IS NOT NULL
          AND pi.cell_barcode != ''
    """
    params = [item_code]
    if exclude_cells:
        placeholders = ",".join(["?"] * len(exclude_cells))
        sql += f" AND pi.cell_barcode NOT IN ({placeholders})"
        params.extend(exclude_cells)
    sql += " GROUP BY pi.cell_barcode ORDER BY pi.cell_barcode"
    cur.execute(sql, params)
    rows = []
    acc = 0
    for r in cur.fetchall():
        if acc >= limit:
            break
        avail = available_qty(cur, item_code, r[0])
        if avail <= 0:
            continue
        take = min(avail, limit - acc)
        rows.append({"cell_barcode": r[0], "qty": take})
        acc += take
    return rows


def create_followup_task(cur, src_task, item_code, qty,
                         item_barcode=None, assign_to=None):
    if qty is None or qty <= 0:
        return None
    cur.execute("SELECT COALESCE(MAX(id),0)+1 FROM tasks")
    nid = cur.fetchone()[0]
    number = f"TASK-{nid:06d}"
    now = datetime.now().isoformat()
    # FIX: наследуем platform исходной задачи, иначе
    # pc-задача превращается в android-only followup.
    platform = (src_task.get("platform") if src_task else None) \
        or "android"
    cur.execute("""
        INSERT INTO tasks (task_number, task_type, status,
            assignee_login, target_a, processed_a,
            target_b, processed_b, barcode, created_at,
            platform)
        VALUES (?, 'pick', ?, ?, ?, 0, 0, 0, ?, ?, ?)
    """, (number,
          'in_progress' if assign_to else 'pending',
          assign_to, qty, number, now, platform))
    tid = cur.lastrowid

    cur.execute("""
        SELECT cell_barcode, SUM(quantity) AS qty
        FROM placed_instances
        WHERE item_code=? AND quantity > 0
          AND cell_barcode IS NOT NULL AND cell_barcode != ''
        GROUP BY cell_barcode
        ORDER BY cell_barcode
    """, (item_code,))
    remaining = qty
    step_no = 1
    for r in cur.fetchall():
        if remaining <= 0:
            break
        avail = available_qty(cur, item_code, r[0])
        if avail <= 0:
            continue
        take = min(avail, remaining)
        cur.execute("""
            INSERT INTO task_items
                (task_id, item_code, cell_barcode, quantity,
                 step_no, status)
            VALUES (?, ?, ?, ?, ?, 'pending')
        """, (tid, item_code, r[0], take, step_no))
        reserve(cur, tid, item_code, r[0], take,
                minutes=RESERVE_DEFAULT_MINUTES)
        remaining -= take
        step_no += 1

    msg = tr(
        "task.notif.followup_created",
        "Создано задание {number} на подбор {item_code} "
        "({qty} шт) — товара нет в исходном блоке",
        number=number, item_code=item_code, qty=qty)
    payload = {
        "key": "task.notif.followup_created",
        "params": {"number": number, "item_code": item_code,
                   "qty": qty},
        "item_code": item_code,
        "qty": qty,
        "origin_task": src_task.get("task_number", "") if src_task else "",
    }
    cur.execute("""
        INSERT INTO notifications
            (task_id, message, created_at, sender_login,
             type, recipient_login, read_at, payload)
        VALUES (?, ?, ?, 'system', 'system', '', '', ?)
    """, (tid, msg, now, json.dumps(payload)))
    return number


def create_putaway_for_container(cur, src_task, container):
    """Создаёт задание на размещение для тары.

    Возвращает:
      - str (номер задания)   — задача создана;
      - "already_exists"      — на эту тару уже есть активная
                                putaway-задача;
      - "empty"               — тара пуста (status выставлен free);
      - None                  — некорректный вызов (пустой container).
    """
    if not container:
        return None
    cur.execute("""
        SELECT 1 FROM task_items ti
        JOIN tasks t ON t.id=ti.task_id
        WHERE t.task_type='putaway'
          AND t.status IN ('pending','in_progress')
          AND ti.container_barcode=?
        LIMIT 1
    """, (container,))
    if cur.fetchone():
        return "already_exists"

    cur.execute("""
        SELECT COALESCE(SUM(quantity), 0)
        FROM placed_instances
        WHERE cell_or_container_barcode=?
    """, (container,))
    total_qty = cur.fetchone()[0] or 0
    if total_qty == 0:
        set_container_status(cur, container, "free")
        return "empty"

    cur.execute("SELECT COALESCE(MAX(id),0)+1 FROM tasks")
    nid = cur.fetchone()[0]
    number = f"TASK-{nid:06d}"
    now = datetime.now().isoformat()
    cur.execute("""
        INSERT INTO tasks (task_number, task_type, status,
            assignee_login, target_a, processed_a,
            target_b, processed_b, barcode, created_at,
            platform)
        VALUES (?, 'putaway', 'pending', NULL, 1, 0, ?, 0, ?, ?,
                'android')
    """, (number, total_qty, number, now))
    tid = cur.lastrowid
    cur.execute("""
        INSERT INTO task_items
            (task_id, container_barcode, quantity,
             step_no, status)
        VALUES (?, ?, ?, 1, 'pending')
    """, (tid, container, total_qty))
    origin = src_task.get("task_number", "") if src_task else ""

    if origin:
        msg = tr(
            "task.notif.putaway_created_with_origin",
            "Создано задание {number} на размещение тары "
            "{container} (после приёмки {origin})",
            number=number, container=container, origin=origin)
        payload = {
            "key": "task.notif.putaway_created_with_origin",
            "params": {"number": number, "container": container,
                       "origin": origin},
            "container": container,
            "origin_task": origin,
        }
    else:
        msg = tr(
            "task.notif.putaway_created",
            "Создано задание {number} на размещение "
            "тары {container}",
            number=number, container=container)
        payload = {
            "key": "task.notif.putaway_created",
            "params": {"number": number, "container": container},
            "container": container,
        }
    cur.execute("""
        INSERT INTO notifications
            (task_id, message, created_at, sender_login,
             type, recipient_login, read_at, payload)
        VALUES (?, ?, ?, 'system', 'system', '', '', ?)
    """, (tid, msg, now, json.dumps(payload)))
    return number