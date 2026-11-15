import sqlite3
import hashlib as _h
import hmac as _hm
import secrets as _secrets
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
    Пароль хранится только как pass_hash (PBKDF2-SHA256).
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


def ensure_auth_sessions(db_path):
    """Сессии аутентификации (opaque-токены).

    token_hash = sha256(token). TTL 12 ч, продлевается при
    каждом успешном запросе. При logout/смене пароля/regen_badge
    запись удаляется.
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS auth_sessions (
            token_hash TEXT PRIMARY KEY,
            login TEXT NOT NULL,
            kind TEXT NOT NULL,
            role TEXT DEFAULT '',
            created_at TEXT,
            expires_at TEXT,
            last_seen_at TEXT,
            ip TEXT DEFAULT ''
        )
    """)
    _ensure_index(cur, "idx_auth_login",
                  "CREATE INDEX idx_auth_login "
                  "ON auth_sessions(login)")
    _ensure_index(cur, "idx_auth_expires",
                  "CREATE INDEX idx_auth_expires "
                  "ON auth_sessions(expires_at)")
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
    ensure_auth_sessions(db_path)


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


# ==================================================================
# Безопасность: пароли (PBKDF2-SHA256) и сессии
# ==================================================================

_PBKDF2_ITER = 600_000
_PBKDF2_SALT = 16
_SESSION_TTL_HOURS = 12


def hash_password(password: str) -> str:
    salt = _secrets.token_bytes(_PBKDF2_SALT)
    digest = _h.pbkdf2_hmac(
        "sha256", (password or "").encode("utf-8"), salt, _PBKDF2_ITER)
    return (f"$pbkdf2-sha256${_PBKDF2_ITER}$"
            f"{salt.hex()}${digest.hex()}")


def verify_password(password: str, stored: str) -> bool:
    if not stored:
        return False
    if stored.startswith("$pbkdf2-sha256$"):
        try:
            parts = stored.split("$")
            iters = int(parts[2])
            salt = bytes.fromhex(parts[3])
            expected = bytes.fromhex(parts[4])
            digest = _h.pbkdf2_hmac(
                "sha256", (password or "").encode("utf-8"),
                salt, iters)
            return _hm.compare_digest(digest, expected)
        except Exception:
            return False
    legacy = _h.sha256(
        (password or "").encode("utf-8")).hexdigest()
    return _hm.compare_digest(legacy, stored)


def needs_rehash(stored: str) -> bool:
    return not (stored or "").startswith("$pbkdf2-sha256$")


def _token_hash(token: str) -> str:
    return _h.sha256(token.encode("utf-8")).hexdigest()


def create_auth_session(db_path, login, kind, role="", ip="",
                        ttl_hours=_SESSION_TTL_HOURS):
    token = _secrets.token_urlsafe(32)
    now = datetime.now()
    exp = now + timedelta(hours=ttl_hours)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO auth_sessions "
            "(token_hash, login, kind, role, created_at, "
            " expires_at, last_seen_at, ip) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (_token_hash(token), login, kind, role or "",
             now.isoformat(), exp.isoformat(),
             now.isoformat(), ip or ""))
        conn.commit()
    finally:
        conn.close()
    return token


def verify_auth_session(db_path, token):
    if not token:
        return None
    th = _token_hash(token)
    now = datetime.now()
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT login, kind, role, expires_at "
            "FROM auth_sessions WHERE token_hash=?", (th,))
        r = cur.fetchone()
        if not r:
            return None
        try:
            exp = datetime.fromisoformat(r[3])
        except Exception:
            exp = now - timedelta(seconds=1)
        if exp < now:
            cur.execute(
                "DELETE FROM auth_sessions WHERE token_hash=?", (th,))
            conn.commit()
            return None
        new_exp = now + timedelta(hours=_SESSION_TTL_HOURS)
        cur.execute(
            "UPDATE auth_sessions SET last_seen_at=?, expires_at=? "
            "WHERE token_hash=?",
            (now.isoformat(), new_exp.isoformat(), th))
        conn.commit()
        return {"login": r[0], "kind": r[1], "role": r[2] or ""}
    finally:
        conn.close()


def invalidate_sessions(db_path, login=None, kind=None):
    conn = sqlite3.connect(db_path)
    try:
        if login and kind:
            conn.execute(
                "DELETE FROM auth_sessions "
                "WHERE login=? AND kind=?", (login, kind))
        elif login:
            conn.execute(
                "DELETE FROM auth_sessions WHERE login=?", (login,))
        conn.commit()
    finally:
        conn.close()


def invalidate_session_by_token(db_path, token):
    if not token:
        return
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "DELETE FROM auth_sessions WHERE token_hash=?",
            (_token_hash(token),))
        conn.commit()
    finally:
        conn.close()