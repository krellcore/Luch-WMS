"""Обработчик заданий «Подбор» (pick)."""

import json

from view_protocol import ViewNode
from .base import TaskHandler
from . import utils as task_utils
from db import reserve, RESERVE_DEFAULT_MINUTES
from i18n import tr


class PickHandler(TaskHandler):
    task_type = "pick"
    title = "Подбор"
    default_platform = "android"

    def build_steps(self, task, items, settings):
        steps = []
        no = 1
        pc = settings.get("prefix_container", "") or ""
        sc = settings.get("suffix_container", "") or ""

        steps.append({
            "no": no, "type": "scan_container",
            "prompt_key": "task.pick.prompt_container",
            "prompt_params": {},
            "validate": {"prefix": pc, "suffix": sc},
            "data": {"hint": "Любая свободная тара"},
            "repeat": False,
        })
        no += 1

        pcell = settings.get("prefix_cell", "") or ""
        scell = settings.get("suffix_cell", "") or ""

        grouped = []
        index = {}
        for it in items:
            cell = it.get("cell_barcode") or ""
            if cell not in index:
                index[cell] = len(grouped)
                grouped.append((cell, []))
            grouped[index[cell]][1].append(it)

        for cell, cell_items in grouped:
            addr = cell_items[0].get("cell_address") or cell
            addr_short = task_utils.short_addr(addr) or addr
            steps.append({
                "no": no, "type": "scan_cell",
                "prompt_key": "task.pick.prompt_cell",
                "prompt_params": {"addr": addr_short},
                "validate": {"prefix": pcell, "suffix": scell},
                "data": {"cell_barcode": cell,
                         "cell_address": addr,
                         "expected_barcode": cell},
                "repeat": False,
            })
            no += 1
            for it in cell_items:
                name = it.get("item_name") or it.get("item_code") or ""
                qty = it.get("quantity") or 0
                bc = it.get("item_barcode") or ""
                steps.append({
                    "no": no, "type": "scan_item",
                    "prompt_key": "task.pick.prompt_item",
                    "prompt_params": {"name": name, "qty": qty},
                    "validate": {},
                    "data": {
                        "step_id": it["id"],
                        "item_code": it.get("item_code"),
                        "item_barcode": bc,
                        "item_name": name,
                        "quantity": qty,
                        "cell_barcode": cell,
                        "cell_address": addr,
                        "expected_barcode": bc,
                    },
                    "repeat": False,
                })
                no += 1

        return steps

    def enrich_step(self, cur, task, step, items, settings):
        if not step:
            return step
        s = dict(step)
        s_data = dict(s.get("data") or {})

        if s.get("type") == "scan_item":
            step_id = s_data.get("step_id")
            if step_id:
                cur.execute(
                    "SELECT COALESCE(scanned_qty,0), "
                    "COALESCE(quantity,0) FROM task_items WHERE id=?",
                    (step_id,))
                r = cur.fetchone()
                if r:
                    s_data["scanned_qty"] = r[0]
                    s_data["quantity_total"] = r[1]
                photo = task_utils.photo_b64(
                    cur, s_data.get("item_code"))
                if photo:
                    s_data["photo_b64"] = photo
            cell = s_data.get("cell_barcode")
            if cell:
                cur.execute("""
                    SELECT COALESCE(SUM(COALESCE(scanned_qty,0)),0),
                           COALESCE(SUM(quantity),0)
                    FROM task_items
                    WHERE task_id=? AND cell_barcode=?
                """, (task["id"], cell))
                r = cur.fetchone()
                if r:
                    s_data["cell_scanned"] = r[0] or 0
                    s_data["cell_total"] = r[1] or 0

        s["data"] = s_data
        return s

    def enrich_task(self, cur, task, items, settings):
        cur.execute("""
            SELECT DISTINCT te.barcode, c.status, c.placed_in
            FROM task_events te
            JOIN containers c ON c.barcode = te.barcode
            WHERE te.task_id = ? AND te.event_type='close_container'
        """, (task["id"],))
        containers = []
        closed_count = 0
        for row in cur.fetchall():
            st = row[1] or ""
            placed_in = row[2] or ""
            containers.append({
                "barcode": row[0],
                "status": st,
                "placed_in": placed_in,
            })
            if st == "closed" and not placed_in:
                closed_count += 1
        task["drop_containers"] = containers
        task["closed_containers_count"] = closed_count

        container_bc = (task.get("container_barcode") or "").strip()
        container_closed = False
        if container_bc:
            cur.execute("SELECT status FROM containers "
                        "WHERE barcode=?", (container_bc,))
            r = cur.fetchone()
            if r and r[0] == "closed":
                container_closed = True
        task["container_closed"] = container_closed

        pending = (task.get("pending_action") or "").strip()
        try:
            ok, _ = self.can_cancel_pending(cur, task, pending)
        except Exception:
            ok = True
        task["can_cancel_pending"] = ok

        return task

    def extra_buttons(self, task, step):
        if not step:
            return []
        out = []
        stype = step.get("type")
        if stype == "scan_item":
            out.append(ViewNode.button(
                tr("task.btn.not_found", "Товар не найден"),
                action="tap", action_id="item_not_found"))

        container = (task.get("container_barcode") or "").strip()
        container_closed = bool(task.get("container_closed"))
        if container and not container_closed:
            out.append(ViewNode.button(
                tr("task.btn.close_container", "Закрыть тару"),
                action="tap", action_id="close_container_pick",
                style="danger"))

        n_closed = int(task.get("closed_containers_count") or 0)
        if n_closed > 0:
            out.append(ViewNode.button(
                tr("task.btn.drop_containers",
                   "Сбросить тары ({n})", n=n_closed),
                action="tap", action_id="drop_containers"))
        return out

    def can_cancel_pending(self, cur, task, pending):
        pending = (pending or "").strip()

        if pending == "scan_new_container":
            return False, tr(
                "task.pick.err_cant_cancel_new",
                "Тара уже закрыта. Сканируйте новую тару, "
                "чтобы продолжить.")

        if pending == "scan_close_container":
            cur.execute("""
                SELECT COUNT(*) FROM task_items
                WHERE task_id=? AND status NOT IN ('done','not_found')
            """, (task["id"],))
            left = cur.fetchone()[0] or 0
            if left == 0:
                return False, tr(
                    "task.pick.err_cant_cancel",
                    "Все позиции подобраны. Сканируйте ШК тары, "
                    "чтобы закрыть её.")
            return True, None

        if pending == "drop_containers":
            if (task.get("drop_status") or "") == "finish_after":
                return False, tr(
                    "task.pick.err_cant_cancel_drop",
                    "Сброс тар обязателен для завершения. "
                    "Сканируйте точку сброса.")

        return True, None

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

        if stype == "scan_container":
            cur.execute("SELECT status FROM containers "
                        "WHERE barcode=?", (barcode,))
            r = cur.fetchone()
            cur_status = (r[0] if r and r[0] else "free")
            if cur_status != "free":
                return {"ok": False,
                        "error": tr(
                            "task.pick.err_container_busy",
                            "Тара {barcode} занята (статус: {status})",
                            barcode=barcode, status=cur_status)}
            task_utils.set_container_status(cur, barcode, "picking")
            cur.execute("UPDATE tasks SET container_barcode=? "
                        "WHERE id=?", (barcode, task_id))
            return {"ok": True,
                    "message": tr(
                        "task.pick.msg_container",
                        "Тара: {barcode} (подбор)",
                        barcode=barcode)}

        if stype == "scan_cell":
            expected = sd.get("cell_barcode")
            if expected and barcode != expected:
                return {"ok": False,
                        "error": tr(
                            "task.pick.err_expected_cell",
                            "ожидалась ячейка {expected}",
                            expected=expected)}
            cur.execute(
                "UPDATE tasks SET current_cell_barcode=? WHERE id=?",
                (barcode, task_id))
            return {"ok": True,
                    "message": tr("task.pick.msg_cell",
                                  "Ячейка: {barcode}",
                                  barcode=barcode)}

        if stype == "scan_item":
            expected = sd.get("item_barcode") or ""
            if expected and barcode != expected:
                return {"ok": False,
                        "error": tr(
                            "task.pick.err_wrong_barcode",
                            "Это не ШК «{expected}»",
                            expected=expected)}
            step_id = sd["step_id"]
            quantity = int(sd.get("quantity") or 1)
            cell_bc = sd.get("cell_barcode") or ""
            item_code = sd.get("item_code") or ""
            container_bc = task.get("container_barcode") or ""

            if not container_bc:
                return {"ok": False,
                        "error": tr(
                            "task.pick.err_no_container",
                            "Сначала отсканируйте тару")}

            cur.execute("SELECT status FROM containers "
                        "WHERE barcode=?", (container_bc,))
            r = cur.fetchone()
            if not r or r[0] != "picking":
                return {"ok": False,
                        "error": tr(
                            "task.pick.err_bad_status",
                            "Тара {container} не в статусе подбора",
                            container=container_bc)}

            cur.execute("SELECT COALESCE(scanned_qty,0) "
                        "FROM task_items WHERE id=?", (step_id,))
            row = cur.fetchone()
            current = row[0] if row else 0
            new_scanned = current + 1
            done = new_scanned >= quantity

            moved = task_utils.move_one(cur, item_code, cell_bc,
                                        container_bc)
            if not moved:
                return {
                    "ok": False,
                    "error": tr(
                        "task.pick.err_no_stock",
                        "В ячейке {cell} больше нет товара {item}. "
                        "Нажмите «Товар не найден».",
                        cell=cell_bc, item=item_code),
                }

            cur.execute("""
                SELECT id, qty FROM reservations
                WHERE task_id=? AND item_code=?
                  AND cell_barcode=?
                ORDER BY id LIMIT 1
            """, (task_id, item_code, cell_bc))
            rr = cur.fetchone()
            if rr:
                left = int(rr[1] or 0) - 1
                if left > 0:
                    cur.execute(
                        "UPDATE reservations SET qty=? WHERE id=?",
                        (left, rr[0]))
                else:
                    cur.execute(
                        "DELETE FROM reservations WHERE id=?",
                        (rr[0],))

            cur.execute("""
                UPDATE task_items
                SET scanned_qty=?, scanned_item_barcode=?,
                    status=?, processed=?
                WHERE id=?
            """, (new_scanned, barcode,
                  'done' if done else 'pending',
                  1 if done else 0,
                  step_id))

            cur.execute("UPDATE tasks SET processed_a = "
                        "processed_a + 1 WHERE id=?", (task_id,))

            try:
                from plugin_hooks import registry as hook_registry
                hook_registry.call_event(
                    "on_pick", task=task, item_code=item_code,
                    cell=cell_bc, container=container_bc)
            except Exception:
                pass

            msg = tr("task.pick.msg_item",
                     "Товар: {barcode} ({scanned}/{qty})",
                     barcode=barcode, scanned=new_scanned,
                     qty=quantity)

            if done and self._all_items_done(cur, task_id):
                return self._after_last_item(
                    cur, task, base_message=msg)

            return {"ok": True, "message": msg,
                    "stay_on_step": not done}

        return {"ok": False,
                "error": tr("task.err_unknown_step",
                            "Неизвестный тип шага")}

    def _all_items_done(self, cur, task_id):
        cur.execute("""
            SELECT COUNT(*) FROM task_items
            WHERE task_id=? AND status NOT IN ('done','not_found')
        """, (task_id,))
        return (cur.fetchone()[0] or 0) == 0

    def _has_unsent_closed(self, cur, task_id):
        cur.execute("""
            SELECT DISTINCT te.barcode
            FROM task_events te
            JOIN containers c ON c.barcode = te.barcode
            WHERE te.task_id = ? AND te.event_type='close_container'
              AND c.status = 'closed'
              AND (c.placed_in IS NULL OR c.placed_in = '')
        """, (task_id,))
        return [r[0] for r in cur.fetchall()]

    def _after_last_item(self, cur, task, base_message=""):
        container = (task.get("container_barcode") or "").strip()
        if container:
            cur.execute("SELECT status FROM containers "
                        "WHERE barcode=?", (container,))
            r = cur.fetchone()
            if r and r[0] == "picking":
                cur.execute("""
                    UPDATE tasks SET
                        pending_action='scan_close_container',
                        pending_cell=?
                    WHERE id=?
                """, (container, task["id"]))
                msg = base_message + ("\n" if base_message else "")
                msg += tr("task.pick.msg_close",
                          "Сканируйте ШК тары {container}, "
                          "чтобы закрыть её", container=container)
                return {"ok": True, "message": msg,
                        "stay_on_step": True}

        closed = self._has_unsent_closed(cur, task["id"])
        if closed:
            cur.execute("""
                UPDATE tasks SET pending_action='drop_containers',
                                 drop_pending='scan_point',
                                 drop_point_barcode='',
                                 drop_status='finish_after'
                WHERE id=?
            """, (task["id"],))
            msg = base_message + ("\n" if base_message else "")
            msg += tr("task.pick.msg_drop",
                      "Сбросьте тары на точку сброса: {closed}",
                      closed=', '.join(closed))
            return {"ok": True, "message": msg,
                    "stay_on_step": True}

        msg = base_message or tr("task.pick.msg_finished",
                                 "Задание завершено")
        return {"ok": True, "message": msg, "finished": True}

    def handle_action(self, cur, task, step, action_id, value,
                      items, settings):
        if action_id == "item_not_found":
            return self._item_not_found(cur, task, step)
        if action_id == "close_container_pick":
            return self._request_close_container(cur, task)
        if action_id == "drop_containers":
            return self._drop_start(cur, task)
        if action_id == "container_contents":
            return {"ok": True,
                    "view_override": "container_contents"}
        if action_id == "back_to_step":
            return {"ok": True, "stay_on_step": True}
        return {"ok": False,
                "error": tr("task.err_unknown_button",
                            "Неизвестная кнопка: {id}",
                            id=action_id)}

    def _item_not_found(self, cur, task, step):
        if step["type"] != "scan_item":
            return {"ok": False,
                    "error": tr("task.pick.err_not_scan_item",
                                "Не на шаге scan_item")}
        cell = (step.get("data") or {}).get("cell_barcode") or ""
        if not cell:
            return {"ok": False,
                    "error": tr("task.pick.err_no_cell",
                                "В шаге нет ячейки")}
        cur.execute("""
            UPDATE tasks SET pending_action='not_found',
                             pending_cell=?
            WHERE id=?
        """, (cell, task["id"]))
        return {"ok": True,
                "message": tr("task.pick.msg_scan_cell",
                              "Сканируйте ячейку {cell} "
                              "для подтверждения", cell=cell),
                "stay_on_step": True}

    def _request_close_container(self, cur, task):
        container = (task.get("container_barcode") or "").strip()
        if not container:
            return {"ok": False,
                    "error": tr(
                        "task.pick.err_no_active_container",
                        "Нет активной тары")}
        cur.execute("""
            UPDATE tasks SET pending_action='scan_close_container',
                             pending_cell=?
            WHERE id=?
        """, (container, task["id"]))
        return {"ok": True,
                "message": tr("task.pick.msg_close",
                              "Сканируйте ШК тары {container}, "
                              "чтобы закрыть её",
                              container=container),
                "stay_on_step": True}

    def _apply_close_container(self, cur, task, scanned):
        container = (task.get("container_barcode") or "").strip()
        if not container:
            return {"ok": False,
                    "error": tr(
                        "task.pick.err_no_active_container",
                        "Нет активной тары")}
        if scanned != container:
            return {"ok": False,
                    "error": tr(
                        "task.pick.err_expected_container",
                        "Ожидался ШК тары {container}",
                        container=container)}

        task_utils.set_container_status(cur, container, "closed")
        task_utils.add_task_event(
            cur, task["id"], 0, "close_container", container)
        cur.execute("""
            UPDATE tasks SET container_barcode='',
                             pending_action='', pending_cell=''
            WHERE id=?
        """, (task["id"],))

        if self._all_items_done(cur, task["id"]):
            task2 = dict(task)
            task2["container_barcode"] = ""
            return self._after_last_item(
                cur, task2,
                base_message=tr(
                    "task.pick.msg_closed",
                    "Тара {container} закрыта.",
                    container=container))

        cur.execute("""
            UPDATE tasks SET pending_action='scan_new_container',
                             pending_cell='any_container'
            WHERE id=?
        """, (task["id"],))
        return {"ok": True,
                "message": tr("task.pick.msg_need_new_container",
                              "Тара закрыта. Сканируйте ШК "
                              "новой тары"),
                "stay_on_step": True}

    def _scan_new_container(self, cur, task, scanned):
        if not scanned:
            return {"ok": False, "error": "empty barcode"}
        cur.execute("SELECT status FROM containers "
                    "WHERE barcode=?", (scanned,))
        r = cur.fetchone()
        if not r or (r[0] or "free") != "free":
            return {"ok": False,
                    "error": tr(
                        "task.pick.err_container_not_free",
                        "Тара {barcode} не свободна или не найдена",
                        barcode=scanned)}
        task_utils.set_container_status(cur, scanned, "picking")
        cur.execute("""
            UPDATE tasks SET container_barcode=?,
                             pending_action='', pending_cell=''
            WHERE id=?
        """, (scanned, task["id"]))

        if self._all_items_done(cur, task["id"]):
            task2 = dict(task)
            task2["container_barcode"] = scanned
            return self._after_last_item(
                cur, task2,
                base_message=tr(
                    "task.pick.msg_new_container",
                    "Новая тара: {barcode}", barcode=scanned))

        return {"ok": True,
                "message": tr("task.pick.msg_new_container",
                              "Новая тара: {barcode}",
                              barcode=scanned),
                "stay_on_step": True}

    def _drop_start(self, cur, task):
        closed = self._has_unsent_closed(cur, task["id"])
        if not closed:
            return {"ok": False,
                    "error": tr("task.pick.err_no_closed",
                                "Нет закрытых тар для сброса")}
        cur.execute("""
            UPDATE tasks SET pending_action='drop_containers',
                             drop_pending='scan_point',
                             drop_point_barcode='',
                             drop_status='manual'
            WHERE id=?
        """, (task["id"],))
        return {"ok": True,
                "message": tr("task.pick.msg_scan_drop_point",
                              "Сканируйте точку сброса"),
                "stay_on_step": True}

    def _drop_scan(self, cur, task, scanned):
        if not scanned:
            return {"ok": False, "error": "empty barcode"}
        drop_pending = (task.get("drop_pending")
                        or "scan_point").strip()

        if drop_pending == "scan_point":
            cur.execute("SELECT id, barcode, name FROM drop_points "
                        "WHERE barcode=?", (scanned,))
            dp = cur.fetchone()
            if not dp:
                return {"ok": False,
                        "error": tr(
                            "task.pick.err_bad_drop_point",
                            "Точка сброса {barcode} не найдена",
                            barcode=scanned)}
            cur.execute("""
                UPDATE tasks SET drop_point_barcode=?,
                                 drop_pending='scan_containers'
                WHERE id=?
            """, (scanned, task["id"]))
            return {"ok": True,
                    "message": tr(
                        "task.pick.msg_drop_point",
                        "Точка сброса: {barcode}. Сканируйте тары.",
                        barcode=scanned),
                    "stay_on_step": True}

        point = (task.get("drop_point_barcode") or "").strip()
        if not point:
            return {"ok": False,
                    "error": tr("task.pick.err_no_drop_point",
                                "Не указана точка сброса")}

        cur.execute("""
            SELECT 1 FROM task_events te
            JOIN containers c ON c.barcode = te.barcode
            WHERE te.task_id = ? AND te.event_type='close_container'
              AND te.barcode = ?
              AND c.status = 'closed'
              AND (c.placed_in IS NULL OR c.placed_in = '')
            LIMIT 1
        """, (task["id"], scanned))
        if not cur.fetchone():
            return {"ok": False,
                    "error": tr(
                        "task.pick.err_not_from_task",
                        "Тара {barcode} не из этого задания "
                        "или уже сброшена", barcode=scanned)}

        cur.execute("""
            UPDATE containers SET placed_in=?
            WHERE barcode=?
        """, (point, scanned))

        left = self._has_unsent_closed(cur, task["id"])
        if not left:
            finish_after = (task.get("drop_status")
                            or "") == 'finish_after'
            cur.execute("""
                UPDATE tasks SET pending_action='',
                                 drop_pending='',
                                 drop_point_barcode='',
                                 drop_status=''
                WHERE id=?
            """, (task["id"],))
            if finish_after:
                return {"ok": True,
                        "message": tr(
                            "task.pick.msg_finish_drop",
                            "Все тары сброшены. Задание завершено."),
                        "finished": True}
            return {"ok": True,
                    "message": tr(
                        "task.pick.msg_all_dropped",
                        "Все тары сброшены. Продолжайте."),
                    "stay_on_step": True}

        return {"ok": True,
                "message": tr(
                    "task.pick.msg_dropped",
                    "Тара {barcode} сброшена на {point}. "
                    "Осталось: {left}.",
                    barcode=scanned, point=point,
                    left=len(left)),
                "stay_on_step": True}

    def handle_pending_scan(self, cur, task, pending, scanned,
                            items, settings):
        if pending == "not_found":
            return self._not_found_apply(cur, task, scanned,
                                           items, settings)
        if pending == "scan_close_container":
            return self._apply_close_container(cur, task, scanned)
        if pending == "scan_new_container":
            return self._scan_new_container(cur, task, scanned)
        if pending == "drop_containers":
            return self._drop_scan(cur, task, scanned)
        return None

    def _not_found_apply(self, cur, task, scanned, items, settings):
        from .utils import (
            find_items_in_bf, find_items_anywhere,
            create_followup_task,
        )

        plan = self._load_plan(task)
        cur_index = int(task.get("current_step_no") or 0)
        step = plan[cur_index] if 0 <= cur_index < len(plan) else None
        if not step:
            return {"ok": False,
                    "error": tr("task.pick.err_no_step",
                                "Нет шага")}

        sd = step.get("data") or {}
        step_id = sd.get("step_id")
        item_code = sd.get("item_code")
        item_name = sd.get("item_name") or item_code or ""
        item_barcode = sd.get("item_barcode") or ""
        total_qty = int(sd.get("quantity") or 1)
        expected_cell = sd.get("cell_barcode") or ""
        expected_addr = sd.get("cell_address") or ""

        if scanned != expected_cell:
            return {"ok": False,
                    "error": tr(
                        "task.pick.err_not_found_cell",
                        "Ожидался ШК {cell}. Сканируйте его "
                        "или «Отменить».", cell=expected_cell)}

        if not item_code:
            return {"ok": False,
                    "error": tr("task.pick.err_no_item_code",
                                "В шаге нет item_code")}

        scanned_qty = 0
        if step_id:
            cur.execute(
                "SELECT COALESCE(scanned_qty, 0) FROM task_items "
                "WHERE id=?", (step_id,))
            r = cur.fetchone()
            if r:
                scanned_qty = int(r[0] or 0)

        need_qty = max(0, total_qty - scanned_qty)

        cur.execute("""
            UPDATE tasks SET pending_action='', pending_cell=''
            WHERE id=?
        """, (task["id"],))

        if need_qty <= 0:
            return {"ok": True,
                    "message": tr(
                        "task.pick.msg_all_scanned",
                        "Все единицы уже отсканированы")}

        pcell = settings.get("prefix_cell", "") or ""
        scell = settings.get("suffix_cell", "") or ""

        cur.execute("""
            DELETE FROM placed_instances
            WHERE item_code=? AND cell_barcode=?
        """, (item_code, expected_cell))

        if step_id:
            cur.execute("""
                DELETE FROM reservations
                WHERE task_id=? AND item_code=?
                  AND cell_barcode=?
            """, (task["id"], item_code, expected_cell))

        task_utils.add_task_event(
            cur, task["id"], step["no"], "item_not_found",
            item_code,
            {"cell": expected_cell,
             "missing_qty": need_qty,
             "scanned_qty": scanned_qty,
             "total_qty": total_qty})

        if step_id:
            cur.execute("UPDATE task_items SET status='not_found' "
                        "WHERE id=?", (step_id,))

        # FIX: раньше bf_prefix вычислялся как expected_cell[:2]
        # (первые два символа ШК ячейки). Если у склада задан
        # prefix_cell (например «C-»), ШК начинается с префикса,
        # а не с номера блока-этажа. Тогда поиск «в том же блоке»
        # ничего не находил, товар в 11-01-03-A1 не находился
        # как «найденный рядом», и вместо добавления второй
        # ячейки в маршрут создавалось новое задание.
        # Теперь берём bf из адреса (он в step.data.cell_address),
        # а если адреса нет — достаём через lookup cells.
        bf_prefix = ""
        if expected_addr:
            bf_prefix = expected_addr.split("-", 1)[0]
        elif expected_cell:
            cur.execute("SELECT address FROM cells WHERE barcode=?",
                        (expected_cell,))
            _row = cur.fetchone()
            if _row and _row[0]:
                bf_prefix = _row[0].split("-", 1)[0]

        alt_same_bf = find_items_in_bf(
            cur, item_code, bf_prefix,
            exclude_cell=expected_cell, limit=need_qty)
        found_in_bf = sum(x["qty"] for x in alt_same_bf)
        remaining = need_qty - found_in_bf

        alt_other = []
        if remaining > 0:
            alt_other = find_items_anywhere(
                cur, item_code,
                exclude_cells=[expected_cell] +
                              [x["cell_barcode"] for x in alt_same_bf],
                limit=remaining)
        found_other = sum(x["qty"] for x in alt_other)

        result = {"result": "relocated", "message": "",
                  "new_cell": "", "new_task_number": ""}

        new_steps = []
        for alt in alt_same_bf:
            cell_bc = alt["cell_barcode"]
            qty = alt["qty"]
            cur.execute("SELECT address FROM cells WHERE barcode=?",
                        (cell_bc,))
            r = cur.fetchone()
            addr = r[0] if r else cell_bc
            addr_short = task_utils.short_addr(addr)

            cur.execute("""
                INSERT INTO task_items
                    (task_id, item_code, cell_barcode, quantity,
                     step_no, status)
                VALUES (?, ?, ?, ?, ?, 'pending')
            """, (task["id"], item_code, cell_bc, qty, step["no"]))
            new_item_id = cur.lastrowid

            reserve(cur, task["id"], item_code, cell_bc, qty,
                    minutes=RESERVE_DEFAULT_MINUTES)

            new_steps.append({
                "no": 0, "type": "scan_cell",
                "prompt_key": "task.pick.prompt_cell",
                "prompt_params": {"addr": addr_short},
                "validate": {"prefix": pcell, "suffix": scell},
                "data": {"cell_barcode": cell_bc,
                         "cell_address": addr,
                         "expected_barcode": cell_bc},
                "repeat": False,
            })
            new_steps.append({
                "no": 0, "type": "scan_item",
                "prompt_key": "task.pick.prompt_item",
                "prompt_params": {"name": item_name, "qty": qty},
                "validate": {},
                "data": {
                    "step_id": new_item_id,
                    "item_code": item_code,
                    "item_barcode": item_barcode,
                    "item_name": item_name,
                    "quantity": qty,
                    "cell_barcode": cell_bc,
                    "cell_address": addr,
                    "expected_barcode": item_barcode,
                },
                "repeat": False,
            })
        if alt_same_bf:
            result["new_cell"] = alt_same_bf[0]["cell_barcode"]

        if new_steps:
            new_plan = plan[:cur_index] + new_steps + \
                plan[cur_index + 1:]
        else:
            new_plan = plan[:cur_index] + plan[cur_index + 1:]
        for i, s in enumerate(new_plan):
            s["no"] = i + 1

        cur.execute("UPDATE tasks SET task_plan=? WHERE id=?",
                    (json.dumps(new_plan, ensure_ascii=False),
                     task["id"]))
        cur.execute("UPDATE tasks SET current_step_no=? WHERE id=?",
                    (cur_index, task["id"]))

        followup_qty = 0
        if not alt_same_bf and alt_other:
            followup_qty = need_qty
        elif alt_same_bf and remaining > 0 and alt_other:
            followup_qty = remaining

        if followup_qty > 0:
            new_num = create_followup_task(
                cur, task, item_code, followup_qty, item_barcode,
                assign_to=None)
            if new_num:
                result["result"] = "split"
                if alt_same_bf:
                    result["message"] = tr(
                        "task.pick.not_found_split",
                        "В блоке найдено {found} шт. "
                        "Остаток {remaining} шт оформлен "
                        "заданием {task}",
                        found=found_in_bf,
                        remaining=followup_qty, task=new_num)
                else:
                    result["message"] = tr(
                        "task.pick.not_found_split_other",
                        "В блоке нет. Найдено вне блока {found} шт, "
                        "создано задание {task}",
                        found=found_other, task=new_num)
                result["new_task_number"] = new_num
        elif alt_same_bf and remaining > 0:
            result["result"] = "relocated"
            result["message"] = tr(
                "task.pick.not_found_relocated_partial",
                "В блоке найдено {found} шт, но {remaining} шт "
                "нигде нет. Уведомление отправлено.",
                found=found_in_bf, remaining=remaining)
        elif alt_same_bf and remaining == 0:
            result["result"] = "relocated"
            result["message"] = tr(
                "task.pick.not_found_relocated",
                "Товар найден в блоке. Маршрут обновлён "
                "({qty} шт)", qty=found_in_bf)
        else:
            result["result"] = "lost"
            result["message"] = tr(
                "task.pick.not_found_lost",
                "Товар не найден нигде. Не хватает {qty} шт. "
                "Уведомление отправлено.", qty=need_qty)

        if not new_steps and cur_index >= len(new_plan):
            res = self._after_last_item(
                cur, task,
                base_message=result.get("message", ""))
        else:
            res = {"ok": True, "message": "",
                   "stay_on_step": True}

        res["not_found_result"] = result
        return res

    def _load_plan(self, task):
        try:
            raw = task.get("task_plan") or ""
            if raw:
                return json.loads(raw)
        except Exception:
            pass
        return []

    def on_finalize(self, cur, task, items, settings):
        container = (task.get("container_barcode") or "").strip()
        if not container:
            return
        cur.execute("""
            SELECT COALESCE(SUM(quantity), 0)
            FROM placed_instances
            WHERE cell_or_container_barcode=?
        """, (container,))
        qty = cur.fetchone()[0] or 0
        if qty > 0:
            task_utils.set_container_status(cur, container, "waiting")
        else:
            task_utils.set_container_status(cur, container, "free")