import sqlite3
import time
import random
import string

DB_FILE = 'bot_database.db'

def get_conn():
    # Conexión optimizada para el bot Lite
    conn = sqlite3.connect(DB_FILE, check_same_thread=False, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def execute_query(query, params=(), commit=False, fetchone=False, fetchall=False):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(query, params)
        if commit:
            conn.commit()
            return True
        if fetchone: return c.fetchone()
        if fetchall: return c.fetchall()
        return True
    except Exception as e:
        print(f"DB Error: {e}")
        return None
    finally:
        conn.close()

def init_db():
    conn = get_conn()
    try:
        c = conn.cursor()
        # Mantenemos las tablas mínimas para Keys y Membresías
        c.execute('''CREATE TABLE IF NOT EXISTS users (
                tg_id INTEGER PRIMARY KEY, username TEXT, expiry_date INTEGER)''')
        c.execute('''CREATE TABLE IF NOT EXISTS membership_keys (
                key_code TEXT PRIMARY KEY, days INTEGER, used INTEGER DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS install_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                key_code TEXT, creator_id INTEGER, 
                expiry_date INTEGER, used INTEGER DEFAULT 0, 
                used_by_ip TEXT, used_at INTEGER)''')
        conn.commit()
    finally:
        conn.close()

# --- FUNCIONES DE MEMBRESÍA Y KEYS ---
def generate_random_string(length=12):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def add_membership_key(days):
    key = "VIP-" + generate_random_string(10)
    if execute_query("INSERT INTO membership_keys (key_code, days, used) VALUES (?, ?, 0)", (key, days), commit=True):
        return key
    return None

def redeem_membership(tg_id, username, key):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("SELECT days, used FROM membership_keys WHERE key_code = ?", (key,))
        row = c.fetchone()
        if not row or row['used'] == 1: return False, 0
        days = row['days']
        c.execute("UPDATE membership_keys SET used = 1 WHERE key_code = ?", (key,))
        c.execute("SELECT expiry_date FROM users WHERE tg_id = ?", (tg_id,))
        user_row = c.fetchone()
        now = int(time.time())
        if user_row:
            new_exp = max(now, user_row['expiry_date']) + (days * 86400)
            c.execute("UPDATE users SET expiry_date = ?, username = ? WHERE tg_id = ?", (new_exp, username, tg_id))
        else:
            new_exp = now + (days * 86400)
            c.execute("INSERT INTO users (tg_id, username, expiry_date) VALUES (?, ?, ?)", (tg_id, username, new_exp))
        conn.commit()
        return True, days
    finally:
        conn.close()

def get_user(tg_id):
    row = execute_query("SELECT * FROM users WHERE tg_id = ?", (tg_id,), fetchone=True)
    return dict(row) if row else None

def can_user_generate(tg_id):
    user = get_user(tg_id)
    return True if user and user['expiry_date'] > int(time.time()) else False

def generate_install_key(creator_id):
    key = "KRAKER-" + generate_random_string(8)
    expiry = int(time.time()) + (4 * 3600)
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("INSERT INTO install_keys (key_code, creator_id, expiry_date, used) VALUES (?, ?, ?, 0)", (key, creator_id, expiry))
        c.execute("SELECT COUNT(*) as total FROM install_keys")
        count = c.fetchone()['total']
        conn.commit()
        return key, count
    finally:
        conn.close()

def validate_and_burn_install_key(key, ip):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("SELECT id, expiry_date, used, creator_id FROM install_keys WHERE key_code = ?", (key,))
        row = c.fetchone()
        if row and row['used'] == 0 and row['expiry_date'] > int(time.time()):
            c.execute("UPDATE install_keys SET used = 1, used_by_ip = ?, used_at = ? WHERE id = ?", (ip, int(time.time()), row['id']))
            conn.commit()
            return True, row['creator_id'], row['id']
        return False, None, None
    finally:
        conn.close()

def get_active_vps_ips():
    rows = execute_query("SELECT DISTINCT i.used_by_ip, u.username FROM install_keys i LEFT JOIN users u ON i.creator_id = u.tg_id WHERE i.used = 1 AND i.used_by_ip IS NOT NULL", (), fetchall=True)
    return [{"ip": r["used_by_ip"], "username": r["username"] if r["username"] else "Desconocido"} for r in rows] if rows else []
