from __future__ import annotations
import os
import json
import io
import sqlite3
from typing import List, Optional, Dict, Any

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputFile,
)

from data.database import get_user as get_user_db
import models.transaksi_terjadwal as mtx  # type: ignore

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
        return {}


def _get_back_keyboard(role: str = "user") -> InlineKeyboardMarkup:
    """
    Return a single-button keyboard matching the style in the Sidompul example.
    Role can be "admin" or anything else (treated as user).
    """
    if role == "admin":
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Kembali ke Menu Admin", callback_data="back_to_admin_menu")]
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Kembali ke Menu Utama", callback_data="back_to_user_menu")]
    ])


def _fmt_rp(amount: Any) -> str:
    try:
        a = int(amount)
        return f"Rp{format(a, ',').replace(',', '.')}"
    except Exception:
        try:
            return f"Rp{amount}"
        except Exception:
            return "-"


def _rows_to_dicts(rows: List[tuple]) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        out.append({
            "id": r[0],
            "userid": r[1],
            "produk_id": r[2],
            "produk_nama": r[3],
            "kategori": r[4],
            "harga_jual": r[5],
            "metode_pembayaran": r[6],
            "msisdn": r[7],
            "waktu_pembelian": r[8],
            "status": r[9],
            "created_at": r[10],
        })
    return out


async def _fetch_all_pending_from_db(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Fetch all pending transaksi_terjadwal rows directly from the DB used by models.transaksi_terjadwal."""
    try:
        db_path = getattr(mtx, "DB_PATH", None)
        if not db_path:
            return []
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        q = ("SELECT id, userid, produk_id, produk_nama, kategori, harga_jual, metode_pembayaran, "
             "msisdn, waktu_pembelian, status, created_at FROM transaksi_terjadwal "
             "WHERE status = 'pending' ORDER BY waktu_pembelian DESC")
        if limit:
            q = q + " LIMIT ?"
            c.execute(q, (limit,))
        else:
            c.execute(q)
        rows = c.fetchall()
        conn.close()
        return _rows_to_dicts(rows)
    except Exception:
        return []


@router.callback_query(F.data == "pending_transaksi")
async def handle_pending_transaksi(callback: CallbackQuery) -> None:
    """
    Show pending scheduled transactions by EDITING the existing message (no new reply).

    - Admin: show all transactions with status 'pending'.
    - User: show only their transactions with status 'pending'.
    - If content too long, edit the message to indicate file will be sent, then send a .txt document.
    """
    await callback.answer()  # stop Telegram spinner

    tg_user_id = int(callback.from_user.id)
    setup = read_setup()
    admin_cfg = setup.get("admin") or {}
    setup_admin_userid: Optional[int] = None
    try:
        if admin_cfg.get("userid"):
            setup_admin_userid = int(admin_cfg.get("userid"))
    except Exception:
        setup_admin_userid = None

    # Determine role from DB (preferred) or setup admin id
    role = "user"
    try:
        user_info = get_user_db(tg_user_id) or {}
        role = user_info.get("role", "user") or "user"
        # normalize
        role = str(role).lower()
    except Exception:
        role = "user"

    is_admin = role == "admin" or (setup_admin_userid is not None and setup_admin_userid == tg_user_id)

    # Fetch items
    items: List[Dict[str, Any]] = []
    if is_admin:
        items = await _fetch_all_pending_from_db()
    else:
        # use model helper to get user's transactions then filter pending
        try:
            items = mtx.get_transaksi_by_user(tg_user_id, limit=500)
        except Exception:
            all_pending = await _fetch_all_pending_from_db()
            uid_str = str(tg_user_id)
            items = [it for it in all_pending if str(it.get("userid")) == uid_str]

        # ensure only pending
        items = [it for it in items if str(it.get("status", "")).lower() == "pending"]

    back_kb = _get_back_keyboard("admin" if is_admin else "user")

    if not items:
        # edit existing message to say there are no pending transactions and show back button
        try:
            await callback.message.edit_text(
                "Tidak ada transaksi terjadwal yang berstatus pending.",
                reply_markup=back_kb,
                parse_mode=None
            )
        except Exception:
            # fallback: send a new message if edit fails
            try:
                await callback.message.answer("Tidak ada transaksi terjadwal yang berstatus pending.", reply_markup=back_kb)
            except Exception:
                pass
        return

    # Build textual list (plain) and HTML representation for editing
    lines_plain: List[str] = []
    lines_html: List[str] = []
    from html import escape as _escape
    for it in items:
        tx_id = it.get("id") or "-"
        produk = it.get("produk_nama") or it.get("produk_id") or "-"
        harga = it.get("harga_jual") or it.get("amount") or "-"
        metode = it.get("metode_pembayaran") or it.get("payment_method") or "-"
        msisdn = it.get("msisdn") or "-"
        waktu = it.get("waktu_pembelian") or it.get("waktu") or "-"
        status = it.get("status") or "-"

        # Try to display Telegram username and userid when possible
        uid = it.get("userid")
        username_display = "-"
        userid_display = uid if uid is not None else "-"
        try:
            # get_user_db expects an int userid in most implementations
            try:
                user_record = get_user_db(int(uid)) if uid is not None else {}
            except Exception:
                user_record = get_user_db(uid) if uid is not None else {}
            if user_record:
                uname = user_record.get("username") or user_record.get("user_name") or user_record.get("tg_username") or None
                if uname:
                    # normalize to remove leading @ if present
                    uname = str(uname)
                    if uname.startswith("@"):
                        uname = uname[1:]
                    username_display = f"@{uname}"
                # ensure userid_display is string
                userid_display = str(user_record.get("userid") or user_record.get("user_id") or uid)
        except Exception:
            # ignore and leave defaults
            pass

        try:
            harga_str = _fmt_rp(harga)
        except Exception:
            harga_str = str(harga)

        lines_plain.append(
            f"ID lokal: {tx_id}\n"
            f"Telegram Username: {username_display}\n"
            f"Telegram UserID: {userid_display}\n"
            f"Produk: {produk}\n"
            f"Harga: {harga_str}\n"
            f"Metode: {metode}\n"
            f"Nomor: {msisdn}\n"
            f"Waktu (scheduled): {waktu}\n"
            f"Status: {status}\n"
            "-------------------------"
        )

        lines_html.append(
            f"ID lokal: <code>{_escape(str(tx_id))}</code>\n"
            f"• Telegram Username: <b>{_escape(str(username_display))}</b>\n"
            f"• Telegram UserID: <code>{_escape(str(userid_display))}</code>\n"
            f"• Produk: <b>{_escape(str(produk))}</b>\n"
            f"• Harga: <b>{_escape(str(harga_str))}</b>\n"
            f"• Metode: <b>{_escape(str(metode))}</b>\n"
            f"• Nomor: <code>{_escape(str(msisdn))}</code>\n"
            f"• Waktu (scheduled): <code>{_escape(str(waktu))}</code>\n"
            f"• Status: <b>{_escape(str(status))}</b>\n"
            "-------------------------"
        )

    content_plain = "\n".join(lines_plain)
    content_html = "Daftar Transaksi Terjadwal (Pending):\n\n" + "\n".join(lines_html)

    # Decide whether to send as file
    MAX_MESSAGE_CHARS = 3800
    MAX_INLINE_ITEMS = 50
    send_as_file = len(content_plain) > MAX_MESSAGE_CHARS or len(items) > MAX_INLINE_ITEMS

    if send_as_file:
        # edit existing message to notify user file will be sent, then send file as document
        try:
            await callback.message.edit_text("Daftar terlalu panjang, sedang menyiapkan file daftar transaksi pending...", reply_markup=back_kb)
        except Exception:
            pass

        bio = io.BytesIO()
        bio.write(content_plain.encode("utf-8"))
        bio.seek(0)
        filename = "pending_transaksi_terjadwal.txt"
        input_file = InputFile(bio, filename=filename)
        try:
            # send document as a new message (can't edit to a document)
            await callback.message.answer_document(input_file, caption=f"Daftar Transaksi Terjadwal (Pending) - {'Semua' if is_admin else 'User Anda'}", reply_markup=back_kb)
        except Exception:
            try:
                await callback.message.edit_text("Gagal mengirim file daftar transaksi.", reply_markup=back_kb)
            except Exception:
                pass
        return

    # Otherwise edit the existing message with the HTML list and back button
    try:
        await callback.message.edit_text(content_html, reply_markup=back_kb, parse_mode="HTML")
    except Exception:
        # fallback: send a new message if edit fails
        try:
            await callback.message.answer(content_html, reply_markup=back_kb, parse_mode="HTML")
        except Exception:
            pass


@router.callback_query(F.data == "back_to_admin_menu")
async def back_to_admin_menu(callback: CallbackQuery) -> None:
    """
    Edit the existing message to show the admin menu keyboard (like the Sidompul example).
    """
    await callback.answer()
    try:
        from button.start import get_admin_keyboard  # type: ignore
        kb = get_admin_keyboard()
        await callback.message.edit_text(
            "<b>Selamat datang di Menu Admin!</b>\nSilakan pilih menu yang tersedia di bawah ini:",
            parse_mode="HTML",
            reply_markup=kb
        )
    except Exception:
        # fallback: try to send a new message
        try:
            from button.start import get_admin_keyboard  # type: ignore
            kb = get_admin_keyboard()
            await callback.message.answer(
                "<b>Selamat datang di Menu Admin!</b>\nSilakan pilih menu yang tersedia di bawah ini:",
                parse_mode="HTML",
                reply_markup=kb
            )
        except Exception:
            pass


@router.callback_query(F.data == "back_to_user_menu")
async def back_to_user_menu(callback: CallbackQuery) -> None:
    """
    Edit the existing message to show the user menu keyboard (like the Sidompul example).
    """
    await callback.answer()
    try:
        from button.start import get_user_keyboard  # type: ignore
        kb = get_user_keyboard()
        await callback.message.edit_text(
            "<b>Selamat datang di Menu Utama!</b>\nSilakan pilih menu yang tersedia di bawah ini:",
            parse_mode="HTML",
            reply_markup=kb
        )
    except Exception:
        # fallback: try to send a new message
        try:
            from button.start import get_user_keyboard  # type: ignore
            kb = get_user_keyboard()
            await callback.message.answer(
                "<b>Selamat datang di Menu Utama!</b>\nSilakan pilih menu yang tersedia di bawah ini:",
                parse_mode="HTML",
                reply_markup=kb
            )
        except Exception:
            pass