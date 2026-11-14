# Луч — Плагины: установка, разработка, API

Версия **1.0.0**

Руководство для пользователей и разработчиков. Справочник по
API — `PLUGIN_API.md`.

---

## 1. Что такое плагин

Плагин — это **папка** в `plugins/`, внутри которой:

- `plugin.json` — характеристики (обязательно);
- `plugin.py` — код (имя настраивается через `entry`);
- `lang/` — языки плагина (опционально);
- любые дополнительные файлы (`helpers.py`, шаблоны, ресурсы),
  если они нужны для работы.

Плагин — полноценный Python-код с доступом к БД, hooks, UI,
HTTP-эндпоинтам. Устанавливайте только доверенные плагины.

Активация хранится в настройках склада (`settings.active_plugins`)
и распространяется только на тот склад, где была сделана.

### Совместимость

Старый формат — один `.py`-файл в `plugins/` — **работает**. Из
него читается `PLUGIN_INFO`, файл грузится как обычный модуль.
Новые плагины рекомендуется делать папками: они поддерживают
доп. файлы, относительные импорты, языки и аккуратнее
изолированы.

Если в `plugins/` есть и папка, и `.py`-файл с одинаковым
именем — выигрывает папка (новый формат).

---

## 2. Установка и активация

1. Скопируйте папку плагина в `plugins/`.
   Например: `plugins/my_plugin/` → в ней `plugin.json`,
   `plugin.py` и, если нужно, `lang/`, `helpers.py`.
2. ПК-клиент управления → «🧩 Плагины» → «Обновить».
3. Двойной клик по плагину → «Активировать».

Деактивация — там же. При деактивации ядро автоматически:

- снимает подписки на hooks;
- удаляет зарегистрированные страницы, эндпоинты, menu-пункты;
- снимает роли, зарегистрированные плагином;
- вызывает `unregister(context)`, если плагин её объявил.

В **safe mode** (`--safe`) плагины не загружаются. Используйте
этот режим, если плагин сломал склад: заходите в safe mode,
деактивируйте проблемный, перезапускайте без `--safe`.

---

## 3. Структура папки плагина

```
plugins/
└── my_plugin/
    ├── plugin.json         ← характеристики (обязательно)
    ├── plugin.py           ← код (entry из plugin.json)
    ├── lang/               ← (опционально) языки
    │   ├── ru.json
    │   └── en.json
    ├── helpers.py          ← (опционально) доп. модули
    ├── templates/          ← (опционально) ресурсы
    └── ...
```

Папки, начинающиеся с `_` или `.`, сканер пропускает — это
удобно для шаблонов (`plugins/_template/`) и «черновиков».

Имя папки = имя плагина. Поле `name` в `plugin.json` должно
совпадать с именем папки; если не совпадает, ядро всё равно
использует имя папки (и пишет предупреждение в лог).

---

## 4. `plugin.json` — справочник полей

```json
{
  "name": "my_plugin",
  "title": "Мой плагин",
  "version": "1.0.0",
  "api_version": "1.0",
  "author": "Автор",
  "description": "Краткое описание.",
  "entry": "plugin.py",
  "hooks": [],
  "creates_tables": [],
  "reads_tables": [],
  "writes_tables": [],
  "dependencies": []
}
```

| Поле | Обязательно | Что значит |
|---|---|---|
| `name` | да | Имя плагина. Должно совпадать с именем папки. |
| `title` | да | Человеческое название для UI. |
| `version` | да | semver, `"1.0.0"`. |
| `api_version` | рекомендуется | Версия API (`"1.0"`). Если мажор не совпадает с ядром — активация отклоняется. |
| `author` | нет | Автор. |
| `description` | нет | Описание. |
| `entry` | нет | Имя Python-файла внутри папки (по умолчанию `plugin.py`). |
| `hooks` | нет | Список используемых hooks (для UI). |
| `creates_tables` | нет | Какие таблицы создаёт. |
| `reads_tables` | нет | Какие таблицы читает. |
| `writes_tables` | нет | В какие таблицы пишет. |
| `dependencies` | нет | Имена других плагинов, от которых зависит. |

---

## 4.1. Языки плагина — `plugins/<name>/lang/*.json`

Плагин может хранить свои переводы **рядом с собой**:

```
plugins/my_plugin/
├── plugin.json
├── plugin.py
└── lang/
    ├── ru.json
    ├── en.json
    └── de.json
```

Формат — как у основных `lang/*.json`, **но без `_meta`**
(метаданные языка задаёт основной `lang/<code>.json`; если
такого нет — ядро возьмёт имя языка из builtin-словаря).

Ключи в файле — **простые** (`audit.title`, `btn.create`).
Ядро при загрузке оборачивает их в `plugin.<name>.` и мержит
в общий словарь. Коллизий между плагинами нет.

В коде плагина:

```python
context.tr("audit.title")                # → plugin.my_plugin.audit.title
context.tr("audit.prompt", addr="A1")    # подставит {addr}
context.tr_in("de", "audit.title")       # явная локаль
```

Если ключа в `plugin.<name>.<key>` нет, `context.tr` падает
в обычный `tr(key)` — можно переиспользовать общие строки
(`common.cancel`, `common.refresh` и т.п.).

Языковые файлы плагина читаются при загрузке сервера и при
`reload_locales()`. Плагин не обязан быть активирован —
языки загружаются из папки всегда (если плагин деактивирован,
строки просто никто не использует).

### `prompt_key` в `task_plan`

Клиент (`view_builder._prompt`) зовёт `tr(key)` без контекста
плагина. Поэтому в `build_steps` указывайте **полный** ключ:

```python
"prompt_key": "plugin.my_plugin.audit.prompt_scan_cell",
"prompt_params": {"addr": addr},
```

`context.tr` для этого не подходит (он умеет только внутри
вызова). Используйте `f"plugin.{self.PLUGIN_NAME}.{key}"`.

---

## 5. `plugin.py` — точка входа

```python
def register(context):
    """Вызывается при активации. Здесь регистрируем hooks,
    страницы, эндпоинты, menu-пункты и т.д."""
    context.log("hello from my_plugin")

def unregister(context):
    """Вызывается при деактивации. Необязательна.

    Ядро само снимает hooks/pages/endpoints/menu/roles, здесь —
    только ваша ручная очистка (файлы, сокеты и т.п.)."""
    context.log("bye from my_plugin")
```

`context` — объект `PublicContext` из `utils/api_public.py`.
Через него идёт **весь** доступ к ядру (см. `PLUGIN_API.md`).

### Дополнительные файлы

Папка плагина загружается как пакет `luch_plugin_<name>`,
поэтому внутри плагина работают **относительные** импорты:

```python
from . import helpers            # helpers.py рядом с plugin.py
from .helpers import foo
```

Абсолютный `import helpers` работать **не будет** — не
добавляйте папку плагина в `sys.path` вручную. Используйте
относительный импорт.

---

## 6. Что умеет плагин

Ниже — полный список возможностей. Подробные сигнатуры —
`PLUGIN_API.md`.

### 6.0. Роли сотрудников

```python
context.register_role(
    "audit",                      # ключ (сохраняется в employees.roles)
    title_key="audit.role_title", # i18n-ключ (без префикса)
    title="Аудит ячеек",          # fallback
    task_types=("audit",),        # что видит в /tasks/next
)
```

После регистрации роль:

- появляется **чекбоксом** в карточке сотрудника;
- появляется в **фильтре** «Сотрудники → Роль» и
  «Уведомления → По роли»;
- учитывается в `/tasks/next`: если `task_types` содержит
  тип задания, сотрудник с этой ролью будет их получать.

Деактивация плагина убирает роль из UI, но значения в
`employees.roles` (JSON) сохраняются. При следующей правке
карточки они не теряются (код сохраняет «неизвестные» роли,
которых нет в реестре).

Никаких «дописываний в `employees.roles`» делать не нужно —
это теперь штатная операция.

### 6.1. Читать и писать БД

```python
rows = context.query("SELECT * FROM my_table")
row  = context.query_one("SELECT ... WHERE id=?", (42,))
n, last_id = context.execute("INSERT INTO my_table ...", (v,))

# низкоуровневое соединение (для транзакций)
conn = context.db()
cur = conn.cursor()
cur.execute(...)
conn.commit()
conn.close()
```

Свои таблицы — через `CREATE TABLE IF NOT EXISTS`. Свои колонки
в базовых таблицах — идемпотентно через `PRAGMA table_info`.

### 6.2. Настройки

```python
v = context.get_setting("my_key", default=None)
context.set_setting("my_key", "value")
```

### 6.3. Готовые обёртки

```python
context.get_task(task_id)          # dict | None
context.get_items(task_id)         # list[dict]
context.get_cell(barcode)          # dict | None
context.get_item(item_code)        # dict | None
context.find_cells_with_item(item_code, exclude_cell=None)
```

### 6.4. Hooks

Три вида:

- **chain** — по очереди до первого не-`None`. Перехватывают
  действие (`on_scan`).
- **event** — все вызываются, результат игнорируется (логирование).
- **filter** — каждый получает значение от предыдущего и может
  вернуть новое (`on_view_build`, `on_ui_config`).

```python
@context.hook("on_scan", priority=100)
def intercept(*, task, step, barcode, login, context):
    if barcode.startswith("SPECIAL-"):
        return {"handled": True, "message": "перехвачено"}
    return None
```

Полный список hooks — `PLUGIN_API.md`, раздел 8.

### 6.5. Свой тип задания

```python
from tasks.base import TaskHandler

class MyHandler(TaskHandler):
    task_type = "my_type"
    title = "Мой тип"
    default_platform = "android"

    def build_steps(self, task, items, settings): ...
    def handle_scan(self, cur, task, step, barcode, items, settings): ...
    def handle_action(self, cur, task, step, action_id, value,
                      items, settings): ...

def register(context):
    context.register_task_handler(MyHandler())
```

Wizard создания задач подхватывает `my_type` автоматически
(если `register_role` свяжет роль с этим типом).

### 6.6. Своя сессия

```python
from sessions.base import SessionHandler

class MySession(SessionHandler):
    key = "my_session"
    title = "Моя сессия"
    platforms = ("pc",)

    def can_start(self, login, roles): ...
    def start(self, cur, login, payload): ...
    def get_state(self, cur, login): ...
    def handle_action(self, cur, login, action_id, value, settings): ...
    def get_view(self, cur, login, settings, caps): ...
    def close(self, cur, login, force=False): ...

def register(context):
    context.register_session(MySession())
```

Сессии с `platforms=("android",)` появятся на Android-клиенте,
с `("pc",)` — на ПК-терминале, `("any",)` — везде.

### 6.7. Обработчик шага

```python
def my_step(*, task, items, step, barcode, settings, context):
    return {"ok": True, "message": "готово", "stay_on_step": False}

context.register_step_handler("my_step_type", my_step, priority=0)
```

Позволяет использовать свой `type` шага в `task_plan` без
переписывания всего `TaskHandler`.

### 6.8. mgmt-страница (все режимы, включая удалённый)

```python
from mgmt_protocol import mgmt_page, heading, text

def builder(login, role, context):
    return mgmt_page("my_key", "Моя страница", [
        heading("Привет"),
        text(f"Вы {login} ({role})"),
    ])

def handler(action, action_id, value, login, role, context, values):
    if action == "tap" and action_id == "do":
        return {"ok": True, "message": "Готово"}
    return {"ok": False, "error": "unknown"}

context.register_mgmt_page(
    "my_key", "Моя страница", builder, handler,
    roles=("owner", "admin"),  # None — всем
)
```

Страница появится в сайдбаре **всех** режимов. Плагин на
клиенте не нужен — рендерится штатным `mgmt_render`.

### 6.9. Qt-страница (legacy, только локальный режим)

```python
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

class MyPage(QWidget):
    def __init__(self, db_path, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Моя страница"))

context.register_page("my_key", "Моя страница", MyPage)
```

`register_page` передаёт **Qt-класс**, который инстанцируется
**на клиенте**. Работает **только** в локальном режиме («Сервер
+ клиент» на одном ПК). В удалённом и headless — используйте
`register_mgmt_page`.

### 6.10. HTTP-эндпоинт (терминалы)

```python
def status(request):
    return {"ok": True, "value": 42}

context.register_endpoint(
    "/plugin/my_plugin/status", status, methods=("POST",))
```

Клиент: `POST /plugin/my_plugin/status`.

### 6.11. mgmt-эндпоинт

```python
def do_thing(request):
    return {"ok": True}

context.register_mgmt_endpoint(
    "/mgmt/plugin/my_plugin/do", do_thing, methods=("POST",))
```

Путь должен начинаться с `/mgmt/plugin/<name>/`.

### 6.12. Пункт бокового меню (Android drawer)

```python
from view_protocol import make_document, ViewNode

def build_help(login, user_roles, context):
    return make_document([
        ViewNode.heading("Помощь"),
        ViewNode.text("Текст"),
    ])

context.register_menu_item(
    "my_plugin:help", "Помощь", build_help,
    roles=("picker", "receiver"),  # None или ("any",) — всем
)
```

Пункт появится в drawer Android-клиента и в `config.menu.items`
из `/ui_config`. По клику клиент зовёт `POST /menu/{id}/view`.

### 6.13. Уведомления сотрудникам

```python
context.notify("Текст", type="info", recipient_login="ivanov")
context.notify("Текст", type="urgent", recipient_role="picker")
context.notify("Товар утерян", type="system",
               payload={"item_code": "ABC"})
```

Типы: `info` | `urgent` | `system`.

### 6.14. Кнопка на панели ШК (legacy)

```python
def on_print(kind, code, parent):
    # kind: "cell" | "container" | ...
    QMessageBox.information(parent, "Печать", f"{kind}: {code}")

context.add_barcode_button("🖨 Печать", on_print,
                           panel_filter=lambda k: k == "cell")
```

Только локальный режим (Qt-панели на клиенте).

---

## 7. Примеры

В комплекте:

- **`plugins/example_printer/`** — минимальный плагин с одним
  hook `on_scan_after` (логирование).
- **`plugins/example_hooks/`** — перехват `on_scan`, свой
  `TaskHandler`, модификация view через `on_view_build`,
  **плюс `helpers.py`** как пример доп. модуля.
- **`plugins/example_audit/`** — полный пример: mgmt-страница,
  пункт меню ТСД, свой тип задания `audit`, **своя роль
  `audit`**, **своя папка `lang/`** с тремя языками.
- **`plugins/_template/`** — пустой каркас для нового плагина
  (сканер пропускает `_`-папки, скопируйте и переименуйте).

Порядок запуска нового плагина:

```bash
cp -r plugins/_template plugins/my_plugin
# отредактировать plugins/my_plugin/plugin.json и plugin.py
```

Затем в ПК-клиенте → «Плагины» → «Обновить» → «Активировать».

---

## 8. Безопасный режим

`python utils/wms.py warehouses/<name> --safe`

В safe mode:

- плагины **не активируются**;
- сервер работает, все mgmt-разделы доступны;
- в сайдбаре — плашка «SAFE MODE»;
- в «Плагинах» — предупреждающая плашка, кнопка
  «Активировать» заблокирована, «Деактивировать» доступна.

Если плагин сломал склад: safe mode → деактивировать → без
`--safe`.

---

## 9. Версии API

В `plugin.json` можно указать `api_version`. Мажорная версия
должна совпадать с ядром (`1.x`). Иначе активация отклоняется.

Текущая версия — **1.0**. При смене мажора ядро не загрузит
старые плагины, пока они не обновятся.

---

## 10. FAQ и частые ошибки

**«Плагин не появляется в списке».**
- Проверьте, что папка в `plugins/`, а не рядом с `main.py`.
- Есть ли `plugin.json` в корне папки?
- Имя папки начинается с `_` или `.`? Такие пропускаются.
- Нажмите «Обновить» в «Плагинах».

**«register() упал: ImportError: no module named helpers».**
Используйте относительный импорт: `from . import helpers`,
`from .helpers import foo`. Абсолютный `import helpers` не
работает.

**«name в plugin.json не совпадает с папкой».**
Предупреждение в логе сервера. Имя папки имеет приоритет.
Переименуйте папку или поправьте `plugin.json`.

**«Плагин работает в локальном режиме, но не в удалённом».**
Скорее всего, используется `register_page` (Qt-виджет на
клиенте) или `add_barcode_button`. Замените на
`register_mgmt_page` / используйте mgmt-эндпоинты.

**«Мажор api_version не совпадает».**
Обновите плагин под текущий API ядра. Или понизьте
`api_version` в `plugin.json`, если плагин действительно
совместим (на свой риск).

**«Мой hook не вызывается».**
- Проверьте имя hook в `PLUGIN_API.md`, раздел 8.
- Порядок вызова = приоритет (больше — раньше).
- Для `chain`: возврат не-`None` останавливает цепочку.

**«Плагин нормально работает, но после перезапуска — нет».**
Проверьте `settings.active_plugins` в БД склада — там должен
быть ваш плагин. Если склад копировался между машинами,
возможно, плагин активирован на одной и отсутствует на другой.

**«В safe mode активация недоступна».**
Так и задумано. Запустите без `--safe`.

**«Роль из плагина не видна в карточке сотрудника».**
- Плагин активирован?
- В логе сервера есть `[plugin:<name>] role registered: <key>`?
- Перезапустите клиент или перезайдите в раздел «Сотрудники».

**«Перевод из lang/ плагина не подхватывается».**
- Файл в `plugins/<name>/lang/<code>.json`?
- Ключи в файле — простые (`audit.title`), не `plugin.<name>.audit.title`.
- `reload_locales()` вызывался (или сервер перезапущен)?

---

## 11. Безопасность

Плагины имеют **полный доступ** к БД, файлам сервера и
внутренним API. Устанавливайте только те, которым доверяете.

Если мажорная версия API сменится (например, с 1 на 2),
старые плагины не загрузятся, пока не будут обновлены.