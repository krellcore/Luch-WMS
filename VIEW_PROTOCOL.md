# Луч — Протокол view model для клиентов

**Протокол v1.0**

Клиент не знает предметной области. Он получает от сервера дерево
компонентов и рендерит его. Всё поведение — на сервере.

---

## 1. Корневой документ

```json
{
  "protocol": "1.0",
  "screen": "task_exec" | "session" | "container_contents"
            | "drop_containers" | "offline",
  "title": "TASK-000123",
  "children": [ { узел }, { узел }, ... ]
}
```

- `protocol` — версия протокола. Мажорная должна совпасть.
- `screen` — идентификатор экрана.
- `children` — список узлов верхнего уровня.

---

## 2. Meta (для `/view` и `/action`)

```json
{
  "task_id": 12,
  "task_type": "pick",
  "task_number": "TASK-000012",
  "status": "in_progress",
  "step_no": 3,
  "total_steps": 10,
  "finished": false,
  "pending_action": "",
  "pending_cell": "",
  "batch_id": "BATCH-20261018143000-a1b2c3",
  "block_bf": "45",
  "batch_position": 1,
  "batch_total": 2,
  "partial": 0,
  "progress": {
    "a": 3, "a_max": 10,
    "b": 0, "b_max": 0
  }
}
```

Значения `pending_action`:

| Значение | Что делать |
|---|---|
| `""` | Обычный шаг |
| `"not_found"` | Ждём скан ячейки (товар не найден) |
| `"finish_cell"` | Ждём скан ячейки (инвентаризация) |
| `"finish_container"` | Ждём скан тары (putaway) |
| `"finish_cargo"` | Ждём скан грузоместа |
| `"partial_cargo"` | Ждём скан грузоместа (частичное) |
| `"scan_close_container"` | Ждём скан тары (закрытие, pick) |
| `"scan_new_container"` | Ждём скан новой тары (pick) |
| `"drop_containers"` | Ждём скан точки/тар (pick) |
| `"unknown_item"` | Диалог (инвентаризация): две кнопки |
| `"unknown_scan_container"` | Ждём скан свободной тары (инв.) |
| `"drop_unknown"` | Ждём скан точки сброса (инв.) |

`pending_action=finish_cargo` / `partial_cargo` относятся
**только к сессии приёмки** (`/sessions/receive/*`), не к
`/tasks/*`. В потоке `/tasks/*` эти значения не появляются:
приёмка через задания заблокирована на стороне сервера.

Клиент обязан игнорировать неизвестные значения `pending_action`
(forward-compatibility).

`pending_cell` — что сканировать (ШК), либо подпись для диалога.
`progress.b_max` — для inventory и putaway обычно 0.

---

## 3. Узлы

### 3.1. text

```json
{ "type": "text", "value": "строка",
  "style": {"bold": true, "color": "#e67e22", "size": 14} }
```

### 3.2. heading

```json
{ "type": "heading", "value": "Заголовок", "level": 1 }
```

### 3.3. caption

```json
{ "type": "caption", "value": "мелкая подпись" }
```

### 3.4. card

```json
{ "type": "card", "title": "Необязательный",
  "accent": "primary|success|warning|error",
  "children": [ ... ] }
```

### 3.5. group

```json
{ "type": "group", "orientation": "vertical|horizontal",
  "spacing": 8, "children": [ ... ] }
```

### 3.6. divider

```json
{ "type": "divider" }
```

### 3.7. spacer

```json
{ "type": "spacer", "size": 12 }
```

### 3.8. progress

```json
{ "type": "progress", "value": 3, "max": 10, "label": "3 / 10" }
```

### 3.9. button

```json
{ "type": "button", "label": "Подтвердить",
  "action": "tap", "id": "confirm",
  "value": null, "style": "primary|default|danger",
  "enabled": true }
```

Если `value="ask"` — клиент показывает диалог подтверждения перед
отправкой action.

### 3.10. input

```json
{ "type": "input", "id": "qty",
  "input_type": "text|number|select",
  "label": "Количество", "value": "1",
  "options": ["a", "b"] }
```

### 3.11. list

```json
{ "type": "list", "item_renderer": "default",
  "children": [ ... ] }
```

### 3.12. tiles

```json
{ "type": "tiles",
  "items": [
    { "barcode": "BC-1", "status": "done",
      "label": "BC-1", "accent": "success" }
  ] }
```

`status` — статус шага (`pending`/`scanned`/`done`/`in_use`) или
статус тары (`free`/`accepting`/`placing`/`picking`/`waiting`/
`closed`/`unknown_scan`). `accent` — цвет
(`default`/`success`/`warning`/`primary`/`error`).

### 3.13. image

```json
{ "type": "image",
  "url": "http://...|data:image/...;base64,...",
  "width": 200, "height": 100 }
```

### 3.14. barcode

```json
{ "type": "barcode", "value": "BC-1", "label": "Товар" }
```

### 3.15. slot

```json
{ "type": "slot", "id": "step_footer", "children": [ ... ] }
```

Точка расширения для `on_view_build` плагинов.

### 3.16. webview

```json
{ "type": "webview", "html": "<h1>...</h1>", "height": 300 }
```

### 3.17. table

```json
{ "type": "table",
  "title": "Необязательный",
  "columns": [
    {"key": "photo", "label": "Фото", "type": "image", "width": 0.15},
    {"key": "name",  "label": "Название", "type": "text", "width": 0.35},
    {"key": "total", "label": "Всего", "type": "number", "width": 0.25}
  ],
  "rows": [
    {"photo": "data:image/png;base64,...",
     "name": "Товар 1", "total": 10}
  ] }
```

Колонки: `text | number | image`. `width` — доля от общей ширины.

---

## 4. Actions

Клиент отправляет:

```json
{
  "action": "tap",
  "id": "confirm",
  "value": null,
  "step_no": 3
}
```

Возможные `action`:

- `scan` — скан ШК. `value` — распознанная строка.
- `tap` — тап по кнопке. `id` — идентификатор.
- `input_submit` — ввод. `id` — id поля, `value` — значение.
- `cancel` — отмена текущего шага.
- `custom:<id>` — произвольное действие (плагины).

Поле `step_no` опциональное. Если передано, сервер проверит, что
клиент на актуальном шаге.

---

## 5. Протокол обмена

1. Клиент логинится: `POST /login`.
2. Клиент сообщает возможности:

   ```json
   POST /capabilities/hello
   {"protocol": "1.0",
    "widgets": ["text", "card", "tiles", "table", "..."],
    "actions": ["scan", "tap", "input_submit", "cancel", "custom"],
    "features": ["camera", "hardware_scan", "vibrate", "beep"],
    "device": "pc" | "android"}
   ```

3. Клиент запрашивает список сессий:

   ```json
   POST /sessions/list
   {"token": "...", "device": "pc"|"android"}
   → {"ok": true, "sessions": [{"key": "receive",
                                 "title": "Сессия приёмки"}]}
   ```

4. Клиент получает задание:

   ```json
   POST /tasks/next
   {"token": "...", "platform": "pc"|"android"|"any"}
   → {"ok": true, "task": {...}, "items": [...]}
   ```

   или

   ```json
   POST /tasks/{id}/view
   {"token": "..."}
   ```

5. Сервер возвращает `view` + `meta`.
6. Клиент рендерит.
7. Пользователь действует → клиент отправляет action:

   ```json
   POST /tasks/{id}/action
   ```

8. Сервер применяет, возвращает новый `view` + `meta`.
9. Клиент раз в 4-5 сек опрашивает:

   ```json
   POST /tasks/{id}/status
   ```

   для обнаружения удаления / завершения / передачи.

**Важно.** `/tasks/*` для `receive` заблокирован на сервере.
`POST /tasks/next` никогда не отдаёт задачу с `task_type=receive`.
`POST /tasks/{id}/view` / `/action` / `/report` / `/finish` для
`receive` возвращают `{"ok": false, "error": "..."}`. Приёмка
выполняется через `/sessions/receive/*`.

Также `/tasks/{id}/view` / `/action` / `/report` / `/finish`
проверяют, что `assignee_login` совпадает с текущим пользователем
(кроме случая, когда задача не назначена — тогда сначала
`/tasks/next`).

---

## 6. Локализация

Каждый POST-запрос клиента содержит поле `locale` (`"ru"` или
`"en"`). Сервер возвращает все строки в view на этом языке.

Если клиент не прислал `locale`, сервер берёт его из БД склада
(`settings.locale`).

Сервер возвращает `locale` в каждом JSON-ответе. Клиент может
использовать это для синхронизации (например, если другой
руководитель сменил язык).

Язык **хранится на клиенте** и не влияет на других клиентов —
несколько клиентов могут работать одновременно на разных языках.

---

## 7. Деградация под возможности

Если клиент не поддерживает узел — сервер понижает:

| Узел | Куда |
|---|---|
| `tiles` | `list` |
| `table` | `list` (каждая строка как text «Label: value») |
| `webview` | `text` с пометкой |
| `barcode` | `text` |
| `image` | `text` |

---

## 8. Офлайн

Клиент блокируется при потере связи. При восстановлении
перезапрашивает view текущего шага (или сессии).

Сервер при активном задании продлевает резервы на каждом
`view`/`action`/`status`.

---

## 9. Расширения от плагинов

Плагин влияет на view тремя путями:

- hook `on_view_build` — обогатить готовое дерево;
- `context.register_step_handler` — вернуть свой view для шага;
- `context.add_barcode_button` — добавить кнопку в панель.

Все расширения работают в тех же примитивах, что и встроенные.

---

## 10. Сессии

Сессия — долгоживущий процесс (например, приёмка). Работает поверх
того же view-протокола, но отдельными эндпоинтами.

```json
POST /sessions/list
{"token": "...", "device": "pc"}
→ {"ok": true,
   "sessions": [{"key": "receive",
                 "title": "Сессия приёмки"}]}

POST /sessions/{key}/start
{"token": "...", "payload": {...}, "device": "pc"}
→ {"ok": true,
   "view": {...},
   "meta": {
     "session_key": "receive",
     "session_title": "Сессия приёмки",
     "state": {"container_barcode": "TAR-1", ...}
   }}

POST /sessions/{key}/action
{"token": "...", "id": "take_container",
 "value": "TAR-1", "device": "pc"}
→ {"ok": true, "message": "...",
   "view": {...}, "meta": {...}}

POST /sessions/{key}/close
{"token": "...", "device": "pc"}
→ {"ok": true, "message": "Сессия закрыта"}
```

Значения `id` зависят от сессии. Для receive:

- `take_container` — взять тару (value = ШК).
- `cancel_container` — отменить тару (value = ШК).
- `finish_container` — закрыть тару (value = ШК).
- `finish_cargo` — закрыть ГМ (pending + скан).
- `partial_cargo` — частичное закрытие.
- `_scan_` — универсальный скан (сервер сам решает).

`device` передаётся в каждом запросе `/sessions/*`. Сервер фильтрует
сессии по `platforms`. Например, `receive.platforms=("pc",)` — на
Android эта сессия не появится в списке и не запустится.

Состояние сессии хранится на сервере (таблица `sessions`) и
приходит клиенту в `meta.state`. Клиент может его игнорировать —
всё равно рендерит view.

**Приёмка — только через эту сессию.** Через `/tasks/*` она
заблокирована. Задание `receive`, созданное в старых версиях,
при попытке открытия вернёт `{"ok": false, "error": "..."}`.

---

## 11. Хранение состояния

Клиент должен:

- хранить последний view (для мгновенного показа);
- отправлять action с правильным `step_no`;
- при ошибке — запросить актуальный view через `/view` или `/status`.

Сервер хранит:

- `task_plan` (JSON) — список шагов. `prompt` хранится как
  `prompt_key` + `prompt_params` (переводится при рендере);
  старые задачи с готовым `prompt` поддерживаются как fallback;
- `current_step_no`;
- `pending_action` / `pending_cell`;
- состояние сессии в таблице `sessions`.

Поле `platform` в `/tasks/next` — фильтр: если задание имеет
`platform='pc'`, оно не появится у клиента с `platform='android'`
(и наоборот). `platform='any'` доступно везде.