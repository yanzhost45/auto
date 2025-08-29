import sqlite3
from datetime import datetime
import os
import pytz

DB_PATH = os.path.join(os.path.dirname(__file__), "database.db")

def add_user(userid, username, role="user"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Cek apakah user sudah ada
    c.execute("SELECT 1 FROM users WHERE userid = ?", (userid,))
    if c.fetchone() is None:
        # Ambil waktu Asia/Jakarta
        tz = pytz.timezone("Asia/Jakarta")
        tanggal_daftar = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
        c.execute(
            "INSERT INTO users (userid, username, role, tanggal_daftar) VALUES (?, ?, ?, ?)",
            (userid, username, role, tanggal_daftar)
        )
        conn.commit()
    conn.close()

def user_exists(userid):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM users WHERE userid = ?", (userid,))
    result = c.fetchone() is not None
    conn.close()
    return result

# Tambahkan fungsi ini di data/database.py
def get_user(userid):
    import sqlite3
    from .database import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT userid, username, saldo, role, tanggal_daftar, status FROM users WHERE userid = ?", (userid,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "userid": row[0],
            "username": row[1],
            "saldo": row[2],
            "role": row[3],
            "tanggal_daftar": row[4],
            "status": row[5]
        }
    return None

def get_all_kategori():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT DISTINCT kategori FROM produk_xl ORDER BY kategori")
    result = [row[0] for row in c.fetchall()]
    conn.close()
    return result

def get_produk_by_kategori(kategori):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, nama_produk FROM produk_xl WHERE kategori = ? ORDER BY nama_produk", (kategori,))
    result = c.fetchall()
    conn.close()
    return result

def get_produk_detail(produk_id):
    if not produk_id:
        return None
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, nama_produk, kategori, produk_kode, harga, harga_jual, total_amount, deskripsi, status
        FROM produk_xl WHERE id = ?
    """, (produk_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "id": row[0],
            "nama_produk": row[1],
            "kategori": row[2],
            "produk_kode": row[3],
            "harga": row[4],
            "harga_jual": row[5],
            "total_amount": row[6],
            "deskripsi": row[7],
            "status": row[8],
        }
    return None

def update_user_saldo(userid, nominal):
    import sqlite3
    from .database import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET saldo = saldo + ? WHERE userid = ?", (nominal, userid))
    conn.commit()
    conn.close()