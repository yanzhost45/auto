from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
import sqlite3
import os
import re
import aiohttp
import asyncio
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import logging
import random

logger = logging.getLogger(__name__)
# Lokasi database
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "database.db")

# FSM State group untuk proses edit user
class EditUserState(StatesGroup):
    waiting_userid = State()
    choosing_field = State()
    editing_username = State()
    editing_saldo = State()
    # editing_role and editing_status handled via inline buttons/callbacks

router = Router()

def get_back_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Kembali ke Menu Seting User", callback_data="seting_user")]
        ]
    )

def get_edit_field_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Username", callback_data="edit_field_username"),
                InlineKeyboardButton(text="Saldo", callback_data="edit_field_saldo"),
            ],
            [
                InlineKeyboardButton(text="Role", callback_data="edit_field_role"),
                InlineKeyboardButton(text="Status", callback_data="edit_field_status"),
            ],
            [
                InlineKeyboardButton(text="❌ Batal", callback_data="seting_user"),
            ]
        ]
    )

TELEGRAM_USERNAME_REGEX = re.compile(r"^(?!.*__)[a-zA-Z0-9_]{5,32}$")

# --- helper: load setup and send notification via notification bot ----------------
def _load_setup():
    setup_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "core", "setup.json")
    if not os.path.exists(setup_path):
        return {}
    try:
        with open(setup_path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}

async def _send_notif_message(notif_token: str, chat_id: str, text: str, parse_mode: str = "HTML", max_try: int = 3) -> bool:
    """
    Send a text notification via notification bot token.
    Returns True on success, False on failure.
    Uses simple retry/backoff to handle transient network issues.
    """
    if not notif_token:
        return False
    url = f"https://api.telegram.org/bot{notif_token}/sendMessage"
    payload = {
        "chat_id": str(chat_id),
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }
    backoff = 1.0
    for attempt in range(1, max_try + 1):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=30) as resp:
                    text_resp = await resp.text()
                    if resp.status == 200:
                        logger.debug("Notif sent OK to %s: %s", chat_id, text_resp)
                        return True
                    logger.error("Notif send failed (status %s): %s", resp.status, text_resp)
        except (aiohttp.client_exceptions.ClientConnectorError, ConnectionResetError, asyncio.TimeoutError) as e:
            logger.warning("Network error sending notif (attempt %s/%s): %s", attempt, max_try, e)
        except Exception as e:
            logger.exception("Unexpected error sending notif (attempt %s/%s): %s", attempt, max_try, e)
        await asyncio.sleep(backoff)
        backoff *= 1.8
    return False

# ------------------------------------------------------------------------------

@router.callback_query(F.data == "admin_edit_user")
async def admin_edit_user_handler(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "<b>📝 Edit User</b>\n\n"
        "Masukkan <b>User ID</b> user yang ingin diedit.\n"
        "Contoh: <code>12345678</code>",
        parse_mode="HTML",
        reply_markup=get_back_keyboard()
    )
    await state.set_state(EditUserState.waiting_userid)
    await callback.answer()

@router.message(EditUserState.waiting_userid)
async def process_edit_userid(message: Message, state: FSMContext):
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
        await message.answer("❗ User ID tidak ditemukan di database.")
        await state.clear()
        return
    await state.update_data(userid=userid)
    await message.answer(
        "<b>Pilih field yang ingin diedit:</b>",
        parse_mode="HTML",
        reply_markup=get_edit_field_keyboard()
    )
    await state.set_state(EditUserState.choosing_field)

@router.callback_query(F.data.in_(["edit_field_username", "edit_field_saldo", "edit_field_role", "edit_field_status"]))
async def choose_edit_field(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    userid = data.get("userid")
    if not userid:
        await callback.message.edit_text("Proses edit dibatalkan.", reply_markup=get_back_keyboard())
        await state.clear()
        await callback.answer()
        return

    if callback.data == "edit_field_username":
        await callback.message.edit_text(
            "Masukkan username baru untuk user ini (tanpa @).",
            parse_mode="HTML",
            reply_markup=get_back_keyboard()
        )
        await state.set_state(EditUserState.editing_username)
    elif callback.data == "edit_field_saldo":
        await callback.message.edit_text(
            "Masukkan perubahan saldo: gunakan +angka untuk menambahkan, -angka untuk mengurangi.\n"
            "Contoh: <code>+2000</code> (tambah 2000) atau <code>-500</code> (kurangi 500).",
            parse_mode="HTML",
            reply_markup=get_back_keyboard()
        )
        await state.set_state(EditUserState.editing_saldo)
    elif callback.data == "edit_field_role":
        # show buttons to pick role
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Set ke user", callback_data=f"set_role:{userid}:user"),
             InlineKeyboardButton(text="Set ke admin", callback_data=f"set_role:{userid}:admin")],
            [InlineKeyboardButton(text="❌ Batal", callback_data="seting_user")]
        ])
        await callback.message.edit_text("Pilih role baru untuk user ini:", reply_markup=kb)
        await state.set_state(EditUserState.choosing_field)
    elif callback.data == "edit_field_status":
        # show buttons to pick status
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Set ke active", callback_data=f"set_status:{userid}:active"),
             InlineKeyboardButton(text="Set ke nonactive", callback_data=f"set_status:{userid}:nonactive")],
            [InlineKeyboardButton(text="❌ Batal", callback_data="seting_user")]
        ])
        await callback.message.edit_text("Pilih status baru untuk user ini:", reply_markup=kb)
        await state.set_state(EditUserState.choosing_field)
    await callback.answer()

@router.message(EditUserState.editing_username)
async def edit_username(message: Message, state: FSMContext):
    username = message.text.strip().lstrip("@")
    if not TELEGRAM_USERNAME_REGEX.match(username) or username.startswith("_") or username.endswith("_"):
        await message.answer(
            "Username tidak valid!\n\nUsername harus sesuai aturan Telegram:\n"
            "- 5-32 karakter\n- Huruf, angka, dan underscore (_)\n- Tidak boleh __ (dua underscore berturut-turut)\n- Tidak boleh diawali atau diakhiri underscore (_)\n\n"
            "Contoh valid: <code>kamisama_asep</code>",
            parse_mode="HTML"
        )
        return
    data = await state.get_data()
    userid = data["userid"]
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET username = ? WHERE userid = ?", (username, userid))
    conn.commit()
    conn.close()
    await message.answer(f"Username user <code>{userid}</code> berhasil diubah menjadi <code>{username}</code>.", parse_mode="HTML", reply_markup=get_back_keyboard())
    await state.clear()

@router.message(EditUserState.editing_saldo)
async def edit_saldo(message: Message, state: FSMContext):
    """
    Now supports adding/subtracting saldo:
    - Input must start with '+' or '-' followed by digits, e.g. +2000 or -500.
    - The handler applies the delta to the current saldo (does not replace).
    - Sends notification via notification bot when delta != 0 (both add and subtract).
    """
    text = message.text.strip()
    if not re.match(r"^[+-]\d+$", text):
        await message.answer("Format tidak valid. Masukkan perubahan saldo dengan format +angka atau -angka, mis. +2000 atau -500.")
        return

    delta = int(text)  # will be positive or negative
    data = await state.get_data()
    userid = data["userid"]

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT saldo, username FROM users WHERE userid = ?", (userid,))
    row = c.fetchone()
    if not row:
        conn.close()
        await message.answer("❗ User ID tidak ditemukan di database.")
        await state.clear()
        return

    old_saldo = row[0] or 0
    username = row[1] or "-"

    new_saldo = old_saldo + delta
    if new_saldo < 0:
        new_saldo = 0  # prevent negative balance, adjust as you prefer

    # update saldo to new_saldo
    c.execute("UPDATE users SET saldo = ? WHERE userid = ?", (new_saldo, userid))
    conn.commit()
    conn.close()

    verb = "ditambahkan" if delta > 0 else "dikurangi"
    abs_delta = abs(delta)
    await message.answer(
        f"Saldo user <code>{userid}</code> berhasil {verb} sebesar <b>Rp{abs_delta}</b>.\n"
        f"Sebelum: <b>Rp{old_saldo}</b>\n"
        f"Sesudah: <b>Rp{new_saldo}</b>",
        parse_mode="HTML",
        reply_markup=get_back_keyboard()
    )

    # notify via notification bot if change occurred
    if delta != 0:
        setup = _load_setup()
        notif_token = setup.get("notifikasi")
        if notif_token:
            # buat id transaksi unik sederhana
            trx_id = f"admin_update_{userid}_{int(time.time())}_{random.randint(100,999)}"
            # waktu Asia/Jakarta
            try:
                now_jkt = datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                now_jkt = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

            # format pesan sesuai permintaan, show delta with sign
            amount_label = f"+Rp{abs_delta}" if delta > 0 else f"-Rp{abs_delta}"
            caption = (
                f"🔔 <b>Perubahan Saldo oleh Admin</b>\n"
                f"• Userid: <code>{userid}</code>\n"
                f"• Username: @{(username or '-').lstrip('@')}\n"
                f"• Jumlah: <b>{amount_label}</b>\n"
                f"• Saldo sebelum: <b>Rp{old_saldo}</b>\n"
                f"• Saldo sekarang: <b>Rp{new_saldo}</b>\n"
                f"• ID Transaksi: <code>{trx_id}</code>\n"
                f"• Waktu: <code>{now_jkt}</code>\n"
            )
            try:
                sent = await _send_notif_message(notif_token, str(userid), caption, parse_mode="HTML")
                if not sent:
                    logger.warning("Gagal mengirim notifikasi perubahan saldo ke user %s menggunakan token notifikasi", userid)
            except Exception:
                logger.exception("Exception saat mengirim notifikasi perubahan saldo ke user %s", userid)

    await state.clear()

# Callback handler to set role via buttons
@router.callback_query(F.data.regexp(r"^set_role:(\d+):(user|admin)$"))
async def set_role_callback(callback: CallbackQuery, state: FSMContext):
    match = re.match(r"^set_role:(\d+):(user|admin)$", callback.data)
    if not match:
        await callback.answer("Data role tidak valid.", show_alert=True)
        return
    userid = int(match.group(1))
    new_role = match.group(2)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT role, username FROM users WHERE userid = ?", (userid,))
    row = c.fetchone()
    if not row:
        conn.close()
        await callback.answer("User ID tidak ditemukan.", show_alert=True)
        return
    old_role = row[0] or "-"
    username = row[1] or "-"

    if old_role == new_role:
        conn.close()
        await callback.answer(f"Role sudah {new_role}.", show_alert=True)
        return

    c.execute("UPDATE users SET role = ? WHERE userid = ?", (new_role, userid))
    conn.commit()
    conn.close()

    # notify admin (confirmation) and user via notification bot
    await callback.message.edit_text(f"Role user <code>{userid}</code> berhasil diubah menjadi <code>{new_role}</code>.", parse_mode="HTML", reply_markup=get_back_keyboard())
    await callback.answer()

    # send notification to user via notif bot (like saldo update)
    setup = _load_setup()
    notif_token = setup.get("notifikasi")
    if notif_token:
        trx_id = f"admin_update_role_{userid}_{int(time.time())}_{random.randint(100,999)}"
        try:
            now_jkt = datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            now_jkt = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        caption = (
            f"🔔 <b>Perubahan Role oleh Admin</b>\n"
            f"• Userid: <code>{userid}</code>\n"
            f"• Username: @{(username or '-').lstrip('@')}\n"
            f"• Role baru: <b>{new_role}</b>\n"
            f"• ID Transaksi: <code>{trx_id}</code>\n"
            f"• Waktu: <code>{now_jkt}</code>\n"
        )
        try:
            sent = await _send_notif_message(notif_token, str(userid), caption, parse_mode="HTML")
            if not sent:
                logger.warning("Gagal mengirim notifikasi role change ke user %s", userid)
        except Exception:
            logger.exception("Exception saat mengirim notifikasi role change ke user %s", userid)

# Callback handler to set status via buttons
@router.callback_query(F.data.regexp(r"^set_status:(\d+):(active|nonactive)$"))
async def set_status_callback(callback: CallbackQuery, state: FSMContext):
    match = re.match(r"^set_status:(\d+):(active|nonactive)$", callback.data)
    if not match:
        await callback.answer("Data status tidak valid.", show_alert=True)
        return
    userid = int(match.group(1))
    new_status = match.group(2)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT status, username FROM users WHERE userid = ?", (userid,))
    row = c.fetchone()
    if not row:
        conn.close()
        await callback.answer("User ID tidak ditemukan.", show_alert=True)
        return
    old_status = row[0] or "-"
    username = row[1] or "-"

    if old_status == new_status:
        conn.close()
        await callback.answer(f"Status sudah {new_status}.", show_alert=True)
        return

    c.execute("UPDATE users SET status = ? WHERE userid = ?", (new_status, userid))
    conn.commit()
    conn.close()

    # confirm to admin in UI
    await callback.message.edit_text(f"Status user <code>{userid}</code> berhasil diubah menjadi <code>{new_status}</code>.", parse_mode="HTML", reply_markup=get_back_keyboard())
    await callback.answer()

    # send notification to user via notif bot (like saldo update)
    setup = _load_setup()
    notif_token = setup.get("notifikasi")
    if notif_token:
        trx_id = f"admin_update_status_{userid}_{int(time.time())}_{random.randint(100,999)}"
        try:
            now_jkt = datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            now_jkt = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        caption = (
            f"🔔 <b>Perubahan Status oleh Admin</b>\n"
            f"• Userid: <code>{userid}</code>\n"
            f"• Username: @{(username or '-').lstrip('@')}\n"
            f"• Status baru: <b>{new_status}</b>\n"
            f"• ID Transaksi: <code>{trx_id}</code>\n"
            f"• Waktu: <code>{now_jkt}</code>\n"
        )
        try:
            sent = await _send_notif_message(notif_token, str(userid), caption, parse_mode="HTML")
            if not sent:
                logger.warning("Gagal mengirim notifikasi status change ke user %s", userid)
        except Exception:
            logger.exception("Exception saat mengirim notifikasi status change ke user %s", userid)