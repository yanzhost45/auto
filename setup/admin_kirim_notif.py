from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto, InputMediaVideo, InputMediaAudio, InputMediaDocument
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "database.db")

class KirimNotifStates(StatesGroup):
    waiting_for_content = State()

router = Router()

def get_back_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Kembali ke Menu Seting Bot", callback_data="seting_bot")]
        ]
    )

@router.callback_query(F.data == "kirim_notif_user")
async def notif_menu(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "<b>📢 Kirim Notifikasi User</b>\n\n"
        "Kirimkan pesan, foto, video, audio, file, atau media apa pun yang ingin Anda broadcast ke semua user yang terdaftar.",
        parse_mode="HTML",
        reply_markup=get_back_keyboard()
    )
    await state.set_state(KirimNotifStates.waiting_for_content)
    await callback.answer()

def get_all_user_ids():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT userid FROM users WHERE status='active'")
    userids = [row[0] for row in c.fetchall()]
    conn.close()
    return userids

async def broadcast_to_all_users(bot, user_ids, message: Message):
    sent, failed = 0, 0
    for uid in user_ids:
        try:
            if message.text:
                await bot.send_message(uid, message.text, parse_mode="HTML" if message.html_text else None)
            elif message.photo:
                await bot.send_photo(uid, message.photo[-1].file_id, caption=message.caption or "", parse_mode="HTML")
            elif message.video:
                await bot.send_video(uid, message.video.file_id, caption=message.caption or "", parse_mode="HTML")
            elif message.audio:
                await bot.send_audio(uid, message.audio.file_id, caption=message.caption or "", parse_mode="HTML")
            elif message.document:
                await bot.send_document(uid, message.document.file_id, caption=message.caption or "", parse_mode="HTML")
            elif message.sticker:
                await bot.send_sticker(uid, message.sticker.file_id)
            elif message.voice:
                await bot.send_voice(uid, message.voice.file_id, caption=message.caption or "")
            elif message.animation:
                await bot.send_animation(uid, message.animation.file_id, caption=message.caption or "", parse_mode="HTML")
            else:
                failed += 1
                continue
            sent += 1
        except Exception as e:
            failed += 1
    return sent, failed

@router.message(KirimNotifStates.waiting_for_content)
async def process_broadcast(message: Message, state: FSMContext):
    from aiogram import Bot
    bot: Bot = message.bot

    user_ids = get_all_user_ids()
    sent, failed = await broadcast_to_all_users(bot, user_ids, message)
    await message.answer(
        f"✅ Selesai broadcast.\n"
        f"Berhasil dikirim ke: <b>{sent}</b> user.\n"
        f"Gagal dikirim ke: <b>{failed}</b> user.",
        parse_mode="HTML",
        reply_markup=get_back_keyboard()
    )
    await state.clear()