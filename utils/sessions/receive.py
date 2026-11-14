"""Сессия приёмки (ПК)."""

import json

from view_protocol import ViewNode, make_document, degrade_document
from .base import SessionHandler
from .utils import load_session, save_session, drop_session
from tasks import utils as task_utils
from tasks import get_handler as get_task_handler
from i18n import tr


class ReceiveSession(SessionHandler):
    key = "receive"
    platforms = ("pc",)

    @property
    def title(self):
        return tr("sess.recv.title", "Сессия приёмки")

    def can_start(self, login, roles):
        return "receiver" in (roles or [])

    def _is_role_revoked(self, cur, login):
        try:
            cur.execute(
                "SELECT roles, role FROM employees WHERE login=?",
                (login,))
            r = cur.fetchone()
            if not r:
                return True
            roles_txt = r[0]
            try:
                roles = json.loads(roles_txt) if roles_txt else []
            except Exception:
                roles = []
            return "receiver" not in roles
        except Exception:
            return False

    def start(self, cur, login, payload):
        state = load_session(cur, login, self.key)
        if state is None:
            state = {
                "container_barcode": "",
                "task_id": 0,
                "task_number": "",
                "pending": "",
            }
            save_session(cur, login, self.key, state)
        return state

    def get_state(self, cur, login):
        state = load_session(cur, login, self.key) or {}
        state.setdefault("container_barcode", "")
        state.setdefault("task_id", 0)
        state.setdefault("task_number", "")
        state.setdefault("pending", "")
        return state

    def _save(self, cur, login, state):
        save_session(cur, login, self.key, state)

    def handle_action(self, cur, login, action_id, value, settings):
        # FIX: клиент при восстановлении связи шлёт _refresh_.
        # Раньше сервер возвращал «unknown action: _refresh_»
        # и в UI появлялся snackbar с ошибкой. Теперь — no-op:
        # _session_action ниже вернёт свежий view.
        if action_id == "_refresh_":
            return {"ok": True, "message": ""}

        role_revoked = self._is_role_revoked(cur, login)

        if action_id == "_scan_":
            return self._scan_any(cur, login, value)

        if action_id == "take_container":
            if role_revoked:
                return {
                    "ok": False,
                    "error": tr(
                        "sess.recv.err_role_revoked_take",
                        "Ваша роль приёмки отозвана. "
                        "Вы не можете брать новые тары. "
                        "Завершите текущую работу."),
                    "role_revoked": True,
                }
            return self._take_container(cur, login, value)

        if action_id == "cancel_container":
            if role_revoked:
                state = self.get_state(cur, login)
                container = state.get("container_barcode") or ""
                if container:
                    cur.execute(
                        "SELECT COALESCE(SUM(quantity), 0) "
                        "FROM placed_instances "
                        "WHERE cell_or_container_barcode=?",
                        (container,))
                    qty = cur.fetchone()[0] or 0
                    if qty > 0:
                        return {
                            "ok": False,
                            "error": tr(
                                "sess.recv.err_role_revoked_cancel",
                                "Ваша роль приёмки отозвана. "
                                "Используйте «Закрыть рабочую тару»."),
                            "role_revoked": True,
                        }
            return self._cancel_container(cur, login)

        if action_id == "finish_container":
            return self._pend(cur, login, "finish_container")
        if action_id == "finish_cargo":
            return self._pend(cur, login, "finish_cargo")
        if action_id == "partial_cargo":
            return self._pend(cur, login, "partial_cargo")
        if action_id == "cancel_pending":
            return self._cancel_pending(cur, login)
        return {"ok": False,
                "error": tr("sess.recv.err_unknown_action",
                            "неизвестное действие: {id}",
                            id=action_id)}

    def _pend(self, cur, login, pending):
        state = self.get_state(cur, login)
        if state.get("pending"):
            return {"ok": False,
                    "error": tr("sess.recv.err_pending_exists",
                                "Уже идёт подтверждение")}
        if pending == "finish_container" \
                and not state.get("container_barcode"):
            return {"ok": False,
                    "error": tr("sess.recv.err_no_container",
                                "нет открытой тары")}
        if pending in ("finish_cargo", "partial_cargo") \
                and not state.get("task_id"):
            return {"ok": False,
                    "error": tr("sess.recv.err_no_cargo",
                                "нет открытого грузоместа")}
        state["pending"] = pending
        self._save(cur, login, state)
        return {"ok": True, "message": ""}

    def _cancel_pending(self, cur, login):
        state = self.get_state(cur, login)
        state["pending"] = ""
        self._save(cur, login, state)
        return {"ok": True,
                "message": tr("sess.recv.msg_cancelled", "Отменено")}

    def _take_container(self, cur, login, barcode):
        barcode = (barcode or "").strip()
        if not barcode:
            return {"ok": False,
                    "error": tr("sess.recv.err_empty_barcode",
                                "пустой ШК")}
        state = self.get_state(cur, login)
        if state.get("container_barcode"):
            return {"ok": False,
                    "error": tr(
                        "sess.recv.err_container_already_open",
                        "Уже открыта тара {container}",
                        container=state['container_barcode'])}

        cur.execute("SELECT status FROM containers WHERE barcode=?",
                    (barcode,))
        r = cur.fetchone()
        if not r:
            return {"ok": False,
                    "error": tr("sess.recv.err_container_not_found",
                                "Тара {barcode} не найдена",
                                barcode=barcode)}
        st = r[0] or "free"
        if st != "free":
            return {"ok": False,
                    "error": tr("sess.recv.err_container_busy",
                                "Тара занята ({st})", st=st)}

        task_utils.set_container_status(cur, barcode, "accepting")
        state["container_barcode"] = barcode
        self._save(cur, login, state)
        return {"ok": True,
                "message": tr("sess.recv.msg_container_taken",
                              "Тара: {barcode}", barcode=barcode)}

    def _cancel_container(self, cur, login):
        state = self.get_state(cur, login)
        container = state.get("container_barcode") or ""
        if not container:
            return {"ok": False,
                    "error": tr("sess.recv.err_no_container",
                                "нет открытой тары")}
        cur.execute("""
            SELECT COALESCE(SUM(quantity), 0)
            FROM placed_instances
            WHERE cell_or_container_barcode=?
        """, (container,))
        qty = cur.fetchone()[0] or 0
        if qty > 0:
            return {"ok": False,
                    "error": tr(
                        "sess.recv.err_container_not_empty",
                        "Тара не пуста. Используйте "
                        "«Закрыть рабочую тару».")}
        task_utils.set_container_status(cur, container, "free")
        state["container_barcode"] = ""
        self._save(cur, login, state)
        return {"ok": True,
                "message": tr(
                    "sess.recv.msg_container_cancelled",
                    "Тара {container} отменена", container=container)}

    def _scan_any(self, cur, login, scanned):
        scanned = (scanned or "").strip()
        if not scanned:
            return {"ok": False, "error": "empty scan"}
        state = self.get_state(cur, login)
        pending = state.get("pending") or ""

        if pending == "finish_container":
            return self._apply_finish_container(cur, login, scanned)
        if pending == "finish_cargo":
            return self._apply_finish_cargo(cur, login, scanned)
        if pending == "partial_cargo":
            return self._apply_partial_cargo(cur, login, scanned)

        if self._is_role_revoked(cur, login):
            return {
                "ok": False,
                "error": tr(
                    "sess.recv.err_role_revoked_scan",
                    "Ваша роль приёмки отозвана. "
                    "Завершите текущую работу: нажмите "
                    "«Закончить грузоместо» и «Закрыть рабочую тару»."),
                "role_revoked": True,
            }

        container = state.get("container_barcode") or ""
        task_id = int(state.get("task_id") or 0)

        if not container:
            cur.execute("SELECT status FROM containers "
                        "WHERE barcode=?", (scanned,))
            r = cur.fetchone()
            if r:
                st = r[0] or "free"
                if st != "free":
                    return {"ok": False,
                            "error": tr(
                                "sess.recv.err_container_busy",
                                "Тара занята ({st})", st=st)}
                task_utils.set_container_status(cur, scanned,
                                                 "accepting")
                state["container_barcode"] = scanned
                self._save(cur, login, state)
                return {"ok": True,
                        "message": tr(
                            "sess.recv.msg_container_taken",
                            "Тара: {barcode}", barcode=scanned)}
            return {"ok": False,
                    "error": tr(
                        "sess.recv.err_not_container",
                        "ШК {barcode} — не тара или не найдено",
                        barcode=scanned)}

        if not task_id:
            cur.execute("""
                SELECT id, status, assignee_login
                FROM tasks
                WHERE task_number=? AND task_type='receive'
            """, (scanned,))
            row = cur.fetchone()
            if not row:
                return {"ok": False,
                        "error": tr(
                            "sess.recv.err_cargo_not_found",
                            "Грузоместо {barcode} не найдено",
                            barcode=scanned)}
            tid, t_status, assignee = row[0], row[1], row[2]
            if t_status == "done":
                return {"ok": False,
                        "error": tr(
                            "sess.recv.err_cargo_processed",
                            "Грузоместо уже обработано")}
            if assignee and assignee != login:
                return {"ok": False,
                        "error": tr(
                            "sess.recv.err_cargo_assigned",
                            "Грузоместо назначено: {assignee}",
                            assignee=assignee)}
            cur.execute("""
                UPDATE tasks SET assignee_login=?,
                                 status='in_progress'
                WHERE id=?
            """, (login, tid))
            state["task_id"] = tid
            state["task_number"] = scanned
            self._save(cur, login, state)
            return {"ok": True,
                    "message": tr("sess.recv.msg_cargo_taken",
                                  "Грузоместо: {barcode}",
                                  barcode=scanned)}

        return self._scan_item(cur, login, task_id, container, scanned)

    def _scan_item(self, cur, login, task_id, container_bc, barcode):
        handler = get_task_handler("receive")
        if not handler:
            return {"ok": False, "error": "no receive handler"}

        cur.execute(
            "UPDATE tasks SET container_barcode=? WHERE id=?",
            (container_bc, task_id))

        cur.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        row = cur.fetchone()
        if not row:
            return {"ok": False, "error": "task not found"}
        task = dict(row) if not isinstance(row, dict) else row
        task["container_barcode"] = container_bc

        cur.execute("""
            SELECT ti.*,
                   ic.name AS item_name,
                   ic.barcode AS item_barcode
            FROM task_items ti
            LEFT JOIN item_characteristics ic
                   ON ic.item_code = ti.item_code
            WHERE ti.task_id=?
            ORDER BY ti.step_no, ti.id
        """, (task_id,))
        items = [dict(r) for r in cur.fetchall()]
        fake_step = {
            "no": 1, "type": "scan_item",
            "data": {"action": "receive_scan"},
            "validate": {},
        }
        return handler.handle_scan(cur, task, fake_step, barcode,
                                    items, {})

    def _apply_finish_container(self, cur, login, scanned):
        state = self.get_state(cur, login)
        container = state.get("container_barcode") or ""
        if scanned != container:
            return {"ok": False,
                    "error": tr(
                        "sess.recv.err_expected_container",
                        "Ожидался ШК тары {container}",
                        container=container)}

        cur.execute("""
            SELECT COUNT(*) FROM tasks
            WHERE assignee_login=? AND task_type='receive'
              AND status='in_progress'
        """, (login,))
        active = cur.fetchone()[0] or 0
        if active > 0:
            state["pending"] = ""
            self._save(cur, login, state)
            return {"ok": False,
                    "error": tr(
                        "sess.recv.err_active_cargos_close",
                        "Сначала закройте все грузоместа "
                        "(активных: {active}). Затем повторите "
                        "закрытие тары.", active=active)}

        cur.execute("""
            SELECT COALESCE(SUM(quantity), 0)
            FROM placed_instances
            WHERE cell_or_container_barcode=?
        """, (container,))
        qty = cur.fetchone()[0] or 0

        if qty > 0:
            task_utils.set_container_status(cur, container, "placing")
            result = task_utils.create_putaway_for_container(
                cur, {}, container)
            if result == "already_exists":
                msg = tr(
                    "sess.recv.msg_container_to_putaway_exists",
                    "Тара {container} уже в задании на размещение",
                    container=container)
            elif result == "empty":
                msg = tr(
                    "sess.recv.msg_container_freed",
                    "Тара {container} освобождена (пуста)",
                    container=container)
            else:
                msg = tr(
                    "sess.recv.msg_container_to_putaway",
                    "Тара {container} отправлена на размещение",
                    container=container)
        else:
            task_utils.set_container_status(cur, container, "free")
            msg = tr(
                "sess.recv.msg_container_freed",
                "Тара {container} освобождена (пуста)",
                container=container)

        state["container_barcode"] = ""
        state["pending"] = ""
        self._save(cur, login, state)
        return {"ok": True, "message": msg}

    def _apply_finish_cargo(self, cur, login, scanned):
        state = self.get_state(cur, login)
        task_id = int(state.get("task_id") or 0)
        task_number = state.get("task_number") or ""
        if not task_id:
            return {"ok": False,
                    "error": tr("sess.recv.err_no_cargo",
                                "нет открытого грузоместа")}
        if scanned != task_number:
            return {"ok": False,
                    "error": tr(
                        "sess.recv.err_expected_cargo",
                        "Ожидался ШК грузоместа {task_number}",
                        task_number=task_number)}

        cur.execute(
            "SELECT target_a, processed_a FROM tasks WHERE id=?",
            (task_id,))
        r = cur.fetchone()
        if not r:
            state["task_id"] = 0
            state["task_number"] = ""
            state["pending"] = ""
            self._save(cur, login, state)
            return {"ok": False,
                    "error": tr(
                        "sess.recv.err_cargo_processed",
                        "Грузоместо уже обработано")}
        target_a = int(r[0] or 0)
        processed_a = int(r[1] or 0)
        if processed_a < target_a:
            return {"ok": False,
                    "error": tr(
                        "sess.recv.err_not_full",
                        "Принято не всё ({p}/{t}). Используйте "
                        "«Частичное завершение».",
                        p=processed_a, t=target_a)}

        from db import release_task

        cur.execute("""
            UPDATE tasks SET status='done', assignee_login=NULL,
                pending_action='', pending_cell='',
                container_barcode=''
            WHERE id=?
        """, (task_id,))
        if cur.rowcount == 0:
            state["task_id"] = 0
            state["task_number"] = ""
            state["pending"] = ""
            self._save(cur, login, state)
            return {"ok": False,
                    "error": tr(
                        "sess.recv.err_cargo_processed",
                        "Грузоместо уже обработано")}
        release_task(cur, task_id)

        state["task_id"] = 0
        state["task_number"] = ""
        state["pending"] = ""
        self._save(cur, login, state)
        return {"ok": True,
                "message": tr("sess.recv.msg_cargo_closed",
                              "Грузоместо {task_number} закрыто",
                              task_number=task_number)}

    def _apply_partial_cargo(self, cur, login, scanned):
        state = self.get_state(cur, login)
        task_id = int(state.get("task_id") or 0)
        task_number = state.get("task_number") or ""
        if not task_id:
            return {"ok": False,
                    "error": tr("sess.recv.err_no_cargo",
                                "нет открытого грузоместа")}
        if scanned != task_number:
            return {"ok": False,
                    "error": tr(
                        "sess.recv.err_expected_cargo",
                        "Ожидался ШК грузоместа {task_number}",
                        task_number=task_number)}

        cur.execute(
            "SELECT target_a, processed_a FROM tasks WHERE id=?",
            (task_id,))
        r = cur.fetchone()
        if not r:
            state["task_id"] = 0
            state["task_number"] = ""
            state["pending"] = ""
            self._save(cur, login, state)
            return {"ok": False,
                    "error": tr(
                        "sess.recv.err_cargo_processed",
                        "Грузоместо уже обработано")}
        target_a = int(r[0] or 0)
        processed_a = int(r[1] or 0)

        if processed_a <= 0:
            return {"ok": False,
                    "error": tr(
                        "sess.recv.err_partial_empty",
                        "Нечего завершать: ни один товар "
                        "не принят.")}

        cur.execute("""
            SELECT item_code, COALESCE(scanned_qty,0) AS q
            FROM task_items
            WHERE task_id=? AND COALESCE(scanned_qty,0) > 0
        """, (task_id,))
        for row in cur.fetchall():
            code, q = row[0], row[1]
            if code and q:
                task_utils.add_task_event(
                    cur, task_id, 0, "receive_done", code,
                    {"item_code": code, "qty": q})

        cur.execute("""
            UPDATE task_items
            SET quantity = MAX(0, COALESCE(quantity,0)
                                  - COALESCE(scanned_qty, 0)),
                scanned_qty = 0,
                scanned_item_barcode = '',
                status = CASE
                    WHEN MAX(0, COALESCE(quantity,0)
                                - COALESCE(scanned_qty, 0)) > 0
                    THEN 'pending'
                    ELSE 'done'
                END
            WHERE task_id=?
        """, (task_id,))
        cur.execute("""
            DELETE FROM task_items
            WHERE task_id=? AND quantity <= 0
        """, (task_id,))
        cur.execute("""
            SELECT COALESCE(SUM(quantity),0)
            FROM task_items WHERE task_id=?
        """, (task_id,))
        new_target = cur.fetchone()[0] or 0

        from db import release_task

        if new_target == 0:
            cur.execute("""
                UPDATE tasks SET status='done', assignee_login=NULL,
                    processed_a=?, partial=1,
                    pending_action='', pending_cell='',
                    container_barcode=''
                WHERE id=?
            """, (processed_a, task_id))
            msg = tr("sess.recv.msg_partial_full",
                     "Всё принято, задание закрыто")
        else:
            cur.execute("""
                UPDATE tasks SET status='pending',
                    assignee_login=NULL,
                    target_a=?, processed_a=0, partial=1,
                    pending_action='', pending_cell='',
                    container_barcode='', current_step_no=0,
                    task_plan=''
                WHERE id=?
            """, (new_target, task_id))
            msg = tr("sess.recv.msg_partial_remaining",
                     "Остаток {new_target} шт возвращён в очередь",
                     new_target=new_target)

        release_task(cur, task_id)
        state["task_id"] = 0
        state["task_number"] = ""
        state["pending"] = ""
        self._save(cur, login, state)
        return {"ok": True, "message": msg}

    def get_view(self, cur, login, settings, caps):
        state = self.get_state(cur, login)
        container = state.get("container_barcode") or ""
        task_id = int(state.get("task_id") or 0)
        task_number = state.get("task_number") or ""
        pending = state.get("pending") or ""
        role_revoked = self._is_role_revoked(cur, login)

        parts = [ViewNode.heading(tr("sess.recv.title",
                                     "Сессия приёмки"))]

        if role_revoked:
            parts.append(ViewNode.card([
                ViewNode.text(
                    tr("sess.recv.role_revoked_title",
                       "⚠ Ваша роль приёмки отозвана"),
                    style={"bold": True, "color": "#c0392b"}),
                ViewNode.caption(
                    tr("sess.recv.role_revoked_hint",
                       "Завершите текущую работу: закройте "
                       "грузоместо и рабочую тару. "
                       "Новые операции недоступны.")),
            ], accent="warning"))

        status_children = []
        if container:
            status_children.append(ViewNode.text(
                tr("sess.recv.container", "Тара: {container}",
                   container=container),
                style={"bold": True}))
            cur.execute("""
                SELECT COALESCE(SUM(quantity), 0)
                FROM placed_instances
                WHERE cell_or_container_barcode=?
            """, (container,))
            qty = cur.fetchone()[0] or 0
            status_children.append(
                ViewNode.caption(tr("sess.recv.in_container",
                                    "В таре: {qty} шт", qty=qty)))
        else:
            status_children.append(ViewNode.text(
                tr("sess.recv.container_not_open",
                   "Тара: не открыта"), style={"bold": True}))

        task_partial = 0
        if task_id:
            cur.execute("""
                SELECT task_number, target_a, processed_a, partial
                FROM tasks WHERE id=?
            """, (task_id,))
            row = cur.fetchone()
            if row:
                task_partial = int(row[3] or 0)
                status_children.append(ViewNode.text(
                    tr("sess.recv.cargo",
                       "Грузоместо: {task_number}",
                       task_number=row[0]),
                    style={"bold": True}))
                status_children.append(ViewNode.caption(
                    tr("sess.recv.received",
                       "Принято: {processed} / {target}",
                       processed=row[2], target=row[1])))
                if task_partial:
                    status_children.append(ViewNode.caption(
                        tr("sess.recv.partial_warn",
                           "⚠ Частичное задание")))
        else:
            status_children.append(ViewNode.text(
                tr("sess.recv.cargo_not_selected",
                   "Грузоместо: не выбрано"), style={"bold": True}))

        parts.append(ViewNode.card(status_children, accent="primary"))

        if pending:
            hints = {
                "finish_container":
                    tr("sess.recv.hint_finish_container",
                       "Сканируйте ШК тары {container}",
                       container=container),
                "finish_cargo":
                    tr("sess.recv.hint_finish_cargo",
                       "Сканируйте ШК грузоместа {task_number}",
                       task_number=task_number),
                "partial_cargo":
                    tr("sess.recv.hint_partial_cargo",
                       "Сканируйте ШК грузоместа {task_number}",
                       task_number=task_number),
            }
            parts.append(ViewNode.card([
                ViewNode.text(
                    hints.get(pending,
                              tr("sess.recv.hint_scan", "Сканируйте")),
                    style={"bold": True}),
                ViewNode.caption(
                    tr("sess.recv.hint_cancel",
                       "Нажмите «Отменить», чтобы отменить")),
                ViewNode.button(
                    tr("sess.recv.btn_cancel", "Отменить"),
                    action="tap",
                    action_id="cancel_pending"),
            ], accent="warning"))
        else:
            btns = []
            if container:
                btns.append(ViewNode.button(
                    tr("sess.recv.btn_finish_container",
                       "Закрыть рабочую тару"),
                    action="tap", action_id="finish_container",
                    style="primary"))
                if not role_revoked:
                    btns.append(ViewNode.button(
                        tr("sess.recv.btn_cancel_container",
                           "Отменить тару"),
                        action="tap", action_id="cancel_container"))
            if task_id:
                btns.append(ViewNode.button(
                    tr("sess.recv.btn_finish_cargo",
                       "Закончить грузоместо"),
                    action="tap", action_id="finish_cargo",
                    style="primary"))
                btns.append(ViewNode.button(
                    tr("sess.recv.btn_partial_cargo",
                       "Частичное завершение"),
                    action="tap", action_id="partial_cargo"))
            if btns:
                parts.append(ViewNode.group(btns,
                                            orientation="vertical"))

            if role_revoked:
                hint = tr(
                    "sess.recv.hint_finish_only",
                    "Роль отозвана. Завершите текущую работу.")
            elif not container:
                hint = tr("sess.recv.hint_take_container",
                          "Возьмите тару и отсканируйте её ШК")
            elif not task_id:
                hint = tr("sess.recv.hint_take_cargo",
                          "Возьмите грузоместо и отсканируйте его ШК")
            else:
                hint = tr("sess.recv.hint_scan_items",
                          "Сканируйте товары из грузоместа")
            parts.append(ViewNode.card([
                ViewNode.text(hint, style={"bold": True}),
            ], accent="success"))

        if task_id:
            cur.execute("""
                SELECT ti.item_code, ti.quantity,
                       COALESCE(ti.scanned_qty, 0) AS scanned_qty,
                       ti.status,
                       ic.name AS item_name,
                       ic.barcode AS item_barcode
                FROM task_items ti
                LEFT JOIN item_characteristics ic
                       ON ic.item_code = ti.item_code
                WHERE ti.task_id=?
                ORDER BY ti.step_no, ti.id
            """, (task_id,))
            rows = cur.fetchall()
            if rows:
                parts.append(ViewNode.spacer(8))
                parts.append(ViewNode.text(
                    tr("sess.recv.items_in_cargo",
                       "Товары в грузоместе:"), style={"bold": True}))
                for it in rows:
                    item_code = it[0]
                    quantity = it[1]
                    scanned_qty = it[2]
                    status = it[3]
                    item_name = it[4]
                    item_barcode = it[5]
                    photo = task_utils.photo_b64(cur, item_code)
                    children = [
                        ViewNode.text(item_name or item_code or "—",
                                      style={"bold": True}),
                    ]
                    if item_barcode:
                        children.append(ViewNode.caption(
                            tr("sess.recv.barcode",
                               "ШК: {barcode}", barcode=item_barcode)))
                    children.append(ViewNode.caption(
                        tr("sess.recv.accepted",
                           "Принято: {scanned} / {quantity}",
                           scanned=scanned_qty, quantity=quantity)))
                    if status == "extra":
                        children.append(ViewNode.caption(
                            tr("sess.recv.extra", "сверх плана")))
                    if photo:
                        children.append(ViewNode.image(
                            photo, width=120, height=120))
                    parts.append(ViewNode.card(children))

        doc = make_document(parts, screen_id="session",
                            title=tr("sess.recv.title",
                                     "Сессия приёмки"))
        if caps is not None:
            doc = degrade_document(doc, caps)
        return doc

    def close(self, cur, login, force=False):
        state = self.get_state(cur, login)
        container = state.get("container_barcode") or ""
        task_id = int(state.get("task_id") or 0)
        task_number = state.get("task_number") or ""

        if not force:
            if task_id:
                return {
                    "ok": False,
                    "error": tr(
                        "sess.recv.err_close_cargo",
                        "Сначала закончите грузоместо "
                        "{task_number}: нажмите «Закончить "
                        "грузоместо».",
                        task_number=task_number),
                }
            if container:
                cur.execute("""
                    SELECT COALESCE(SUM(quantity), 0)
                    FROM placed_instances
                    WHERE cell_or_container_barcode=?
                """, (container,))
                qty = cur.fetchone()[0] or 0
                if qty > 0:
                    return {
                        "ok": False,
                        "error": tr(
                            "sess.recv.err_close_container",
                            "Сначала закройте рабочую тару "
                            "{container}: нажмите «Закрыть рабочую "
                            "тару».",
                            container=container),
                    }

        cur.execute("""
            UPDATE tasks SET status='pending', assignee_login=NULL,
                current_step_no=0, pending_action='', pending_cell='',
                container_barcode=''
            WHERE assignee_login=? AND task_type='receive'
              AND status='in_progress'
        """, (login,))

        if container:
            cur.execute("""
                SELECT COALESCE(SUM(quantity), 0)
                FROM placed_instances
                WHERE cell_or_container_barcode=?
            """, (container,))
            qty = cur.fetchone()[0] or 0
            if qty == 0:
                task_utils.set_container_status(cur, container,
                                                 "free")
            else:
                task_utils.set_container_status(cur, container,
                                                 "placing")
                try:
                    task_utils.create_putaway_for_container(
                        cur, {}, container)
                except Exception:
                    pass

        drop_session(cur, login, self.key)
        return {"ok": True}


from . import register  # noqa: E402
register(ReceiveSession)