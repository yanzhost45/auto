from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
import sqlite3
import os
from datetime import datetime
import re
import pytz
import json

# Lokasi database
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "database.db")

# State group untuk proses tambah user
class AddUserState(StatesGroup):
    waiting_userid = State()
    waiting_username = State()

router = Router()

def get_back_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Kembali ke Menu Seting User", callback_data="seting_user")]
        ]
    )

TELEGRAM_USERNAME_REGEX = re.compile(r"^(?!.*__)[a-zA-Z0-9_]{5,32}$")

def get_notif_bot_token_and_adminid():
    setup_path = os.path.join("core", "setup.json")
    if os.path.exists(setup_path):
        with open(setup_path, "r") as f:
            data = json.load(f)
            notif_token = data.get("notifikasi")
            admin = data.get("admin", {})
            admin_id = admin.get("userid")
            return notif_token, admin_id
    return None, None

async def send_new_user_notification(userid, username, tanggal_daftar, message: Message):
    notif_token, admin_id = get_notif_bot_token_and_adminid()
    if notif_token and admin_id:
        notif_bot = Bot(token=notif_token)
        try:
            text = (
                f"👤 <b>User Berhasil Didaftarkan (Manual Admin)</b>\n"
                f"<b>User ID:</b> <code>{userid}</code>\n"
                f"<b>Username:</b> <code>@{username}</code>\n"
                f"<b>Tanggal Daftar:</b> <code>{tanggal_daftar}</code>\n"
                f"Ditambahkan oleh admin: <code>@{message.from_user.username or message.from_user.id}</code>"
            )
            await notif_bot.send_message(
                chat_id=admin_id,
                text=text,
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Failed to send admin notif: {e}")

@router.callback_query(F.data == "admin_add_user")
async def admin_tambah_user_handler(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "<b>➕ Tambah User</b>\n\n"
        "Masukkan <b>User ID</b> user yang ingin ditambahkan.\n"
        "Contoh: <code>12345678</code>",
        parse_mode="HTML",
        reply_markup=get_back_keyboard()
    )
    await state.set_state(AddUserState.waiting_userid)
    await callback.answer()

@router.message(AddUserState.waiting_userid)
async def process_userid(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("User ID harus berupa angka. Silakan masukkan lagi.")
        return
    await state.update_data(userid=message.text)
    await message.answer(
        "Sekarang masukkan <b>username</b> user (tanpa @). Username harus mengikuti aturan Telegram:\n"
        "- 5-32 karakter\n- Huruf, angka, dan underscore (_)\n- Tidak boleh mengandung dua underscore berturut-turut (__)\n- Tidak boleh diawali atau diakhiri dengan underscore\n"
        "Contoh: <code>kamisama_asep</code>",
        parse_mode="HTML"
    )
    await state.set_state(AddUserState.waiting_username)

@router.message(AddUserState.waiting_username)
async def process_username(message: Message, state: FSMContext):
    username = message.text.strip().lstrip("@")

    # Telegram username validation
    if not TELEGRAM_USERNAME_REGEX.match(username) or username.startswith("_") or username.endswith("_"):
        await message.answer(
            "Username tidak valid!\n\nUsername harus sesuai aturan Telegram:\n"
            "- 5-32 karakter\n- Huruf, angka, dan underscore (_)\n- Tidak boleh __ (dua underscore berturut-turut)\n- Tidak boleh diawali atau diakhiri underscore (_)\n\n"
            "Contoh valid: <code>kamisama_asep</code>",
            parse_mode="HTML"
        )
        return

    data = await state.get_data()
    userid = int(data["userid"])

    # Gunakan zona waktu Asia/Jakarta untuk tanggal daftar
    jakarta = pytz.timezone("Asia/Jakarta")
    tanggal_daftar = datetime.now(jakarta).strftime("%Y-%m-%d %H:%M:%S")

    # Simpan ke database
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Cek, kalau user sudah ada, jangan dobel
    c.execute("SELECT * FROM users WHERE userid = ?", (userid,))
    user = c.fetchone()
    if user:
        await message.answer("❗ User ID tersebut sudah terdaftar di database.")
        conn.close()
        await state.clear()
        return

    c.execute(
        "INSERT INTO users (userid, username, tanggal_daftar) VALUES (?, ?, ?)",
        (userid, username, tanggal_daftar)
    )
    conn.commit()
    conn.close()

    await message.answer(
        f"<b>User berhasil ditambahkan!</b>\n\n"
        f"<b>User ID:</b> <code>{userid}</code>\n"
        f"<b>Username:</b> <code>{username}</code>\n"
        f"<b>Tanggal Daftar:</b> <code>{tanggal_daftar}</code>",
        parse_mode="HTML",
        reply_markup=get_back_keyboard()
    )
    await send_new_user_notification(userid, username, tanggal_daftar, message)
    await state.clear()