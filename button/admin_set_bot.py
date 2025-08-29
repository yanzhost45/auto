from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_admin_set_bot_keyboard():
    keyboard = [
        [
            InlineKeyboardButton(text="🟢 Seting Status Bot", callback_data="seting_status_bot"),
            InlineKeyboardButton(text="📢 Kirim Notifikasi User", callback_data="kirim_notif_user"),
        ],
        [
            InlineKeyboardButton(text="🛒 Set Cara Pembelian", callback_data="set_cara_pembelian"),
            InlineKeyboardButton(text="💰 Set Cara Deposit", callback_data="set_cara_deposit"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Kembali ke Menu Admin", callback_data="back_to_admin_menu"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)