from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.fsm.context import FSMContext
from setup.admin_edit_produk import EditProdukStates
from data.database import get_all_kategori, get_produk_by_kategori, get_produk_detail, get_user
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "database.db")

router = Router()


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

@router.callback_query(F.data == "daftar_produk")
async def show_kategori(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "Pilih kategori produk:",
        reply_markup=get_kategori_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("kategori_"))
async def show_produk_by_kategori(callback: CallbackQuery, state: FSMContext):
    kategori = callback.data.replace("kategori_", "", 1)
    produk_list = get_produk_by_kategori(kategori)
    await state.update_data(last_kategori=kategori)
    if not produk_list:
        await callback.message.edit_text("Tidak ada produk pada kategori ini.", reply_markup=get_kategori_keyboard())
        return
    await callback.message.edit_text(
        f"Daftar produk di kategori <b>{kategori}</b>:",
        parse_mode="HTML",
        reply_markup=get_produk_keyboard(kategori)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("produk_"))
async def show_produk_detail(callback: CallbackQuery, state: FSMContext):
    produk_id = callback.data.replace("produk_", "", 1)
    produk = get_produk_detail(produk_id)
    if not produk:
        # Ambil kategori terakhir dari FSMContext
        data = await state.get_data()
        kategori = data.get("last_kategori")
        if kategori:
            await callback.message.edit_text(
                "Produk tidak ditemukan atau sudah dihapus.",
                reply_markup=get_produk_keyboard(kategori)
            )
        else:
            await callback.message.edit_text(
                "Produk tidak ditemukan atau sudah dihapus.",
                reply_markup=get_kategori_keyboard()
            )
        await callback.answer()
        return
    # Simpan kategori supaya tombol back bisa kembali ke kategori ini
    await state.update_data(last_kategori=produk['kategori'])
    text = (
        f"<b>Detail Produk</b>\n\n"
        f"ID: <code>{produk['id']}</code>\n"
        f"Nama: <b>{produk['nama_produk']}</b>\n"
        f"Kategori: <b>{produk['kategori']}</b>\n"
        f"Kode: <code>{produk['produk_kode']}</code>\n"
        f"Harga Supplier: <b>{produk['harga']}</b>\n"
        f"Harga Jual: <b>{produk['harga_jual']}</b>\n"
        f"Bayar Ke XL: <b>{produk['total_amount']}</b>\n"
        f"Status: <b>{produk['status']}</b>\n"
        f"Deskripsi: <i>{produk['deskripsi']}</i>"
    )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=get_detail_produk_keyboard(produk_id)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("hapus_produk_confirm_"))
async def konfirmasi_hapus_produk(callback: CallbackQuery, state: FSMContext):
    produk_id = callback.data.replace("hapus_produk_confirm_", "", 1)
    # Hapus produk
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM produk_xl WHERE id = ?", (produk_id,))
    deleted = c.rowcount
    conn.commit()
    conn.close()
    # Ambil kategori terakhir dari FSM
    data = await state.get_data()
    kategori = data.get("last_kategori")
    if deleted:
        msg = f"Produk dengan ID <code>{produk_id}</code> berhasil dihapus."
    else:
        msg = f"Produk dengan ID <code>{produk_id}</code> sudah tidak ada di database."
    await callback.message.edit_text(
        msg,
        parse_mode="HTML",
        reply_markup=get_produk_keyboard(kategori) if kategori else get_kategori_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "hapus_produk_batal")
async def batal_hapus_produk(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    kategori = data.get("last_kategori")
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

@router.callback_query(F.data.startswith("hapus_produk_"))
async def hapus_produk_from_daftar(callback: CallbackQuery, state: FSMContext):
    # Handler ini hanya untuk hapus_produk_{id} SAJA, bukan hapus_produk_confirm_{id}
    produk_id = callback.data.replace("hapus_produk_", "", 1)
    # Jika callback_data dimulai dengan "hapus_produk_confirm_", jangan proses di sini!
    if callback.data.startswith("hapus_produk_confirm_"):
        return
    data = await state.get_data()
    kategori = data.get("last_kategori")
    if not produk_id:
        await callback.message.edit_text(
            "Produk tidak valid.",
            reply_markup=get_produk_keyboard(kategori) if kategori else get_kategori_keyboard()
        )
        await callback.answer()
        return
    keyboard = get_konfirmasi_hapus_keyboard(produk_id)
    await callback.message.edit_text(
        f"Yakin ingin menghapus produk dengan ID <code>{produk_id}</code>?\n\nPilih 'Ya, Hapus' untuk menghapus atau 'Batal' untuk kembali.",
        parse_mode="HTML",
        reply_markup=keyboard
    )
    await callback.answer()

@router.callback_query(F.data == "back_to_produk")
async def back_to_produk_list(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    kategori = data.get("last_kategori")
    if kategori:
        await callback.message.edit_text(
            f"Daftar produk di kategori <b>{kategori}</b>:",
            parse_mode="HTML",
            reply_markup=get_produk_keyboard(kategori)
        )
    else:
        await callback.message.edit_text(
            "Pilih kategori produk:",
            reply_markup=get_kategori_keyboard()
        )
    await callback.answer()

@router.callback_query(F.data == "back_to_kategori")
async def back_to_kategori_list(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Pilih kategori produk:",
        reply_markup=get_kategori_keyboard()
    )
    await callback.answer()