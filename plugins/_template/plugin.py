"""Шаблон плагина (API 1.0).

Как начать:
  1. Скопируйте папку plugins/_template в plugins/my_plugin.
  2. В plugin.json поменяйте "name" на "my_plugin"
     (должно совпадать с именем папки) и заполните title/
     description/version.
  3. Пишите код в register(context).
  4. ПК-клиент → «🧩 Плагины» → «Обновить» → двойной клик →
     «Активировать».

Подробнее — см. PLUGINS.md и PLUGIN_API.md.
"""


def register(context):
    """Вызывается при активации плагина.

    context — PublicContext (см. PLUGIN_API.md).
    """
    context.log("hello from my_plugin")

    # Пример: hook на каждый скан
    # @context.hook("on_scan_after", priority=0)
    # def after_scan(*, task, step, barcode, result, context):
    #     context.log(f"scan: {barcode}")


def unregister(context):
    """Вызывается при деактивации плагина.

    Hook'и, страницы, эндпоинты, menu-пункты и т.п. ядро
    снимает автоматически. Здесь — только ваша ручная очистка
    (например, закрытие своих файлов/сокетов).
    """
    context.log("bye from my_plugin")