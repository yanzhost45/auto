from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from models.seting_bot import set_cara_pembelian, get_latest_cara_pembelian

router = Router()

class CaraPembelianStates(StatesGroup):
    waiting_for_content = State()

@router.callback_query(F.data == "set_cara_pembelian")
async def set_cara_pembelian_menu(callback: CallbackQuery, state: FSMContext):
    current = get_latest_cara_pembelian()
    await callback.message.edit_text(
        "<b>🛒 Set Cara Pembelian</b>\n\n"
        f"Berikut cara pembelian saat ini:\n\n"
        f"<code>{current if current else 'Belum diatur.'}</code>\n\n"
        "Kirimkan cara pembelian baru (format text, boleh multi-line).\n"
        "Ketik /batal untuk membatalkan.",
        parse_mode="HTML"
    )
    await state.set_state(CaraPembelianStates.waiting_for_content)
    await callback.answer()

@router.message(CaraPembelianStates.waiting_for_content)
async def save_cara_pembelian(message: Message, state: FSMContext):
    if message.text and message.text.strip().lower() == "/batal":
        await message.answer("❌ Proses set cara pembelian dibatalkan.")
        await state.clear()
        return
    content = message.text.strip()
    set_cara_pembelian(content)
    await message.answer("<b>✅ Cara pembelian berhasil diperbarui!</b>", parse_mode="HTML")
    await state.clear()