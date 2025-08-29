import sqlite3
import os
import math

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "database.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS produk_xl (
            id TEXT PRIMARY KEY,
            nama_produk TEXT,
            kategori TEXT,
            produk_kode TEXT,
            harga INTEGER,
            harga_jual INTEGER,
            total_amount INTEGER,
            deskripsi TEXT,
            status TEXT
        )
    """)
    conn.commit()
    conn.close()

def insert_or_update_produk(produk: dict):
    """
    Simpan data produk (insert jika baru, update jika sudah ada) berdasarkan id produk dari API.
    - Jika produk sudah ada, TIDAK mengubah nama_produk, kategori, dan deskripsi.
    - Jika harga_jual saat ini < harga_jual_baru (dari API), maka update harga dan harga_jual saja.
    - Field lain seperti produk_kode, total_amount, status tetap diupdate.
    """
    import sqlite3
    import math

    DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "database.db")
    harga_baru = int(produk["harga"])
    harga_jual_baru = math.ceil(harga_baru * 1.3)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Cek apakah produk sudah ada
    c.execute("SELECT harga, harga_jual FROM produk_xl WHERE id = ?", (produk["id"],))
    row = c.fetchone()
    if row:
        harga_lama, harga_jual_lama = row
        # Jika harga_jual_lama < harga_jual_baru, update harga dan harga_jual SAJA
        if harga_jual_lama < harga_jual_baru:
            c.execute("""
                UPDATE produk_xl SET
                    harga = ?,
                    harga_jual = ?,
                    produk_kode = ?,
                    total_amount = ?,
                    status = ?
                WHERE id = ?
            """, (
                harga_baru,
                harga_jual_baru,
                produk["produk_kode"],
                int(produk["total_amount"]),
                produk.get("status", "active"),
                produk["id"]
            ))
        else:
            # Update field lain, TIDAK mengubah harga, harga_jual, nama_produk, kategori, deskripsi
            c.execute("""
                UPDATE produk_xl SET
                    produk_kode = ?,
                    total_amount = ?,
                    status = ?
                WHERE id = ?
            """, (
                produk["produk_kode"],
                int(produk["total_amount"]),
                produk.get("status", "active"),
                produk["id"]
            ))
    else:
        # Insert baru, harga_jual = harga + 30%
        c.execute("""
            INSERT INTO produk_xl (id, nama_produk, kategori, produk_kode, harga, harga_jual, total_amount, deskripsi, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            produk["id"],
            produk["nama_produk"],
            produk["kategori"],
            produk["produk_kode"],
            harga_baru,
            harga_jual_baru,
            int(produk["total_amount"]),
            produk.get("deskripsi", ""),
            produk.get("status", "active")
        ))
    conn.commit()
    conn.close()

def sinkronisasi_produk_xl(list_produk_api):
    """
    Sinkronisasi data produk:
    - Hanya insert/update produk yang ada di list_produk_api (menggunakan insert_or_update_produk)
    - Hapus produk di database yang id-nya TIDAK ada di list_produk_api
    """
    ids_api = set(str(produk["id"]) for produk in list_produk_api)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Ambil semua id produk di database
    c.execute("SELECT id FROM produk_xl")
    ids_db = set(row[0] for row in c.fetchall())
    # Hapus produk yang sudah tidak ada di API
    ids_to_delete = ids_db - ids_api
    if ids_to_delete:
        c.executemany("DELETE FROM produk_xl WHERE id = ?", [(id_,) for id_ in ids_to_delete])
    conn.commit()
    conn.close()
    # Insert/update produk dari API
    for produk in list_produk_api:
        insert_or_update_produk(produk)

def get_produk_by_kategori(kategori):
    """
    Ambil semua produk di kategori tertentu dari database.
    Return list of tuple: (id, nama_produk)
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, nama_produk FROM produk_xl WHERE kategori=? ORDER BY id", (kategori,))
    result = c.fetchall()
    conn.close()
    return result