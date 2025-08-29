from __future__ import annotations
import json

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from api.cek_sesi_nomor import refresh_xl_session
from api.kirim_otp import kirim_otp_xl
from api.login_otp import login_xl_with_otp
from data.database import get_user

# Import the function from menu_login_xl for direct call
from handler.menu_login_xl import show_menu_login_xl

router = Router()

class OtpLoginStates(StatesGroup):
    waiting_for_msisdn = State()
    waiting_for_otp = State()


def get_back_keyboard(role: str = "user") -> InlineKeyboardMarkup:
    if role == "admin":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Kembali ke Menu Admin", callback_data="back_to_admin_menu")]
            ]
        )
    else:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Kembali ke Menu Utama", callback_data="back_to_user_menu")]
            ]
        )


def get_kirim_otp_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Kirim OTP", callback_data="kirim_otp")],
            [InlineKeyboardButton(text="⬅️ Batal", callback_data="otp_login_cancel")],
        ]
    )


def get_webapp_keyboard_for_input(webapp_url_base: str = "https://web-otp-xl.vercel.app") -> InlineKeyboardMarkup:
    """
    Show a WebApp button for entering the phone number. This is presented
    immediately when user opens the OTP login flow, so user can enter the
    MSISDN inside the mini-app instead of typing in chat.
    """
    url = f"{webapp_url_base}"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Masukkan Nomor di Web (Web OTP)", web_app=WebAppInfo(url=url))],
            [InlineKeyboardButton(text="⬅️ Batal", callback_data="otp_login_cancel")],
        ]
    )
    return kb


@router.callback_query(F.data == "otp_login")
async def ask_phone(callback: CallbackQuery, state: FSMContext):
    """
    Entry point: show WebApp button to input number (as requested),
    plus a fallback option to type number in chat.
    """
    user = get_user(callback.from_user.id)
    role = user["role"] if user else "user"
    await callback.message.edit_text(
        "🔒 <b>OTP Login XL</b>\n\n"
        "Anda bisa memasukkan nomor XL melalui web-otp (disarankan) atau ketik langsung di chat.\n"
        'Jika verifikasi otp melalui web-otp langsung masukan nomor disini'
        "Format: 08xxx atau 628xxx",
        parse_mode="HTML",
        reply_markup=get_webapp_keyboard_for_input(),
    )
    await state.set_state(OtpLoginStates.waiting_for_msisdn)
    await callback.answer()


@router.callback_query(F.data == "type_msisdn")
async def enable_type_msisdn(callback: CallbackQuery, state: FSMContext):
    """
    If user chooses fallback to typing, prompt them to type the number.
    """
    user = get_user(callback.from_user.id)
    role = user["role"] if user else "user"
    await callback.message.edit_text(
        "Silakan ketik nomor XL Anda di chat (format 08xxx atau 628xxx).",
        parse_mode="HTML",
        reply_markup=get_back_keyboard(role),
    )
    await state.set_state(OtpLoginStates.waiting_for_msisdn)
    await callback.answer()


@router.message(OtpLoginStates.waiting_for_msisdn)
async def process_msisdn(message: Message, state: FSMContext):
    """
    Fallback: user typed MSISDN in chat. Validate and proceed exactly as before.
    """
    msisdn = message.text.strip()
    if msisdn.startswith("08"):
        msisdn = "62" + msisdn[1:]
    if not msisdn.isdigit() or len(msisdn) < 10:
        await message.answer("❗️ Format nomor tidak valid. Masukkan nomor XL yang benar (08xxxx atau 628xxxx).")
        return

    await state.update_data(msisdn=msisdn)
    await message.answer("⏳ Mengecek sesi nomor...")

    cek = refresh_xl_session(msisdn)
    if cek.get("success"):
        await state.update_data(msisdn=msisdn)
        await message.answer("✅ <b>Nomor sudah terdaftar & sesi aktif.</b>\nMengambil info pulsa dan kuota...", parse_mode="HTML")
        user = get_user(message.from_user.id)
        role = user["role"] if user else "user"
        await show_menu_login_xl(message, state, msisdn, role)
        await state.clear()
        return

    # session not active -> offer to send OTP (via bot) or instruct to use webapp (again)
    await message.answer(
        "❗️ Sesi nomor belum aktif atau gagal cek sesi.\n"
        "Anda bisa kirim OTP lewat bot atau kembali ke mini-app untuk verifikasi.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Kirim OTP (via bot)", callback_data="kirim_otp")],
                [InlineKeyboardButton(text="⬅️ Batal", callback_data="otp_login_cancel")],
            ]
        ),
    )


@router.callback_query(F.data == "kirim_otp")
async def send_otp(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    msisdn = data.get("msisdn")
    if not msisdn:
        await callback.message.answer("Nomor tidak ditemukan, silakan ulangi proses login.")
        await state.clear()
        return
    await callback.message.edit_text("🔄 Mengirim OTP ke nomor Anda, mohon tunggu...")
    result = kirim_otp_xl(msisdn)
    if result.get("success"):
        await callback.message.answer(
            "✅ OTP berhasil dikirim!\n\nSilakan masukkan kode OTP yang Anda terima:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Batal", callback_data="otp_login_cancel")]
                ]
            )
        )
        await state.set_state(OtpLoginStates.waiting_for_otp)
    else:
        await callback.message.answer(
            f"❌ Gagal mengirim OTP:\n<code>{result.get('error','Tidak diketahui')}</code>",
            parse_mode="HTML",
            reply_markup=get_kirim_otp_keyboard(),
        )
    await callback.answer()


@router.message(OtpLoginStates.waiting_for_otp)
async def process_otp(message: Message, state: FSMContext):
    data = await state.get_data()
    msisdn = data.get("msisdn")
    otp = message.text.strip()
    user = get_user(message.from_user.id)
    role = user["role"] if user else "user"
    if not otp.isdigit() or len(otp) < 4:
        await message.answer("Kode OTP tidak valid. Masukkan kode OTP angka yang Anda terima.")
        return
    await message.answer("⏳ Memverifikasi kode OTP...")

    result = login_xl_with_otp(msisdn, otp)
    if result.get("success"):
        await state.update_data(msisdn=msisdn)
        await message.answer("✅ Login OTP berhasil! Mengambil info pulsa dan kuota...", parse_mode="HTML")
        await show_menu_login_xl(message, state, msisdn, role)
        await state.clear()
        return
    else:
        await message.answer(
            f"❌ Gagal verifikasi OTP:\n<code>{result.get('error','OTP salah atau kadaluarsa')}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Kirim Ulang OTP", callback_data="kirim_otp")],
                    [InlineKeyboardButton(text="⬅️ Batal", callback_data="otp_login_cancel")],
                ]
            ),
        )


@router.callback_query(F.data == "otp_login_cancel")
async def cancel_otp_login(callback: CallbackQuery, state: FSMContext):
    user = get_user(callback.from_user.id)
    role = user["role"] if user else "user"
    await callback.message.edit_text("❌ Login OTP dibatalkan.", parse_mode="HTML", reply_markup=get_back_keyboard(role))
    await state.clear()
    await callback.answer()


@router.message(F.web_app_data)
async def handle_webapp_data(message: Message, state: FSMContext):
    """
    Handle data sent from the WebApp (Telegram.WebApp.sendData).
    The web mini-app will send an action 'msisdn_entered' when the user inputs the phone number.
    Expected payload example:
      { "action": "msisdn_entered", "msisdn": "62812..." }
      or
      { "action": "otp_requested_from_web", "msisdn": "62812..." }  # if web triggers OTP via backend
      or
      { "action": "login_result", "success": true, "msisdn": "62..." }  # if web completed login
    Behavior:
      - msisdn_entered: bot validates the number, checks session, and responds (either proceeds to menu or offers sending OTP)
      - otp_requested_from_web: set state waiting_for_otp and inform user to check web or chat
      - login_result success: same as successful OTP login -> call show_menu_login_xl
    """
    raw = message.web_app_data.data if message.web_app_data else None
    if not raw:
        await message.reply("Data web tidak ditemukan.")
        return

    try:
        payload = json.loads(raw)
    except Exception:
        await message.reply("Tidak dapat memproses data web (format JSON tidak valid).")
        return

    action = payload.get("action")
    msisdn = payload.get("msisdn")
    user = get_user(message.from_user.id)
    role = user["role"] if user else "user"

    if action == "msisdn_entered":
        # Normalize and validate
        if not msisdn:
            await message.reply("Nomor tidak ditemukan di data web.")
            return
        msisdn = msisdn.strip()
        if msisdn.startswith("08"):
            msisdn = "62" + msisdn[1:]
        if not msisdn.isdigit() or len(msisdn) < 10:
            await message.reply("❗️ Nomor yang dimasukkan di web tidak valid.")
            return

        # Store and check session exactly like typed flow
        await state.update_data(msisdn=msisdn)
        await message.reply("⏳ Mengecek sesi nomor...")
        cek = refresh_xl_session(msisdn)
        if cek.get("success"):
            await state.update_data(msisdn=msisdn)
            await message.reply("✅ Nomor sudah terdaftar & sesi aktif. Mengambil info...")
            try:
                await show_menu_login_xl(message, state, msisdn, role)
            except Exception:
                await message.reply("Login berhasil tetapi terjadi error saat mengambil menu. Coba lagi.")
            await state.clear()
            return

        # session not active -> offer to send OTP (web might also trigger sending OTP via backend)
        await message.reply(
            "Sesi belum aktif. Anda bisa meminta OTP melalui web (jika web backend mendukung) atau lewat bot.\n"
            "Pilih tindakan:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🌐 Minta OTP lewat Web (jika tersedia)", callback_data="open_web_for_otp")],
                    [InlineKeyboardButton(text="🔄 Kirim OTP (via bot)", callback_data="kirim_otp")],
                    [InlineKeyboardButton(text="⬅️ Batal", callback_data="otp_login_cancel")],
                ]
            ),
        )
        return

    if action == "otp_requested_from_web":
        # Web/backend already requested OTP and expects user to input code on web or chat
        if not msisdn:
            await message.reply("Nomor tidak tersedia dari web.")
            return
        await state.update_data(msisdn=msisdn)
        await state.set_state(OtpLoginStates.waiting_for_otp)
        await message.reply("✅ OTP telah dikirim melalui web. Jika ingin, Anda juga dapat memasukkan OTP tersebut di sini.")
        return

    if action == "login_result":
        success = bool(payload.get("success"))
        if success:
            await state.update_data(msisdn=msisdn)
            await message.reply("✅ Login sukses melalui web. Mengambil info...")
            try:
                await show_menu_login_xl(message, state, msisdn, role)
            except Exception:
                await message.reply("Login berhasil tetapi terjadi error saat mengambil menu. Coba lagi.")
            await state.clear()
            return
        else:
            err = payload.get("error", "Gagal login via web")
            await message.reply(f"❌ Login via web gagal: {err}")
            return

    # unrecognized action
    await message.reply("Data web diterima, tetapi aksi tidak dikenali.")