"""Пример плагина: логирование подбора (API 1.0).

Формат — ПАПКА в plugins/. Внутри:
  - plugin.json  — характеристики
  - plugin.py    — этот файл (точка входа)

Точка входа — register(context). Необязательная
unregister(context) вызывается при деактивации.
"""


def register(context):
    context.log("register() example_printer")

    @context.hook("on_scan_after", priority=0)
    def after_scan(*, task, step, barcode, result, context):
        try:
            ttype = task.get("task_type")
            if ttype == "pick":
                context.log(
                    f"подбор: скан {barcode}, "
                    f"задача {task.get('task_number')}"
                )
        except Exception as e:
            context.log(f"after_scan: {e}")


def unregister(context):
    context.log("unregister() example_printer")