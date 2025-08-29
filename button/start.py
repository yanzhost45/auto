from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import os
import json
import logging

logger = logging.getLogger(__name__)

def _setup_path() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "core", "setup.json")

def read_setup() -> dict:
    try:
        p = _setup_path()
        if not os.path.exists(p):
            return {}
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        logger.exception("Failed to read setup.json")
        return {}

def _notif_username_from_setup() -> str | None:
    """
    Return the notification bot username (without @) if present in setup.json.
    Looks for the explicit key 'notifikasi_username' (use this exact key in setup.json).
    """
    s = read_setup()
    val = s.get("notifikasi_username")
    if not val:
        return None
    v = str(val).strip()
    if v == "" or ":" in v:  # skip tokens or empty values
        return None
    return v.lstrip("@")

def get_admin_keyboard():
    notif_username = _notif_username_from_setup()
    keyboard = [
        [
            InlineKeyboardButton(text="😎 Seting User", callback_data="seting_user"),
            InlineKeyboardButton(text="🎁 Seting Produk", callback_data="seting_produk"),
        ],
        [
            InlineKeyboardButton(text="🤖 Seting Bot", callback_data="seting_bot"),
        ],
        [
            InlineKeyboardButton(text="📲 OTP Login", callback_data="otp_login"),
            InlineKeyboardButton(text="🎁 Transaksi terjadwal", callback_data="jadwal_transaksi"),
        ],
        [
            InlineKeyboardButton(text="📱 Sidompul Cek Kuota", callback_data="sidompul_cek_kuota"),
        ],
        [
            InlineKeyboardButton(text="💵 Deposit Api", callback_data="deposit_api"),
        ],
        [
            InlineKeyboardButton(text="🧿 Transaksi Pending", callback_data="pending_transaksi"),
            InlineKeyboardButton(
                text="📊 Riwayat Transaksi",
                url=(f"https://t.me/{notif_username}?start=riwayat" if notif_username else None),
                callback_data=("riwayat_transaksi" if not notif_username else None)
            ),
        ],
        [
            InlineKeyboardButton(text="📌 Cara Pembelian", callback_data="cara_pembelian"),
            InlineKeyboardButton(text="📌 Cara Deposit", callback_data="cara_deposit"),
        ],
    ]
    # aiogram InlineKeyboardButton ignores None fields appropriately; construct markup
    # rebuild the deposit/riwayat pair to ensure proper fields
    # (above list already correct for typical aiogram usage)
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_user_keyboard():
    notif_username = _notif_username_from_setup()
    keyboard = [
        [
            InlineKeyboardButton(text="📲 OTP Login", callback_data="otp_login"),
            InlineKeyboardButton(text="🎁 Transaksi terjadwal", callback_data="jadwal_transaksi"),
        ],
        [
            InlineKeyboardButton(text="📱 Sidompul Cek Kuota", callback_data="sidompul_cek_kuota"),
        ],
        [
            InlineKeyboardButton(text="💵 Deposit", callback_data="deposit"),
        ],
        [
            InlineKeyboardButton(text="🧿 Transaksi Pending", callback_data="pending_transaksi"),
            InlineKeyboardButton(
                text="📊 Riwayat Transaksi",
                url=(f"https://t.me/{notif_username}?start=riwayat" if notif_username else None),
                callback_data=("riwayat_transaksi" if not notif_username else None)
            ),
        ],
        [
            InlineKeyboardButton(text="📌 Cara Pembelian", callback_data="cara_pembelian"),
            InlineKeyboardButton(text="📌 Cara Deposit", callback_data="cara_deposit"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)