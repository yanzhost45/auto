from __future__ import annotations
import os
import io
import json
import random
import logging
import tempfile
import re
from typing import Optional, List, Tuple, Dict, Any, Union
from datetime import datetime
from zoneinfo import ZoneInfo
from base64 import b64decode

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

import qrcode
from PIL import Image  # ensure Pillow installed

import aiohttp

from data.database import get_user

logger = logging.getLogger(__name__)
router = Router()

# Try import helper functions (image_to_string + make_qris_dynamic)
# helper.image_to_string provides image_to_string(...) and make_qris_dynamic(...)
try:
    from helper.image_to_string import image_to_string, make_qris_dynamic  # type: ignore
except Exception:
    # We'll still work: image_to_string is imported dynamically in ensure_qris_string
    make_qris_dynamic = None  # type: ignore

# Paths
PROJECT_ROOT = os.path.abspath(os.getcwd())
CORE_DIR = os.path.join(PROJECT_ROOT, "core")
SETUP_PATH = os.path.join(CORE_DIR, "setup.json")
QRIS_IMAGE_PATH = os.path.join(CORE_DIR, "qris.png")

# in-memory pending deposits: user_id -> {amount, trx_id, timestamp, admin_notification: {chat, message_id}}
PENDING_DEPOSITS: dict[int, dict] = {}

class DepositStates(StatesGroup):
    waiting_for_amount = State()
    waiting_for_proof = State()


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


# --- setup.json helpers ---------------------------------------------------
def _load_setup() -> dict:
    try:
        if not os.path.exists(SETUP_PATH):
            return {}
        with open(SETUP_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        logger.exception("Failed to read setup.json")
        return {}


def _save_setup(data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(SETUP_PATH), exist_ok=True)
        with open(SETUP_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        logger.exception("Failed to write setup.json")


def ensure_qris_string() -> Optional[str]:
    s = _load_setup()
    q = s.get("qris_string")
    if q:
        return q

    if not os.path.exists(QRIS_IMAGE_PATH):
        return None

    try:
        import sys
        if PROJECT_ROOT not in sys.path:
            sys.path.insert(0, PROJECT_ROOT)
        from helper.image_to_string import image_to_string  # type: ignore

        decoded = image_to_string(QRIS_IMAGE_PATH)
        if decoded:
            s["qris_string"] = decoded
            s["qris_path"] = os.path.relpath(QRIS_IMAGE_PATH, PROJECT_ROOT).replace("\\", "/")
            _save_setup(s)
            return decoded
    except Exception:
        logger.exception("Failed to import/run helper.image_to_string")
    return None


# --- TLV helpers (EMV-like top-level TLV parser) ---------------------------
def parse_tlv(payload: str) -> Optional[List[Tuple[str, str]]]:
    i = 0
    L = len(payload)
    out: List[Tuple[str, str]] = []
    try:
        while i < L:
            if i + 4 > L:
                return None
            tag = payload[i : i + 2]; i += 2
            length = int(payload[i : i + 2]); i += 2
            if i + length > L:
                return None
            value = payload[i : i + length]; i += length
            out.append((tag, value))
        return out
    except Exception:
        return None


def build_tlv(entries: List[Tuple[str, str]]) -> str:
    parts: List[str] = []
    for tag, val in entries:
        parts.append(f"{tag}{len(val):02d}{val}")
    return "".join(parts)


def inject_or_replace_amount(payload: str, amount_str: str) -> str:
    """
    Legacy TLV-aware injection (keeps structure when parsing is possible).
    Kept as fallback if make_qris_dynamic isn't available.
    """
    entries = parse_tlv(payload)
    if entries is None:
        return payload + f"54{len(amount_str):02d}{amount_str}"

    found = False
    new_entries: List[Tuple[str, str]] = []
    for tag, val in entries:
        if tag == "54":
            new_entries.append(("54", amount_str))
            found = True
        else:
            new_entries.append((tag, val))

    if not found:
        inserted = False
        out: List[Tuple[str, str]] = []
        for tag, val in new_entries:
            out.append((tag, val))
            if tag == "53" and not inserted:
                out.append(("54", amount_str))
                inserted = True
        if not inserted:
            out = []
            for tag, val in new_entries:
                if tag == "58" and not inserted:
                    out.append(("54", amount_str))
                    inserted = True
                out.append((tag, val))
        if not inserted:
            out.append(("54", amount_str))
        new_entries = out

    return build_tlv(new_entries)


# --- QR generation --------------------------------------------------------
def generate_qr_image_bytes(payload: str) -> bytes:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=4)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return bio.getvalue()


# --- admin notify helpers -------------------------------------------------
async def notify_admin_with_qr(setup: dict, user_id: int, user_info: dict, produk_nama: str,
                               harga: int, msisdn: str, trx_id: str, payment_method: str,
                               saldo_akhir, qr_string: str, img_bytes: bytes) -> Optional[Dict[str, Any]]:
    """
    Send notification (text + photo) to admin via the notification bot (setup['notifikasi']).
    img_bytes must be raw PNG/JPEG bytes. Function saves to tmp file and uploads.
    """
    notif_token = setup.get("notifikasi")
    if not notif_token:
        logger.debug("No notification token configured, skipping admin notification.")
        return None

    admin = setup.get("admin") or {}
    admin_target = None
    if admin.get("userid"):
        admin_target = str(admin["userid"])
    elif admin.get("username"):
        admin_target = f"@{str(admin['username']).lstrip('@')}"

    if not admin_target:
        logger.debug("No admin target configured, skipping admin notification.")
        return None

    try:
        now_jkt = datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        now_jkt = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    username = user_info.get("username") if user_info else "-"
    saldo_display = saldo_akhir if saldo_akhir is not None else (user_info.get("saldo") if user_info else "-")

    caption = (
        f"🔔 <b>Permintaan Deposit Baru</b>\n"
        f"• Userid: <code>{user_id}</code>\n"
        f"• Username: @{username}\n"
        f"• Jumlah deposit: <b>Rp{harga}</b>\n"
        f"• Saldo saat ini: <b>Rp{saldo_display}</b>\n"
        f"• Waktu: <code>{now_jkt}</code>\n"
        f"• ID Transaksi: <code>{trx_id}</code>\n"
    )

    # Add a "Buka Chat User" button (prefers username link, falls back to tg://user?id=)
    if username and username != "-":
        user_chat_url = f"https://t.me/{str(username).lstrip('@')}"
    else:
        user_chat_url = f"tg://user?id={user_id}"

    reply_markup = {"inline_keyboard": [[{"text": "Buka Chat User", "url": user_chat_url}]]}

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(img_bytes)
            tmp_path = tmp.name

        url = f"https://api.telegram.org/bot{notif_token}/sendPhoto"
        async with aiohttp.ClientSession() as session:
            with open(tmp_path, "rb") as fh:
                form = aiohttp.FormData()
                form.add_field("chat_id", admin_target)
                form.add_field("caption", caption)
                form.add_field("parse_mode", "HTML")
                form.add_field("reply_markup", json.dumps(reply_markup))
                form.add_field("photo", fh, filename="qris.png", content_type="image/png")
                try:
                    async with session.post(url, data=form, timeout=30) as resp:
                        text = await resp.text()
                        try:
                            j = await resp.json()
                        except Exception:
                            j = None
                        if resp.status != 200:
                            logger.error("Admin notify failed: %s %s", resp.status, text)
                            return None
                        message_id = None
                        if isinstance(j, dict):
                            message_id = j.get("result", {}).get("message_id")
                        logger.debug("Admin notify OK: %s", text)
                        return {"admin_target": admin_target, "message_id": message_id}
                except Exception:
                    logger.exception("Exception while notifying admin")
                    return None
    finally:
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            logger.exception("Failed to remove temporary file after notify_admin_with_qr")


async def notify_admin_with_proof(setup: dict, admin_target: str, user_id: int, username: str, amount: int, img_bytes: bytes, reply_to_message_id: Optional[int] = None):
    """
    Send proof image (photo) to admin with the exact requested format in the caption:
      UserId telegram:
      Username telegram:
      Jumlah deposit:
    Use notification bot token (setup['notifikasi']).
    If reply_to_message_id is provided, include reply_to_message_id so the photo appears as a reply.
    """
    notif_token = setup.get("notifikasi")
    if not notif_token:
        logger.debug("No notification token configured, skipping admin proof notification.")
        return

    try:
        now_jkt = datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        now_jkt = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    caption = (
        "UserId telegram:"
        f"{user_id}\n"
        "Username telegram:"
        f"@{username}\n"
        "Jumlah deposit:"
        f"Rp{amount}\n"
        f"\nWaktu: {now_jkt}\n"
    )

    # prepare chat link/button
    if username and username != "-":
        user_chat_url = f"https://t.me/{str(username).lstrip('@')}"
    else:
        user_chat_url = f"tg://user?id={user_id}"

    reply_markup = {"inline_keyboard": [[{"text": "Buka Chat User", "url": user_chat_url}]]}

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(img_bytes)
            tmp_path = tmp.name

        url = f"https://api.telegram.org/bot{notif_token}/sendPhoto"
        async with aiohttp.ClientSession() as session:
            with open(tmp_path, "rb") as fh:
                form = aiohttp.FormData()
                form.add_field("chat_id", admin_target)
                if reply_to_message_id:
                    form.add_field("reply_to_message_id", str(reply_to_message_id))
                form.add_field("caption", caption)
                form.add_field("parse_mode", "HTML")
                form.add_field("reply_markup", json.dumps(reply_markup))
                form.add_field("photo", fh, filename="bukti.png", content_type="image/png")
                try:
                    async with session.post(url, data=form, timeout=30) as resp:
                        text = await resp.text()
                        if resp.status != 200:
                            logger.error("Admin proof notify failed: %s %s", resp.status, text)
                        else:
                            logger.debug("Admin proof notify OK: %s", text)
                except Exception:
                    logger.exception("Exception while notifying admin with proof")
    finally:
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            logger.exception("Failed to remove temporary file after notify_admin_with_proof")


# --- Handlers --------------------------------------------------------------
@router.callback_query(F.data == "deposit")
async def deposit_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = get_user(callback.from_user.id)
    role = user["role"] if user else "user"

    text = (
        "💵 <b>DEPOSIT</b>\n\n"
        "Silakan masukkan jumlah deposit (hanya angka, tanpa tanda pemisah).\nContoh: 10000"
    )
    try:
        if getattr(callback.message, "text", None):
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_back_keyboard(role))
        else:
            await callback.message.answer(text, parse_mode="HTML", reply_markup=get_back_keyboard(role))
    except Exception:
        try:
            await callback.message.answer(text, parse_mode="HTML", reply_markup=get_back_keyboard(role))
        except Exception:
            logger.exception("Failed to show deposit start message")
    await state.set_state(DepositStates.waiting_for_amount)
    try:
        await callback.answer()
    except Exception:
        pass


# Only match text messages when waiting for amount so photos (proof) are NOT treated as amount input
@router.message(DepositStates.waiting_for_amount, F.text)
async def deposit_amount(message: Message, state: FSMContext):
    txt = (message.text or "").strip()
    digits = "".join(ch for ch in txt if ch.isdigit())
    if not digits:
        await message.reply("❗️ Input tidak valid. Masukkan hanya angka, contoh: 10000")
        return

    try:
        base_amount = int(digits)
    except Exception:
        await message.reply("❗️ Jumlah tidak dapat diproses.")
        return

    unique_code = random.randint(1, 100)
    final_amount = base_amount + unique_code
    amount_str = str(final_amount)

    qris = ensure_qris_string()
    if not qris:
        await message.reply("⚠️ QRIS string tidak ditemukan. Pastikan core/qris.png ada atau setup.json berisi qris_string.")
        await state.clear()
        return

    # Use PHP-like converter (make_qris_dynamic) if available so output payload + CRC
    try:
        if make_qris_dynamic:
            # No service fee by default; mirrors PHP example behavior when fee not provided
            new_payload = make_qris_dynamic(qris, amount_str, fee_value=None, fee_is_percent=False)
        else:
            new_payload = inject_or_replace_amount(qris, amount_str)
    except Exception:
        # fallback to older method
        try:
            new_payload = inject_or_replace_amount(qris, amount_str)
        except Exception:
            new_payload = qris + f"54{len(amount_str):02d}{amount_str}"

    # Call external API / or internal generator to get qris data.
    # If your flow already produces a base64 image from API, prefer that (qris_image).
    # For backward compatibility: if no base64 image, generate from payload.
    img_bytes: Optional[bytes] = None
    qris_image_data = None
    # If your system provides a QR image (base64 data uri) in setup.json or via helper, try to use it:
    try:
        # Example: check setup.json for qris_image (data URI) - optional
        s = _load_setup()
        qris_image_data = s.get("qris_image")  # optional field if you stored data URI
    except Exception:
        qris_image_data = None

    # If there is a dataURI available in setup, use it; otherwise generate an image from payload
    if isinstance(qris_image_data, str) and qris_image_data.startswith("data:") and "base64," in qris_image_data:
        try:
            base64_data = qris_image_data.split(",", 1)[1]
            img_bytes = b64decode(base64_data)
        except Exception:
            logger.exception("Failed to decode base64 qris_image from setup, will generate QR image")
            img_bytes = None

    if not img_bytes:
        try:
            # generate QR image from the new_payload (which includes CRC now if make_qris_dynamic used)
            img_bytes = generate_qr_image_bytes(new_payload)
        except Exception:
            logger.exception("Failed generating QR image")
            await message.reply("Gagal membuat gambar QR. Coba lagi nanti.")
            await state.clear()
            return

    # build inline keyboard: Chat Admin | Back (for the TEXT message)
    setup = _load_setup()
    admin = setup.get("admin") or {}
    if admin.get("username"):
        chat_admin_button = InlineKeyboardButton(text="💬 Chat Admin", url=f"https://t.me/{str(admin['username']).lstrip('@')}")
    elif admin.get("userid"):
        chat_admin_button = InlineKeyboardButton(text="💬 Chat Admin", callback_data=f"contact_admin:{admin.get('userid')}")
    else:
        chat_admin_button = InlineKeyboardButton(text="💬 Chat Admin", callback_data="contact_admin")

    trx_id = f"deposit_{message.from_user.id}_{random.randint(1000,9999)}"
    PENDING_DEPOSITS[message.from_user.id] = {"amount": final_amount, "trx_id": trx_id, "timestamp": datetime.now().isoformat()}

    role = (get_user(message.from_user.id) or {}).get("role", "user")
    back_button = InlineKeyboardButton(
        text=("⬅️ Kembali ke Menu Admin" if role=="admin" else "⬅️ Kembali ke Menu Utama"),
        callback_data=("back_to_admin_menu" if role=="admin" else "back_to_user_menu")
    )

    # Text message markup (contains back so user can go back)
    text_kb = InlineKeyboardMarkup(inline_keyboard=[
        [chat_admin_button],
        [back_button]
    ])

    caption = (
        f"Nominal: {base_amount}\n"
        f"Kode unik: {unique_code}\n"
        f"Total yang harus dibayar: {final_amount}\n\n"
        "Silakan bayar sesuai nominal pada QR di bawah. Setelah membayar, cukup kirimkan foto bukti — bot akan otomatis meneruskannya ke admin."
    )

    # 1) Send PHOTO message first (separate message) WITHOUT any inline buttons.
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(img_bytes)
            tmp_path = tmp.name

        try:
            # Use FSInputFile to pass a filesystem path (aiogram-friendly)
            await message.bot.send_photo(chat_id=message.chat.id, photo=FSInputFile(tmp_path), caption="QRIS (scan untuk membayar)", parse_mode="HTML")
        except Exception:
            # fallback: HTTP multipart upload (ensures work across environments)
            logger.exception("send_photo via aiogram failed, falling back to HTTP multipart upload")
            bot_token = getattr(message.bot, "token", None)
            if bot_token:
                async with aiohttp.ClientSession() as session:
                    with open(tmp_path, "rb") as fh:
                        form = aiohttp.FormData()
                        form.add_field("chat_id", str(message.chat.id))
                        form.add_field("caption", "QRIS (scan untuk membayar)")
                        form.add_field("parse_mode", "HTML")
                        form.add_field("photo", fh, filename="qris.png", content_type="image/png")
                        try:
                            async with session.post(f"https://api.telegram.org/bot{bot_token}/sendPhoto", data=form, timeout=30) as resp:
                                text = await resp.text()
                                if resp.status != 200:
                                    logger.error("Fallback upload QR to user failed: %s %s", resp.status, text)
                        except Exception:
                            logger.exception("Exception while fallback uploading QR to Telegram for user")
    finally:
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            logger.exception("Failed to remove temporary QR file after user send")

    # 2) Then send the TEXT message with details + back & chat admin buttons (so 'Kembali' works reliably)
    try:
        await message.reply(caption, parse_mode="HTML", reply_markup=text_kb)
    except Exception:
        logger.exception("Failed to send deposit text (will try fallback send_message)")
        try:
            await message.bot.send_message(chat_id=message.chat.id, text=caption, parse_mode="HTML", reply_markup=text_kb)
        except Exception:
            logger.exception("Fallback failed to send deposit text")

    # notify admin about new deposit request (non-blocking) and store admin notif ids
    try:
        user_info = get_user(message.from_user.id) or {"username": message.from_user.username or "-", "saldo": 0}
        notif_result = await notify_admin_with_qr(
            setup=_load_setup(),
            user_id=message.from_user.id,
            user_info=user_info,
            produk_nama="Deposit Saldo",
            harga=final_amount,
            msisdn="-",
            trx_id=trx_id,
            payment_method="QRIS",
            saldo_akhir=user_info.get("saldo", 0),
            qr_string=new_payload,
            img_bytes=img_bytes
        )
        if notif_result:
            PENDING_DEPOSITS[message.from_user.id]["admin_notification"] = {
                "admin_target": notif_result.get("admin_target"),
                "message_id": notif_result.get("message_id")
            }
    except Exception:
        logger.exception("Failed to notify admin about deposit request")

    await state.clear()


@router.message(F.photo)
async def auto_receive_proof_photo(message: Message, state: FSMContext):
    """
    Universal photo handler:
    - If the sender has a pending deposit (PENDING_DEPOSITS) -> treat this photo as proof
      and automatically forward original message to admin and send formatted notification + image
      to admin notification bot as a reply to the original admin notif (if available).
    """
    user_id = message.from_user.id
    pending = PENDING_DEPOSITS.get(user_id)
    if not pending:
        # not a proof for deposit; ignore in this handler
        return

    trx_id = pending.get("trx_id")
    amount = pending.get("amount")
    user_db = get_user(user_id) or {}
    username = user_db.get("username") or (message.from_user.username or "-")

    # Determine admin_target & notif token setup
    setup = _load_setup()
    admin = setup.get("admin") or {}
    admin_target_for_forward = None  # for forward_message (main bot)
    if admin.get("userid"):
        try:
            admin_target_for_forward = int(admin["userid"])
        except Exception:
            admin_target_for_forward = str(admin["userid"])
    elif admin.get("username"):
        admin_target_for_forward = f"@{str(admin['username']).lstrip('@')}"

    # If admin not configured -> inform user and stop
    if not admin_target_for_forward:
        await message.reply("❗️ Admin belum dikonfigurasi. Silakan hubungi support.")
        await state.clear()
        return

    # Forward original message to admin so admin can read user's chat directly (best effort)
    try:
        await message.bot.forward_message(chat_id=admin_target_for_forward, from_chat_id=message.chat.id, message_id=message.message_id)
    except Exception:
        logger.exception("Failed to forward original message to admin (non-fatal)")

    # Download photo bytes via Telegram file API
    file_id = message.photo[-1].file_id
    bot_token = getattr(message.bot, "token", None)
    if not bot_token:
        await message.reply("❗️ Gagal mengambil file (token bot tidak tersedia).")
        await state.clear()
        return

    img_bytes = None
    try:
        file_obj = await message.bot.get_file(file_id)
        file_path = file_obj.file_path
        file_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
        async with aiohttp.ClientSession() as session:
            async with session.get(file_url) as resp:
                if resp.status != 200:
                    await message.reply("❗️ Gagal mengunduh file dari Telegram.")
                    await state.clear()
                    return
                img_bytes = await resp.read()
    except Exception:
        logger.exception("Failed to download photo from Telegram")
        await message.reply("❗️ Gagal mengunduh gambar bukti. Coba lagi.")
        await state.clear()
        return

    # Prepare admin_target for notification bot (prefer userid int or @username)
    admin_notify_target = None
    if admin.get("userid"):
        admin_notify_target = str(admin["userid"])
    elif admin.get("username"):
        admin_notify_target = f"@{str(admin['username']).lstrip('@')}"

    if not admin_notify_target:
        await message.reply("❗️ Admin belum dikonfigurasi untuk notifikasi.")
        await state.clear()
        return

    # Determine reply_to_message_id from stored admin notification (if any)
    reply_to_message_id = None
    admin_notif = pending.get("admin_notification") or {}
    if admin_notif:
        reply_to_message_id = admin_notif.get("message_id")

    # Send formatted proof to admin via notification bot (async), as a reply if possible
    try:
        await notify_admin_with_proof(setup=setup, admin_target=admin_notify_target, user_id=user_id, username=username, amount=amount, img_bytes=img_bytes, reply_to_message_id=reply_to_message_id)
        await message.reply("Bukti pembayaran telah dikirimkan ke admin. Silakan tunggu konfirmasi dari admin.")
    except Exception:
        logger.exception("Failed to send proof to admin (notif bot)")
        await message.reply("❗️ Gagal mengirim bukti ke admin. Coba lagi nanti.")

    # Clear pending deposit (one-time)
    try:
        del PENDING_DEPOSITS[user_id]
    except Exception:
        pass

    # Clear any FSM state
    await state.clear()


@router.callback_query(F.data.regexp(r"^contact_admin(?::(.+))?$"))
async def contact_admin_callback(callback: CallbackQuery, state: FSMContext):
    match = re.match(r"^contact_admin(?::(.+))?$", callback.data)
    admin_id = match.group(1) if match and match.group(1) else None
    if admin_id:
        try:
            await callback.answer(f"Hubungi admin: userid {admin_id}", show_alert=True)
        except Exception:
            pass
    else:
        try:
            await callback.answer("Admin belum dikonfigurasi.", show_alert=True)
        except Exception:
            pass


# Export router
deposit_router = router