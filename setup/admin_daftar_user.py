from __future__ import annotations
import os
import sqlite3
import logging
from typing import List, Dict, Any, Optional
from html import escape as _escape

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from data.database import DB_PATH
import models.riwayat_transaksi as rtx
import models.transaksi_terjadwal as ttx

router = Router()
logger = logging.getLogger(__name__)

PER_PAGE = 5


def _format_currency(value: Optional[int]) -> str:
    try:
        v = int(value or 0)
        return f"Rp{format(v, ',').replace(',', '.')}"
    except Exception:
        return str(value or "-")


def _fetch_users_page(page: int = 1, per_page: int = PER_PAGE) -> (List[Dict[str, Any]], int):
    """
    Return (users_list, total_count). Users ordered by tanggal_daftar DESC.
    Each user dict: userid, username, saldo, role, tanggal_daftar, status
    """
    users: List[Dict[str, Any]] = []
    total = 0
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(1) FROM users")
        row = c.fetchone()
        total = int(row[0]) if row else 0

        offset = (page - 1) * per_page
        c.execute(
            "SELECT userid, username, saldo, role, tanggal_daftar, status "
            "FROM users ORDER BY tanggal_daftar DESC LIMIT ? OFFSET ?",
            (per_page, offset),
        )
        rows = c.fetchall()
        conn.close()
        for r in rows:
            users.append({
                "userid": r[0],
                "username": r[1],
                "saldo": r[2],
                "role": r[3],
                "tanggal_daftar": r[4],
                "status": r[5],
            })
    except Exception:
        logger.exception("Failed to fetch paged users from DB")
    return users, total


def _user_stats(userid: Any) -> Dict[str, Any]:
    """
    Compute per-user statistics:
      - total (from riwayat_transaksi)
      - sukses (riwayat_transaksi)
      - gagal (riwayat_transaksi)
      - pending (from transaksi_terjadwal per user with status='pending')
      - total_amount (sum(amount_charged) from riwayat_transaksi)
    """
    stats = {"total": 0, "sukses": 0, "gagal": 0, "pending": 0, "total_amount": 0}
    try:
        # riwayat_transaksi DB
        dbp = getattr(rtx, "DB_PATH", None) or DB_PATH
        conn = sqlite3.connect(dbp)
        c = conn.cursor()
        # total riwayat
        c.execute("SELECT COUNT(1) FROM riwayat_transaksi WHERE user_id = ?", (str(userid),))
        r = c.fetchone()
        stats["total"] = int(r[0]) if r else 0

        # sukses
        c.execute("SELECT COUNT(1) FROM riwayat_transaksi WHERE user_id = ? AND lower(status) IN ('sukses','success')", (str(userid),))
        r = c.fetchone()
        stats["sukses"] = int(r[0]) if r else 0

        # gagal
        c.execute("SELECT COUNT(1) FROM riwayat_transaksi WHERE user_id = ? AND lower(status) IN ('gagal','failed','failure','fail')", (str(userid),))
        r = c.fetchone()
        stats["gagal"] = int(r[0]) if r else 0

        # total_amount (sum of amount_charged)
        c.execute("SELECT COALESCE(SUM(amount_charged),0) FROM riwayat_transaksi WHERE user_id = ?", (str(userid),))
        r = c.fetchone()
        stats["total_amount"] = int(r[0]) if r and r[0] is not None else 0

        conn.close()

        # pending from transaksi_terjadwal (as requested)
        dbp2 = getattr(ttx, "DB_PATH", None) or DB_PATH
        conn2 = sqlite3.connect(dbp2)
        c2 = conn2.cursor()
        c2.execute("SELECT COUNT(1) FROM transaksi_terjadwal WHERE userid = ? AND lower(status) = 'pending'", (str(userid),))
        r2 = c2.fetchone()
        stats["pending"] = int(r2[0]) if r2 else 0
        conn2.close()
    except Exception:
        logger.exception("Failed to compute stats for user %s", userid)
    return stats


def _build_pagination_kb(page: int, total_count: int, per_page: int = PER_PAGE) -> InlineKeyboardMarkup:
    kb_rows = []
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⏮️ Prev", callback_data=f"admin_daftar_user:{page-1}"))
    nav_row.append(InlineKeyboardButton(text=f"Page {page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="Next ⏭️", callback_data=f"admin_daftar_user:{page+1}"))
    kb_rows.append(nav_row)
    kb_rows.append([InlineKeyboardButton(text="⬅️ Kembali ke Menu Seting User", callback_data="seting_user")])
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)


@router.callback_query(F.data.regexp(r"^admin_daftar_user(?::(\d+))?$"))
async def admin_daftar_user_handler(callback: CallbackQuery):
    """
    Paginated admin view of users (PER_PAGE per page).
    Shows for each user: userid, username, role, saldo, tanggal_daftar, status
    and statistics: total trx, sukses, gagal (from riwayat_transaksi), pending (from transaksi_terjadwal),
    and total saldo terpakai (sum amount_charged).
    """
    await callback.answer()
    # determine page if provided
    import re
    match = re.match(r"^admin_daftar_user(?::(\d+))?$", callback.data)
    page = 1
    if match and match.group(1):
        try:
            page = max(1, int(match.group(1)))
        except Exception:
            page = 1

    users, total_count = _fetch_users_page(page, PER_PAGE)
    if not users:
        try:
            await callback.message.edit_text("Tidak ada user terdaftar.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Kembali ke Menu Seting User", callback_data="seting_user")]
            ]))
        except Exception:
            await callback.message.answer("Tidak ada user terdaftar.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Kembali ke Menu Seting User", callback_data="seting_user")]
            ]))
        return

    lines_html: List[str] = []
    for u in users:
        userid = u.get("userid", "-")
        username = u.get("username") or "-"
        username_disp = f"@{username}" if username and not str(username).startswith("@") else (username or "-")
        saldo = _format_currency(u.get("saldo"))
        role = u.get("role") or "-"
        tanggal = u.get("tanggal_daftar") or "-"
        status = u.get("status") or "-"

        stats = _user_stats(userid)
        total_trx = stats.get("total", 0)
        sukses = stats.get("sukses", 0)
        gagal = stats.get("gagal", 0)
        pending = stats.get("pending", 0)
        total_amount = _format_currency(stats.get("total_amount", 0))

        lines_html.append(
            f"UserID: <code>{_escape(str(userid))}</code>\n"
            f"• Username: <b>{_escape(str(username_disp))}</b>\n"
            f"• Role: <b>{_escape(str(role))}</b>\n"
            f"• Saldo: <b>{_escape(str(saldo))}</b>\n"
            f"• Terdaftar: <code>{_escape(str(tanggal))}</code>\n"
            f"• Status: <b>{_escape(str(status))}</b>\n"
            f"• Statistik Transaksi: total <b>{total_trx}</b>, sukses <b>{sukses}</b>, gagal <b>{gagal}</b>, pending <b>{pending}</b>\n"
            f"• Total saldo terpakai: <b>{_escape(str(total_amount))}</b>\n"
            "-------------------------"
        )

    content_html = "<b>Daftar User Terdaftar</b>\n\n" + "\n".join(lines_html)
    kb = _build_pagination_kb(page, total_count, PER_PAGE)
    try:
        await callback.message.edit_text(content_html, reply_markup=kb, parse_mode="HTML")
    except Exception:
        try:
            await callback.message.answer(content_html, reply_markup=kb, parse_mode="HTML")
        except Exception:
            logger.exception("Failed to send paginated user list")