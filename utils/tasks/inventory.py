"""Обработчик заданий «Инвентаризация» (inventory)."""

import json
from datetime import datetime

from view_protocol import ViewNode
from .base import TaskHandler
from . import utils as task_utils
from i18n import tr


class InventoryHandler(TaskHandler):
    task_type = "inventory"
    title = "Инвентаризация"
    default_platform = "android"

    def build_steps(self, task, items, settings):
        steps = []
        no = 1
        pcell = settings.get("prefix_cell", "") or ""
        scell = settings.get("suffix_cell", "") or ""
        for cell_item in items:
            cell = cell_item.get("cell_barcode") or ""
            addr = cell_item.get("cell_address") or cell
            addr_short = task_utils.short_addr(addr) or addr
            steps.append({
                "no": no, "type": "scan_cell",
                "prompt_key": "task.inv.prompt_cell",
                "prompt_params": {"addr": addr_short},
                "validate": {"prefix": pcell, "suffix": scell},
                "data": {"step_id": cell_item["id"],
                         "cell_barcode": cell,
                         "cell_address": addr,
                         "expected_barcode": cell},
                "repeat": False,
            })
            no += 1
            steps.append({
                "no": no, "type": "scan_item",
                "prompt_key": "task.inv.prompt_item",
                "prompt_params": {},
                "validate": {},
                "data": {"action": "inventory_scan",
                         "cell_barcode": cell},
                "repeat": True,
            })
            no += 1
        steps.append({
            "no": no, "type": "confirm",
            "prompt_key": "task.inv.prompt_finish",
            "prompt_params": {},
            "validate": {}, "data": {"action": "finish_task"},
            "repeat": False,
        })
        return steps

    def enrich_step(self, cur, task, step, items, settings):
        if not step:
            return step
        s = dict(step)
        sd = dict(s.get("data") or {})
        if sd.get("action") == "inventory_scan":
            cell_i = sd.get("cell_barcode") or ""
            if cell_i:
                cur.execute("""
                    SELECT COUNT(*) FROM task_events
                    WHERE task_id=? AND event_type='inventory_scan'
                      AND payload=?
                """, (task["id"], json.dumps(cell_i)))
                sd["cell_scanned"] = cur.fetchone()[0] or 0
        s["data"] = sd
        return s

    def extra_buttons(self, task, step):
        if not step:
            return []
        sd = step.get("data") or {}
        if step.get("type") == "scan_item" and \
                sd.get("action") == "inventory_scan":
            return [
                ViewNode.button(
                    tr("task.inv.btn_restart", "Начать заново"),
                    action="tap", action_id="restart_cell",
                    value="ask"),
                ViewNode.button(
                    tr("task.inv.btn_finish_cell",
                       "Закончить ячейку"),
                    action="tap", action_id="confirm",
                    style="primary"),
            ]
        return []

    def handle_scan(self, cur, task, step, barcode, items, settings):
        barcode = (barcode or "").strip()
        if not barcode:
            return {"ok": False, "error": "empty barcode"}
        ok, err = self.validate_barcode(barcode, step)
        if not ok:
            return {"ok": False, "error": err}

        stype = step["type"]
        sd = step.get("data") or {}
        task_id = task["id"]

        if stype == "scan_cell":
            expected = sd.get("cell_barcode")
            if expected and barcode != expected:
                return {"ok": False,
                        "error": tr(
                            "task.inv.err_expected_cell",
                            "ожидалась ячейка {expected}",
                            expected=expected)}
            cur.execute("UPDATE tasks SET current_cell_barcode=? "
                        "WHERE id=?", (barcode, task_id))
            return {"ok": True,
                    "message": tr("task.inv.msg_cell",
                                  "Ячейка: {barcode}",
                                  barcode=barcode)}

        if stype == "scan_item" and \
                sd.get("action") == "inventory_scan":
            cell = (sd.get("cell_barcode")
                    or task.get("current_cell_barcode") or "")
            if not cell:
                return {"ok": False,
                        "error": tr("task.inv.err_no_cell",
                                    "нет ячейки")}

            cur.execute("""
                SELECT item_code FROM item_characteristics
                WHERE barcode=? OR item_code=?
                LIMIT 1
            """, (barcode, barcode))
            known = cur.fetchone()
            if not known:
                cur.execute("""
                    UPDATE tasks SET pending_action='unknown_item',
                                     pending_cell=?
                    WHERE id=?
                """, (barcode, task_id))
                return {"ok": True,
                        "message": tr(
                            "task.inv.msg_unknown",
                            "Неизвестный ШК: {barcode}",
                            barcode=barcode),
                        "stay_on_step": True}

            task_utils.add_task_event(
                cur, task_id, step["no"], "inventory_scan",
                barcode, cell)
            cur.execute("UPDATE tasks SET processed_b = "
                        "processed_b + 1 WHERE id=?", (task_id,))
            cur.execute("""
                SELECT COUNT(*) FROM task_events
                WHERE task_id=? AND event_type='inventory_scan'
                  AND payload=?
            """, (task_id, json.dumps(cell)))
            cnt = cur.fetchone()[0] or 0
            return {"ok": True,
                    "message": tr(
                        "task.inv.msg_found",
                        "Найдено: {barcode} (в ячейке {cnt})",
                        barcode=barcode, cnt=cnt),
                    "stay_on_step": True}

        return {"ok": False,
                "error": tr("task.inv.err_unknown_step",
                            "неизвестный тип шага")}

    def handle_action(self, cur, task, step, action_id, value,
                      items, settings):
        if action_id == "restart_cell":
            return self._restart_cell(cur, task, step)
        if action_id == "unknown_to_container":
            return self._unknown_to_container(cur, task)
        if action_id == "confirm":
            return self._confirm(cur, task, step)
        return {"ok": False,
                "error": tr("task.inv.err_unknown_button",
                            "неизвестная кнопка: {id}",
                            id=action_id)}

    def _unknown_to_container(self, cur, task):
        barcode = (task.get("pending_cell") or "").strip()
        if not barcode:
            return {"ok": False,
                    "error": tr(
                        "task.inv.err_unknown_not_saved",
                        "неизвестный ШК не сохранён")}
        cur.execute("""
            UPDATE tasks SET pending_action='unknown_scan_container',
                             pending_cell=?
            WHERE id=?
        """, (barcode, task["id"]))
        return {"ok": True,
                "message": tr(
                    "task.inv.msg_scan_container",
                    "Сканируйте свободную тару"),
                "stay_on_step": True}

    def _restart_cell(self, cur, task, step):
        if (step.get("data") or {}).get("action") != "inventory_scan":
            return {"ok": False,
                    "error": tr(
                        "task.inv.err_restart_unavailable",
                        "недоступно на этом шаге")}
        cell = (step.get("data") or {}).get("cell_barcode") or ""
        if not cell:
            return {"ok": False,
                    "error": tr("task.inv.err_no_cell",
                                "нет ячейки")}
        cur.execute("""
            DELETE FROM task_events
            WHERE task_id=? AND event_type='inventory_scan'
              AND payload=?
        """, (task["id"], json.dumps(cell)))
        cur.execute("""
            SELECT COUNT(*) FROM task_events
            WHERE task_id=? AND event_type='inventory_scan'
        """, (task["id"],))
        cnt = cur.fetchone()[0] or 0
        cur.execute("UPDATE tasks SET processed_b=? WHERE id=?",
                    (cnt, task["id"]))
        return {"ok": True,
                "message": tr("task.inv.msg_restart_done",
                              "Подсчёт ячейки сброшен"),
                "stay_on_step": True}

    def _load_plan(self, task):
        try:
            raw = task.get("task_plan") or ""
            if raw:
                return json.loads(raw)
        except Exception:
            pass
        return []

    def _unknown_containers_for_task(self, cur, task_id):
        cur.execute("""
            SELECT DISTINCT ti.container_barcode
            FROM task_items ti
            JOIN containers c ON c.barcode = ti.container_barcode
            WHERE ti.task_id = ? AND c.status = 'unknown_scan'
              AND (c.placed_in IS NULL OR c.placed_in = '')
        """, (task_id,))
        return [r[0] for r in cur.fetchall()]

    def _confirm(self, cur, task, step):
        if step["type"] != "confirm":
            if (step.get("data") or {}).get("action") == \
                    "inventory_scan":
                cell = (step.get("data") or {}).get(
                    "cell_barcode") or ""
                if not cell:
                    return {"ok": False,
                            "error": tr("task.inv.err_no_cell",
                                        "нет ячейки")}
                cur.execute("""
                    UPDATE tasks SET pending_action='finish_cell',
                                     pending_cell=?
                    WHERE id=?
                """, (cell, task["id"]))
                return {"ok": True,
                        "message": tr(
                            "task.inv.msg_scan_cell_confirm",
                            "Сканируйте ячейку {cell} "
                            "для подтверждения", cell=cell),
                        "stay_on_step": True}
            return {"ok": False,
                    "error": tr("task.inv.err_no_confirm",
                                "шаг не требует подтверждения")}

        act = (step.get("data") or {}).get("action")
        if act == "finish_task":
            unknown = self._unknown_containers_for_task(
                cur, task["id"])
            if unknown:
                cur.execute("""
                    UPDATE tasks SET pending_action='drop_unknown',
                                     pending_cell=?
                    WHERE id=?
                """, (", ".join(unknown), task["id"]))
                return {"ok": True,
                        "message": tr(
                            "task.inv.msg_drop_unknown",
                            "Сбросьте тары с неизвестными ШК "
                            "на точку сброса: {containers}",
                            containers=', '.join(unknown)),
                        "stay_on_step": True}
            return {"ok": True,
                    "message": tr("task.inv.msg_finish",
                                  "Завершение")}
        return {"ok": True, "message": ""}

    def handle_pending_scan(self, cur, task, pending, scanned,
                            items, settings):
        if pending == "finish_cell":
            return self._handle_finish_cell(cur, task, scanned)
        if pending == "unknown_scan_container":
            return self._handle_unknown_container(
                cur, task, scanned)
        if pending == "drop_unknown":
            return self._handle_drop_unknown(cur, task, scanned)
        return None

    def _handle_finish_cell(self, cur, task, scanned):
        expected = (task.get("pending_cell") or "").strip()
        if scanned != expected:
            return {"ok": False,
                    "error": tr(
                        "task.inv.err_expected_barcode",
                        "Ожидался ШК {expected}. Сканируйте его "
                        "или «Отменить».", expected=expected)}

        self._finalize_cell(cur, task["id"], expected)

        cur.execute("UPDATE tasks SET processed_a = "
                    "processed_a + 1 WHERE id=?", (task["id"],))
        cur.execute("""
            UPDATE tasks SET pending_action='', pending_cell=''
            WHERE id=?
        """, (task["id"],))

        plan = self._load_plan(task)
        cur_index = int(task.get("current_step_no") or 0)
        new_index = cur_index + 1
        unknown = self._unknown_containers_for_task(
            cur, task["id"])

        if new_index >= len(plan):
            if unknown:
                cur.execute("""
                    UPDATE tasks SET pending_action='drop_unknown',
                                     pending_cell=?
                    WHERE id=?
                """, (", ".join(unknown), task["id"]))
                return {"ok": True,
                        "message": tr(
                            "task.inv.msg_drop_unknown",
                            "Сбросьте тары с неизвестными ШК "
                            "на точку сброса: {containers}",
                            containers=', '.join(unknown)),
                        "stay_on_step": True}
            cur.execute("UPDATE tasks SET current_step_no=? "
                        "WHERE id=?", (new_index, task["id"]))
            return {"ok": True,
                    "message": tr("task.inv.msg_finish",
                                  "Завершение"),
                    "finished": True}

        cur.execute("UPDATE tasks SET current_step_no=? WHERE id=?",
                    (new_index, task["id"]))
        return {"ok": True,
                "message": tr("task.inv.msg_cell_closed",
                              "Ячейка закрыта"),
                "stay_on_step": True}

    def _handle_unknown_container(self, cur, task, scanned):
        unknown_barcode = (task.get("pending_cell") or "").strip()
        if not unknown_barcode:
            return {"ok": False,
                    "error": tr(
                        "task.inv.err_unknown_not_saved",
                        "неизвестный ШК не сохранён")}
        scanned = (scanned or "").strip()
        if not scanned:
            return {"ok": False, "error": "empty barcode"}

        cur.execute("SELECT status FROM containers WHERE barcode=?",
                    (scanned,))
        r = cur.fetchone()
        if not r:
            return {"ok": False,
                    "error": tr(
                        "task.inv.err_container_not_found",
                        "Тара {scanned} не найдена",
                        scanned=scanned)}
        st = r[0] or "free"

        if st not in ("free", "unknown_scan"):
            return {"ok": False,
                    "error": tr(
                        "task.inv.err_container_busy",
                        "Тара {scanned} занята ({st})",
                        scanned=scanned, st=st)}

        if st == "unknown_scan":
            cur.execute("""
                SELECT 1 FROM task_items
                WHERE task_id=? AND container_barcode=?
                  AND status='unknown'
                LIMIT 1
            """, (task["id"], scanned))
            if not cur.fetchone():
                return {"ok": False,
                        "error": tr(
                            "task.inv.err_container_used",
                            "Тара {scanned} используется "
                            "другим заданием", scanned=scanned)}
        else:
            task_utils.set_container_status(cur, scanned,
                                              "unknown_scan")

        cur.execute("""
            INSERT INTO placed_instances
                (item_code, cell_or_container_barcode, quantity)
            VALUES (?, ?, 1)
        """, (unknown_barcode, scanned))

        cur.execute("""
            INSERT INTO task_items
                (task_id, item_code, container_barcode, quantity,
                 status, step_no)
            VALUES (?, ?, ?, 1, 'unknown', 0)
        """, (task["id"], unknown_barcode, scanned))

        cur.execute("""
            UPDATE tasks SET pending_action='', pending_cell=''
            WHERE id=?
        """, (task["id"],))

        return {"ok": True,
                "message": tr(
                    "task.inv.msg_moved_to_container",
                    "Товар {barcode} -> тара {container}",
                    barcode=unknown_barcode, container=scanned),
                "stay_on_step": True}

    def _handle_drop_unknown(self, cur, task, scanned):
        scanned = (scanned or "").strip()
        if not scanned:
            return {"ok": False, "error": "empty barcode"}

        cur.execute("SELECT id, barcode, name FROM drop_points "
                    "WHERE barcode=?", (scanned,))
        dp = cur.fetchone()
        if not dp:
            return {"ok": False,
                    "error": tr(
                        "task.inv.err_drop_point_not_found",
                        "Точка сброса {scanned} не найдена",
                        scanned=scanned)}

        cur.execute("""
            SELECT DISTINCT ti.container_barcode
            FROM task_items ti
            JOIN containers c ON c.barcode = ti.container_barcode
            WHERE ti.task_id = ? AND c.status = 'unknown_scan'
              AND (c.placed_in IS NULL OR c.placed_in = '')
        """, (task["id"],))
        containers = [r[0] for r in cur.fetchall()]

        for bc in containers:
            cur.execute("""
                UPDATE containers SET placed_in=?
                WHERE barcode=?
            """, (scanned, bc))
            msg = tr(
                "task.inv.notif_unknown_dropped",
                "Тара {bc} содержит неизвестные ШК "
                "(задание {task})",
                bc=bc, task=task.get('task_number'))
            payload = {
                "key": "task.inv.notif_unknown_dropped",
                "params": {"bc": bc,
                           "task": task.get("task_number")},
                "container": bc,
                "task": task.get("task_number"),
                "drop_point": scanned,
            }
            cur.execute("""
                INSERT INTO notifications
                    (task_id, message, created_at, sender_login,
                     type, recipient_login, read_at, payload)
                VALUES (?, ?, ?, 'system', 'system', '', '', ?)
            """, (task["id"], msg, datetime.now().isoformat(),
                  json.dumps(payload)))

        cur.execute("""
            UPDATE tasks SET pending_action='', pending_cell=''
            WHERE id=?
        """, (task["id"],))

        plan = self._load_plan(task)
        cur_index = int(task.get("current_step_no") or 0)

        if cur_index >= len(plan) - 1:
            cur.execute("UPDATE tasks SET current_step_no=? "
                        "WHERE id=?", (len(plan), task["id"]))
            return {"ok": True,
                    "message": tr(
                        "task.inv.msg_dropped_finished",
                        "Тары сброшены на {scanned}. "
                        "Задание завершено.", scanned=scanned),
                    "finished": True}

        return {"ok": True,
                "message": tr("task.inv.msg_dropped",
                              "Тары сброшены на {scanned}.",
                              scanned=scanned),
                "stay_on_step": True}

    def _finalize_cell(self, cur, task_id, cell):
        cur.execute("""
            SELECT barcode FROM task_events
            WHERE task_id=? AND event_type='inventory_scan'
              AND payload=?
        """, (task_id, json.dumps(cell)))
        scanned = {}
        for r in cur.fetchall():
            code = r[0]
            scanned[code] = scanned.get(code, 0) + 1

        cur.execute("SELECT item_code, barcode "
                    "FROM item_characteristics")
        barcode_to_item = {r[1]: r[0] for r in cur.fetchall()}
        scanned_by_item = {}
        for bc, qty in scanned.items():
            code = barcode_to_item.get(bc, bc)
            scanned_by_item[code] = \
                scanned_by_item.get(code, 0) + qty

        cur.execute("""
            SELECT item_code, COALESCE(quantity, 0) AS quantity
            FROM placed_instances WHERE cell_barcode=?
        """, (cell,))
        before = {r[0]: r[1] for r in cur.fetchall()}

        all_codes = set(list(before.keys()) +
                        list(scanned_by_item.keys()))
        for code in all_codes:
            b = before.get(code, 0)
            a = scanned_by_item.get(code, 0)
            if b != a:
                cur.execute("""
                    INSERT INTO inventory_reports
                        (task_id, cell_barcode, item_code,
                         qty_before, qty_after, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (task_id, cell, code, b, a,
                      datetime.now().isoformat()))

        for code, qty in scanned_by_item.items():
            cur.execute("""
                SELECT id FROM placed_instances
                WHERE cell_barcode=? AND item_code=?
            """, (cell, code))
            r = cur.fetchone()
            if r:
                cur.execute("UPDATE placed_instances "
                            "SET quantity=? WHERE id=?",
                            (qty, r[0]))
            elif qty > 0:
                cur.execute("""
                    INSERT INTO placed_instances
                        (item_code, cell_barcode, quantity)
                    VALUES (?, ?, ?)
                """, (code, cell, qty))
        cur.execute("""
            DELETE FROM placed_instances
            WHERE cell_barcode=? AND quantity=0
        """, (cell,))

    def on_finalize(self, cur, task, items, settings):
        cur.execute("""
            SELECT DISTINCT ti.container_barcode
            FROM task_items ti
            JOIN containers c ON c.barcode = ti.container_barcode
            WHERE ti.task_id = ? AND c.status = 'unknown_scan'
              AND (c.placed_in IS NULL OR c.placed_in = '')
        """, (task["id"],))
        for row in cur.fetchall():
            bc = row[0]
            msg = tr(
                "task.inv.notif_unknown_left",
                "Тара {bc} содержит неизвестные ШК "
                "(задание {task})",
                bc=bc, task=task.get('task_number'))
            payload = {
                "key": "task.inv.notif_unknown_left",
                "params": {"bc": bc,
                           "task": task.get("task_number")},
                "container": bc,
                "task": task.get("task_number"),
            }
            cur.execute("""
                INSERT INTO notifications
                    (task_id, message, created_at, sender_login,
                     type, recipient_login, read_at, payload)
                VALUES (?, ?, ?, 'system', 'system', '', '', ?)
            """, (task["id"], msg, datetime.now().isoformat(),
                  json.dumps(payload)))