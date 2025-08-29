from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_admin_set_user_keyboard():
    keyboard = [
        [
            InlineKeyboardButton(text="😎 Daftar User", callback_data="admin_daftar_user")
        ],
        [
            InlineKeyboardButton(text="➕ Tambah User", callback_data="admin_add_user"),
            InlineKeyboardButton(text="📝 Edit User", callback_data="admin_edit_user"),
        ],
        [
            InlineKeyboardButton(text="❌ Hapus User", callback_data="admin_delete_user")
        ],
        [
            InlineKeyboardButton(text="⬅️ Kembali ke Menu Admin", callback_data="back_to_admin_menu"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)