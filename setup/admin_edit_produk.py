from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from button.admin_set_produk import get_admin_set_produk_keyboard
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "database.db")

router = Router()

class EditProdukStates(StatesGroup):
    waiting_id = State()
    waiting_nama_produk = State()
    waiting_kategori = State()
    waiting_harga_jual = State()
    waiting_deskripsi = State()
    waiting_status = State()

def get_produk_by_id(produk_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, nama_produk, kategori, harga_jual, deskripsi, status FROM produk_xl WHERE id = ?",
        (produk_id,),
    )
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "id": row[0],
            "nama_produk": row[1],
            "kategori": row[2],
            "harga_jual": row[3],
            "deskripsi": row[4],
            "status": row[5],
        }
    return None

def update_produk_by_id(produk_id, nama_produk, kategori, harga_jual, deskripsi, status):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        UPDATE produk_xl SET
            nama_produk = ?,
            kategori = ?,
            harga_jual = ?,
            deskripsi = ?,
            status = ?
        WHERE id = ?
        """,
        (nama_produk, kategori, harga_jual, deskripsi, status, produk_id),
    )
    conn.commit()
    conn.close()

@router.callback_query(F.data == "edit_produk")
async def admin_edit_produk_menu(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Masukkan ID produk yang ingin diedit:")
    await state.set_state(EditProdukStates.waiting_id)
    await callback.answer()

@router.callback_query(F.data.startswith("edit_produk_"))
async def edit_produk_from_any_menu(callback: CallbackQuery, state: FSMContext):
    produk_id = callback.data.replace("edit_produk_", "", 1).split("_")[0]
    produk = get_produk_by_id(produk_id)
    if not produk:
        await callback.message.answer("Produk dengan ID tersebut tidak ditemukan.")
        return
    await state.set_data({
        "produk_id": produk_id,
        "nama_produk": produk["nama_produk"],
        "kategori": produk["kategori"],
        "harga_jual": produk["harga_jual"],
        "deskripsi": produk["deskripsi"],
        "status": produk["status"],
    })
    await callback.message.edit_text(
        f"Nama produk saat ini: <b>{produk['nama_produk']}</b>\n\nKetik nama produk baru (atau ketik - untuk skip):",
        parse_mode="HTML"
    )
    await state.set_state(EditProdukStates.waiting_nama_produk)
    await callback.answer()

@router.message(EditProdukStates.waiting_id)
async def admin_edit_produk_id(message: Message, state: FSMContext):
    produk_id = message.text.strip()
    produk = get_produk_by_id(produk_id)
    if not produk:
        await message.answer("Produk dengan ID tersebut tidak ditemukan. Silakan masukkan ID yang valid.")
        return
    await state.set_data({
        "produk_id": produk_id,
        "nama_produk": produk["nama_produk"],
        "kategori": produk["kategori"],
        "harga_jual": produk["harga_jual"],
        "deskripsi": produk["deskripsi"],
        "status": produk["status"],
    })
    await message.answer(
        f"Nama produk saat ini: <b>{produk['nama_produk']}</b>\n\nKetik nama produk baru (atau ketik - untuk skip):",
        parse_mode="HTML"
    )
    await state.set_state(EditProdukStates.waiting_nama_produk)

@router.message(EditProdukStates.waiting_nama_produk)
async def admin_edit_produk_nama(message: Message, state: FSMContext):
    data = await state.get_data()
    nama_produk = message.text.strip()
    if nama_produk != "-":
        await state.update_data(nama_produk=nama_produk)
    await message.answer(
        f"Kategori saat ini: <b>{data['kategori']}</b>\n\nKetik kategori baru (atau ketik - untuk skip):",
        parse_mode="HTML"
    )
    await state.set_state(EditProdukStates.waiting_kategori)

@router.message(EditProdukStates.waiting_kategori)
async def admin_edit_produk_kategori(message: Message, state: FSMContext):
    data = await state.get_data()
    kategori = message.text.strip()
    if kategori != "-":
        await state.update_data(kategori=kategori)
    await message.answer(
        f"Harga jual saat ini: <b>{data['harga_jual']}</b>\n\nKetik harga jual baru (atau ketik - untuk skip):",
        parse_mode="HTML"
    )
    await state.set_state(EditProdukStates.waiting_harga_jual)

@router.message(EditProdukStates.waiting_harga_jual)
async def admin_edit_produk_harga_jual(message: Message, state: FSMContext):
    data = await state.get_data()
    harga_jual = message.text.strip()
    if harga_jual != "-":
        if not harga_jual.isdigit():
            await message.answer("Harga jual harus berupa angka. Silakan masukkan lagi.")
            return
        await state.update_data(harga_jual=int(harga_jual))
    await message.answer(
        f"Deskripsi saat ini: <b>{data['deskripsi']}</b>\n\nKetik deskripsi baru (atau ketik - untuk skip):",
        parse_mode="HTML"
    )
    await state.set_state(EditProdukStates.waiting_deskripsi)

@router.message(EditProdukStates.waiting_deskripsi)
async def admin_edit_produk_deskripsi(message: Message, state: FSMContext):
    data = await state.get_data()
    deskripsi = message.text.strip()
    if deskripsi != "-":
        await state.update_data(deskripsi=deskripsi)
    await message.answer(
        f"Status saat ini: <b>{data['status']}</b>\n\nKetik status baru (active/nonactive) atau ketik - untuk skip:",
        parse_mode="HTML"
    )
    await state.set_state(EditProdukStates.waiting_status)

@router.message(EditProdukStates.waiting_status)
async def admin_edit_produk_status(message: Message, state: FSMContext):
    data = await state.get_data()
    status = message.text.strip().lower()
    if status != "-":
        if status not in ("active", "nonactive"):
            await message.answer("Status hanya boleh 'active' atau 'nonactive'. Silakan masukkan lagi.")
            return
        await state.update_data(status=status)
    final = await state.get_data()
    update_produk_by_id(
        produk_id=final["produk_id"],
        nama_produk=final["nama_produk"],
        kategori=final["kategori"],
        harga_jual=final["harga_jual"],
        deskripsi=final["deskripsi"],
        status=final["status"]
    )
    await message.answer(
        "Produk berhasil diupdate.\n\n"
        f"Nama Produk: <b>{final['nama_produk']}</b>\n"
        f"Kategori: <b>{final['kategori']}</b>\n"
        f"Harga Jual: <b>{final['harga_jual']}</b>\n"
        f"Deskripsi: <b>{final['deskripsi']}</b>\n"
        f"Status: <b>{final['status']}</b>",
        parse_mode="HTML",
        reply_markup=get_admin_set_produk_keyboard()
    )
    await state.clear()