from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
import sqlite3
import os

# Lokasi database
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "database.db")

# FSM State group untuk proses hapus user
class HapusUserState(StatesGroup):
    waiting_userid = State()
    confirm_delete = State()

router = Router()

def get_back_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Kembali ke Menu Seting User", callback_data="seting_user")]
        ]
    )

def get_confirm_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Ya, Hapus", callback_data="confirm_delete_user"),
                InlineKeyboardButton(text="❌ Batal", callback_data="seting_user"),
            ]
        ]
    )

def format_rupiah(amount):
    try:
        amount = int(float(amount))
    except Exception:
        return str(amount)
    return f"Rp{amount:,}".replace(",", ".")

@router.callback_query(F.data == "admin_delete_user")
async def admin_hapus_user_handler(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "<b>❌ Hapus User</b>\n\n"
        "Masukkan <b>User ID</b> user yang ingin dihapus.\n"
        "Contoh: <code>12345678</code>",
        parse_mode="HTML",
        reply_markup=get_back_keyboard()
    )
    await state.set_state(HapusUserState.waiting_userid)
    await callback.answer()

@router.message(HapusUserState.waiting_userid)
async def process_hapus_userid(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("User ID harus berupa angka. Silakan masukkan lagi.")
        return
    userid = int(message.text)
    # Cek user ada atau tidak
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE userid = ?", (userid,))
    user = c.fetchone()
    conn.close()
    if not user:
        await message.answer("❗ User ID tidak ditemukan di database.", reply_markup=get_back_keyboard())
        await state.clear()
        return
    saldo_fmt = format_rupiah(user[2])
    await state.update_data(userid=userid)
    await message.answer(
        f"Apakah Anda yakin ingin menghapus user berikut?\n\n"
        f"<b>User ID:</b> <code>{userid}</code>\n"
        f"<b>Username:</b> <code>@{user[1]}</code>\n"
        f"<b>Saldo:</b> <code>{saldo_fmt}</code>\n"
        f"<b>Role:</b> <code>{user[3]}</code>\n"
        f"<b>Status:</b> <code>{user[5]}</code>",
        parse_mode="HTML",
        reply_markup=get_confirm_keyboard()
    )
    await state.set_state(HapusUserState.confirm_delete)

@router.callback_query(F.data == "confirm_delete_user")
async def confirm_delete_user(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    userid = data.get("userid")
    if not userid:
        await callback.message.edit_text("Proses hapus dibatalkan.", reply_markup=get_back_keyboard())
        await state.clear()
        await callback.answer()
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE userid = ?", (userid,))
    conn.commit()
    conn.close()
    await callback.message.edit_text(
        f"✅ User dengan User ID <code>{userid}</code> berhasil dihapus.",
        parse_mode="HTML",
        reply_markup=get_back_keyboard()
    )
    await state.clear()
    await callback.answer()