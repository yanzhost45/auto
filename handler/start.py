from aiogram import types, Router, Bot
from aiogram.filters import Command
from sessions import sessions
from data.database import add_user, user_exists, get_user
from button.start import get_admin_keyboard, get_user_keyboard
from api.profile import update_user_profile
from models.seting_bot import get_latest_bot_status_full
import json
import os
import html
import logging

router = Router()
logger = logging.getLogger(__name__)


def format_rupiah(amount):
    try:
        amount = int(float(amount))
    except Exception:
        return str(amount)
    return f"Rp{amount:,}".replace(",", ".")


def get_admin_saldo_api():
    token_path = os.path.join("core", "token.json")
    if os.path.exists(token_path):
        with open(token_path, "r") as f:
            data = json.load(f)
            return data.get("user", {}).get("saldo")
    return None


def get_admin_username():
    setup_path = os.path.join("core", "setup.json")
    if os.path.exists(setup_path):
        with open(setup_path, "r") as f:
            data = json.load(f)
            admin = data.get("admin", {})
            uname = admin.get("username")
            if isinstance(uname, str):
                return uname
    return None


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


async def _safe_send(bot: Bot, chat_id, text, parse_mode="HTML", reply_markup=None):
    """
    Try to send message with HTML parse_mode. If Telegram complains about entities,
    fall back to plain text (no parse_mode) and ensure special characters are escaped.
    """
    try:
        return await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    except Exception as e:
        # If it's a TelegramBadRequest about entities, fallback to safe plain text
        try:
            safe_text = text
            # Remove problematic control characters (like zero byte) and unrecognized tags.
            safe_text = safe_text.replace("\x00", "")
            # Remove all tags for fallback plain text
            from re import sub
            safe_text = sub(r"</?[^>]+>", "", safe_text)
            return await bot.send_message(chat_id=chat_id, text=safe_text, reply_markup=reply_markup)
        except Exception:
            logger.exception("Failed to send fallback message to %s", chat_id)
            raise


async def send_new_user_notification(user_id, username, first_name, last_name):
    notif_token, admin_id = get_notif_bot_token_and_adminid()
    if notif_token and admin_id:
        notif_bot = Bot(token=notif_token)
        try:
            # sanitize inputs
            uname = (username or "-")
            uname_clean = str(uname).lstrip("@").replace("\x00", "")
            name = f"{(first_name or '').strip()} {(last_name or '').strip()}".strip()
            name_clean = name.replace("\x00", "")
            # escape for HTML
            uname_esc = html.escape(uname_clean)
            name_esc = html.escape(name_clean) or "-"
            text = (
                "👤 <b>User Baru Mendaftar</b>\n"
                f"<b>User ID:</b> <code>{html.escape(str(user_id))}</code>\n"
                f"<b>Username:</b> @{uname_esc}\n"
                f"<b>Nama:</b> <code>{name_esc}</code>\n"
                "\nPeriksa dan kelola user di bot utama."
            )
            await _safe_send(notif_bot, admin_id, text, parse_mode="HTML")
        except Exception:
            logger.exception("Failed to send admin notif for new user")


@router.message(Command("start"))
async def start_handler(message: types.Message):
    user_id = message.from_user.id
    # username can be None, and may contain unexpected chars
    raw_username = message.from_user.username if message.from_user.username is not None else "-"
    # remove NUL and other control chars
    raw_username = str(raw_username).replace("\x00", "")
    username = raw_username
    first_name = (message.from_user.first_name or "").replace("\x00", "")
    last_name = (message.from_user.last_name or "").replace("\x00", "")

    # RESET / CLEAR session user setiap start!
    try:
        # sessions may be dict-like or have clear method per earlier code
        if hasattr(sessions, "clear") and callable(sessions.clear):
            try:
                sessions.clear(user_id)
            except TypeError:
                try:
                    sessions.clear()
                except Exception:
                    pass
        else:
            try:
                sessions.pop(user_id, None)
            except Exception:
                pass
    except Exception:
        logger.exception("Failed to clear session for user %s", user_id)

    # Ambil status bot dan mode private/public
    bot_status_data = get_latest_bot_status_full() or {"status": "open", "private_public": "public"}
    bot_status = bot_status_data.get("status", "open")
    bot_mode = bot_status_data.get("private_public", "public")

    status_text = {
        "open": "🟢 Bot Aktif",
        "close": "🔴 Bot Ditutup",
        "maintenance": "🛠 Bot Maintenance"
    }.get(bot_status, bot_status)
    mode_text = {
        "public": "🌐 Mode: Public",
        "private": "🔒 Mode: Private"
    }.get(bot_mode, bot_mode)

    # Jika mode private, hanya user yang sudah terdaftar boleh akses
    if bot_mode == "private" and not user_exists(user_id):
        admin_username = get_admin_username()
        buttons = []
        if admin_username:
            admin_username_safe = str(admin_username).lstrip("@")
            buttons.append(
                [types.InlineKeyboardButton(
                    text="📞 Kontak Admin",
                    url=f"https://t.me/{admin_username_safe}"
                )]
            )
        markup = types.InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
        text = (
            f"{status_text}\n{mode_text}\n\n"
            "🚫 Bot dalam mode <b>PRIVATE</b>. Akun Anda belum terdaftar di bot ini.\n"
            "Silakan hubungi admin untuk mendapatkan akses."
        )
        await _safe_send(message.bot, message.chat.id, text, parse_mode="HTML", reply_markup=markup)
        return

    # Jika mode public, data user baru akan disimpan saat start
    is_new_user = False
    if not user_exists(user_id):
        add_user(user_id, username)
        is_new_user = True

    # Setelah reset, isi session baru
    try:
        if hasattr(sessions, "update") and callable(sessions.update):
            try:
                sessions.update(user_id, {"welcome": True})
            except TypeError:
                try:
                    sessions[user_id] = {"welcome": True}
                except Exception:
                    pass
        else:
            try:
                sessions[user_id] = {"welcome": True}
            except Exception:
                pass
    except Exception:
        logger.exception("Failed to set session for user %s", user_id)

    user = get_user(user_id)

    # Jika user baru, kirim notifikasi ke admin melalui bot notifikasi
    if is_new_user:
        await send_new_user_notification(user_id, username, first_name, last_name)

    # Cek status user
    if user and user.get("status") == "nonactive":
        admin_username = get_admin_username()
        buttons = []
        if admin_username:
            admin_username_safe = str(admin_username).lstrip("@")
            buttons.append(
                [types.InlineKeyboardButton(
                    text="📞 Kontak Admin",
                    url=f"https://t.me/{admin_username_safe}"
                )]
            )
        markup = types.InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
        text = (
            "🚫 Akun Anda saat ini <b>Nonaktif</b>.\n"
            "Silakan hubungi admin untuk mengaktifkan kembali akun Anda."
        )
        await _safe_send(message.bot, message.chat.id, text, parse_mode="HTML", reply_markup=markup)
        return

    # Update profile admin dari API
    if user and user.get("role") == "admin":
        try:
            update_user_profile()
        except Exception as e:
            text = f"⚠️ Gagal update data profile admin dari API:\n<code>{html.escape(str(e))}</code>"
            await _safe_send(message.bot, message.chat.id, text, parse_mode="HTML")

    # Tampilkan menu sesuai role & status bot
    if user and user.get("role") == "admin":
        saldo_bot = user.get("saldo", 0)
        saldo_api = get_admin_saldo_api()
        saldo_bot_fmt = format_rupiah(saldo_bot)
        saldo_api_fmt = format_rupiah(saldo_api) if saldo_api is not None else "Tidak tersedia"
        saldo_text = (
            f"<b>Saldo (Bot DB):</b> <code>{html.escape(saldo_bot_fmt)}</code>\n"
            f"<b>Saldo (API):</b> <code>{html.escape(saldo_api_fmt)}</code>\n"
        )
        keyboard = get_admin_keyboard()
        uname_db = user.get("username") or "-"
        uname_db = str(uname_db).replace("\x00", "").lstrip("@")
        text = (
            f"{status_text}\n{mode_text}\n\n"
            f"<b>Selamat datang di Bot Telegram!</b>\n"
            f"Senang bertemu denganmu, <i>{html.escape(first_name)} {html.escape(last_name)}</i>.\n\n"
            f"<b>User ID:</b> <code>{html.escape(str(user.get('userid')))}</code>\n"
            f"<b>Username:</b> <code>@{html.escape(uname_db)}</code>\n"
            f"{saldo_text}"
            f"<b>Role:</b> <code>{html.escape(str(user.get('role')))}</code>\n"
            f"<b>Tanggal Daftar:</b> <code>{html.escape(str(user.get('tanggal_daftar')))}</code>\n"
            f"<b>Status:</b> <code>{html.escape(str(user.get('status')))}</code>\n"
            f"\nSilakan gunakan menu atau perintah yang tersedia."
        )
        await _safe_send(message.bot, message.chat.id, text, parse_mode="HTML", reply_markup=keyboard)
    else:
        saldo_bot_fmt = format_rupiah((user or {}).get('saldo', 0))
        saldo_text = f"<b>Saldo:</b> <code>{html.escape(saldo_bot_fmt)}</code>\n"
        if bot_status == "open":
            keyboard = get_user_keyboard()
            uname_db = (user or {}).get("username") or "-"
            uname_db = str(uname_db).replace("\x00", "").lstrip("@")
            text = (
                f"{status_text}\n{mode_text}\n\n"
                f"<b>Selamat datang di Bot Telegram!</b>\n"
                f"Senang bertemu denganmu, <i>{html.escape(first_name)} {html.escape(last_name)}</i>.\n\n"
                f"<b>User ID:</b> <code>{html.escape(str((user or {}).get('userid')))}</code>\n"
                f"<b>Username:</b> <code>@{html.escape(uname_db)}</code>\n"
                f"{saldo_text}"
                f"<b>Role:</b> <code>{html.escape(str((user or {}).get('role')))}</code>\n"
                f"<b>Tanggal Daftar:</b> <code>{html.escape(str((user or {}).get('tanggal_daftar')))}</code>\n"
                f"<b>Status:</b> <code>{html.escape(str((user or {}).get('status')))}</code>\n"
                f"\nSilakan gunakan menu atau perintah yang tersedia."
            )
            await _safe_send(message.bot, message.chat.id, text, parse_mode="HTML", reply_markup=keyboard)
        else:
            text = (
                f"{status_text}\n{mode_text}\n\n"
                "Mohon maaf, saat ini bot sedang tidak dapat digunakan.\n"
                "Silakan coba lagi nanti atau hubungi admin jika ada keperluan."
            )
            await _safe_send(message.bot, message.chat.id, text, parse_mode="HTML")