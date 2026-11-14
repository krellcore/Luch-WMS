"""Обработчик заданий «Приёмка» (receive).

Приёмка выполняется ТОЛЬКО через сессию (`sessions/receive.py`).
Поток «Получить задание» (`/tasks/next`) для receive заблокирован
на стороне сервера (`server.py`). Данный handler оставлен как
shared helper: сессия приёмки использует его `handle_scan` для
обработки сканов товаров.

Методы build_steps / enrich_step / handle_action / on_finalize
удалены — они никогда не вызываются (сервер блокирует /tasks/*
для receive, а сессия не использует их).
"""

from .base import TaskHandler
from . import utils as task_utils
from i18n import tr


class ReceiveHandler(TaskHandler):
    task_type = "receive"
    title = "Приёмка"
    default_platform = "pc"

    def handle_scan(self, cur, task, step, barcode, items, settings):
        barcode = (barcode or "").strip()
        if not barcode:
            return {"ok": False, "error": "empty barcode"}
        sd = step.get("data") or {}
        if sd.get("action") != "receive_scan":
            return {"ok": False,
                    "error": tr("task.recv.err_not_scan",
                                "не шаг приёмки")}
        task_id = task["id"]
        container_bc = task.get("container_barcode") or ""
        if not container_bc:
            return {"ok": False,
                    "error": tr("task.recv.err_no_container",
                                "сначала отсканируйте тару")}

        found = None
        for it in items:
            if it.get("item_barcode") == barcode or \
                    it.get("item_code") == barcode:
                found = it
                break

        if not found:
            cur.execute("""
                SELECT item_code, name, barcode
                FROM item_characteristics
                WHERE barcode=? OR item_code=?
            """, (barcode, barcode))
            r = cur.fetchone()
            if r:
                item_code = r[0]
                # 3.14: если у артикула в БД нет item_code —
                # не инкрементим scanned_qty, иначе будет
                # рассинхрон с placed_instances.
                if not item_code:
                    return {"ok": False,
                            "error": tr(
                                "task.recv.err_bad_item_code",
                                "У артикула нет item_code — "
                                "сообщите руководителю.")}
                task_utils.add_to_container(
                    cur, item_code, container_bc, 1)
                cur.execute("""
                    INSERT INTO task_items
                        (task_id, item_code, quantity,
                         scanned_qty, step_no, status,
                         scanned_item_barcode)
                    VALUES (?, ?, 0, 1, ?, 'extra', ?)
                """, (task_id, item_code, step["no"], barcode))
                cur.execute("UPDATE tasks SET processed_a = "
                            "processed_a + 1 WHERE id=?",
                            (task_id,))
                task_utils.add_task_event(
                    cur, task_id, step["no"], "receive_scan",
                    barcode,
                    {"item_code": item_code,
                     "container_barcode": container_bc,
                     "extra": True})
                return {"ok": True,
                        "message": tr(
                            "task.recv.msg_extra",
                            "Принято сверх плана: {barcode}",
                            barcode=barcode),
                        "stay_on_step": True}
            task_utils.add_task_event(
                cur, task_id, step["no"], "rejected", barcode)
            return {"ok": False,
                    "error": tr(
                        "task.recv.err_unknown",
                        "Неизвестный ШК «{barcode}». "
                        "Отложите товар и сообщите "
                        "руководителю.", barcode=barcode)}

        item_code = found.get("item_code")
        # 3.14: симметричная проверка для найденного item.
        if not item_code:
            return {"ok": False,
                    "error": tr(
                        "task.recv.err_bad_item_code",
                        "У артикула нет item_code — "
                        "сообщите руководителю.")}

        cur.execute("""
            UPDATE task_items
            SET scanned_qty = COALESCE(scanned_qty, 0) + 1,
                scanned_item_barcode=?
            WHERE id=?
        """, (barcode, found["id"]))
        task_utils.add_to_container(
            cur, item_code, container_bc, 1)
        cur.execute("UPDATE tasks SET processed_a = "
                    "processed_a + 1 WHERE id=?", (task_id,))
        task_utils.add_task_event(
            cur, task_id, step["no"], "receive_scan", barcode,
            {"item_code": item_code,
             "container_barcode": container_bc})
        return {"ok": True,
                "message": tr("task.recv.msg_accepted",
                              "Принято: {barcode}",
                              barcode=barcode),
                "stay_on_step": True}