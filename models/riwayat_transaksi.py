import sqlite3
import os
from typing import Optional, List, Tuple, Any

# DB path (sama seperti file lain di project)
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "database.db")

def _ensure_data_dir():
    data_dir = os.path.dirname(DB_PATH)
    os.makedirs(data_dir, exist_ok=True)

def init_db():
    """
    Membuat tabel riwayat_transaksi jika belum ada.
    Dipanggil otomatis saat module di-import dan juga sebelum operasi insert.
    """
    _ensure_data_dir()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS riwayat_transaksi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            msisdn TEXT,
            produk_id TEXT,
            produk_nama TEXT,
            kategori TEXT,
            harga_jual INTEGER,
            metode_pembayaran TEXT,
            amount_charged INTEGER,
            saldo_tersisa REAL,
            trx_id TEXT,
            status TEXT,
            waktu TEXT DEFAULT CURRENT_TIMESTAMP,
            keterangan TEXT
        )
    """)
    conn.commit()
    conn.close()

# Pastikan tabel dibuat saat module diimport (mencegah OperationalError: no such table)
try:
    init_db()
except Exception:
    # jangan mem-blok app jika pembuatan tabel gagal di import-time,
    # tapi insert_riwayat juga akan memanggil init_db() sebelum insert.
    pass

def insert_riwayat(
    user_id: str,
    msisdn: str,
    produk_id: str,
    produk_nama: str,
    kategori: str,
    harga_jual: int,
    metode_pembayaran: str,
    amount_charged: int,
    saldo_tersisa: float,
    trx_id: str,
    status: str,
    keterangan: Optional[str] = None
) -> None:
    """
    Menyimpan satu riwayat transaksi. Memastikan tabel ada sebelum insert.
    """
    # Pastikan tabel ada
    init_db()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO riwayat_transaksi
            (user_id, msisdn, produk_id, produk_nama, kategori, harga_jual, metode_pembayaran,
             amount_charged, saldo_tersisa, trx_id, status, keterangan)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, msisdn, produk_id, produk_nama, kategori, harga_jual, metode_pembayaran,
            amount_charged, saldo_tersisa, trx_id, status, keterangan
        ))
        conn.commit()
    finally:
        conn.close()

def get_riwayat_by_user(user_id: str, limit: int = 20) -> List[Tuple[Any, ...]]:
    """
    Mengambil riwayat transaksi terakhir untuk user tertentu.
    """
    # Pastikan tabel ada sehingga query tidak melempar OperationalError
    init_db()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, waktu, produk_nama, metode_pembayaran, amount_charged, saldo_tersisa, trx_id, status, keterangan
        FROM riwayat_transaksi
        WHERE user_id = ?
        ORDER BY waktu DESC
        LIMIT ?
    """, (user_id, limit))
    result = c.fetchall()
    conn.close()
    return result

def get_riwayat_by_trx_id(trx_id: str) -> Optional[Tuple[Any, ...]]:
    """
    Mengambil detail transaksi berdasarkan trx_id.
    """
    init_db()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT * FROM riwayat_transaksi
        WHERE trx_id = ?
    """, (trx_id,))
    result = c.fetchone()
    conn.close()
    return result