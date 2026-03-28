import sqlite3
import os

DB_FILE = "bot_database.db"

def migrate():
    if not os.path.exists(DB_FILE):
        print(f"[*] No DB found at {DB_FILE}. Skipping migration.")
        return
        
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Obtener columnas actuales
    c.execute("PRAGMA table_info(vps_connections)")
    cols = [col[1] for col in c.fetchall()]
    print(f"[*] Current columns: {cols}")
    
    # Añadir auth_type si falta
    if "auth_type" not in cols:
        print("[+] Adding auth_type...")
        c.execute("ALTER TABLE vps_connections ADD COLUMN auth_type TEXT DEFAULT 'pass'")
        
    # Añadir vps_key_content si falta
    if "vps_key_content" not in cols:
        print("[+] Adding vps_key_content...")
        c.execute("ALTER TABLE vps_connections ADD COLUMN vps_key_content TEXT")
        
    # Añadir use_sudo si falta
    if "use_sudo" not in cols:
        print("[+] Adding use_sudo...")
        c.execute("ALTER TABLE vps_connections ADD COLUMN use_sudo INTEGER DEFAULT 0")
        
    conn.commit()
    conn.close()
    print("[*] Migration complete.")

if __name__ == "__main__":
    migrate()
