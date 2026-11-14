"""Пример плагина-перехватчика (API 1.0). Использует helpers.py.

Показывает, как вынести вспомогательные функции в отдельный
модуль внутри папки плагина. Импорт — относительный:
    from . import helpers
(папка загружается как пакет `luch_plugin_<name>`).
"""

from tasks.base import TaskHandler

from . import helpers


class SpecialTaskHandler(TaskHandler):
    task_type = "special"
    title = "Спец-задание"
    default_platform = "any"

    def build_steps(self, task, items, settings):
        return [
            {
                "no": 1, "type": "scan_cell",
                "prompt": "Сканируйте ячейку для спец-задания",
                "validate": {}, "data": {}, "repeat": False,
            },
            {
                "no": 2, "type": "confirm",
                "prompt": "Завершить спец-задание?",
                "validate": {},
                "data": {"action": "finish_task"},
                "repeat": False,
            },
        ]

    def handle_scan(self, cur, task, step, barcode, items, settings):
        return {"ok": True, "message": "OK", "stay_on_step": False}

    def handle_action(self, cur, task, step, action_id, value,
                      items, settings):
        return {"ok": False, "error": "unknown button"}


def register(context):
    context.log("register() example_hooks")

    @context.hook("on_scan", priority=100)
    def intercept_special(*, task, step, barcode, login, context):
        if helpers.is_special(barcode):
            context.log(
                f"перехвачен: {barcode} в задаче "
                f"{task.get('task_number')}"
            )
            return {
                "handled": True,
                "message": helpers.special_message(barcode),
            }
        return None

    context.register_task_handler(SpecialTaskHandler())

    @context.hook("on_view_build", priority=0)
    def decorate(*, value, task, step, items, settings, context):
        try:
            children = value.get("children") or []
            for node in children:
                if (isinstance(node, dict)
                        and node.get("type") == "slot"
                        and node.get("id") == "step_footer"):
                    node["children"] = [{
                        "type": "caption",
                        "value": "Плагин example_hooks активен",
                    }]
                    break
        except Exception as e:
            context.log(f"on_view_build error: {e}")
        return value


def unregister(context):
    context.log("unregister() example_hooks")