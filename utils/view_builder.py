"""Сборка view-документа для клиента."""

from view_protocol import ViewNode, make_document
from capabilities import registry as cap_registry
from i18n import tr

CONTAINER_STATUS_LABELS = {
    "free": "свободна",
    "accepting": "приёмка",
    "placing": "к размещению",
    "picking": "подбор",
    "waiting": "ожидает",
    "closed": "закрыта",
    "dropped": "сброшена",
    "unknown_scan": "неизвестные ШК",
}

def _container_status_accent(status):
    return {
        "done": "success",
        "in_use": "primary",
        "scanned": "warning",
        "pending": "default",
        "free": "default",
        "accepting": "warning",
        "placing": "primary",
        "picking": "primary",
        "waiting": "success",
        "closed": "warning",
        "dropped": "success",
        "unknown_scan": "warning",
    }.get(status or "pending", "default")

def _prompt(step, fallback=""):
    """Рендер prompt шага.

    Приоритет: prompt_key + prompt_params (перевод через tr()).
    Fallback: готовый step["prompt"] — для задач, созданных
    до перехода на prompt_key (этап 2.5).
    """
    if not step:
        return fallback
    key = step.get("prompt_key")
    if key:
        params = step.get("prompt_params") or {}
        try:
            return tr(key, **params)
        except Exception:
            pass
    return step.get("prompt") or fallback

def _tiles_from_containers(containers):
    items = []
    for c in containers or []:
        status = c.get("status", "pending")
        placed_in = (c.get("placed_in") or "").strip()
        if placed_in:
            accent = "success"
        else:
            accent = _container_status_accent(status)
        items.append({
            "barcode": c.get("barcode", ""),
            "status": status,
            "label": c.get("barcode", ""),
            "accent": accent,
        })
    return ViewNode.tiles(items)

def _progress_node(progress):
    a = progress.get("a", 0)
    a_max = progress.get("a_max", 0)
    b = progress.get("b", 0)
    b_max = progress.get("b_max", 0)
    if b_max > 0:
        parts = f"{a}/{a_max}  ·  {b}/{b_max}"
        total = a_max + b_max
        cur = a + b
    else:
        parts = f"{a}/{a_max}"
        total = a_max
        cur = a
    if total <= 0:
        return None
    return ViewNode.progress(cur, total, label=parts)

def _photo_node(data):
    b64 = data.get("photo_b64")
    if b64:
        return ViewNode.image(b64, width=200, height=200)
    return ViewNode.caption(tr("view.no_photo", "Нет фото"))

def _counter_text(step, task):
    d = step.get("data") or {}
    lines = []
    if d.get("scanned_qty") is not None and d.get("quantity_total"):
        lines.append(tr("view.position", "Позиция: {scanned} / {total}", 
                        scanned=d['scanned_qty'], total=d['quantity_total']))
    if d.get("cell_scanned") is not None and d.get("cell_total"):
        lines.append(tr("view.from_cell", "Из ячейки: {scanned} / {total}", 
                        scanned=d['cell_scanned'], total=d['cell_total']))
    if (d.get("action") == "receive_scan"
            and d.get("received_total") is not None):
        lines.append(tr("view.received", "Принято: {received} / {expected}", 
                        received=d['received_total'], expected=d['expected_total']))
    return "\n".join(lines) if lines else None

def _render_scan_container(task, step, items, settings, ctx):
    phase = (step.get("data") or {}).get("phase") or ""
    ttype = task.get("task_type")
    parts = []
    if phase == "collect":
        containers = (step.get("data") or {}).get("containers") or []
        done = sum(1 for c in containers
                   if c.get("status") != "pending")
        total = len(containers)
        parts.append(ViewNode.heading(
            _prompt(step, tr("view.scan_container",
                             "Сканируйте тару"))))
        parts.append(ViewNode.caption(
            tr("view.scanned", "Отсканировано: {done} / {total}", done=done, total=total)))
        if containers:
            parts.append(_tiles_from_containers(containers))
    elif phase == "place":
        containers = (step.get("data") or {}).get("containers") or []
        parts.append(ViewNode.heading(
            _prompt(step, tr("view.select_container",
                             "Выберите тару"))))
        if containers:
            parts.append(_tiles_from_containers(containers))
    else:
        parts.append(ViewNode.heading(
            _prompt(step, tr("view.scan_container",
                             "Сканируйте тару"))))
        if ttype in ("pick", "receive"):
            parts.append(ViewNode.caption(
                tr("view.only_free_container",
                   "Только свободная тара (не в задании)")))
        allowed = (step.get("data") or {}).get(
            "allowed_containers")
        if allowed:
            parts.append(ViewNode.caption(
                tr("view.allowed_containers",
                   "Тара из задания: {list}",
                   list=", ".join(allowed))))
    return parts

def _render_scan_cell(task, step, items, settings, ctx):
    parts = [ViewNode.heading(
        _prompt(step, tr("view.scan_cell",
                         "Сканируйте ячейку")))]
    expected = (step.get("data") or {}).get("expected_barcode")
    if expected:
        parts.append(ViewNode.caption(
            tr("view.expected", "Ожидается: {barcode}",
               barcode=expected)))
    addr = (step.get("data") or {}).get("cell_address")
    if addr:
        parts.append(ViewNode.caption(
            tr("view.cell_addr", "Адрес: {addr}", addr=addr)))
    return parts

def _render_scan_item(task, step, items, settings, ctx):
    d = step.get("data") or {}
    action = d.get("action") or ""
    ttype = task.get("task_type")

    if action == "receive_scan":
        parts = [ViewNode.heading(
            _prompt(step, tr("task.recv.prompt_item",
                             "Сканируйте товары")))]
        items_list = d.get("items") or []
        if items_list:
            card_children = []
            for it in items_list:
                row_children = []
                row_children.append(ViewNode.text(
                    it.get("item_name") or it.get("item_code") or "—",
                    style={"bold": True}))
                bc = it.get("item_barcode") or ""
                if bc:
                    row_children.append(ViewNode.caption(
                        tr("view.shk", "ШК: {barcode}",
                           barcode=bc)))
                row_children.append(ViewNode.caption(
                    tr("view.received",
                       "Принято: {received} / {expected}", 
                       received=it.get('scanned', 0),
                       expected=it.get('expected', 0))))
                if it.get("extra"):
                    row_children.append(ViewNode.caption(
                        tr("view.extra_plan", "сверх плана")))
                row_children.append(_photo_node(it))
                card_children.append(ViewNode.card(row_children))
            parts.append(ViewNode.text(
                tr("view.items_in_cargo",
                   "Товары в грузоместе:")))
            parts.extend(card_children)
        counter = _counter_text(step, task)
        if counter:
            parts.append(ViewNode.text(counter, style={"bold": True}))
        return parts

    if action == "inventory_scan":
        parts = [ViewNode.heading(
            _prompt(step, tr("task.inv.prompt_item",
                             "Сканируйте товары в ячейке")))]
        cnt = d.get("cell_scanned")
        if cnt is None:
            cnt = 0
        parts.append(ViewNode.text(
            tr("view.found", "Найдено: {count}", count=cnt),
            style={"bold": True}))
        return parts

    if ttype == "putaway" and action == "putaway_scan":
        parts = [ViewNode.heading(
            _prompt(step, tr("task.put.prompt_item",
                             "Сканируйте товары из тары")))]
        cell_addr = d.get("cell_address") or ""
        if cell_addr:
            parts.append(ViewNode.caption(
                tr("view.cell", "Ячейка: {addr}", addr=cell_addr)))
        return parts

    parts = [ViewNode.heading(
        _prompt(step, tr("view.scan_item",
                         "Сканируйте товар")))]

    addr = d.get("cell_address") or d.get("cell_barcode") or ""
    if addr:
        parts.append(ViewNode.text(
            tr("view.cell", "Ячейка: {addr}", addr=addr),
            style={"bold": True}))

    name = d.get("item_name")
    bc = d.get("expected_barcode")
    qty = d.get("quantity")
    if name:
        parts.append(ViewNode.text(f"«{name}»"))
    if bc:
        parts.append(ViewNode.caption(
            tr("view.shk", "ШК: {barcode}", barcode=bc)))
    if qty:
        parts.append(ViewNode.caption(
            tr("view.qty", "Кол-во: {qty}", qty=qty)))
    parts.append(_photo_node(d))
    counter = _counter_text(step, task)
    if counter:
        parts.append(ViewNode.text(counter, style={"bold": True}))
    return parts

def _render_confirm(task, step, items, settings, ctx):
    action = (step.get("data") or {}).get("action") or ""
    label = {
        "start_putaway": tr("view.btn_start",
                            "Приступить к заданию"),
        "finish_container": tr("view.btn_finish_container",
                               "Закончить тару"),
        "finish_task": tr("view.btn_finish_task",
                          "Завершить задание"),
        "finish_cell": tr("view.btn_finish_cell",
                          "Закончить ячейку"),
    }.get(action, tr("view.btn_confirm", "Подтвердить"))
    parts = [ViewNode.heading(
        _prompt(step, tr("view.confirm", "Подтвердите")))]
    parts.append(ViewNode.button(
        label, action="tap", action_id="confirm",
        style="primary"))
    return parts

_RENDERERS = {
    "scan_container": _render_scan_container,
    "scan_cell": _render_scan_cell,
    "scan_item": _render_scan_item,
    "confirm": _render_confirm,
}

def _extra_buttons(task, step, ctx):
    try:
        from tasks import get_handler
    except Exception:
        return []
    handler = get_handler(task.get("task_type"))
    if not handler:
        return []
    try:
        return handler.extra_buttons(task, step) or []
    except Exception as e:
        print("view_builder._extra_buttons:", e)
        return []

def _render_pending(task):
    pending_action = (task.get("pending_action") or "").strip()
    pending_cell = task.get("pending_cell") or ""
    can_cancel = bool(task.get("can_cancel_pending", True))

    if pending_action == "unknown_item":
        return [
            ViewNode.heading(tr("view.unknown_title",
                                "Неизвестный ШК")),
            ViewNode.card([
                ViewNode.text(
                    tr("view.unknown_text",
                       "ШК: {barcode}", barcode=pending_cell),
                    style={"bold": True}),
                ViewNode.caption(
                    tr("view.unknown_hint",
                       "Такого товара нет в базе. "
                       "Что сделать?")),
            ], accent="warning"),
            ViewNode.group([
                ViewNode.button(
                    tr("view.btn_skip_unknown",
                       "Найти другой ШК"),
                    action="tap", action_id="cancel_pending"),
                ViewNode.button(
                    tr("view.btn_move_to_container",
                       "Переложить в тару"),
                    action="tap", action_id="unknown_to_container",
                    style="primary"),
            ], orientation="vertical"),
        ]

    if pending_action == "unknown_scan_container":
        return [
            ViewNode.heading(tr(
                "view.scan_free_container_title",
                "Переложить в тару")),
            ViewNode.card([
                ViewNode.text(
                    tr("view.scan_free_container_item",
                       "Товар: {barcode}", barcode=pending_cell),
                    style={"bold": True}),
                ViewNode.caption(tr(
                    "view.scan_free_container_hint",
                    "Сканируйте свободную тару. Первая тара "
                    "будет закреплена за заданием.")),
            ], accent="primary"),
            ViewNode.button(tr("view.btn_cancel", "Отменить"),
                            action="tap",
                            action_id="cancel_pending"),
        ]

    if pending_action == "drop_unknown":
        return [
            ViewNode.heading(tr(
                "view.drop_unknown_title",
                "Сброс тар с неизвестными ШК")),
            ViewNode.card([
                ViewNode.text(
                    tr("view.drop_unknown_containers",
                       "Тары: {containers}",
                       containers=pending_cell),
                    style={"bold": True}),
                ViewNode.caption(tr(
                    "view.drop_unknown_hint",
                    "Отнесите тары на точку сброса и "
                    "отсканируйте её ШК.")),
            ], accent="warning"),
            ViewNode.button(tr("view.btn_cancel", "Отменить"),
                            action="tap",
                            action_id="cancel_pending"),
        ]

    if pending_action == "not_found":
        title = tr("view.pending_not_found",
                   "Товар не найден: подтверждение")
        hint = tr("view.pending_not_found_hint",
                  "Сканируйте ту же ячейку, в которой должен "
                  "был быть товар, чтобы подтвердить")
    elif pending_action == "finish_cell":
        title = tr("view.pending_finish_cell",
                   "Завершение ячейки: подтверждение")
        hint = tr("view.pending_finish_cell_hint",
                  "Сканируйте ячейку, которую пересчитывали")
    elif pending_action == "finish_container":
        title = tr("view.pending_finish_container",
                   "Закрытие тары: подтверждение")
        hint = tr("view.pending_finish_container_hint",
                  "Сканируйте ШК тары, чтобы подтвердить "
                  "закрытие")
    elif pending_action == "finish_cargo":
        title = tr("view.pending_finish_cargo",
                   "Закрытие грузоместа: подтверждение")
        hint = tr("view.pending_finish_cargo_hint",
                  "Сканируйте ШК грузоместа для подтверждения")
    elif pending_action == "partial_cargo":
        title = tr("view.pending_partial_cargo",
                   "Частичное завершение: подтверждение")
        hint = tr("view.pending_partial_cargo_hint",
                  "Сканируйте ШК грузоместа, чтобы подтвердить. "
                  "Остаток вернётся в очередь.")
    elif pending_action == "scan_close_container":
        title = tr("view.pending_scan_close", "Закрытие тары")
        hint = tr("view.pending_scan_close_hint",
                  "Сканируйте ШК тары, которую хотите закрыть.")
    elif pending_action == "scan_new_container":
        title = tr("view.pending_scan_new", "Новая тара")
        hint = tr("view.pending_scan_new_hint",
                  "Сканируйте ШК любой свободной тары")
    elif pending_action == "drop_containers":
        title = tr("view.pending_drop", "Сброс закрытых тар")
        hint = tr("view.pending_drop_hint",
                  "Сканируйте ШК точки сброса")
    else:
        title = tr("view.confirm", "Подтверждение")
        hint = tr("view.scan_cell", "Сканируйте ячейку")

    if pending_action == "scan_new_container":
        card_text = tr("view.scan_new_container",
                       "Сканируйте ШК новой тары")
    else:
        card_text = tr("view.scan_shk",
                       "Сканируйте ШК: {cell}", cell=pending_cell)

    parts = [
        ViewNode.heading(title),
        ViewNode.card([
            ViewNode.text(card_text),
            ViewNode.caption(hint),
        ], accent="warning"),
    ]
    if can_cancel:
        parts.append(ViewNode.button(
            tr("view.btn_cancel", "Отменить"), action="tap",
            action_id="cancel_pending"))
    return parts

def _header_nodes(task):
    task_type = (task.get("task_type") or "").upper()
    task_number = task.get("task_number") or ""
    block_bf = (task.get("block_bf") or "").strip()
    batch_id = (task.get("batch_id") or "").strip()

    header = f"{task_type}  {task_number}"
    if block_bf:
        header += f"  ·  B{block_bf}"
    nodes = [ViewNode.heading(header)]

    if batch_id:
        nodes.append(ViewNode.caption(
            tr("view.order", "Заказ: {id}", id=batch_id)))

    if int(task.get("partial") or 0):
        nodes.append(ViewNode.caption(
            tr("view.partial_warn", "⚠ Частичное задание")))

    created = (task.get("created_at") or "")[:19]
    if created:
        nodes.append(ViewNode.caption(
            tr("view.created", "Создано: {date}", date=created)))
    return nodes

def build_step_view(task, step, items, settings, context=None,
                    capabilities=None, extra_state=None):
    parts = []
    parts.extend(_header_nodes(task))

    progress = {
        "a": task.get("processed_a", 0),
        "a_max": task.get("target_a", 0),
        "b": task.get("processed_b", 0),
        "b_max": task.get("target_b", 0),
    }
    if task.get("task_type") == "inventory":
        progress["b_max"] = 0
    elif task.get("task_type") == "putaway":
        container_total = 0
        container_placed = 0
        if step is not None:
            sd = step.get("data") or {}
            container_total = int(sd.get("container_total") or 0)
            container_placed = int(sd.get("container_placed") or 0)
        if container_total > 0:
            progress["a"] = container_placed
            progress["a_max"] = container_total
            progress["b"] = 0
            progress["b_max"] = 0

    pnode = _progress_node(progress)
    if pnode:
        parts.append(pnode)

    pending = (task.get("pending_action") or "").strip()

    if pending == "drop_containers":
        return build_drop_view(task, step, items, settings,
                                context=context,
                                capabilities=capabilities)

    if pending:
        parts.extend(_render_pending(task))
    else:
        if step is None:
            parts.append(ViewNode.text(
                tr("view.loading", "Загрузка...")))
        else:
            stype = step.get("type")
            renderer = _RENDERERS.get(stype)
            if renderer:
                card_children = renderer(task, step, items,
                                          settings, context)
            else:
                card_children = [ViewNode.text(
                    _prompt(step,
                            tr("view.step", "Шаг")))]
            parts.append(ViewNode.card(card_children))

            extra = _extra_buttons(task, step, context)
            if extra:
                parts.append(ViewNode.group(extra,
                                            orientation="vertical"))

            parts.append(ViewNode.slot("step_footer"))

    doc = make_document(parts, screen_id="task_exec",
                        title=task.get("task_number") or "")

    if context and hasattr(context, "host") and context.host:
        pm = getattr(context.host, "plugin_manager", None)
        if pm is not None:
            doc = pm.call_filter(
                "on_view_build", doc,
                task=task, step=step, items=items,
                settings=settings, context=context)

    if capabilities is not None:
        from view_protocol import degrade_document
        doc = degrade_document(doc, capabilities)

    return doc

def build_offline_view(message=None):
    if not message:
        message = tr("view.offline", "Нет связи с сервером")
    return make_document([
        ViewNode.heading(message),
        ViewNode.caption(
            tr("view.try_later", "Попробуйте позже")),
    ], screen_id="offline")

def build_container_contents_view(task, container_barcode, items,
                                  settings, context=None,
                                  capabilities=None):
    parts = []
    parts.append(ViewNode.heading(
        tr("view.container_contents",
           "Состав тары {barcode}", barcode=container_barcode)))
    parts.append(ViewNode.caption(
        tr("view.task", "Задание: {num}",
           num=task.get('task_number', ''))))

    if not items:
        parts.append(ViewNode.card([
            ViewNode.text(
                tr("view.container_empty", "Тара пуста")),
        ], accent="warning"))
    else:
        rows = []
        for it in items:
            rows.append({
                "photo": it.get("photo_b64") or "",
                "name": it.get("item_name") or it.get("item_code") or "",
                "barcode": it.get("item_barcode") or "",
                "total": int(it.get("qty_total") or 0),
                "placed": int(it.get("qty_placed") or 0),
            })
        columns = [
            {"key": "photo",
             "label": tr("view.photo", "Фото"),
             "type": "image", "width": 0.15},
            {"key": "name",
             "label": tr("view.name", "Название"),
             "type": "text", "width": 0.35},
            {"key": "barcode",
             "label": tr("view.shk", "ШК"),
             "type": "text", "width": 0.20},
            {"key": "total",
             "label": tr("view.total", "Всего"),
             "type": "number", "width": 0.15},
            {"key": "placed",
             "label": tr("view.placed", "Размещено"),
             "type": "number", "width": 0.15},
        ]
        parts.append(ViewNode.table(columns, rows))

    parts.append(ViewNode.spacer(8))
    parts.append(ViewNode.button(
        tr("view.btn_back_task", "Вернуться к заданию"),
        action="tap", action_id="back_to_step",
        style="primary"))

    doc = make_document(parts, screen_id="container_contents",
                        title=tr("view.container_title",
                                 "Тара {barcode}",
                                 barcode=container_barcode))

    if capabilities is not None:
        from view_protocol import degrade_document
        doc = degrade_document(doc, capabilities)
    return doc

def build_drop_view(task, step, items, settings, context=None,
                    capabilities=None):
    drop_pending = (task.get("drop_pending") or "scan_point")
    drop_point = (task.get("drop_point_barcode") or "")
    containers = task.get("drop_containers") or []

    parts = [ViewNode.heading(
        tr("view.drop_title", "Сброс закрытых тар"))]
    parts.append(ViewNode.caption(
        tr("view.task", "Задание: {num}",
           num=task.get('task_number', ''))))

    if drop_pending == "scan_point":
        parts.append(ViewNode.card([
            ViewNode.text(
                tr("view.drop_step1",
                   "Шаг 1. Сканируйте точку сброса")),
            ViewNode.caption(
                tr("view.drop_step1_hint",
                   "Точка сброса — место, куда вы складываете "
                   "закрытые тары.")),
        ], accent="primary"))
    else:
        total = len(containers)
        done = sum(1 for c in containers
                   if (c.get("placed_in") or "").strip())
        parts.append(ViewNode.card([
            ViewNode.text(
                tr("view.drop_point",
                   "Точка сброса: {point}", point=drop_point)),
            ViewNode.caption(
                tr("view.drop_step2",
                   "Шаг 2. Сканируйте тары и складывайте их "
                   "на точку. Отсканировано: {done} / {total}",
                   done=done, total=total)),
        ], accent="primary"))

        if containers:
            parts.append(ViewNode.spacer(8))
            parts.append(ViewNode.text(
                tr("view.drop_containers_list", "Тары:"),
                style={"bold": True}))
            parts.append(_tiles_from_containers(containers))

    can_cancel = bool(task.get("can_cancel_pending", True))
    if can_cancel:
        parts.append(ViewNode.spacer(8))
        parts.append(ViewNode.button(
            tr("view.btn_cancel_drop", "Отменить сброс"),
            action="tap", action_id="cancel_pending"))

    doc = make_document(parts, screen_id="drop_containers",
                        title=tr("view.drop_title", "Сброс тар"))

    if capabilities is not None:
        from view_protocol import degrade_document
        doc = degrade_document(doc, capabilities)
    return doc