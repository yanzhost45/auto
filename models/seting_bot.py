import sqlite3
import os
import json

DB_PATH = os.path.join("data", "database.db")

def get_db():
    return sqlite3.connect(DB_PATH)

def init_bot_setting_tables():
    conn = get_db()
    c = conn.cursor()
    # Table for bot status
    c.execute('''
        CREATE TABLE IF NOT EXISTS bot_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT NOT NULL CHECK(status IN ('open', 'close', 'maintenance')),
            private_public TEXT NOT NULL DEFAULT 'public' CHECK(private_public IN ('private', 'public')),
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Table for cara pembelian
    c.execute('''
        CREATE TABLE IF NOT EXISTS cara_pembelian (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Table for cara deposit
    c.execute('''
        CREATE TABLE IF NOT EXISTS cara_deposit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

# BOT STATUS FUNCTIONS

def set_bot_status(status, private_public="public"):
    if status not in ['open', 'close', 'maintenance']:
        raise ValueError("Status harus 'open', 'close', atau 'maintenance'")
    if private_public not in ['private', 'public']:
        raise ValueError("private_public harus 'private' atau 'public'")
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO bot_status (status, private_public) VALUES (?, ?)", (status, private_public))
    conn.commit()
    conn.close()

def get_latest_bot_status():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT status, private_public FROM bot_status ORDER BY updated_at DESC, id DESC LIMIT 1")
    row = c.fetchone()
    conn.close()
    if row:
        return row[0]  # for backward compat
    return None

def get_latest_bot_status_full():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT status, private_public FROM bot_status ORDER BY updated_at DESC, id DESC LIMIT 1")
    row = c.fetchone()
    conn.close()
    if row:
        return {"status": row[0], "private_public": row[1]}
    return None

# CARA PEMBELIAN FUNCTIONS

def set_cara_pembelian(content):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO cara_pembelian (content) VALUES (?)", (content,))
    conn.commit()
    conn.close()

def get_latest_cara_pembelian():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT content FROM cara_pembelian ORDER BY updated_at DESC, id DESC LIMIT 1")
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

# CARA DEPOSIT FUNCTIONS

def set_cara_deposit(content):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO cara_deposit (content) VALUES (?)", (content,))
    conn.commit()
    conn.close()

def get_latest_cara_deposit():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT content FROM cara_deposit ORDER BY updated_at DESC, id DESC LIMIT 1")
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def insert_default_data_from_json():
    # Bot status
    bot_status_path = os.path.join("core", "bot_status.json")
    if os.path.exists(bot_status_path):
        with open(bot_status_path, "r") as f:
            data = json.load(f)
            status = data.get("status")
            private_public = data.get("private_public", "public")
            # Insert only if empty
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM bot_status")
            count = c.fetchone()[0]
            conn.close()
            if status and count == 0:
                set_bot_status(status, private_public)

    # Cara pembelian
    cara_pembelian_path = os.path.join("core", "cara_pembelian.json")
    if os.path.exists(cara_pembelian_path):
        with open(cara_pembelian_path, "r") as f:
            data = json.load(f)
            text = f"{data.get('judul','')}\n"
            langkah = data.get("langkah", [])
            for idx, l in enumerate(langkah, 1):
                text += f"{idx}. {l}\n"
            if data.get("catatan"):
                text += f"\nCatatan: {data.get('catatan')}\n"
            if not get_latest_cara_pembelian():
                set_cara_pembelian(text.strip())

    # Cara deposit
    cara_deposit_path = os.path.join("core", "cara_deposit.json")
    if os.path.exists(cara_deposit_path):
        with open(cara_deposit_path, "r") as f:
            data = json.load(f)
            text = f"{data.get('judul','')}\n"
            langkah = data.get("langkah", [])
            for idx, l in enumerate(langkah, 1):
                text += f"{idx}. {l}\n"
            if data.get("catatan"):
                text += f"\nCatatan: {data.get('catatan')}\n"
            if not get_latest_cara_deposit():
                set_cara_deposit(text.strip())

# Inisialisasi tabel saat import pertama kali
init_bot_setting_tables()
insert_default_data_from_json()