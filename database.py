import sqlite3
import time
import random
import string

DB_FILE = 'bot_database.db'

def get_conn():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    try:
        c = conn.cursor()
        # Tabla de Usuarios (Membresía VIP)
        c.execute('''CREATE TABLE IF NOT EXISTS users (
                tg_id INTEGER PRIMARY KEY, username TEXT, expiry_date INTEGER)''')
        # Tabla de Pases VIP (para canjear)
        c.execute('''CREATE TABLE IF NOT EXISTS membership_keys (
                key_code TEXT PRIMARY KEY, days INTEGER, used INTEGER DEFAULT 0)''')
        # Tabla de Keys de Instalación (una por cada VPS)
        c.execute('''CREATE TABLE IF NOT EXISTS install_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                key_code TEXT, creator_id INTEGER, 
                expiry_date INTEGER, used INTEGER DEFAULT 0, 
                used_by_ip TEXT, used_at INTEGER)''')
        # Nueva Tabla de Tickets de Soporte
        c.execute('''CREATE TABLE IF NOT EXISTS tickets (
                ticket_id INTEGER PRIMARY KEY AUTOINCREMENT, 
                user_id INTEGER, message TEXT, status TEXT DEFAULT 'OPEN', created_at INTEGER)''')
        # NUEVA TABLA: Conexiones VPS (Añadido Auth Type y Key Content)
        c.execute('''CREATE TABLE IF NOT EXISTS vps_connections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER,
                vps_name TEXT,
                vps_ip TEXT,
                vps_user TEXT,
                vps_pass TEXT,
                auth_type TEXT DEFAULT 'pass',
                vps_key_content TEXT,
                use_sudo INTEGER DEFAULT 0)''')
        conn.commit()
    finally:
        conn.close()

# --- FUNCIONES DE VPS (SIEMPRE RETORNAN DICT) ---
def add_vps(owner_id, name, ip, user, auth_type, auth_val, use_sudo=0):
    conn = get_conn()
    try:
        if auth_type == 'pass':
            conn.execute("INSERT INTO vps_connections (owner_id, vps_name, vps_ip, vps_user, vps_pass, auth_type, use_sudo) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (owner_id, name, ip, user, auth_val, 'pass', use_sudo))
        else:
            conn.execute("INSERT INTO vps_connections (owner_id, vps_name, vps_ip, vps_user, vps_key_content, auth_type, use_sudo) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (owner_id, name, ip, user, auth_val, 'key', use_sudo))
        conn.commit()
    finally:
        conn.close()

def get_user_vps(owner_id):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM vps_connections WHERE owner_id = ?", (owner_id,))
        rows = c.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_vps_by_id(vps_id):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM vps_connections WHERE id = ?", (vps_id,))
        row = c.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def delete_vps(vps_id, owner_id):
    conn = get_conn()
    try:
        conn.execute("DELETE FROM vps_connections WHERE id = ? AND owner_id = ?", (vps_id, owner_id))
        conn.commit()
    finally:
        conn.close()

# --- FUNCIONES AUXILIARES ---
def generate_random_string(length=12):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def add_membership_key(days):
    key = "VIP-" + generate_random_string(10)
    conn = get_conn()
    try:
        conn.execute("INSERT INTO membership_keys (key_code, days, used) VALUES (?, ?, 0)", (key, days))
        conn.commit()
        return key
    finally:
        conn.close()

def redeem_membership(tg_id, username, key):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("SELECT days, used FROM membership_keys WHERE key_code = ?", (key,))
        row = c.fetchone()
        if not row or row['used'] == 1:
            return False, 0
        days = row['days']
        c.execute("UPDATE membership_keys SET used = 1 WHERE key_code = ?", (key,))
        c.execute("SELECT expiry_date FROM users WHERE tg_id = ?", (tg_id,))
        user_row = c.fetchone()
        now = int(time.time())
        if user_row:
            current_exp = user_row['expiry_date']
            new_exp = max(now, current_exp) + (days * 86400)
            c.execute("UPDATE users SET expiry_date = ?, username = ? WHERE tg_id = ?", (new_exp, username, tg_id))
        else:
            new_exp = now + (days * 86400)
            c.execute("INSERT INTO users (tg_id, username, expiry_date) VALUES (?, ?, ?)", (tg_id, username, new_exp))
        conn.commit()
        return True, days
    finally:
        conn.close()

def get_user(tg_id):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
        row = c.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def can_user_generate(tg_id):
    user = get_user(tg_id)
    if user and user['expiry_date'] > int(time.time()):
        return True
    return False

def generate_install_key(creator_id):
    key = "KRAKER-" + generate_random_string(8)
    expiry = int(time.time()) + (4 * 3600)
    conn = get_conn()
    try:
        conn.execute("INSERT INTO install_keys (key_code, creator_id, expiry_date, used) VALUES (?, ?, ?, 0)", 
                     (key, creator_id, expiry))
        c = conn.cursor()
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
            c.execute("UPDATE install_keys SET used = 1, used_by_ip = ?, used_at = ? WHERE id = ?", 
                      (ip, int(time.time()), row['id']))
            conn.commit()
            return True, row['creator_id'], row['id']
        return False, None, None
    finally:
        conn.close()

def get_active_vps_ips(creator_id=None):
    conn = get_conn()
    try:
        c = conn.cursor()
        if creator_id:
            c.execute("""SELECT DISTINCT i.used_by_ip, u.username 
                         FROM install_keys i 
                         LEFT JOIN users u ON i.creator_id = u.tg_id 
                         WHERE i.creator_id = ? AND i.used = 1 AND i.used_by_ip IS NOT NULL""", (creator_id,))
        else:
            c.execute("""SELECT DISTINCT i.used_by_ip, u.username 
                         FROM install_keys i 
                         LEFT JOIN users u ON i.creator_id = u.tg_id 
                         WHERE i.used = 1 AND i.used_by_ip IS NOT NULL""")
        rows = c.fetchall()
        vips = [{"ip": r["used_by_ip"], "username": r["username"] if r["username"] else "Desconocido"} for r in rows]
        return vips
    finally:
        conn.close()

def get_expiring_users(days_left=2):
    conn = get_conn()
    try:
        c = conn.cursor()
        limit = int(time.time()) + (days_left * 86400)
        now = int(time.time())
        c.execute("SELECT tg_id, username, expiry_date FROM users WHERE expiry_date > ? AND expiry_date < ?", (now, limit))
        rows = c.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def create_ticket(user_id, message):
    conn = get_conn()
    try:
        now = int(time.time())
        conn.execute("INSERT INTO tickets (user_id, message, created_at) VALUES (?, ?, ?)", (user_id, message, now))
        conn.commit()
    finally:
        conn.close()
