from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from api.sidompul import cek_kuota_sidompul
from data.database import get_user

router = Router()

class SidompulStates(StatesGroup):
    waiting_for_msisdn = State()

def get_back_keyboard(role="user"):
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

@router.callback_query(F.data == "sidompul_cek_kuota")
async def ask_msisdn_handler(callback: CallbackQuery, state: FSMContext):
    user = get_user(callback.from_user.id)
    role = user["role"] if user else "user"
    await callback.message.edit_text(
        "📱 <b>SIDOMPUL - CEK KUOTA XL</b>\n\n"
        "Silakan masukkan nomor XL yang akan dicek (format: 08xxxx atau 628xxxx):",
        parse_mode="HTML",
        reply_markup=get_back_keyboard(role)
    )
    await state.set_state(SidompulStates.waiting_for_msisdn)
    await callback.answer()

@router.message(SidompulStates.waiting_for_msisdn)
async def process_msisdn(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)
    role = user["role"] if user else "user"
    msisdn = message.text.strip()
    if msisdn.startswith("08"):
        msisdn = "62" + msisdn[1:]
    if not msisdn.isdigit() or len(msisdn) < 10:
        await message.answer("❗️ Format nomor tidak valid. Masukkan nomor XL yang benar (08xxxx atau 628xxxx).")
        return

    await message.answer("⏳ <b>Sedang memproses cek kuota...</b>", parse_mode="HTML")

    result = cek_kuota_sidompul(msisdn)
    if not result.get("success"):
        await message.answer(
            f"❌ Gagal cek kuota:\n<code>{result.get('error','Tidak diketahui')}</code>",
            parse_mode="HTML",
            reply_markup=get_back_keyboard(role)
        )
        await state.clear()
        return

    data = result.get("result", {})
    reply = (
        "🎉 <b>HASIL CEK KUOTA XL</b> 🎉\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📱 <b>Nomor:</b> <code>{data.get('msisdn','-')}</code>\n"
        f"👤 <b>Nama:</b> <code>{data.get('owner','-')}</code>\n"
        f"📶 <b>Status:</b> <code>{data.get('status','-')}</code>\n"
        f"🏷️ <b>Kategori:</b> <code>{data.get('category','-')}</code>\n"
        f"⏳ <b>Tenure:</b> <code>{data.get('tenure','-')}</code>\n"
        f"🗓️ <b>SP Exp:</b> <code>{data.get('SPExpDate','-')}</code>\n"
        f"🗓️ <b>Exp Date:</b> <code>{data.get('expDate','-')}</code>\n"
        f"🆔 <b>Dukcapil:</b> <code>{data.get('dukcapil','-')}</code>\n"
    )

    d = data.get("data", {})
    if d:
        reply += f"\n🕒 <b>Last Update:</b> <code>{d.get('lastUpdate','-')}</code>\n"
        # Paket Info
        package_info = d.get("packageInfo", [])
        if package_info:
            reply += "\n<b>🎁 Daftar Paket Aktif:</b>\n"
            for idx, package_group in enumerate(package_info, 1):
                for package in package_group:
                    pkg = package.get("packages", {})
                    benefits = package.get("benefits", [])
                    reply += (
                        f"\n<b>📦 {pkg.get('name','-')}</b>\n"
                        f"⏰ Exp: <code>{pkg.get('expDate','-')}</code>\n"
                    )
                    for b in benefits:
                        emoji = "🌐" if b.get("type","") == "DATA" else "⭐️"
                        reply += f"{emoji} {b.get('bname','')}: <b>{b.get('remaining','-')}</b> / {b.get('quota','-')}\n"
                    reply += "────────────────────"  # Garis putus-putus antar paket
        # Paket Info SP
        package_info_sp = d.get("packageInfoSP", [])
        if package_info_sp:
            reply += "\n<b>🎗️ Paket SP:</b>\n"
            for package_group in package_info_sp:
                for package in package_group:
                    benefits = package.get("benefits", [])
                    for b in benefits:
                        emoji = "💸" if b.get("type","") == "ACCUMCHARGE" else "⭐️"
                        reply += f"{emoji} {b.get('bname','')}: <b>{b.get('remaining','-')}</b> / {b.get('quota','-')}\n"
            reply += "────────────────────\n"

    await message.answer(reply, parse_mode="HTML", reply_markup=get_back_keyboard(role))
    await state.clear()

@router.callback_query(F.data == "back_to_admin_menu")
async def back_to_admin_menu(callback: CallbackQuery, state: FSMContext):
    from button.start import get_admin_keyboard
    await callback.message.edit_text(
        "<b>Selamat datang di Menu Admin!</b>\n"
        "Silakan pilih menu yang tersedia di bawah ini:",
        parse_mode="HTML",
        reply_markup=get_admin_keyboard()
    )
    await state.clear()
    await callback.answer()

@router.callback_query(F.data == "back_to_user_menu")
async def back_to_user_menu(callback: CallbackQuery, state: FSMContext):
    from button.start import get_user_keyboard
    await callback.message.edit_text(
        "<b>Selamat datang di Menu Utama!</b>\n"
        "Silakan pilih menu yang tersedia di bawah ini:",
        parse_mode="HTML",
        reply_markup=get_user_keyboard()
    )
    await state.clear()
    await callback.answer()