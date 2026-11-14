"""Пункт меню на ТСД «Мои аудиты»."""

from view_protocol import ViewNode, make_document


def build_view(login, user_roles, context):
    db = context.db()
    rows = []
    try:
        cur = db.cursor()
        cur.execute("""
            SELECT task_number, status, assignee_login
            FROM tasks
            WHERE task_type='audit'
              AND status IN ('pending','in_progress','action_required')
              AND (assignee_login IS NULL
                   OR assignee_login=''
                   OR assignee_login=?)
            ORDER BY id DESC
            LIMIT 20
        """, (login,))
        for r in cur.fetchall():
            rows.append({
                "number": r[0] or "",
                "status": r[1] or "",
                "assignee": r[2] or "",
            })
    finally:
        db.close()

    parts = [ViewNode.heading(context.tr("audit.title"))]

    if not rows:
        parts.append(ViewNode.card([
            ViewNode.text(context.tr("audit.pda_empty")),
            ViewNode.caption(context.tr("audit.pda_hint")),
        ], accent="warning"))
    else:
        for r in rows:
            lines = [
                ViewNode.text(f'№ {r["number"]}',
                              style={"bold": True}),
                ViewNode.caption(f'Статус: {r["status"]}'),
            ]
            if r["assignee"]:
                lines.append(ViewNode.caption(
                    f'Исполнитель: {r["assignee"]}'))
            parts.append(ViewNode.card(lines))
        parts.append(ViewNode.caption(context.tr("audit.pda_hint")))

    return make_document(parts, screen_id="menu_audit")