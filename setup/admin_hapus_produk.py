from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.fsm.context import FSMContext
from setup.admin_edit_produk import EditProdukStates
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "database.db")

router = Router()

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

def get_kategori_by_produk_id(prod_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT kategori FROM produk_xl WHERE id = ?", (prod_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def get_kategori_keyboard():
    kategori_list = get_all_kategori()
    keyboard = []
    for kategori in kategori_list:
        keyboard.append([InlineKeyboardButton(text=kategori, callback_data=f"kategori_{kategori}")])
    keyboard.append([InlineKeyboardButton(text="🔙 Kembali ke Admin", callback_data="admin_start")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_produk_keyboard(kategori):
    produk_list = get_produk_by_kategori(kategori)
    keyboard = []
    for prod_id, nama in produk_list:
        keyboard.append([InlineKeyboardButton(text=nama, callback_data=f"produk_{prod_id}")])
    keyboard.append([InlineKeyboardButton(text="🔙 Kembali ke Kategori", callback_data="back_to_kategori")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_detail_produk_keyboard(prod_id):
    keyboard = [
        [
            InlineKeyboardButton(text="✏️ Edit", callback_data=f"edit_produk_{prod_id}"),
            InlineKeyboardButton(text="🗑️ Hapus", callback_data=f"hapus_produk_{prod_id}"),
        ],
        [
            InlineKeyboardButton(text="🔙 Kembali ke Daftar Produk", callback_data="back_to_produk")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_konfirmasi_hapus_keyboard(prod_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Ya, Hapus", callback_data=f"hapus_produk_confirm_{prod_id}"),
            InlineKeyboardButton(text="❌ Batal", callback_data="hapus_produk_batal"),
        ]
    ])

@router.callback_query(F.data.startswith("hapus_produk_") & ~F.data.startswith("hapus_produk_confirm_") & ~F.data.startswith("hapus_produk_batal"))
async def konfirmasi_hapus_produk(callback: CallbackQuery):
    prod_id = callback.data.replace("hapus_produk_", "", 1)
    kategori = get_kategori_by_produk_id(prod_id)
    if not kategori:
        await callback.message.edit_text(
            "Produk tidak ditemukan atau sudah dihapus.",
            reply_markup=get_kategori_keyboard()
        )
        await callback.answer()
        return
    await callback.message.edit_text(
        f"Yakin ingin menghapus produk dengan ID <code>{prod_id}</code>?\n\nPilih 'Ya, Hapus' untuk menghapus atau 'Batal' untuk kembali.",
        parse_mode="HTML",
        reply_markup=get_konfirmasi_hapus_keyboard(prod_id)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("hapus_produk_confirm_"))
async def proses_hapus_produk(callback: CallbackQuery):
    prod_id = callback.data.replace("hapus_produk_confirm_", "", 1)
    kategori = get_kategori_by_produk_id(prod_id)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM produk_xl WHERE id = ?", (prod_id,))
    conn.commit()
    conn.close()
    if kategori:
        await callback.message.edit_text(
            f"Produk dengan ID <code>{prod_id}</code> berhasil dihapus.",
            parse_mode="HTML",
            reply_markup=get_produk_keyboard(kategori)
        )
    else:
        await callback.message.edit_text(
            "Produk sudah tidak ada.",
            parse_mode="HTML",
            reply_markup=get_kategori_keyboard()
        )
    await callback.answer()

@router.callback_query(F.data == "hapus_produk_batal")
async def batal_hapus_produk(callback: CallbackQuery):
    # Ambil kategori dari pesan sebelumnya (regex) atau tampilkan daftar kategori
    last_text = callback.message.text or ""
    import re
    match = re.search(r"kategori <b>(.*?)</b>", last_text)
    kategori = match.group(1) if match else None
    if kategori:
        await callback.message.edit_text(
            f"Pilih produk yang ingin dihapus dari kategori <b>{kategori}</b>:",
            parse_mode="HTML",
            reply_markup=get_produk_keyboard(kategori)
        )
    else:
        await callback.message.edit_text(
            "Pilih kategori produk:",
            reply_markup=get_kategori_keyboard()
        )
    await callback.answer()