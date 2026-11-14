"""Реестр точек расширения (hooks) с приоритетами.

Идея: плагины подписываются на события ядра. События бывают трёх видов:
  - chain  — вызываем по очереди до первого результата != None.
             Первый, кто вернул что-то, останавливает цепочку.
             Используется там, где можно перехватить действие (on_scan).
  - event  — вызываем всех, результат игнорируем. Только побочные
             эффекты (логирование, отправка уведомлений).
  - filter — вызываем всех по очереди, каждый получает на входе
             значение от предыдущего и может вернуть новое.
             Используется там, где нужно обогатить данные
             (on_view_build, on_ui_config).
"""

import traceback


# Классификация известных hooks. Неизвестные считаем event.
KNOWN_HOOKS = {
    # chain — можно перехватить и остановить
    "on_scan": "chain",
    "on_step_start": "chain",
    "on_step_complete": "chain",
    "on_task_assign": "chain",
    "on_task_finish": "chain",
    "on_receive_finish": "chain",
    "on_putaway_finish": "chain",
    "on_inventory_finish": "chain",

    # event — только побочные эффекты
    "on_task_created": "event",
    "on_task_done": "event",
    "on_item_not_found": "event",
    "on_item_relocated": "event",
    "on_item_lost": "event",
    "on_place": "event",
    "on_pick": "event",
    "on_notification_sent": "event",
    "on_scan_after": "event",
    "on_plugin_activate": "event",
    "on_plugin_deactivate": "event",
    "on_task_plan_change": "event",

    # filter — накапливающие изменения
    "on_ui_config": "filter",
    "on_view_build": "filter",
    "on_barcode_button": "filter",
    "on_task_plan_build": "filter",
    "on_cell_contents": "filter",
    "on_item_details": "filter",

    # mgmt — управление складом (ПК-клиент управления)
    # filter: плагин получает initial=True и может вернуть
    #         False / строку / {"error": ...} чтобы запретить вход.
    # filter: плагин получает готовый mgmt-документ и может его
    #         обогатить; возвращает новое значение.
    # chain:  плагин может вернуть {"handled": True, ...} чтобы
    #         остановить стандартную обработку действия.
    "on_mgmt_login": "filter",
    "on_mgmt_page_build": "filter",
    "on_mgmt_action": "chain",
}


class _HookEntry:
    __slots__ = ("plugin_name", "func", "priority", "order")

    def __init__(self, plugin_name, func, priority, order):
        self.plugin_name = plugin_name
        self.func = func
        self.priority = priority
        self.order = order

    def __repr__(self):
        return (f"<Hook {self.plugin_name} "
                f"priority={self.priority} order={self.order}>")


class HookRegistry:
    def __init__(self):
        self._hooks = {}          # name -> list[_HookEntry]
        self._enabled = True
        self._order_counter = 0

    # ---- регистрация ----

    def register(self, plugin_name, name, func, priority=0):
        if name not in KNOWN_HOOKS:
            KNOWN_HOOKS[name] = "event"
        entries = self._hooks.setdefault(name, [])
        self._order_counter += 1
        entries.append(_HookEntry(plugin_name, func, priority,
                                  self._order_counter))
        # сортируем: по приоритету убыв., при равенстве — по порядку возр.
        entries.sort(key=lambda e: (-e.priority, e.order))

    def unregister_plugin(self, plugin_name):
        for name in list(self._hooks.keys()):
            rest = [e for e in self._hooks[name]
                    if e.plugin_name != plugin_name]
            if rest:
                self._hooks[name] = rest
            else:
                del self._hooks[name]

    def clear(self):
        self._hooks.clear()

    def has(self, name):
        return bool(self._hooks.get(name))

    def set_enabled(self, enabled):
        self._enabled = bool(enabled)

    def is_enabled(self):
        return self._enabled

    # ---- вызовы ----

    def call_chain(self, name, **kwargs):
        if not self._enabled:
            return None
        for entry in self._hooks.get(name, []):
            try:
                result = entry.func(**kwargs)
            except Exception:
                traceback.print_exc()
                print(f"[hooks] {entry.plugin_name}.{name} упал")
                continue
            if result is not None:
                return result
        return None

    def call_event(self, name, **kwargs):
        if not self._enabled:
            return
        for entry in self._hooks.get(name, []):
            try:
                entry.func(**kwargs)
            except Exception:
                traceback.print_exc()
                print(f"[hooks] {entry.plugin_name}.{name} упал")

    def call_filter(self, name, initial, **kwargs):
        if not self._enabled:
            return initial
        value = initial
        for entry in self._hooks.get(name, []):
            try:
                result = entry.func(value=value, **kwargs)
                if result is not None:
                    value = result
            except Exception:
                traceback.print_exc()
                print(f"[hooks] {entry.plugin_name}.{name} упал")
        return value

    def stats(self):
        return {
            name: [(e.plugin_name, e.priority) for e in entries]
            for name, entries in self._hooks.items()
        }


# Глобальный реестр (один на процесс wms.py)
registry = HookRegistry()