"""Базовый интерфейс обработчика задания."""


class TaskHandler:
    task_type = ""
    title = ""
    default_platform = "any"

    # ---------- Построение шагов ----------

    def build_steps(self, task, items, settings):
        raise NotImplementedError

    # ---------- Жизненный цикл ----------

    def on_enter(self, cur, task, items, settings):
        pass

    def enrich_task(self, cur, task, items, settings):
        return task

    def enrich_step(self, cur, task, step, items, settings):
        return step

    def extra_buttons(self, task, step):
        """Список ViewNode.button для доп. кнопок."""
        return []

    # ---------- Сканы и действия ----------

    def handle_scan(self, cur, task, step, barcode, items, settings):
        raise NotImplementedError

    def handle_action(self, cur, task, step, action_id, value,
                      items, settings):
        raise NotImplementedError

    def handle_pending_scan(self, cur, task, pending, scanned,
                            items, settings):
        """Обработка скана в pending-состоянии.
        Возвращает dict как handle_scan или None (если pending
        не принадлежит этому handler'у).
        """
        return None

    def can_cancel_pending(self, cur, task, pending):
        """Можно ли отменить текущее pending-подтверждение.

        Возвращает (ok: bool, reason: str|None).
        По умолчанию — можно отменить.
        """
        return True, None

    # ---------- Завершение ----------

    def on_finalize(self, cur, task, items, settings):
        pass

    # ---------- Утилита ----------

    def validate_barcode(self, barcode, step):
        v = step.get("validate") or {}
        p = v.get("prefix") or ""
        s = v.get("suffix") or ""
        if p and not barcode.startswith(p):
            return False, f"ШК не начинается на «{p}»"
        if s and not barcode.endswith(s):
            return False, f"ШК не заканчивается на «{s}»"
        return True, None