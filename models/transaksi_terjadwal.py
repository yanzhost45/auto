from __future__ import annotations
import os
import sqlite3
from typing import Optional, List, Dict, Any

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "database.db")


def _ensure_db_dir():
    data_dir = os.path.dirname(DB_PATH)
    os.makedirs(data_dir, exist_ok=True)


def init_db() -> None:
    _ensure_db_dir()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Create table with msisdn column. If table exists but missing column, add it.
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS transaksi_terjadwal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            userid INTEGER NOT NULL,
            produk_id TEXT,
            produk_nama TEXT,
            kategori TEXT,
            harga_jual INTEGER,
            metode_pembayaran TEXT,
            msisdn TEXT,
            waktu_pembelian TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    # Ensure msisdn column exists for older DBs
    try:
        c.execute("PRAGMA table_info(transaksi_terjadwal)")
        cols = [r[1] for r in c.fetchall()]
        if "msisdn" not in cols:
            c.execute("ALTER TABLE transaksi_terjadwal ADD COLUMN msisdn TEXT")
    except Exception:
        # ignore if cannot alter
        pass

    conn.commit()
    conn.close()


def create_transaksi(
    userid: int,
    produk_id: str,
    produk_nama: str,
    kategori: str,
    harga_jual: int,
    metode_pembayaran: str,
    waktu_pembelian_iso: str,
    msisdn: Optional[str] = None,
    status: str = "pending",
) -> int:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO transaksi_terjadwal
        (userid, produk_id, produk_nama, kategori, harga_jual, metode_pembayaran, msisdn, waktu_pembelian, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (userid, produk_id, produk_nama, kategori, harga_jual, metode_pembayaran, msisdn, waktu_pembelian_iso, status),
    )
    conn.commit()
    rowid = c.lastrowid
    conn.close()
    return rowid


def get_transaksi_by_id(tx_id: int) -> Optional[Dict[str, Any]]:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, userid, produk_id, produk_nama, kategori, harga_jual, metode_pembayaran, msisdn, waktu_pembelian, status, created_at FROM transaksi_terjadwal WHERE id = ?",
        (tx_id,),
    )
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0],
        "userid": row[1],
        "produk_id": row[2],
        "produk_nama": row[3],
        "kategori": row[4],
        "harga_jual": row[5],
        "metode_pembayaran": row[6],
        "msisdn": row[7],
        "waktu_pembelian": row[8],
        "status": row[9],
        "created_at": row[10],
    }


def get_transaksi_by_user(userid: int, limit: int = 50) -> List[Dict[str, Any]]:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, userid, produk_id, produk_nama, kategori, harga_jual, metode_pembayaran, msisdn, waktu_pembelian, status, created_at FROM transaksi_terjadwal WHERE userid = ? ORDER BY waktu_pembelian DESC LIMIT ?",
        (userid, limit),
    )
    rows = c.fetchall()
    conn.close()
    out = []
    for r in rows:
        out.append({
            "id": r[0],
            "userid": r[1],
            "produk_id": r[2],
            "produk_nama": r[3],
            "kategori": r[4],
            "harga_jual": r[5],
            "metode_pembayaran": r[6],
            "msisdn": r[7],
            "waktu_pembelian": r[8],
            "status": r[9],
            "created_at": r[10],
        })
    return out


def list_pending_due(before_iso: str) -> List[Dict[str, Any]]:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, userid, produk_id, produk_nama, kategori, harga_jual, metode_pembayaran, msisdn, waktu_pembelian, status, created_at FROM transaksi_terjadwal WHERE status = 'pending' AND datetime(waktu_pembelian) <= datetime(?) ORDER BY waktu_pembelian ASC",
        (before_iso,),
    )
    rows = c.fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "userid": r[1],
            "produk_id": r[2],
            "produk_nama": r[3],
            "kategori": r[4],
            "harga_jual": r[5],
            "metode_pembayaran": r[6],
            "msisdn": r[7],
            "waktu_pembelian": r[8],
            "status": r[9],
            "created_at": r[10],
        }
        for r in rows
    ]


def update_status(tx_id: int, status: str) -> bool:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE transaksi_terjadwal SET status = ? WHERE id = ?", (status, tx_id))
    conn.commit()
    changed = c.rowcount > 0
    conn.close()
    return changed


def delete_transaksi(tx_id: int) -> bool:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM transaksi_terjadwal WHERE id = ?", (tx_id,))
    conn.commit()
    changed = c.rowcount > 0
    conn.close()
    return changed


# Ensure table exists on import so handlers/workers can use the model immediately
try:
    init_db()
except Exception:
    # don't block imports if DB creation fails at import-time; functions call init_db() too
    pass