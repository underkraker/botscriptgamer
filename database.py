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
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
            tg_id INTEGER PRIMARY KEY, username TEXT, expiry_date INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS membership_keys (
            key_code TEXT PRIMARY KEY, days INTEGER, used INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS install_keys (
            key_code TEXT PRIMARY KEY, creator_id INTEGER, 
            expiry_date INTEGER, used INTEGER DEFAULT 0, used_ip TEXT)''')
    conn.commit()
    conn.close()

def generate_random_string(length=12):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def add_membership_key(days):
    key = "VIP-" + generate_random_string(10)
    conn = get_conn()
    conn.execute("INSERT INTO membership_keys (key_code, days, used) VALUES (?, ?, 0)", (key, days))
    conn.commit()
    conn.close()
    return key

def redeem_membership(tg_id, username, key):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT days, used FROM membership_keys WHERE key_code = ?", (key,))
    row = c.fetchone()
    if not row or row['used'] == 1:
        return False, 0
    days = row['days']
    
    # Mark used
    c.execute("UPDATE membership_keys SET used = 1 WHERE key_code = ?", (key,))
    
    # Update user
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
    conn.close()
    return True, days

def get_user(tg_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def can_user_generate(tg_id):
    user = get_user(tg_id)
    if user and user['expiry_date'] > int(time.time()):
        return True
    return False

def generate_install_key(creator_id):
    key = "KRAKER-" + generate_random_string(8)
    expiry = int(time.time()) + (4 * 3600) # 4 horas
    conn = get_conn()
    conn.execute("INSERT INTO install_keys (key_code, creator_id, expiry_date, used) VALUES (?, ?, ?, 0)", 
                 (key, creator_id, expiry))
    conn.commit()
    conn.close()
    return key

def validate_and_burn_install_key(key, ip):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT expiry_date, used FROM install_keys WHERE key_code = ?", (key,))
    row = c.fetchone()
    
    if not row:
        conn.close()
        return False
        
    if row['used'] == 1 or row['expiry_date'] < int(time.time()):
        conn.close()
        return False
        
    c.execute("UPDATE install_keys SET used = 1, used_ip = ? WHERE key_code = ?", (ip, key))
    conn.commit()
    conn.close()
    return True
