from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from models.seting_bot import set_cara_deposit, get_latest_cara_deposit

router = Router()

class CaraDepositStates(StatesGroup):
    waiting_for_content = State()

@router.callback_query(F.data == "set_cara_deposit")
async def set_cara_deposit_menu(callback: CallbackQuery, state: FSMContext):
    current = get_latest_cara_deposit()
    await callback.message.edit_text(
        "<b>💰 Set Cara Deposit</b>\n\n"
        f"Berikut cara deposit saat ini:\n\n"
        f"<code>{current if current else 'Belum diatur.'}</code>\n\n"
        "Kirimkan cara deposit baru (format text, boleh multi-line).\n"
        "Ketik /batal untuk membatalkan.",
        parse_mode="HTML"
    )
    await state.set_state(CaraDepositStates.waiting_for_content)
    await callback.answer()

@router.message(CaraDepositStates.waiting_for_content)
async def save_cara_deposit(message: Message, state: FSMContext):
    if message.text and message.text.strip().lower() == "/batal":
        await message.answer("❌ Proses set cara deposit dibatalkan.")
        await state.clear()
        return
    content = message.text.strip()
    set_cara_deposit(content)
    await message.answer("<b>✅ Cara deposit berhasil diperbarui!</b>", parse_mode="HTML")
    await state.clear()