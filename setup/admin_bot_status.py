from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from models.seting_bot import set_bot_status, get_latest_bot_status_full

router = Router()

def get_status_choice_keyboard():
    keyboard = [
        [
            InlineKeyboardButton(text="🟢 Open", callback_data="bot_status_open"),
            InlineKeyboardButton(text="🔴 Close", callback_data="bot_status_close"),
            InlineKeyboardButton(text="🛠 Maintenance", callback_data="bot_status_maintenance"),
        ],
        [
            InlineKeyboardButton(text="🌐 Public", callback_data="bot_mode_public"),
            InlineKeyboardButton(text="🔒 Private", callback_data="bot_mode_private"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Kembali", callback_data="seting_bot"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

@router.callback_query(F.data == "seting_status_bot")
async def ask_bot_status_handler(callback: CallbackQuery):
    current = get_latest_bot_status_full()
    current_status = current["status"] if current else None
    current_mode = current["private_public"] if current else "public"
    status_text = {
        "open": "🟢 <b>Open</b> (Bot aktif dan bisa digunakan)",
        "close": "🔴 <b>Close</b> (Bot tidak bisa dipakai user)",
        "maintenance": "🛠 <b>Maintenance</b> (Bot dalam pemeliharaan)"
    }.get(current_status, "Belum ada status bot yang diatur.")
    mode_text = {
        "public": "🌐 <b>Public</b> (Siapa saja bisa pakai)",
        "private": "🔒 <b>Private</b> (Hanya user terdaftar)"
    }.get(current_mode, "Belum ada mode yang diatur.")
    await callback.message.edit_text(
        f"<b>Seting Status Bot</b>\n\n"
        f"Status bot saat ini: {status_text}\n"
        f"Mode bot saat ini: {mode_text}\n\n"
        "Pilih status atau mode baru untuk bot:",
        parse_mode="HTML",
        reply_markup=get_status_choice_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data.in_(["bot_status_open", "bot_status_close", "bot_status_maintenance"]))
async def set_bot_status_handler(callback: CallbackQuery):
    status_map = {
        "bot_status_open": "open",
        "bot_status_close": "close",
        "bot_status_maintenance": "maintenance",
    }
    status = status_map[callback.data]
    # Ambil mode terakhir
    current = get_latest_bot_status_full()
    private_public = current["private_public"] if current else "public"
    set_bot_status(status, private_public)
    status_text = {
        "open": "🟢 <b>Open</b> (Bot aktif dan bisa digunakan)",
        "close": "🔴 <b>Close</b> (Bot tidak bisa dipakai user)",
        "maintenance": "🛠 <b>Maintenance</b> (Bot dalam pemeliharaan)"
    }[status]
    mode_text = {
        "public": "🌐 <b>Public</b> (Siapa saja bisa pakai)",
        "private": "🔒 <b>Private</b> (Hanya user terdaftar)"
    }[private_public]
    await callback.message.edit_text(
        f"✅ Status bot berhasil diubah menjadi: {status_text}\n"
        f"Mode bot saat ini: {mode_text}",
        parse_mode="HTML",
        reply_markup=get_status_choice_keyboard()
    )
    await callback.answer("Status bot diperbarui!")

@router.callback_query(F.data.in_(["bot_mode_public", "bot_mode_private"]))
async def set_bot_mode_handler(callback: CallbackQuery):
    mode_map = {
        "bot_mode_public": "public",
        "bot_mode_private": "private",
    }
    private_public = mode_map[callback.data]
    # Ambil status terakhir
    current = get_latest_bot_status_full()
    status = current["status"] if current else "open"
    set_bot_status(status, private_public)
    status_text = {
        "open": "🟢 <b>Open</b> (Bot aktif dan bisa digunakan)",
        "close": "🔴 <b>Close</b> (Bot tidak bisa dipakai user)",
        "maintenance": "🛠 <b>Maintenance</b> (Bot dalam pemeliharaan)"
    }[status]
    mode_text = {
        "public": "🌐 <b>Public</b> (Siapa saja bisa pakai)",
        "private": "🔒 <b>Private</b> (Hanya user terdaftar)"
    }[private_public]
    await callback.message.edit_text(
        f"✅ Mode bot berhasil diubah menjadi: {mode_text}\n"
        f"Status bot saat ini: {status_text}",
        parse_mode="HTML",
        reply_markup=get_status_choice_keyboard()
    )
    await callback.answer("Mode bot diperbarui!")