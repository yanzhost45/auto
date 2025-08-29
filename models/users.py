import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "database.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            userid INTEGER PRIMARY KEY,
            username TEXT,
            saldo INTEGER DEFAULT 0,
            role TEXT DEFAULT 'user',
            tanggal_daftar TEXT,
            status TEXT DEFAULT 'active'
        )
    """)
    conn.commit()
    conn.close()