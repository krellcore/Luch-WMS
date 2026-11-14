import sqlite3
from datetime import datetime, timedelta


RESERVE_DEFAULT_MINUTES = 120
RESERVE_ACTIVE_MINUTES = 60


def get_connection(db_path):
    return sqlite3.connect(db_path)


def read_settings(db_path):
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM settings")
        rows = cur.fetchall()
        conn.close()
        return dict(rows)
    except Exception:
        return {}


def _ensure_index(cur, name, sql):
    """Создаёт индекс, если его нет. Пропускает молча, если
    колонки, по которым строится индекс, отсутствуют —
    старые базы складов не поддерживаются (программа 1.0.0
    выпускается как новая)."""
    try:
        cur.execute("SELECT name FROM sqlite_master "
                    "WHERE type='index' AND name=?", (name,))
        if not cur.fetchone():
            cur.execute(sql)
    except sqlite3.OperationalError as e:
        print(f"[db] индекс {name} не создан: {e}")


def ensure_employees(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT, last_name TEXT, middle_name TEXT,
            login TEXT UNIQUE, pass_hash TEXT,
            photo BLOB, role TEXT DEFAULT '',
            roles TEXT DEFAULT '[]'
        )
    """)
    conn.commit()
    conn.close()


def ensure_managers(db_path):
    """Руководители склада (ПК-клиент управления).

    role: owner | admin | operator
    Пароль хранится только как pass_hash (SHA-256 hex).
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS managers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            login TEXT UNIQUE NOT NULL,
            pass_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'operator',
            created_at TEXT
        )
    """)
    _ensure_index(cur, "idx_managers_role",
                  "CREATE INDEX idx_managers_role "
                  "ON managers(role)")
    conn.commit()
    conn.close()


def ensure_blocks(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS blocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE
        )
    """)
    conn.commit()
    conn.close()


def ensure_cells(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cells (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            block_id INTEGER DEFAULT 0,
            floor INTEGER, row INTEGER, section INTEGER, cell TEXT,
            address TEXT UNIQUE, barcode TEXT UNIQUE,
            cell_type TEXT DEFAULT 'standart'
        )
    """)
    _ensure_index(cur, "idx_cells_address",
                  "CREATE INDEX idx_cells_address ON cells(address)")
    _ensure_index(cur, "idx_cells_barcode",
                  "CREATE INDEX idx_cells_barcode ON cells(barcode)")
    conn.commit()
    conn.close()


def ensure_items(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS item_characteristics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, description TEXT, barcode TEXT UNIQUE,
            dimensions_mm TEXT, volume REAL, weight_g REAL,
            item_code TEXT UNIQUE
        )
    """)
    conn.commit()
    conn.close()


def ensure_placed(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS placed_instances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_code TEXT, cell_barcode TEXT,
            cell_or_container_barcode TEXT, quantity INTEGER
        )
    """)
    _ensure_index(
        cur, "idx_placed_cell",
        "CREATE INDEX idx_placed_cell "
        "ON placed_instances(cell_barcode, item_code)")
    _ensure_index(
        cur, "idx_placed_container",
        "CREATE INDEX idx_placed_container "
        "ON placed_instances(cell_or_container_barcode, item_code)")
    conn.commit()
    conn.close()


def ensure_photos(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS photos (
            item_code TEXT PRIMARY KEY, mime TEXT,
            data BLOB, updated_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def ensure_containers(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS containers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            barcode TEXT UNIQUE, type TEXT DEFAULT 'standart',
            placed_in TEXT DEFAULT '',
            status TEXT DEFAULT 'free'
        )
    """)
    _ensure_index(cur, "idx_containers_status",
                  "CREATE INDEX idx_containers_status "
                  "ON containers(status)")
    conn.commit()
    conn.close()


def ensure_drop_points(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS drop_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            barcode TEXT UNIQUE NOT NULL,
            name TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def ensure_sessions(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            login TEXT NOT NULL,
            session_key TEXT NOT NULL,
            payload TEXT DEFAULT '{}',
            created_at TEXT,
            UNIQUE(login, session_key)
        )
    """)
    _ensure_index(
        cur, "idx_sessions_login",
        "CREATE INDEX idx_sessions_login "
        "ON sessions(login, session_key)")
    conn.commit()
    conn.close()


def ensure_tasks(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_number TEXT UNIQUE, task_type TEXT,
            status TEXT DEFAULT 'pending',
            assignee_login TEXT,
            target_a INTEGER DEFAULT 0,
            processed_a INTEGER DEFAULT 0,
            target_b INTEGER DEFAULT 0,
            processed_b INTEGER DEFAULT 0,
            barcode TEXT,
            container_barcode TEXT DEFAULT '',
            created_at TEXT,
            current_step_no INTEGER DEFAULT 0,
            current_cell_barcode TEXT DEFAULT '',
            task_plan TEXT DEFAULT '',
            pending_action TEXT DEFAULT '',
            pending_cell TEXT DEFAULT '',
            not_found_pending INTEGER DEFAULT 0,
            not_found_cell TEXT DEFAULT '',
            batch_id TEXT DEFAULT '',
            block_bf TEXT DEFAULT '',
            partial INTEGER DEFAULT 0,
            drop_status TEXT DEFAULT '',
            drop_point_barcode TEXT DEFAULT '',
            drop_pending TEXT DEFAULT '',
            platform TEXT DEFAULT 'any'
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS task_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER, item_code TEXT,
            cell_barcode TEXT, container_barcode TEXT,
            quantity INTEGER, processed INTEGER DEFAULT 0,
            step_no INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            scanned_item_barcode TEXT,
            scanned_qty INTEGER DEFAULT 0,
            rejected INTEGER DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS task_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER, step_no INTEGER,
            event_type TEXT, barcode TEXT,
            payload TEXT, created_at TEXT
        )
    """)
    _ensure_index(cur, "idx_tasks_status",
                  "CREATE INDEX idx_tasks_status "
                  "ON tasks(status, task_type, assignee_login)")
    _ensure_index(cur, "idx_tasks_batch",
                  "CREATE INDEX idx_tasks_batch ON tasks(batch_id)")
    _ensure_index(cur, "idx_tasks_platform",
                  "CREATE INDEX idx_tasks_platform "
                  "ON tasks(platform, status)")
    _ensure_index(cur, "idx_task_items_task",
                  "CREATE INDEX idx_task_items_task "
                  "ON task_items(task_id)")
    conn.commit()
    conn.close()


def ensure_reservations(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            item_code TEXT NOT NULL,
            cell_barcode TEXT NOT NULL,
            qty INTEGER NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT
        )
    """)
    _ensure_index(
        cur, "idx_res_item_cell",
        "CREATE INDEX idx_res_item_cell "
        "ON reservations(item_code, cell_barcode)")
    _ensure_index(cur, "idx_res_task",
                  "CREATE INDEX idx_res_task ON reservations(task_id)")
    _ensure_index(cur, "idx_res_expires",
                  "CREATE INDEX idx_res_expires "
                  "ON reservations(expires_at)")
    conn.commit()
    conn.close()


def ensure_notifications(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER,
            message TEXT,
            created_at TEXT,
            sender_login TEXT DEFAULT '',
            type TEXT DEFAULT 'info',
            recipient_login TEXT DEFAULT '',
            read_at TEXT DEFAULT '',
            payload TEXT DEFAULT ''
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER, cell_barcode TEXT, item_code TEXT,
            qty_before INTEGER, qty_after INTEGER,
            created_at TEXT
        )
    """)
    _ensure_index(
        cur, "idx_notif_recipient",
        "CREATE INDEX idx_notif_recipient "
        "ON notifications(recipient_login, read_at)")
    _ensure_index(
        cur, "idx_notif_created",
        "CREATE INDEX idx_notif_created "
        "ON notifications(created_at DESC)")
    conn.commit()
    conn.close()


def run_all_migrations(db_path):
    """Инициализация схемы БД (без миграций).
    Программа выпускается как новая — старые склады
    не поддерживаются."""
    ensure_employees(db_path)
    ensure_managers(db_path)
    ensure_blocks(db_path)
    ensure_cells(db_path)
    ensure_items(db_path)
    ensure_placed(db_path)
    ensure_photos(db_path)
    ensure_containers(db_path)
    ensure_drop_points(db_path)
    ensure_sessions(db_path)
    ensure_tasks(db_path)
    ensure_reservations(db_path)
    ensure_notifications(db_path)


# ==================================================================
# Резервы
# ==================================================================

def _now_iso():
    return datetime.now().isoformat()


def _future_iso(minutes):
    return (datetime.now() + timedelta(minutes=minutes)).isoformat()


def expire_reservations(db_path_or_cur):
    if isinstance(db_path_or_cur, sqlite3.Cursor):
        cur = db_path_or_cur
        cur.execute("DELETE FROM reservations "
                    "WHERE expires_at < ?", (_now_iso(),))
        return
    try:
        conn = sqlite3.connect(db_path_or_cur)
        conn.execute("DELETE FROM reservations "
                     "WHERE expires_at < ?", (_now_iso(),))
        conn.commit()
        conn.close()
    except Exception as e:
        print("expire_reservations:", e)


def reserved_qty(cur, item_code, cell_barcode):
    cur.execute("""
        SELECT COALESCE(SUM(qty), 0)
        FROM reservations
        WHERE item_code=? AND cell_barcode=?
          AND expires_at >= ?
    """, (item_code, cell_barcode, _now_iso()))
    r = cur.fetchone()
    return int(r[0] or 0) if r else 0


def available_qty(cur, item_code, cell_barcode):
    cur.execute("""
        SELECT COALESCE(quantity, 0)
        FROM placed_instances
        WHERE item_code=? AND cell_barcode=?
    """, (item_code, cell_barcode))
    r = cur.fetchone()
    have = int(r[0] or 0) if r else 0
    return max(0, have - reserved_qty(cur, item_code, cell_barcode))


def reserve(cur, task_id, item_code, cell_barcode, qty,
            minutes=RESERVE_DEFAULT_MINUTES):
    if qty <= 0:
        return
    cur.execute("""
        INSERT INTO reservations
            (task_id, item_code, cell_barcode, qty,
             expires_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (task_id, item_code, cell_barcode, int(qty),
          _future_iso(minutes), _now_iso()))


def refresh_task_reservations(cur, task_id,
                              minutes=RESERVE_ACTIVE_MINUTES):
    cur.execute("""
        UPDATE reservations SET expires_at=?
        WHERE task_id=?
    """, (_future_iso(minutes), task_id))


def release_task(cur, task_id):
    cur.execute("DELETE FROM reservations WHERE task_id=?", (task_id,))


# ==================================================================
# Фото
# ==================================================================

def save_photo_bytes(db_path, item_code, mime, blob):
    ensure_photos(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        INSERT INTO photos (item_code, mime, data, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(item_code) DO UPDATE SET
            mime=excluded.mime, data=excluded.data,
            updated_at=excluded.updated_at
    """, (item_code, mime, blob, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def load_photo_bytes(db_path, item_code):
    if not item_code:
        return None
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT data FROM photos WHERE item_code=?",
                    (item_code,))
        r = cur.fetchone()
        conn.close()
        return bytes(r[0]) if r and r[0] else None
    except Exception:
        return None


def delete_photo(db_path, item_code):
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("DELETE FROM photos WHERE item_code=?",
                     (item_code,))
        conn.commit()
        conn.close()
    except Exception:
        pass


def detect_mime(blob):
    if not blob:
        return "image/png"
    if blob[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if blob[:2] == b"BM":
        return "image/bmp"
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return "image/png"