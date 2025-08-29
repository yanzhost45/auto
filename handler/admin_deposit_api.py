import os
import json
import logging
import io
import asyncio
import re
from html import escape
from typing import Optional

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from api.deposit_api import create_deposit

logger = logging.getLogger(__name__)
router = Router()

# admin keyboard helper (menampilkan menu admin saat "admin_menu" dipencet)
from button.start import get_admin_keyboard


def _setup_path() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "core", "setup.json")


def read_setup() -> dict:
    try:
        p = _setup_path()
        if not os.path.exists(p):
            return {}
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        logger.exception("Failed to read setup.json")
        return {}


class AdminDepositStates(StatesGroup):
    waiting_amount = State()


def _back_to_admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⟵ Kembali ke Admin", callback_data="admin_menu")]
    ])


def _deposit_options_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(text="Rp10.000", callback_data="deposit_amount_10000"),
            InlineKeyboardButton(text="Rp20.000", callback_data="deposit_amount_20000"),
            InlineKeyboardButton(text="Rp50.000", callback_data="deposit_amount_50000"),
        ],
        [
            InlineKeyboardButton(text="Rp100.000", callback_data="deposit_amount_100000"),
            InlineKeyboardButton(text="Lainnya (Masukan jumlah)", callback_data="deposit_custom"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Kembali", callback_data="admin_menu"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


@router.callback_query(F.data == "deposit_api")
async def show_deposit_options(callback: CallbackQuery, state: FSMContext):
    text = "<b>Deposit API</b>\nPilih nominal deposit yang ingin dibuat:"
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_deposit_options_keyboard())
    except Exception:
        try:
            await callback.message.answer(text, parse_mode="HTML", reply_markup=_deposit_options_keyboard())
        except Exception:
            logger.exception("Failed to show deposit options")


@router.callback_query(F.data.regexp(r"^deposit_amount_(\d+)$"))
async def handle_deposit_amount(callback: CallbackQuery, state: FSMContext):
    m = re.match(r"^deposit_amount_(\d+)$", callback.data or "")
    if not m:
        await callback.answer("Nominal tidak valid.", show_alert=True)
        try:
            await callback.message.answer("Nominal tidak valid.", parse_mode="HTML", reply_markup=_back_to_admin_kb())
        except Exception:
            pass
        return
    try:
        amount = int(m.group(1))
    except Exception:
        await callback.answer("Nominal tidak valid.", show_alert=True)
        try:
            await callback.message.answer("Nominal tidak valid.", parse_mode="HTML", reply_markup=_back_to_admin_kb())
        except Exception:
            pass
        return

    # enforce minimal deposit amount
    if amount < 10000:
        try:
            await callback.message.edit_text(f"❗️ Minimal deposit adalah Rp10.000.", parse_mode="HTML", reply_markup=_back_to_admin_kb())
        except Exception:
            try:
                await callback.message.answer(f"❗️ Minimal deposit adalah Rp10.000.", parse_mode="HTML", reply_markup=_back_to_admin_kb())
            except Exception:
                logger.exception("Failed to notify minimal deposit")
        return

    await callback.message.edit_text(f"<b>Membuat deposit Rp{amount:,} ...</b>", parse_mode="HTML")

    try:
        resp = await asyncio.to_thread(create_deposit, amount)
    except Exception as e:
        logger.exception("create_deposit raised exception")
        try:
            await callback.message.edit_text(f"❗️ Gagal membuat deposit (exception): {escape(str(e))}", parse_mode="HTML", reply_markup=_back_to_admin_kb())
        except Exception:
            try:
                await callback.message.answer(f"❗️ Gagal membuat deposit (exception): {escape(str(e))}", parse_mode="HTML", reply_markup=_back_to_admin_kb())
            except Exception:
                logger.exception("Failed to report exception to admin")
        return

    if not resp:
        try:
            await callback.message.edit_text("❗️ Gagal membuat deposit: respons kosong dari fungsi.", parse_mode="HTML", reply_markup=_back_to_admin_kb())
        except Exception:
            try:
                await callback.message.answer("❗️ Gagal membuat deposit: respons kosong dari fungsi.", parse_mode="HTML", reply_markup=_back_to_admin_kb())
            except Exception:
                logger.exception("Failed to report empty response")
        return

    if not resp.get("success"):
        err = resp.get("error") or resp.get("message") or str(resp)
        try:
            await callback.message.edit_text(f"❗️ Deposit gagal: {escape(str(err))}", parse_mode="HTML", reply_markup=_back_to_admin_kb())
        except Exception:
            try:
                await callback.message.answer(f"❗️ Deposit gagal: {escape(str(err))}", parse_mode="HTML", reply_markup=_back_to_admin_kb())
            except Exception:
                logger.exception("Failed to report deposit failure")
        return

    data = resp.get("data") or {}
    trx_id = data.get("transaction_id") or data.get("ref_id") or "-"
    amount_resp = data.get("amount") or amount
    qr_string = data.get("qr_string")
    qr_link = data.get("qr_link") or data.get("payment_url")  # prefer qr_link if provided, fallback to payment_url
    payment_url = data.get("payment_url") or data.get("qr_link")  # payment_url primary for "Bayar" action
    status = data.get("status", "pending")

    caption = (
        f"<b>Deposit dibuat</b>\n"
        f"• ID Transaksi: <code>{escape(str(trx_id))}</code>\n"
        f"• Nominal: <b>Rp{escape(str(amount_resp))}</b>\n"
        f"• Status: <b>{escape(str(status))}</b>\n"
    )

    # Build reply keyboard:
    buttons = []
    first_row = []
    if qr_link:
        first_row.append(InlineKeyboardButton(text="🔍 Lihat QR", url=qr_link))
    if payment_url and payment_url != qr_link:
        first_row.append(InlineKeyboardButton(text="💳 Bayar", url=payment_url))
    if first_row:
        buttons.append(first_row)

    # back button row
    buttons.append([InlineKeyboardButton(text="⟵ Kembali ke Admin", callback_data="admin_menu")])
    reply_kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    body = caption
    if qr_link:
        body += f"\n• Link QR: <a href=\"{escape(qr_link)}\">Buka Gambar QR</a>\n"
    elif qr_string:
        body += f"\n• QR Data: <code>{escape(str(qr_string))}</code>\n"

    if payment_url and payment_url != qr_link:
        body += f"\n• Link Pembayaran: <a href=\"{escape(payment_url)}\">Klik untuk bayar</a>\n"

    try:
        await callback.message.answer(body, parse_mode="HTML", disable_web_page_preview=False, reply_markup=reply_kb)
    except Exception:
        logger.exception("Failed to send deposit result message")
        # fallback: try without web preview but still include back button
        try:
            await callback.message.answer(body, parse_mode="HTML", disable_web_page_preview=True, reply_markup=reply_kb)
        except Exception:
            logger.exception("Fallback send also failed")
            # final fallback: send minimal error with back button
            try:
                await callback.message.answer("❗️ Gagal mengirim hasil deposit. Silakan coba lagi.", parse_mode="HTML", reply_markup=_back_to_admin_kb())
            except Exception:
                pass


@router.callback_query(F.data == "deposit_custom")
async def deposit_custom_prompt(callback: CallbackQuery, state: FSMContext):
    try:
        await callback.message.edit_text(
            "<b>Deposit Custom</b>\nSilakan ketik jumlah (mis. 25000 untuk Rp25.000).",
            parse_mode="HTML"
        )
    except Exception:
        try:
            await callback.message.answer(
                "<b>Deposit Custom</b>\nSilakan ketik jumlah (mis. 25000 untuk Rp25.000).",
                parse_mode="HTML"
            )
        except Exception:
            logger.exception("Failed to prompt custom deposit")
    await state.set_state(AdminDepositStates.waiting_amount)


@router.message(AdminDepositStates.waiting_amount)
async def process_custom_amount(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        try:
            await message.answer("Nominal tidak valid. Masukan hanya angka, mis. 25000", reply_markup=_back_to_admin_kb())
        except Exception:
            pass
        return
    try:
        amount = int(digits)
    except Exception:
        try:
            await message.answer("Nominal tidak valid.", reply_markup=_back_to_admin_kb())
        except Exception:
            pass
        return

    # enforce minimal deposit amount
    if amount < 10000:
        try:
            await message.answer("❗️ Minimal deposit adalah Rp10.000.", reply_markup=_back_to_admin_kb())
        except Exception:
            pass
        return

    await message.answer(f"<b>Membuat deposit Rp{amount:,} ...</b>", parse_mode="HTML")
    await state.clear()

    try:
        resp = await asyncio.to_thread(create_deposit, amount)
    except Exception as e:
        logger.exception("create_deposit raised exception (custom amount)")
        try:
            await message.answer(f"❗️ Gagal membuat deposit (exception): {escape(str(e))}", reply_markup=_back_to_admin_kb())
        except Exception:
            pass
        return

    if not resp:
        try:
            await message.answer("❗️ Gagal membuat deposit: respons kosong dari fungsi.", reply_markup=_back_to_admin_kb())
        except Exception:
            pass
        return

    if not resp.get("success"):
        err = resp.get("error") or resp.get("message") or str(resp)
        try:
            await message.answer(f"❗️ Deposit gagal: {escape(str(err))}", parse_mode="HTML", reply_markup=_back_to_admin_kb())
        except Exception:
            pass
        return

    data = resp.get("data") or {}
    trx_id = data.get("transaction_id") or data.get("ref_id") or "-"
    amount_resp = data.get("amount") or amount
    qr_string = data.get("qr_string")
    qr_link = data.get("qr_link") or data.get("payment_url")
    payment_url = data.get("payment_url") or data.get("qr_link")
    status = data.get("status", "pending")

    caption = (
        f"<b>Deposit dibuat</b>\n"
        f"• ID Transaksi: <code>{escape(str(trx_id))}</code>\n"
        f"• Nominal: <b>Rp{escape(str(amount_resp))}</b>\n"
        f"• Status: <b>{escape(str(status))}</b>\n"
    )

    buttons = []
    first_row = []
    if qr_link:
        first_row.append(InlineKeyboardButton(text="🔍 Lihat QR", url=qr_link))
    if payment_url and payment_url != qr_link:
        first_row.append(InlineKeyboardButton(text="💳 Bayar", url=payment_url))
    if first_row:
        buttons.append(first_row)
    buttons.append([InlineKeyboardButton(text="⟵ Kembali ke Admin", callback_data="admin_menu")])
    reply_kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    body = caption
    if qr_link:
        body += f"\n• Link QR: <a href=\"{escape(qr_link)}\">Buka Gambar QR</a>\n"
    elif qr_string:
        body += f"\n• QR Data: <code>{escape(str(qr_string))}</code>\n"
    if payment_url and payment_url != qr_link:
        body += f"\n• Link Pembayaran: <a href=\"{escape(payment_url)}\">Klik untuk bayar</a>\n"

    try:
        await message.answer(body, parse_mode="HTML", disable_web_page_preview=False, reply_markup=reply_kb)
    except Exception:
        logger.exception("Failed to send deposit (custom) result message")
        try:
            await message.answer(body, parse_mode="HTML", disable_web_page_preview=True, reply_markup=reply_kb)
        except Exception:
            logger.exception("Fallback send also failed")
            try:
                await message.answer("❗️ Gagal mengirim hasil deposit. Silakan coba lagi.", reply_markup=_back_to_admin_kb())
            except Exception:
                pass


@router.callback_query(F.data == "admin_menu")
async def show_admin_menu(callback: CallbackQuery, state: FSMContext):
    try:
        await callback.message.edit_text("<b>Menu Admin</b>", parse_mode="HTML", reply_markup=get_admin_keyboard())
    except Exception:
        try:
            await callback.message.answer("<b>Menu Admin</b>", parse_mode="HTML", reply_markup=get_admin_keyboard())
        except Exception:
            logger.exception("Failed to show admin menu")