from aiogram import Router, F
from aiogram.types import CallbackQuery
from button.admin_set_user import get_admin_set_user_keyboard
from button.start import get_admin_keyboard  # <- Import tombol start admin

router = Router()

@router.callback_query(F.data == "seting_user")
async def admin_set_user_handler(callback: CallbackQuery):
    await callback.message.edit_text(
        "<b>😎 Menu Seting User</b>\n\n"
        "Silakan pilih aksi yang ingin dilakukan untuk user:",
        parse_mode="HTML",
        reply_markup=get_admin_set_user_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "back_to_admin_menu")
async def back_to_admin_menu_handler(callback: CallbackQuery):
    await callback.message.edit_text(
        "<b>Selamat datang di Menu Admin!</b>\n"
        "Silakan pilih menu yang tersedia di bawah ini:",
        parse_mode="HTML",
        reply_markup=get_admin_keyboard()
    )
    await callback.answer()