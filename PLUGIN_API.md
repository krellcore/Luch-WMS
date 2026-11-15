# Луч — Публичный API плагинов

**API v1.0**

Единственный контракт, который гарантированно стабилен. Всё, что
не описано здесь — внутренние дела ядра, могут меняться.

Плагин получает в `register()` объект `context` типа `PublicContext`.
Через него: логирование, БД, hooks, TaskHandler, SessionHandler,
UI, эндпоинты, уведомления, mgmt-страницы, роли, локализация.

---

## 1. Структура плагина

Плагин — **папка** в `plugins/`:

```
plugins/
└── my_plugin/
    ├── plugin.json      ← характеристики (обязательно)
    ├── plugin.py        ← код (entry, см. plugin.json)
    ├── lang/            ← (опционально) языки плагина
    │   ├── ru.json
    │   └── en.json
    ├── helpers.py       ← (опционально) доп. модули
    └── ...              ← (опционально) ресурсы
```

Папка загружается как Python-пакет `luch_plugin_<name>`,
поэтому внутри работают **относительные** импорты:

```python
from . import helpers
from .helpers import foo
```

Абсолютный `import helpers` не работает — не добавляйте папку
плагина в `sys.path`.

Старый формат (один `.py`-файл в `plugins/`) поддерживается
для совместимости: читается `PLUGIN_INFO`, файл грузится как
обычный модуль.

---

## 2. Метаданные (`plugin.json`)

```json
{
  "name": "my_plugin",
  "title": "Мой плагин",
  "version": "1.0.0",
  "api_version": "1.0",
  "author": "...",
  "description": "...",
  "entry": "plugin.py",
  "creates_tables": [],
  "reads_tables": [],
  "writes_tables": [],
  "hooks": [],
  "dependencies": []
}
```

| Поле | Обязательно | Описание |
|---|---|---|
| `name` | да | Должно совпадать с именем папки. |
| `title` | да | Название в UI. |
| `version` | да | semver. |
| `api_version` | рекомендуется | Мажор должен совпадать с ядром. |
| `author` | нет | Автор. |
| `description` | нет | Описание. |
| `entry` | нет | Имя Python-файла (по умолчанию `plugin.py`). |
| `creates_tables` | нет | Какие таблицы создаёт. |
| `reads_tables` | нет | Какие таблицы читает. |
| `writes_tables` | нет | В какие пишет. |
| `hooks` | нет | Список используемых hooks (для UI). |
| `dependencies` | нет | Другие плагины, от которых зависит. |

Для **legacy**-файлов (`plugins/old.py`) используется
`PLUGIN_INFO` в коде — тот же формат, но в Python-словаре.

---

## 3. Логирование

```python
context.log("текст")   # [plugin:name] текст
```

---

## 4. Работа с БД

Полный доступ. Свои таблицы создавайте через `CREATE TABLE
IF NOT EXISTS`. Свои колонки в базовые таблицы добавляйте
идемпотентно (`PRAGMA table_info`).

```python
# низкоуровневое соединение
conn = context.db()
cur = conn.cursor()
cur.execute(...)
conn.commit()
conn.close()

# удобные обёртки
rows = context.query("SELECT * FROM cells WHERE ...", (p,))
row  = context.query_one("SELECT ...", (p,))
n, last_id = context.execute("INSERT INTO my_table ...", (v,))
```

---

## 4.5. Локализация плагина

`plugins/<name>/lang/*.json` — свои переводы. Ключи простые
(`audit.title`), ядро оборачивает их в `plugin.<name>.` и
мержит в общий словарь.

```python
context.tr("audit.title")              # → plugin.my_plugin.audit.title
context.tr("prompt", addr="A1")        # подставит {addr}
context.tr_in("de", "audit.title")     # явная локаль
```

Для `prompt_key` в `task_plan` используйте **полный** ключ
(`f"plugin.{self.PLUGIN_NAME}.audit.prompt_scan_cell"`) —
`view_builder._prompt` зовёт `tr()` без контекста плагина.

Плагин не обязан быть активирован — языки читаются при
`reload_locales()`.

На клиентах (ПК-терминал, Android) ключи `plugin.<name>.*`
попадают в клиентский словарь через `/ui_config` и применяются
автоматически. Кэшируются в `config.json.ui_cache[<server>]`
(ПК-терминал) и `SharedPreferences` `wms_locales` (Android).
Актуальность проверяется **только при подключении к серверу**.

---

## 5. Настройки

```python
context.get_setting(key, default=None)
context.set_setting(key, value)
```

---

## 6.0. Роли (`register_role`)

```python
context.register_role(
    key,                         # уникальный ключ
    title_key=None,              # i18n-ключ (автопрефикс plugin.<name>.)
    title=None,                  # fallback
    task_types=(),               # типы заданий для /tasks/next
)
```

Роль появляется:

- чекбоксом в карточке сотрудника;
- в фильтре «Сотрудники → Роль»;
- в фильтре «Уведомления → По роли»;
- учитывается в `/tasks/next` (если `task_types` непуст);
- отдаётся клиентам в `/ui_config.roles` — Android/ПК-терминал
  локализуют название через `Lang.t(title_key)`.

Деактивация плагина убирает роль из UI, значения в
`employees.roles` сохраняются (не теряются при сохранении
карточки).

---

## 6.1. Структура данных

### tasks

- `batch_id` — общий id группы заданий (пусто, если одно).
- `block_bf` — блок-этаж задания (например, `"45"`).
- `platform` — `"pc"` | `"android"` | `"any"`.
- `pending_action` — текущее ожидание подтверждения:
  `""` | `"not_found"` | `"finish_cell"` | `"finish_container"`
  | `"finish_cargo"` | `"partial_cargo"` | `"scan_close_container"`
  | `"scan_new_container"` | `"drop_containers"` | `"unknown_item"`
  | `"unknown_scan_container"` | `"drop_unknown"`.
- `pending_cell` — что сканируется (ШК).
- `drop_status` / `drop_pending` / `drop_point_barcode` — состояние
  сброса тар в подборе.
- `current_step_no`, `task_plan`, `current_cell_barcode`,
  `container_barcode` — состояние выполнения.

### containers

Статусы:

- `free` — свободна;
- `accepting` — идёт приёмка;
- `placing` — ждёт размещения;
- `picking` — идёт подбор;
- `waiting` — подбор завершён, тара с товаром;
- `closed` — закрыта (в подборе). После сброса `placed_in=<точка>`,
  статус остаётся `closed`;
- `unknown_scan` — тара с неизвестными ШК (инвентаризация).

### drop_points

`id, barcode, name, created_at`.

### sessions

`id, login, session_key, payload (JSON), created_at`,
`UNIQUE(login, session_key)`.

### reservations

```
available = placed_instances.quantity
          − SUM(reservations.qty WHERE expires_at >= now)
```

### task_events

Типы событий: `scan_item`, `putaway`, `inventory_scan`,
`item_not_found`, `receive_scan`, `rejected`, `close_container`.

### employees

Пароль хранится **только хэшем** (`pass_hash`, SHA-256).
`roles` — JSON-список ролей (может содержать роли, которых нет
в реестре — они сохраняются как «неизвестные»).

### managers

Руководители склада. `id, login, pass_hash, role, created_at`.
`role` — `owner` | `admin` | `operator`. Хэш — SHA-256.

---

## 7. Готовые обёртки данных

```python
context.get_task(task_id)          # dict | None
context.get_items(task_id)         # list[dict]
context.get_cell(barcode)          # dict | None
context.get_item(item_code)        # dict | None
context.find_cells_with_item(item_code, exclude_cell=None)
                                    # list[{"cell_barcode", "qty"}]
```

---

## 8. Hooks

Три вида:

- **chain** — вызываются по очереди до первого `!= None`.
- **event** — вызываются все, результат игнорируется.
- **filter** — вызываются все по очереди, каждый получает значение
  от предыдущего и может вернуть новое.

### 8.1. Hooks для терминальных клиентов

**chain:**

- `on_scan(task, step, barcode, login, context) -> dict | None`
- `on_step_start(task, step, step_no, context)`
- `on_step_complete(task, step, step_no, result, context)`
- `on_task_assign(task, login, context)`
- `on_task_finish(task, result, context)`
- `on_receive_finish(task, data, context)`
- `on_putaway_finish(task, data, context)`
- `on_inventory_finish(task, data, context)`
- `on_custom_action(task, step, custom_id, value, login, context)`

**event:**

- `on_task_created(task_id, task_type, context)`
- `on_task_done(task, context)`
- `on_item_not_found(task, step, barcode, context)`
- `on_item_relocated(task, item_code, from_cell, to_cell, context)`
- `on_item_lost(task, item_code, context)`
- `on_place(task, item_code, container, cell, context)`
- `on_pick(task, item_code, cell, container, context)`
- `on_notification_sent(sender, message, type, ...)`
- `on_scan_after(task, step, barcode, result, context)`
- `on_plugin_activate(plugin, info, context)`
- `on_plugin_deactivate(plugin)`
- `on_task_plan_change(task, plan, context)`
- `on_unknown_button(task, step, action_id, login)`
- `on_task_partial(task, login, context)`

**filter:**

- `on_ui_config(value, db_path, context) -> dict`
- `on_view_build(value, task, step, items, settings, context) -> dict`
- `on_barcode_button(value, kind, barcode, context) -> list`
- `on_task_plan_build(value, task, items, settings, context) -> list`
- `on_cell_contents(value, cell_barcode, context) -> list`
- `on_item_details(value, item_code, context) -> dict`

### 8.2. Hooks для клиента управления (mgmt)

**filter:**

- `on_mgmt_login(value, login, role, context) -> True | False | dict | str`
  - Вызывается в `/mgmt/login` до выдачи токена.
  - `value` изначально `True`; вернуть `False`, строку (причина отказа)
    или `{"error": "..."}` — чтобы запретить вход.
  - Вернуть `True` (или `None`) — пропустить.
- `on_mgmt_page_build(value, page_key, login, role, context) -> dict`
  - Вызывается после сборки view любой mgmt-страницы.
  - `value` — готовый mgmt-документ; можно модифицировать
    `value["page"]["children"]`, добавлять `mgmt_badge`, `text` и т.д.

**chain:**

- `on_mgmt_action(page_key, action, action_id, value, values, login, role, context) -> dict | None`
  - Вызывается перед стандартной обработкой действия.
  - Вернуть `{"handled": True, "message": "..."}` — остановить цепочку.

---

## 9. TaskHandler — свой тип задания

```python
from tasks.base import TaskHandler
from view_protocol import ViewNode


class MyHandler(TaskHandler):
    task_type = "my_type"
    title = "Мой тип"
    default_platform = "any"

    def build_steps(self, task, items, settings):
        return [...]

    def handle_scan(self, cur, task, step, barcode, items, settings):
        return {"ok": True, "message": "OK", "stay_on_step": False}

    def handle_action(self, cur, task, step, action_id, value,
                      items, settings):
        return {"ok": False, "error": "unknown button"}


def register(context):
    context.register_task_handler(MyHandler())
```

Встроенные типы: `pick`, `receive`, `putaway`, `inventory`.
Platform по умолчанию: `pick`/`putaway`/`inventory` → `android`,
`receive` → `pc`.

Чтобы задание попадало в `/tasks/next`, тип задания должен
быть связан с ролью сотрудника через `context.register_role(
..., task_types=("my_type",))`.

---

## 10. SessionHandler — своя сессия

```python
from sessions.base import SessionHandler


class MySession(SessionHandler):
    key = "my_session"
    title = "Моя сессия"
    platforms = ("pc",)

    def can_start(self, login, roles):
        return "receiver" in roles

    def start(self, cur, login, payload): ...
    def get_state(self, cur, login): ...
    def handle_action(self, cur, login, action_id, value, settings): ...
    def get_view(self, cur, login, settings, caps): ...
    def close(self, cur, login, force=False): ...


def register(context):
    context.register_session(MySession())
```

`platforms`: `("pc",)` | `("android",)` | `("any",)`. Сессии
фильтруются на сервере по device клиента.

---

## 11. Обработчики шагов

```python
def handle_my_step(*, task, items, step, barcode, settings, context):
    return {"ok": True, "message": "Готово",
            "stay_on_step": False}


context.register_step_handler("my_step_type", handle_my_step,
                              priority=0)
```

---

## 12. UI: кнопки на панелях (только локальный клиент)

```python
def on_print(kind, code, parent):
    QMessageBox.information(parent, "Печать",
                            f"{kind}: {code}")


context.add_barcode_button("🖨 Печать", on_print,
                           panel_filter=lambda k: k == "cell")
```

Работает только в локальном режиме (legacy Qt-панели).

---

## 13. UI: Qt-страница в сайдбаре (только локальный клиент)

```python
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel


class MyPage(QWidget):
    def __init__(self, db_path, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Моя страница"))


context.register_page("my_key", "Моя страница", MyPage)
```

**Важно.** `register_page` передаёт **Qt-класс**, который
инстанцируется **на клиенте**. Значит:

- плагин должен быть установлен на каждой машине, где сидит
  руководитель;
- **не работает** в режиме headless-сервера;
- **работает только в локальном режиме**.

Для удалённых клиентов используйте `register_mgmt_page`.

---

## 14. UI: mgmt-страница (все режимы, включая удалённые)

```python
from mgmt_protocol import mgmt_page, heading, text


def my_builder(login, role, context):
    return mgmt_page("my_key", "Моя страница", [
        heading("Привет"),
        text(f"Вы вошли как {login} ({role})"),
    ])


def my_handler(action, action_id, value, login, role, context,
               values):
    if action == "tap" and action_id == "do":
        return {"ok": True, "message": "Готово"}
    return {"ok": False, "error": "unknown"}


context.register_mgmt_page(
    "my_key",             # уникальный ключ
    "Моя страница",       # заголовок в сайдбаре
    my_builder,           # callable(login, role, context) -> mgmt_page
    my_handler,           # callable(...) -> dict  (или None)
    roles=None,           # None — всем; иначе tuple ролей
)
```

Builder возвращает результат `mgmt_protocol.mgmt_page(key, title,
children)`. Доступные примитивы:

- Базовые: `text`, `heading`, `caption`, `card`, `group`,
  `divider`, `spacer`, `progress`, `button`.
- Mgmt: `mgmt_toolbar(buttons)`, `mgmt_table(columns, rows,
  on_double_click, row_key, empty_label)`,
  `mgmt_form_field(id, kind, label, value, options, on_change,
  min_value, max_value)`, `mgmt_dialog(id, title, children,
  panel_kind, buttons)`, `mgmt_breadcrumb(parts, on_navigate)`,
  `mgmt_file_trigger(id, label, accept, action, download_b64,
  filename)`, `mgmt_badge(label, accent)`, `mgmt_html(html, height)`,
  `mgmt_image(src, width, height)`.

Handler получает `values` — dict всех полей формы на странице.
Возвращает `{"ok": True, "view": <новый документ>}` или
`{"ok": True, "message": "..."}` или
`{"ok": False, "error": "..."}`.

**Важно (1.0.1).** Если `handler` вернул `{"ok": True,
"view": <документ>}` — сервер использует **этот** view. Полезно
для возврата страницы с открытым диалогом или обновлённого
списка после действия. Если `view` не передан, сервер пересобирает
страницу через `builder`.

Страница плагина доступна по ключу `plugin:<name>:<key>`. В
удалённом режиме она рендерится на клиенте штатным
`mgmt_render.MgmtRenderer`, плагин на клиенте не нужен. При
активации страница сразу появляется в сайдбаре (если роль
подходит); при деактивации — исчезает.

---

## 15. HTTP-эндпоинты

```python
def get_status(request):
    return {"ok": True, "value": 42}


context.register_endpoint(
    "/plugin/hello/status", get_status, methods=("POST",))
```

Клиент: `POST /plugin/hello/status`.

Для mgmt-эндпоинтов — `register_mgmt_endpoint(path, handler,
methods)`; путь должен начинаться на `/mgmt/plugin/<name>/`.

---

## 16. Пункты меню (Android drawer)

```python
from view_protocol import make_document, ViewNode


def build_help(login, user_roles, context):
    return make_document([
        ViewNode.heading("Помощь"),
        ViewNode.text("Обратитесь к руководителю."),
    ])


context.register_menu_item(
    "my_plugin:help", "Помощь", build_help,
    roles=("picker", "receiver"),  # None — всем
)
```

Пункт попадает в `config.menu.items` (`/ui_config`) и в drawer
Android-клиента. По клику клиент зовёт `POST /menu/{id}/view`.

`builder(login, user_roles, context)` возвращает view-документ
(`view_protocol.make_document([...])`). `context` — **настоящий
`PublicContext` плагина** (в 1.0.1; раньше был пустой `_Ctx`
без `db()`/`tr()`).

---

## 17. Уведомления

```python
context.notify("Текст", type="info",
               recipient_login="ivanov")
context.notify("Текст", type="urgent",
               recipient_role="picker")
context.notify("Товар утерян", type="system",
               payload={"item_code": "ABC"})
```

Типы: `info` | `urgent` | `system`.

Если передать `payload={"key": "...", "params": {...}}` — при
отдаче клиенту текст будет переведён на его язык, а оставшиеся
`{name}` подставятся из `params`.

---

## 18. Безопасность

Плагины имеют полный доступ к БД и ядру. Устанавливайте только
те плагины, которым доверяете. Безопасность — на пользователе.

Если мажорная версия API сменится (например, с 1 на 2), старые
плагины не загрузятся, пока не будут обновлены.