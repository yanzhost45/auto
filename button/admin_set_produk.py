from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_admin_set_produk_keyboard():
    keyboard = [
        [
            InlineKeyboardButton(text="🎁 Daftar Produk", callback_data="daftar_produk"),
            InlineKeyboardButton(text="📩 Perbarui Produk", callback_data="perbarui_produk")
        ],
        [
            InlineKeyboardButton(text="🔙 Kembali ke Admin", callback_data="admin_start"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)