from __future__ import annotations
import os
import re
import logging
from html import escape
from datetime import datetime
from typing import Optional, Any
from urllib.parse import quote_plus

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from data.database import get_produk_detail, get_user, update_user_saldo
from models.transaksi_terjadwal import create_transaksi
from models.riwayat_transaksi import insert_riwayat
from sessions import sessions  # keep using sessions only to store msisdn if needed

router = Router()
logger = logging.getLogger(__name__)

PAYMENT_METHODS = [
    ("BALANCE", "Pulsa"),
    ("DANA", "DANA"),
    ("GOPAY", "GoPay"),
    ("SHOPEEPAY", "ShopeePay"),
    ("QRIS", "QRIS"),
]


class JadwalStates(StatesGroup):
    waiting_msisdn = State()
    waiting_method = State()
    waiting_time = State()
    confirming = State()


def _build_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Kembali", callback_data="back_to_user_menu")]
    ])


def _final_save_keyboard(product_id: str) -> InlineKeyboardMarkup:
    """
    Final save keyboard used in the summary step.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Simpan Jadwal", callback_data=f"jadwal_save_{product_id}")],
        [InlineKeyboardButton(text="⬅️ Batal", callback_data=f"jadwal_product_{product_id}")]
    ])


def categories_keyboard() -> InlineKeyboardMarkup:
    kb = []
    try:
        db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "database.db")
        import sqlite3
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT DISTINCT kategori FROM produk_xl WHERE kategori IS NOT NULL ORDER BY kategori")
        rows = c.fetchall()
        conn.close()
        for r in rows:
            k = r[0] or "-"
            kb.append([InlineKeyboardButton(text=str(k), callback_data=f"jadwal_category_{k}")])
    except Exception:
        kb = [[InlineKeyboardButton(text="PULSA", callback_data="jadwal_category_PULSA")]]
    kb.append([InlineKeyboardButton(text="⬅️ Kembali ke Menu Utama", callback_data="back_to_user_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


# --- safe session helpers (avoid AttributeError if sessions is not a plain dict) ---
def _set_session_value(user_id: int, key: str, value: Any) -> None:
    try:
        if isinstance(sessions, dict):
            sessions.setdefault(user_id, {})[key] = value
            return
    except Exception:
        pass
    # try item assignment if possible
    try:
        sessions[user_id] = sessions.get(user_id, {})
        sessions[user_id][key] = value
        return
    except Exception:
        pass
    # try common setter methods
    for setter in ("set", "set_session", "save_session"):
        try:
            if hasattr(sessions, setter) and callable(getattr(sessions, setter)):
                existing = sessions.get(user_id) or {}
                existing = dict(existing)
                existing[key] = value
                getattr(sessions, setter)(user_id, existing)
                return
        except Exception:
            continue
    # otherwise ignore (no persistent session available)


def _get_session_dict(user_id: int) -> dict:
    try:
        if isinstance(sessions, dict):
            return sessions.get(user_id, {}) or {}
    except Exception:
        pass
    try:
        get_m = getattr(sessions, "get", None)
        if callable(get_m):
            val = sessions.get(user_id)
            if isinstance(val, dict):
                return val
    except Exception:
        pass
    # fallback empty
    return {}


# ---------------- Handlers ----------------
@router.callback_query(F.data == "jadwal_transaksi")
async def entry_jadwal_transaksi(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📂 Pilih Kategori untuk dijadwalkan:", reply_markup=categories_keyboard())
    await state.clear()
    await callback.answer()


@router.callback_query(F.data.regexp(r"^jadwal_category_(.+)$"))
async def list_products(callback: CallbackQuery, state: FSMContext):
    match = re.match(r"^jadwal_category_(.+)$", callback.data)
    if not match:
        await callback.answer("Kategori tidak valid.", show_alert=True)
        return
    kategori = match.group(1)
    import sqlite3
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "database.db")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT id, nama_produk, harga_jual FROM produk_xl WHERE kategori = ? ORDER BY id", (kategori,))
    rows = c.fetchall()
    conn.close()
    if not rows:
        await callback.message.edit_text(f"Tidak ada produk di kategori {escape(kategori)}.", reply_markup=_build_back())
        return
    text_lines = [f"📦 Produk di kategori: <b>{escape(kategori)}</b>\n"]
    kb = []
    for r in rows:
        pid, nama, harga = r[0], r[1], r[2] or 0
        text_lines.append(f"• {escape(nama)} — Rp{escape(str(harga))}")
        kb.append([InlineKeyboardButton(text=f"{nama} — Rp{harga}", callback_data=f"jadwal_product_{pid}")])
    kb.append([InlineKeyboardButton(text="⬅️ Kembali ke Kategori", callback_data="jadwal_transaksi")])
    await callback.message.edit_text("\n".join(text_lines), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.regexp(r"^jadwal_product_(.+)$"))
async def show_product(callback: CallbackQuery, state: FSMContext):
    match = re.match(r"^jadwal_product_(.+)$", callback.data)
    if not match:
        await callback.answer("Produk tidak valid.", show_alert=True)
        return
    produk_id = match.group(1)
    product = get_produk_detail(produk_id)
    if not product:
        await callback.message.edit_text("❗ Produk tidak ditemukan atau tidak aktif.", reply_markup=_build_back())
        return

    # Do NOT show pulsa/session info here per request
    text = (
        f"🛒 <b>{escape(product.get('nama_produk','-'))}</b>\n"
        f"Kategori: <b>{escape(product.get('kategori','-'))}</b>\n"
        f"Harga: <b>Rp{escape(str(product.get('harga_jual',0)))}</b>\n"
        f"Deskripsi: {escape(product.get('deskripsi','-'))}\n\n"
        "Tekan tombol Jadwalkan untuk membuat transaksi terjadwal untuk produk ini."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗓️ Jadwalkan", callback_data=f"jadwal_buy_{produk_id}")],
        [InlineKeyboardButton(text="⬅️ Kembali ke Produk", callback_data=f"jadwal_category_{product.get('kategori','-')}")],
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.regexp(r"^jadwal_buy_(.+)$"))
async def sched_buy_start(callback: CallbackQuery, state: FSMContext):
    match = re.match(r"^jadwal_buy_(.+)$", callback.data)
    if not match:
        await callback.answer("Produk tidak valid.", show_alert=True)
        return
    produk_id = match.group(1)
    await state.update_data(produk_id=produk_id)

    # Prompt MSISDN after pressing Jadwalkan and include OTP verification information and WebApp button
    mini_app_base = "https://web-otp-xl.vercel.app"
    prompt = (
        "Silakan masukkan nomor XL untuk transaksi ini (format 08xxxx atau 628xxxx):\n\n"
        "⚠️ Penting — Verifikasi OTP WAJIB\n\n"
        "Nomor yang Anda masukkan harus melewati verifikasi OTP sebelum transaksi terjadwal dapat dijalankan.\n\n"
        "Anda dapat melakukan verifikasi melalui salah satu cara berikut:\n"
        "• Verifikasi lewat menu \"OTP Login\" di bot (tekan tombol Verifikasi OTP), atau\n"
        "• Verifikasi melalui Mini‑App (buka Web OTP) — tekan tombol Web OTP di bawah untuk memasukkan nomor dengan nyaman.\n\n"
        "Silakan masukkan nomor sekarang."
    )

    # Use WebApp button so the user can fill number inside the mini-app (no redirect)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Masukkan Nomor di Web OTP (Mini‑App)", web_app=WebAppInfo(url=mini_app_base))],
        [InlineKeyboardButton(text="🔐 Verifikasi OTP (Menu)", callback_data="otp_login")],
        [InlineKeyboardButton(text="⬅️ Kembali", callback_data="back_to_user_menu")]
    ])

    await callback.message.edit_text(prompt, parse_mode="HTML", reply_markup=kb)
    await state.set_state(JadwalStates.waiting_msisdn)
    await callback.answer()


@router.message(JadwalStates.waiting_msisdn)
async def message_receive_msisdn(message: Message, state: FSMContext):
    txt = (message.text or "").strip()
    if txt.lower() in ("batal", "cancel", "exit"):
        await message.reply("Proses dibatalkan.", reply_markup=_build_back())
        await state.clear()
        return
    msisdn = txt
    if msisdn.startswith("08"):
        msisdn = "62" + msisdn[1:]
    if not msisdn.isdigit() or len(msisdn) < 10:
        await message.reply("Nomor tidak valid. Masukkan format 08xxx atau 628xxx.")
        return

    # store msisdn in session safely
    user_id = message.from_user.id
    _set_session_value(user_id, "msisdn", msisdn)

    data = await state.get_data()
    produk_id = data.get("produk_id")
    await message.reply("Nomor disimpan. Silakan pilih metode pembayaran:", reply_markup=_payment_methods_kb(produk_id))
    await state.set_state(JadwalStates.waiting_method)


def _payment_methods_kb(product_id: str) -> InlineKeyboardMarkup:
    kb = []
    for code, label in PAYMENT_METHODS:
        kb.append([InlineKeyboardButton(text=label, callback_data=f"jadwal_method_{code}_{product_id}")])
    kb.append([InlineKeyboardButton(text="⬅️ Batal", callback_data="back_to_user_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


@router.callback_query(F.data.regexp(r"^jadwal_method_([A-Z]+)_(.+)$"))
async def callback_sched_choose_method(callback: CallbackQuery, state: FSMContext):
    match = re.match(r"^jadwal_method_([A-Z]+)_(.+)$", callback.data)
    if not match:
        await callback.answer("Metode tidak valid.", show_alert=True)
        return
    method = match.group(1)
    produk_id = match.group(2)
    product = get_produk_detail(produk_id)
    if not product:
        await callback.answer("Produk tidak ditemukan.", show_alert=True)
        return

    # Per request: do NOT check pulsa/saldo and do NOT show pulsa info.
    harga = int(product.get("harga_jual", 0))
    total = harga

    # show summary and ask for time next
    method_label = next((lbl for c,lbl in PAYMENT_METHODS if c == method), method)
    text = (
        f"Rincian Pembayaran (jadwal)\n\n"
        f"Produk: <b>{escape(product.get('nama_produk','-'))}</b>\n"
        f"Metode: <b>{escape(method_label)}</b>\n"
        f"Harga: <b>Rp{total}</b>\n\n"
        "Tekan 'Set Waktu' untuk memasukkan kapan transaksi ini harus dijalankan."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🕒 Set Waktu", callback_data=f"jadwal_set_time_{method}_{produk_id}")],
        [InlineKeyboardButton(text="⬅️ Kembali Pilih Metode", callback_data=f"jadwal_product_{produk_id}")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await state.update_data(method=method, produk_id=produk_id, total=total)
    await state.set_state(JadwalStates.confirming)
    await callback.answer()


@router.callback_query(F.data.regexp(r"^jadwal_set_time_([A-Z]+)_(.+)$"))
async def callback_set_time(callback: CallbackQuery, state: FSMContext):
    match = re.match(r"^jadwal_set_time_([A-Z]+)_(.+)$", callback.data)
    if not match:
        await callback.answer("Data tidak valid.", show_alert=True)
        return
    await callback.message.edit_text(
        "Masukkan waktu pembelian untuk transaksi terjadwal ini.\nFormat: YYYY-MM-DD HH:MM\nContoh: 2025-08-26 15:30",
        parse_mode="HTML",
        reply_markup=_build_back()
    )
    await state.set_state(JadwalStates.waiting_time)
    await callback.answer()


def _parse_datetime_input(s: str) -> Optional[str]:
    s = s.strip()
    fmts = ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M")
    for f in fmts:
        try:
            dt = datetime.strptime(s, f)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
    try:
        dt = datetime.fromisoformat(s)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


@router.message(JadwalStates.waiting_time)
async def message_receive_time(message: Message, state: FSMContext):
    txt = (message.text or "").strip()
    if txt.lower() in ("batal", "cancel", "exit"):
        await message.reply("Proses dibatalkan.", reply_markup=_build_back())
        await state.clear()
        return
    waktu_iso = _parse_datetime_input(txt)
    if not waktu_iso:
        await message.reply("Format waktu tidak valid. Gunakan YYYY-MM-DD HH:MM, contoh: 2025-08-26 15:30")
        return

    # store waktu and show final summary with "Simpan Jadwal"
    await state.update_data(waktu_pembelian=waktu_iso)
    data = await state.get_data()
    produk_id = data.get("produk_id")
    method = data.get("method")
    total = int(data.get("total", 0))
    user_id = message.from_user.id
    # try to read msisdn from sessions if present
    sess = _get_session_dict(user_id)
    msisdn = (sess or {}).get("msisdn", "-")
    product = get_produk_detail(produk_id)
    if not product:
        await message.reply("Produk tidak ditemukan. Proses dibatalkan.")
        await state.clear()
        return

    summary = (
        f"Ringkasan Jadwal Transaksi\n\n"
        f"Produk: <b>{escape(product.get('nama_produk','-'))}</b>\n"
        f"Nomor: <code>{escape(msisdn)}</code>\n"
        f"Metode: <b>{escape(method)}</b>\n"
        f"Harga: <b>Rp{total}</b>\n"
        f"Waktu pembelian: <b>{waktu_iso}</b>\n\n"
        "Jika semua sudah benar, tekan ✅ Simpan Jadwal."
    )
    await message.reply(summary, parse_mode="HTML", reply_markup=_final_save_keyboard(produk_id))
    await state.set_state(JadwalStates.confirming)


@router.callback_query(F.data.regexp(r"^jadwal_save_(.+)$"))
async def callback_sched_save(callback: CallbackQuery, state: FSMContext):
    """
    Save scheduled transaction only.
    Per request:
    - Do NOT call external API.
    - Do NOT send notifications.
    - Do NOT perform saldo checking before saving.
    - Immediately deduct user's saldo for the amount regardless of payment method.
    - Persist transaksi_terjadwal and a riwayat entry reflecting the deduction.
    """
    match = re.match(r"^jadwal_save_(.+)$", callback.data)
    if not match:
        await callback.answer("Data tidak valid.", show_alert=True)
        return
    produk_id = match.group(1)
    data = await state.get_data()
    produk_id_state = data.get("produk_id")
    if produk_id_state and produk_id_state != produk_id:
        produk_id = produk_id_state

    method = data.get("method")
    total = int(data.get("total", 0))
    waktu = data.get("waktu_pembelian")
    user_id = callback.from_user.id

    # try to read msisdn from sessions if present
    sess = _get_session_dict(user_id)
    msisdn = (sess or {}).get("msisdn", "-")
    product = get_produk_detail(produk_id) or {}

    # --- Ensure saldo is actually deducted BEFORE saving the scheduled transaksi ---
    # Get current saldo
    try:
        user_before = get_user(user_id) or {}
        prev_saldo = int(user_before.get("saldo", 0))
    except Exception:
        prev_saldo = None

    deduction_succeeded = False
    new_saldo = None

    if total > 0:
        # Try to deduct once (primary attempt)
        try:
            update_user_saldo(user_id, -total)
            user_after = get_user(user_id) or {}
            new_saldo = int(user_after.get("saldo", 0))
            if prev_saldo is None:
                # if we couldn't read prev, consider deduction succeeded if balance reduced or exists
                deduction_succeeded = True
            else:
                deduction_succeeded = (new_saldo == prev_saldo - total)
        except Exception:
            logger.exception("Exception while attempting initial saldo deduction for user %s amount=%s", user_id, total)
            deduction_succeeded = False

        # If deduction didn't appear to take effect, retry once and log
        if not deduction_succeeded:
            logger.warning("Initial saldo deduction did not change balance for user %s (prev=%s new=%s). Retrying once.", user_id, prev_saldo, new_saldo)
            try:
                update_user_saldo(user_id, -total)
                user_after = get_user(user_id) or {}
                new_saldo = int(user_after.get("saldo", 0))
                if prev_saldo is None:
                    deduction_succeeded = True
                else:
                    deduction_succeeded = (new_saldo == prev_saldo - total)
            except Exception:
                logger.exception("Retry saldo deduction failed for user %s amount=%s", user_id, total)
                deduction_succeeded = False

    else:
        # total == 0 -> nothing to deduct but still treat as succeeded
        try:
            user_after = get_user(user_id) or {}
            new_saldo = int(user_after.get("saldo", 0))
        except Exception:
            new_saldo = 0
        deduction_succeeded = True

    if not deduction_succeeded:
        # Deduction failed: do NOT create scheduled transaksi (avoid inconsistent state)
        logger.error("Failed to deduct saldo for user %s amount=%s; aborting scheduled transaksi save.", user_id, total)
        # Inform user (no automatic notifications to admin per request)
        await callback.message.edit_text(
            f"❗ Gagal menyimpan jadwal: saldo Anda tidak dapat dipotong sebesar Rp{total}. "
            "Silakan cek saldo atau hubungi admin.",
            reply_markup=_build_back()
        )
        await state.clear()
        await callback.answer()
        return

    # --- At this point saldo deduction succeeded; create scheduled transaksi and riwayat ---
    tx_id = create_transaksi(
        userid=user_id,
        produk_id=produk_id,
        produk_nama=product.get("nama_produk", produk_id),
        kategori=product.get("kategori", "-"),
        harga_jual=total,
        metode_pembayaran=method,
        waktu_pembelian_iso=waktu,
        msisdn=msisdn,
        status="pending"
    )

    # create riwayat record reflecting the deduction
    trx_local_id = f"local_{tx_id}_{int(datetime.utcnow().timestamp())}"
    try:
        insert_riwayat(
            user_id=str(user_id),
            msisdn=msisdn,
            produk_id=produk_id,
            produk_nama=product.get("nama_produk", "-"),
            kategori=product.get("kategori", "-"),
            harga_jual=total,
            metode_pembayaran=method,
            amount_charged=total,
            saldo_tersisa=new_saldo,
            trx_id=trx_local_id,
            status="sukses",
            keterangan=f"Saldo dipotong saat menyimpan transaksi terjadwal id={tx_id}"
        )
    except Exception:
        logger.exception("Failed to insert riwayat for scheduled payment deduction tx_id=%s user=%s", tx_id, user_id)

    # Reply to user (no API call, no notifications)
    await callback.message.edit_text(
        f"✅ Transaksi terjadwal dibuat dan dibayar (id: {tx_id}).\n"
        f"Produk: <b>{escape(product.get('nama_produk','-'))}</b>\n"
        f"Waktu: <b>{escape(str(waktu))}</b>\n"
        f"Metode: <b>{escape(str(method))}</b>\n"
        f"Nomor: <code>{escape(msisdn)}</code>\n"
        f"Saldo Anda sekarang: <b>Rp{new_saldo}</b>\n\n",
        parse_mode="HTML",
        reply_markup=_build_back()
    )

    await state.clear()
    await callback.answer("Jadwal disimpan dan saldo dipotong.")


# export router for inclusion by main bot
transaksi_terjadwal_router = router