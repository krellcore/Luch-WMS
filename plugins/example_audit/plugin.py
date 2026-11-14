"""Демо-плагин «Аудит ячеек».

Демонстрирует:
  1. mgmt-страница в ПК-клиенте (admin_page.py).
  2. Пункт меню на ТСД (pda_menu.py).
  3. Свой тип задания "audit" (handlers.py).
  4. Своя роль "audit" через register_role() — появляется в
     карточке сотрудника, в фильтрах и в /tasks/next.
  5. Своя папка lang/ — языки лежат рядом с плагином.
"""

from . import handlers
from . import admin_page
from . import pda_menu


def register(context):
    context.log("register() example_audit")

    try:
        context.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER,
                cell_barcode TEXT,
                action TEXT,
                created_at TEXT
            )
        """)
    except Exception as e:
        context.log(f"audit_log: {e}")

    context.register_role(
        "audit",
        title_key="audit.role_title",
        title="Аудит ячеек",
        task_types=("audit",),
    )

    context.register_task_handler(handlers.AuditHandler(context.name))

    context.register_mgmt_page(
        "audit",
        context.tr("audit.title"),
        admin_page.build_view,
        admin_page.handle_action,
        roles=("owner", "admin"),
    )

    context.register_menu_item(
        "example_audit:my_audits",
        context.tr("audit.title"),
        pda_menu.build_view,
        roles=("audit", "picker", "putaway", "any"),
    )


def unregister(context):
    context.log("unregister() example_audit")
    try:
        context.execute("""
            UPDATE tasks
            SET status='pending', assignee_login=NULL,
                current_step_no=0, task_plan=''
            WHERE task_type='audit'
              AND status IN ('in_progress', 'action_required')
        """)
    except Exception as e:
        context.log(f"reset audits: {e}")