"""Обработчик заданий «Размещение» (putaway)."""

from view_protocol import ViewNode
from .base import TaskHandler
from . import utils as task_utils
from i18n import tr


class PutawayHandler(TaskHandler):
    task_type = "putaway"
    title = "Размещение"
    default_platform = "android"

    def build_steps(self, task, items, settings):
        steps = []
        no = 1
        pc = settings.get("prefix_container", "") or ""
        sc = settings.get("suffix_container", "") or ""
        allowed = [it.get("container_barcode") for it in items
                   if it.get("container_barcode")]

        steps.append({
            "no": no, "type": "scan_container",
            "prompt_key": "task.put.prompt_containers",
            "prompt_params": {"len": len(allowed)},
            "validate": {"prefix": pc, "suffix": sc},
            "data": {"allowed_containers": allowed,
                     "phase": "collect"},
            "repeat": False,
        })
        no += 1

        steps.append({
            "no": no, "type": "confirm",
            "prompt_key": "task.put.prompt_start",
            "prompt_params": {},
            "validate": {}, "data": {"action": "start_putaway"},
            "repeat": False,
        })
        no += 1

        steps.append({
            "no": no, "type": "scan_container",
            "prompt_key": "task.put.prompt_place",
            "prompt_params": {},
            "validate": {"prefix": pc, "suffix": sc},
            "data": {"allowed_containers": allowed,
                     "phase": "place"},
            "repeat": False,
        })
        no += 1

        pcell = settings.get("prefix_cell", "") or ""
        scell = settings.get("suffix_cell", "") or ""
        steps.append({
            "no": no, "type": "scan_cell",
            "prompt_key": "task.put.prompt_cell",
            "prompt_params": {},
            "validate": {"prefix": pcell, "suffix": scell},
            "data": {"any_cell": True, "putaway": True},
            "repeat": False,
        })
        no += 1

        steps.append({
            "no": no, "type": "scan_item",
            "prompt_key": "task.put.prompt_item",
            "prompt_params": {},
            "validate": {},
            "data": {"action": "putaway_scan"},
            "repeat": True,
        })
        no += 1

        steps.append({
            "no": no, "type": "confirm",
            "prompt_key": "task.put.prompt_finish_container",
            "prompt_params": {},
            "validate": {}, "data": {"action": "finish_container"},
            "repeat": False,
        })
        no += 1

        steps.append({
            "no": no, "type": "confirm",
            "prompt_key": "task.put.prompt_finish_task",
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

        if s.get("type") == "scan_container":
            phase = sd.get("phase") or ""
            if phase in ("collect", "place"):
                cur.execute("""
                    SELECT container_barcode, status
                    FROM task_items
                    WHERE task_id=? AND container_barcode IS NOT NULL
                    ORDER BY step_no, id
                """, (task["id"],))
                containers = []
                for row in cur.fetchall():
                    containers.append({
                        "barcode": row[0],
                        "status": row[1] or "pending",
                    })
                sd["containers"] = containers

        if sd.get("action") == "putaway_scan":
            sd["container_total"] = task.get("target_b") or 0
            sd["container_placed"] = task.get("processed_b") or 0

        s["data"] = sd
        return s

    def extra_buttons(self, task, step):
        if not step:
            return []
        out = []
        sd = step.get("data") or {}
        if step.get("type") == "scan_item" and \
                sd.get("action") == "putaway_scan":
            out.append(ViewNode.button(
                tr("task.put.btn_contents", "Состав тары"),
                action="tap", action_id="container_contents"))
            out.append(ViewNode.button(
                tr("task.put.btn_change_cell", "Сменить ячейку"),
                action="tap", action_id="change_cell"))
        return out

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
            phase = sd.get("phase") or ""
            cur.execute("SELECT status FROM containers "
                        "WHERE barcode=?", (barcode,))
            r = cur.fetchone()
            cur_status = (r[0] if r and r[0] else "free")

            if phase == "collect":
                cur.execute("""
                    SELECT id, status FROM task_items
                    WHERE task_id=? AND container_barcode=?
                """, (task_id, barcode))
                row = cur.fetchone()
                if not row:
                    return {"ok": False,
                            "error": tr(
                                "task.put.err_not_from_task",
                                "Эта тара не из этого задания")}
                if row[1] == "done":
                    return {"ok": False,
                            "error": tr(
                                "task.put.err_already_done",
                                "Эта тара уже завершена")}
                if cur_status not in ("free", "placing"):
                    return {"ok": False,
                            "error": tr(
                                "task.put.err_container_busy",
                                "Тара {barcode} занята "
                                "(статус: {status})",
                                barcode=barcode,
                                status=cur_status)}
                task_utils.set_container_status(cur, barcode, "placing")
                cur.execute("""
                    UPDATE task_items SET status='scanned'
                    WHERE task_id=? AND container_barcode=?
                      AND status != 'done'
                """, (task_id, barcode))
                cur.execute("""
                    SELECT COUNT(*) FROM task_items
                    WHERE task_id=? AND container_barcode IS NOT NULL
                      AND status = 'pending'
                """, (task_id,))
                remaining = cur.fetchone()[0] or 0
                if remaining == 0:
                    return {"ok": True,
                            "message": tr(
                                "task.put.msg_all_scanned",
                                "Все тары отсканированы"),
                            "stay_on_step": False}
                return {"ok": True,
                        "message": tr(
                            "task.put.msg_scanned_container",
                            "Отсканирована тара {barcode}",
                            barcode=barcode),
                        "stay_on_step": True}

            if phase == "place":
                cur.execute("""
                    SELECT id, status FROM task_items
                    WHERE task_id=? AND container_barcode=?
                """, (task_id, barcode))
                row = cur.fetchone()
                if not row:
                    return {"ok": False,
                            "error": tr(
                                "task.put.err_not_from_task",
                                "Эта тара не из этого задания")}
                if row[1] == "done":
                    return {"ok": False,
                            "error": tr(
                                "task.put.err_already_placed",
                                "Тара уже размещена")}
                if cur_status not in ("free", "placing"):
                    return {"ok": False,
                            "error": tr(
                                "task.put.err_container_busy",
                                "Тара {barcode} занята "
                                "(статус: {status})",
                                barcode=barcode,
                                status=cur_status)}
                task_utils.set_container_status(cur, barcode, "placing")
                cur.execute("""
                    UPDATE task_items SET status='in_use'
                    WHERE task_id=? AND container_barcode=?
                """, (task_id, barcode))
                cur.execute("UPDATE tasks SET container_barcode=? "
                            "WHERE id=?", (barcode, task_id))
                return {"ok": True,
                        "message": tr(
                            "task.put.msg_placing_from",
                            "Размещаем из {barcode}",
                            barcode=barcode)}

            return {"ok": False,
                    "error": tr("task.put.err_unknown_phase",
                                "неизвестная фаза")}

        if stype == "scan_cell":
            cur.execute("UPDATE tasks SET current_cell_barcode=? "
                        "WHERE id=?", (barcode, task_id))
            return {"ok": True,
                    "message": tr("task.put.msg_cell",
                                  "Ячейка: {barcode}",
                                  barcode=barcode)}

        if stype == "scan_item" and sd.get("action") == "putaway_scan":
            cell = task.get("current_cell_barcode") or ""
            container = task.get("container_barcode") or ""
            if not cell:
                return {"ok": False,
                        "error": tr(
                            "task.put.err_no_cell",
                            "сначала отсканируйте ячейку")}
            if not container:
                return {"ok": False,
                        "error": tr(
                            "task.put.err_no_container",
                            "сначала отсканируйте тару")}

            cur.execute("""
                SELECT id, quantity, item_code
                FROM placed_instances
                WHERE cell_or_container_barcode = ?
                  AND item_code = ?
            """, (container, barcode))
            src = cur.fetchone()
            if not src:
                cur.execute("""
                    SELECT id, quantity, item_code
                    FROM placed_instances
                    WHERE cell_or_container_barcode = ?
                      AND item_code IN (
                          SELECT item_code
                          FROM item_characteristics
                          WHERE barcode = ?
                      )
                """, (container, barcode))
                src = cur.fetchone()
            if not src:
                return {"ok": False,
                        "error": tr(
                            "task.put.err_item_not_in_container",
                            "товара {barcode} нет в таре",
                            barcode=barcode)}
            if (src[1] or 0) <= 0:
                return {"ok": False,
                        "error": tr(
                            "task.put.err_item_exhausted",
                            "товар закончился")}
            new_qty = (src[1] or 0) - 1
            if new_qty > 0:
                cur.execute("UPDATE placed_instances "
                            "SET quantity=? WHERE id=?",
                            (new_qty, src[0]))
            else:
                cur.execute("DELETE FROM placed_instances "
                            "WHERE id=?", (src[0],))

            item_code = src[2]
            cur.execute("""
                SELECT id FROM placed_instances
                WHERE cell_barcode=? AND item_code=?
            """, (cell, item_code))
            dst = cur.fetchone()
            if dst:
                cur.execute("UPDATE placed_instances "
                            "SET quantity=quantity+1 WHERE id=?",
                            (dst[0],))
            else:
                cur.execute("""
                    INSERT INTO placed_instances
                        (item_code, cell_barcode, quantity)
                    VALUES (?, ?, 1)
                """, (item_code, cell))

            cur.execute("UPDATE tasks SET processed_b = "
                        "processed_b + 1 WHERE id=?", (task_id,))
            task_utils.add_task_event(
                cur, task_id, step["no"], "putaway", barcode)

            try:
                from plugin_hooks import registry as hook_registry
                hook_registry.call_event(
                    "on_place", task=task, item_code=item_code,
                    container=container, cell=cell)
            except Exception:
                pass

            cur.execute("""
                SELECT COALESCE(SUM(quantity), 0)
                FROM placed_instances
                WHERE cell_or_container_barcode=?
            """, (container,))
            left = cur.fetchone()[0] or 0
            if left == 0:
                task_utils.set_container_status(cur, container, "free")
                return {"ok": True,
                        "message": tr(
                            "task.put.msg_placed_empty",
                            "Размещено: {barcode} -> {cell}. "
                            "Тара пуста",
                            barcode=barcode, cell=cell),
                        "stay_on_step": False}
            return {"ok": True,
                    "message": tr(
                        "task.put.msg_placed",
                        "Размещено: {barcode} -> {cell}",
                        barcode=barcode, cell=cell),
                    "stay_on_step": True}

        return {"ok": False,
                "error": tr("task.put.err_unknown_step",
                            "неизвестный тип шага")}

    def handle_action(self, cur, task, step, action_id, value,
                      items, settings):
        if action_id == "change_cell":
            return self._change_cell(cur, task, items, settings)
        if action_id == "container_contents":
            return {"ok": True,
                    "view_override": "container_contents"}
        if action_id == "back_to_step":
            return {"ok": True, "stay_on_step": True}
        if action_id == "confirm":
            return self._confirm(cur, task, step, items, settings)
        return {"ok": False,
                "error": tr("task.put.err_unknown_button",
                            "неизвестная кнопка: {id}",
                            id=action_id)}

    def _change_cell(self, cur, task, items, settings):
        plan = []
        try:
            raw = task.get("task_plan") or ""
            if raw:
                import json
                plan = json.loads(raw)
        except Exception:
            plan = []
        cur_index = int(task.get("current_step_no") or 0)
        target = None
        for i in range(cur_index, -1, -1):
            if i >= len(plan):
                continue
            s = plan[i]
            if s and s.get("type") == "scan_cell" and \
                    (s.get("data") or {}).get("putaway"):
                target = i
                break
        if target is None:
            return {"ok": False,
                    "error": tr(
                        "task.put.err_no_change_cell",
                        "нет шага для смены ячейки")}
        cur.execute("UPDATE tasks SET current_step_no=? WHERE id=?",
                    (target, task["id"]))
        cur.execute("UPDATE tasks SET current_cell_barcode='' "
                    "WHERE id=?", (task["id"],))
        return {"ok": True,
                "message": tr("task.put.msg_choose_cell",
                              "Выберите ячейку"),
                "stay_on_step": True}

    def _confirm(self, cur, task, step, items, settings):
        if step["type"] != "confirm":
            return {"ok": False,
                    "error": tr("task.put.err_no_confirm",
                                "шаг не требует подтверждения")}
        act = (step.get("data") or {}).get("action")

        if act == "finish_container":
            container = task.get("container_barcode") or ""
            if not container:
                return {"ok": False,
                        "error": tr(
                            "task.put.err_no_active_container",
                            "нет активной тары")}
            cur.execute("""
                UPDATE tasks SET pending_action='finish_container',
                                 pending_cell=?
                WHERE id=?
            """, (container, task["id"]))
            return {"ok": True,
                    "message": tr(
                        "task.put.msg_scan_container_confirm",
                        "Сканируйте ШК тары {container} "
                        "для подтверждения",
                        container=container)}

        if act == "start_putaway":
            return {"ok": True,
                    "message": tr("task.put.msg_started",
                                  "Приступили")}

        if act == "finish_task":
            return {"ok": True,
                    "message": tr("task.put.msg_finish",
                                  "Завершение"),
                    "action": "finish"}

        return {"ok": True, "message": ""}

    def handle_pending_scan(self, cur, task, pending, scanned,
                            items, settings):
        if pending != "finish_container":
            return None
        container = (task.get("pending_cell") or "").strip()
        if scanned != container:
            return {"ok": False,
                    "error": tr(
                        "task.put.err_expected_container",
                        "Ожидался ШК тары {container}. "
                        "Сканируйте его или «Отменить».",
                        container=container)}
        cur.execute("""
            UPDATE task_items SET status='done'
            WHERE task_id=? AND container_barcode=?
        """, (task["id"], container))
        # FIX: не помечаем free контейнер, в котором ещё остались
        # товары — иначе следующая задача может его занять и
        # остатки потеряются. Проверяем фактическое содержимое.
        cur.execute("""
            SELECT COALESCE(SUM(quantity), 0)
            FROM placed_instances
            WHERE cell_or_container_barcode=?
        """, (container,))
        qty_left = cur.fetchone()[0] or 0
        task_utils.set_container_status(
            cur, container, "free" if qty_left == 0 else "placing")

        cur.execute("""
            UPDATE tasks SET pending_action='', pending_cell=''
            WHERE id=?
        """, (task["id"],))

        cur.execute("""
            SELECT COUNT(*) FROM task_items
            WHERE task_id=? AND container_barcode IS NOT NULL
              AND status != 'done'
        """, (task["id"],))
        remaining = cur.fetchone()[0] or 0
        if remaining > 0:
            plan = []
            try:
                raw = task.get("task_plan") or ""
                if raw:
                    import json
                    plan = json.loads(raw)
            except Exception:
                plan = []
            target = None
            for i, s in enumerate(plan):
                if s.get("type") == "scan_container" and \
                        (s.get("data") or {}).get("phase") == "place":
                    target = i
                    break
            if target is not None:
                cur.execute(
                    "UPDATE tasks SET current_step_no=?, "
                    "container_barcode='' WHERE id=?",
                    (target, task["id"]))
                return {"ok": True,
                        "message": tr(
                            "task.put.msg_container_closed_next",
                            "Тара закрыта. Выберите следующую."),
                        "stay_on_step": True}
        return {"ok": True,
                "message": tr("task.put.msg_finish", "Завершение"),
                "finished": True}

    def on_finalize(self, cur, task, items, settings):
        cur.execute("""
            SELECT DISTINCT container_barcode FROM task_items
            WHERE task_id=? AND container_barcode IS NOT NULL
        """, (task["id"],))
        for (bc,) in cur.fetchall():
            # FIX: free только для действительно пустых.
            # Непустые → placing, чтобы не потерять остатки.
            cur.execute("""
                SELECT COALESCE(SUM(quantity), 0)
                FROM placed_instances
                WHERE cell_or_container_barcode=?
            """, (bc,))
            qty = cur.fetchone()[0] or 0
            task_utils.set_container_status(
                cur, bc, "free" if qty == 0 else "placing")