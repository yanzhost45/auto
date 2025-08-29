from html import escape
import os
import json
import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from models.seting_bot import get_latest_cara_pembelian, get_latest_cara_deposit
from button.start import get_admin_keyboard, get_user_keyboard

logger = logging.getLogger(__name__)
router = Router()


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


def _is_admin(user_id: int) -> bool:
    try:
        s = read_setup()
        admin = s.get("admin") or {}
        admin_userid = admin.get("userid")
        if admin_userid is None:
            return False
        try:
            return int(admin_userid) == int(user_id)
        except Exception:
            return False
    except Exception:
        return False


def _get_back_keyboard_for_user(user_id: int):
    return get_admin_keyboard() if _is_admin(user_id) else get_user_keyboard()


@router.callback_query(F.data == "cara_pembelian")
async def show_cara_pembelian(callback: CallbackQuery, state: FSMContext):
    content = get_latest_cara_pembelian() or "Belum ada panduan cara pembelian yang diset. Silakan hubungi admin untuk menambahkan konten."
    body = f"<b>Cara Pembelian</b>\n\n{escape(content)}"
    back_kb = _get_back_keyboard_for_user(callback.from_user.id)
    try:
        await callback.message.edit_text(body, parse_mode="HTML", reply_markup=back_kb)
    except Exception:
        try:
            await callback.message.answer(body, parse_mode="HTML", reply_markup=back_kb)
        except Exception:
            logger.exception("Failed to send cara_pembelian content")


@router.callback_query(F.data == "cara_deposit")
async def show_cara_deposit(callback: CallbackQuery, state: FSMContext):
    content = get_latest_cara_deposit() or "Belum ada panduan cara deposit yang diset. Silakan hubungi admin untuk menambahkan konten."
    body = f"<b>Cara Deposit</b>\n\n{escape(content)}"
    back_kb = _get_back_keyboard_for_user(callback.from_user.id)
    try:
        await callback.message.edit_text(body, parse_mode="HTML", reply_markup=back_kb)
    except Exception:
        try:
            await callback.message.answer(body, parse_mode="HTML", reply_markup=back_kb)
        except Exception:
            logger.exception("Failed to send cara_deposit content")