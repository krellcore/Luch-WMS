"""TaskHandler для типа 'audit' — проверка ячейки.

Сценарий:
  1. Скан ячейки (scan_cell).
  2. Подтверждение проверки (confirm) → +1 в processed_a,
     запись в audit_log.
  3. После всех ячеек — финальный confirm → finished=True.

Тексты берутся через prompt_key = "plugin.<name>.audit.*".
"""

from tasks.base import TaskHandler


class AuditHandler(TaskHandler):
    task_type = "audit"
    title = "Аудит ячеек"
    default_platform = "any"

    def __init__(self, plugin_name):
        self.PLUGIN_NAME = plugin_name

    def _k(self, key):
        return f"plugin.{self.PLUGIN_NAME}.audit.{key}"

    def build_steps(self, task, items, settings):
        steps = []
        no = 1
        pcell = settings.get("prefix_cell", "") or ""
        scell = settings.get("suffix_cell", "") or ""

        for cell_item in items:
            cell = cell_item.get("cell_barcode") or ""
            addr = cell_item.get("cell_address") or cell
            steps.append({
                "no": no, "type": "scan_cell",
                "prompt_key": self._k("prompt_scan_cell"),
                "prompt_params": {"addr": addr},
                "validate": {"prefix": pcell, "suffix": scell},
                "data": {
                    "step_id": cell_item["id"],
                    "cell_barcode": cell,
                    "cell_address": addr,
                    "expected_barcode": cell,
                },
                "repeat": False,
            })
            no += 1
            steps.append({
                "no": no, "type": "confirm",
                "prompt_key": self._k("prompt_confirm_cell"),
                "prompt_params": {"addr": addr},
                "validate": {},
                "data": {
                    "action": "confirm_cell",
                    "cell_barcode": cell,
                    "step_id": cell_item["id"],
                },
                "repeat": False,
            })
            no += 1

        steps.append({
            "no": no, "type": "confirm",
            "prompt_key": self._k("prompt_finish"),
            "prompt_params": {},
            "validate": {},
            "data": {"action": "finish_task"},
            "repeat": False,
        })
        return steps

    def handle_scan(self, cur, task, step, barcode, items, settings):
        if step.get("type") != "scan_cell":
            return {"ok": True, "stay_on_step": True, "message": ""}

        barcode = (barcode or "").strip()
        if not barcode:
            return {"ok": False, "error": "empty barcode"}

        ok, err = self.validate_barcode(barcode, step)
        if not ok:
            return {"ok": False, "error": err}

        expected = (step.get("data") or {}).get("cell_barcode") or ""
        if expected and barcode != expected:
            return {"ok": False,
                    "error": f"Ожидалась ячейка {expected}"}

        cur.execute(
            "UPDATE tasks SET current_cell_barcode=? WHERE id=?",
            (barcode, task["id"]))
        return {"ok": True, "message": f"Ячейка: {barcode}"}

    def handle_action(self, cur, task, step, action_id, value,
                      items, settings):
        if step.get("type") != "confirm":
            return {"ok": False,
                    "error": f"Шаг {step.get('type')} не "
                             f"требует подтверждения"}
        if action_id != "confirm":
            return {"ok": False,
                    "error": f"unknown button: {action_id}"}

        act = (step.get("data") or {}).get("action") or ""

        if act == "confirm_cell":
            cell = (step.get("data") or {}).get("cell_barcode") or ""
            step_id = (step.get("data") or {}).get("step_id")
            try:
                cur.execute("""
                    INSERT INTO audit_log
                        (task_id, cell_barcode, action, created_at)
                    VALUES (?, ?, 'checked', datetime('now'))
                """, (task["id"], cell))
            except Exception:
                pass
            if step_id:
                cur.execute(
                    "UPDATE task_items "
                    "SET status='done', processed=1 WHERE id=?",
                    (step_id,))
            cur.execute(
                "UPDATE tasks SET processed_a = processed_a + 1 "
                "WHERE id=?", (task["id"],))
            return {"ok": True,
                    "message": f"Ячейка {cell} проверена"}

        if act == "finish_task":
            cur.execute("""
                SELECT COUNT(*) FROM task_items
                WHERE task_id=? AND status NOT IN ('done','not_found')
            """, (task["id"],))
            remaining = cur.fetchone()[0] or 0
            if remaining > 0:
                return {"ok": False,
                        "error": f"Осталось непроверенных "
                                 f"ячеек: {remaining}"}
            return {"ok": True,
                    "message": "Аудит завершён",
                    "finished": True}

        return {"ok": True, "message": ""}

    def on_finalize(self, cur, task, items, settings):
        pass