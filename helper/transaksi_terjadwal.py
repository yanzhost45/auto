from __future__ import annotations
import os
import json
import asyncio
import logging
import io
import tempfile
import qrcode
import aiohttp
import urllib.parse
import re
from html import escape
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Any as _Any

from aiogram import Bot as AiogramBot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from models.transaksi_terjadwal import list_pending_due, update_status
from models.riwayat_transaksi import insert_riwayat
from data.database import get_user, update_user_saldo
from api.xl_payment import xl_payment_settlement

logger = logging.getLogger(__name__)


def _read_setup() -> Dict[str, Any]:
    try:
        path = os.path.join("core", "setup.json")
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        logger.exception("Failed to read setup.json")
        return {}


def _fmt_rp(amount: Any) -> str:
    try:
        a = int(amount)
        return f"Rp{format(a, ',').replace(',', '.')}"
    except Exception:
        return f"Rp{escape(str(amount))}"


def _now_jakarta_str() -> str:
    try:
        from zoneinfo import ZoneInfo  # Python 3.9+
        now = datetime.now(ZoneInfo("Asia/Jakarta"))
    except Exception:
        try:
            import pytz  # type: ignore
            tz = pytz.timezone("Asia/Jakarta")
            now = datetime.now(tz)
        except Exception:
            now = datetime.utcnow() + timedelta(hours=7)
    return now.strftime("%Y-%m-%d %H:%M:%S")


def _now_jakarta_dt() -> datetime:
    try:
        from zoneinfo import ZoneInfo  # Python 3.9+
        return datetime.now(ZoneInfo("Asia/Jakarta"))
    except Exception:
        try:
            import pytz  # type: ignore
            tz = pytz.timezone("Asia/Jakarta")
            return datetime.now(tz)
        except Exception:
            return datetime.utcnow() + timedelta(hours=7)


def _parse_datetime_jakarta(s: str) -> Optional[datetime]:
    if not s:
        return None
    s = s.strip()
    fmts = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S")
    for f in fmts:
        try:
            dt = datetime.strptime(s, f)
            try:
                from zoneinfo import ZoneInfo  # type: ignore
                return dt.replace(tzinfo=ZoneInfo("Asia/Jakarta"))
            except Exception:
                try:
                    import pytz  # type: ignore
                    tz = pytz.timezone("Asia/Jakarta")
                    return tz.localize(dt)
                except Exception:
                    return dt
        except Exception:
            continue
    try:
        dt = datetime.fromisoformat(s)
        try:
            from zoneinfo import ZoneInfo  # type: ignore
            return dt.astimezone(ZoneInfo("Asia/Jakarta"))
        except Exception:
            return dt
    except Exception:
        return None


def _deep_find_value(obj: _Any, target_keys):
    import json as _json

    if obj is None:
        return {}

    if isinstance(obj, str):
        s = obj.strip()
        if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
            try:
                parsed = _json.loads(s)
                return _deep_find_value(parsed, target_keys)
            except Exception:
                return {}

    if isinstance(obj, dict):
        lower_map = {k.lower(): k for k in obj.keys()}
        found = {}
        for tk in target_keys:
            lk = tk.lower()
            if lk in lower_map:
                found[tk] = obj.get(lower_map[lk])
        if found:
            return found
        for v in obj.values():
            res = _deep_find_value(v, target_keys)
            if res:
                return res
        return {}

    if isinstance(obj, (list, tuple)):
        for item in obj:
            res = _deep_find_value(item, target_keys)
            if res:
                return res
        return {}

    return {}


def _extract_xl_fields(result: dict, data: dict):
    target_keys = [
        "xl_status", "xl_code_detail", "xl_code",
        "xl_description", "xl_title", "xl_message",
        "trx_id", "transaction_id", "transactionId"
    ]
    candidates = []
    if data:
        candidates.append(data)
    if result:
        candidates.append(result)
    combined_found = {}
    for cand in candidates:
        try:
            found = _deep_find_value(cand, target_keys)
            if found:
                combined_found.update(found)
        except Exception:
            continue

    def norm(k):
        v = combined_found.get(k)
        if v is None:
            return ""
        return str(v)

    xl_status = norm("xl_status")
    xl_code_detail = norm("xl_code_detail") or norm("xl_code")
    xl_description = norm("xl_description") or norm("xl_title")
    xl_message = norm("xl_message")
    trx_id = norm("trx_id") or norm("transaction_id") or norm("transactionId") or "-"
    return xl_status, xl_code_detail, xl_description, xl_message, trx_id


def _short_json(obj: Any, max_len: int = 2000) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False)
    except Exception:
        try:
            s = str(obj)
        except Exception:
            s = repr(obj)
    if len(s) > max_len:
        return s[:max_len] + "...(truncated)"
    return s


async def _call_settlement_in_thread(produk_id: str, msisdn: str, metode: str) -> dict:
    return await asyncio.to_thread(xl_payment_settlement, produk_id, msisdn, metode)


async def _send_text_notifications(notif_token: str, admin_target: Optional[str], admin_msg: str, user_id: int, user_msg: str, reply_kb: Optional[InlineKeyboardMarkup] = None):
    try:
        async with AiogramBot(token=notif_token) as notif_bot:
            if admin_target:
                try:
                    await notif_bot.send_message(chat_id=admin_target, text=admin_msg, parse_mode="HTML", disable_web_page_preview=False, reply_markup=reply_kb)
                except Exception:
                    logger.exception("Failed to send admin notification (text)")
            try:
                await notif_bot.send_message(chat_id=int(user_id), text=user_msg, parse_mode="HTML", disable_web_page_preview=False, reply_markup=reply_kb)
            except Exception:
                logger.exception("Failed to send user notification (text)")
    except Exception:
        logger.exception("Notification bot failure during send_message")


async def _upload_qr_and_notify(notif_token: str, admin_target: Optional[str], user_id: int, qr_string: str, produk_nama: str, harga: Any, trx_id: str, payment_link: Optional[str]):
    try:
        qr_img = qrcode.make(qr_string)
    except Exception:
        logger.exception("Failed to create QR image")
        return

    buffer = io.BytesIO()
    tmp_path = None
    try:
        qr_img.save(buffer, format="PNG")
        buffer.seek(0)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(buffer.getvalue())
            tmp_path = tmp.name

        caption = (
            f"🧾 <b>QRIS untuk Pembayaran</b>\n"
            f"• Produk: <b>{escape(produk_nama)}</b>\n"
            f"• Harga: <b>{escape(_fmt_rp(harga))}</b>\n"
            f"• ID Transaksi: <code>{escape(str(trx_id))}</code>\n"
        )

        url = f"https://api.telegram.org/bot{notif_token}/sendPhoto"
        async with aiohttp.ClientSession() as session:
            if admin_target:
                try:
                    with open(tmp_path, "rb") as fh_admin:
                        form = aiohttp.FormData()
                        form.add_field("chat_id", str(admin_target))
                        form.add_field("caption", caption)
                        form.add_field("parse_mode", "HTML")
                        # include payment link button if URL
                        if payment_link and urllib.parse.urlparse(str(payment_link)).scheme in ("http", "https"):
                            form.add_field("reply_markup", json.dumps({"inline_keyboard": [[{"text": "Buka Link Pembayaran", "url": payment_link}]]}))
                        form.add_field("photo", fh_admin, filename="qris.png", content_type="image/png")
                        async with session.post(url, data=form, timeout=30) as resp_admin:
                            body = await resp_admin.text()
                            if resp_admin.status != 200:
                                logger.error("Upload QR to admin failed: %s %s", resp_admin.status, body)
                except Exception:
                    logger.exception("Exception while uploading QR to admin")

            try:
                with open(tmp_path, "rb") as fh_user:
                    form = aiohttp.FormData()
                    form.add_field("chat_id", str(user_id))
                    form.add_field("caption", caption)
                    form.add_field("parse_mode", "HTML")
                    if payment_link and urllib.parse.urlparse(str(payment_link)).scheme in ("http", "https"):
                        form.add_field("reply_markup", json.dumps({"inline_keyboard": [[{"text": "Buka Link Pembayaran", "url": payment_link}]]}))
                    form.add_field("photo", fh_user, filename="qris.png", content_type="image/png")
                    async with session.post(url, data=form, timeout=30) as resp_user:
                        body = await resp_user.text()
                        if resp_user.status != 200:
                            logger.error("Upload QR to user failed: %s %s", resp_user.status, body)
            except Exception:
                logger.exception("Exception while uploading QR to user")

    finally:
        try:
            buffer.close()
        except Exception:
            pass
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            logger.exception("Failed to remove temporary QR file in notification")


# Heuristic detection whether a payload is EMV/QRIS data to render as QR image.
def _is_qr_emv(payload: Optional[str]) -> bool:
    try:
        if not payload:
            return False
        s = str(payload).strip()
        # Do not treat URLs or deeplinks as EMV
        if s.lower().startswith(("http://", "https://")):
            return False
        # Common EMV header
        if s.startswith("000201"):
            return True
        # Provider marker often present
        if "ID.CO.QRIS" in s.upper():
            return True
        # fallback: long alphanumeric payloads are likely EMV
        clean = re.sub(r"\s+", "", s)
        if len(clean) >= 50 and re.match(r"^[0-9A-Z\:\.\-/&_=%]+$", clean, flags=re.I):
            return True
    except Exception:
        return False
    return False


async def notify_admin_and_user_on_success(setup: dict, user_id: int, user_info: dict, produk_nama: str,
                                           harga: int, msisdn: str, trx_id: str, payment_method: str, saldo_akhir,
                                           payment_link: str = None, qr_string: str = None, product_id: str = None):
    def is_http_url(u):
        if not u:
            return False
        try:
            p = urllib.parse.urlparse(str(u))
            return p.scheme in ("http", "https") and bool(p.netloc)
        except Exception:
            return False

    notif_token = setup.get("notifikasi")
    admin = setup.get("admin") or {}

    if not notif_token:
        logger.info("No notification token configured in setup.json, skipping notifications.")
        return

    if payment_link and str(payment_link).strip() in ("", "-", "None", "null"):
        payment_link = None

    payment_link_is_url = is_http_url(payment_link)

    admin_userid = admin.get("userid")
    admin_username = admin.get("username")
    admin_target = None
    if admin_userid:
        admin_target = str(admin_userid)
    elif admin_username:
        admin_target = f"@{admin_username.lstrip('@')}"

    harga_str = _fmt_rp(harga)
    saldo_str = _fmt_rp(saldo_akhir)
    waktu = _now_jakarta_str()
    user_display = user_info.get("username") if user_info else "-"

    admin_msg = (
        f"🔔 <b>Notifikasi Transaksi Baru</b>\n"
        f"• Waktu (Jakarta): <code>{escape(waktu)}</code>\n"
        f"• User: @{escape(str(user_display))} (<code>{escape(str(user_id))}</code>)\n"
        f"• Produk: <b>{escape(produk_nama)}</b>\n"
        f"• Harga: <b>{escape(harga_str)}</b>\n"
        f"• Metode: <b>{escape(payment_method)}</b>\n"
        f"• Nomor: <code>{escape(msisdn)}</code>\n"
        f"• ID Transaksi: <code>{escape(str(trx_id))}</code>\n"
        f"• Saldo user: <b>{escape(saldo_str)}</b>\n"
    )

    user_msg = (
        f"✅ <b>Transaksi Selesai</b>\n"
        f"• Waktu (Jakarta): <code>{escape(waktu)}</code>\n"
        f"• Produk: <b>{escape(produk_nama)}</b>\n"
        f"• Harga: <b>{escape(harga_str)}</b>\n"
        f"• Metode: <b>{escape(payment_method)}</b>\n"
        f"• Nomor: <code>{escape(msisdn)}</code>\n"
        f"• ID Transaksi: <code>{escape(str(trx_id))}</code>\n"
        f"• Saldo Anda: <b>{escape(saldo_str)}</b>\n\n"
        "Terima kasih telah menggunakan layanan kami."
    )

    # If payment_link is not an URL, include as Data QRIS text (e.g. EMV payload)
    if payment_link and not payment_link_is_url:
        admin_msg += f"\n• Data QRIS: <code>{escape(str(payment_link))}</code>\n"
        user_msg += f"\n• Data QRIS: <code>{escape(str(payment_link))}</code>\n"

    reply_kb = None
    if payment_link_is_url:
        try:
            reply_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Buka Link Pembayaran", url=payment_link)]
            ])
        except Exception:
            reply_kb = None

    await _send_text_notifications(notif_token, admin_target, admin_msg, user_id, user_msg, reply_kb)

    # Only render/send QR image when payment_method == "QRIS" and payload looks like EMV/QRIS
    try:
        if payment_method and str(payment_method).upper() == "QRIS" and qr_string and _is_qr_emv(qr_string):
            await _upload_qr_and_notify(notif_token, admin_target, user_id, qr_string, produk_nama, harga, trx_id, payment_link)
        else:
            logger.debug("Skipping QR image for trx=%s: method=%s is_qr_emv=%s", trx_id, payment_method, bool(qr_string and _is_qr_emv(qr_string)))
    except Exception:
        logger.exception("Failed to upload QR and notify for trx=%s", trx_id)


async def notify_admin_and_user_on_failure(setup: dict, user_id: int, user_info: dict, produk_nama: str,
                                           harga: int, msisdn: str, trx_id: str, payment_method: str, saldo_after,
                                           reason: str = None, payment_link: str = None, qr_string: str = None, product_id: str = None,
                                           prev_saldo: Optional[int] = None, refunded_amount: int = 0, xl_message: Optional[str] = None):
    def is_http_url(u):
        if not u:
            return False
        try:
            p = urllib.parse.urlparse(str(u))
            return p.scheme in ("http", "https") and bool(p.netloc)
        except Exception:
            return False

    notif_token = setup.get("notifikasi")
    admin = setup.get("admin") or {}

    if not notif_token:
        logger.info("No notification token configured in setup.json, skipping notifications.")
        return

    if payment_link and str(payment_link).strip() in ("", "-", "None", "null"):
        payment_link = None

    payment_link_is_url = is_http_url(payment_link)

    admin_userid = admin.get("userid")
    admin_username = admin.get("username")
    admin_target = None
    if admin_userid:
        admin_target = str(admin_userid)
    elif admin_username:
        admin_target = f"@{admin_username.lstrip('@')}"

    harga_str = _fmt_rp(harga)
    saldo_str = _fmt_rp(saldo_after)
    waktu = _now_jakarta_str()
    user_display = user_info.get("username") if user_info else "-"

    prev_saldo_str = _fmt_rp(prev_saldo) if prev_saldo is not None else "-"
    refunded_str = _fmt_rp(refunded_amount) if refunded_amount else "-"

    admin_msg = (
        f"❗ <b>Notifikasi Transaksi Gagal</b>\n"
        f"• Waktu (Jakarta): <code>{escape(waktu)}</code>\n"
        f"• User: @{escape(str(user_display))} (<code>{escape(str(user_id))}</code>)\n"
        f"• Produk: <b>{escape(produk_nama)}</b>\n"
        f"• Harga: <b>{escape(harga_str)}</b>\n"
        f"• Metode: <b>{escape(payment_method)}</b>\n"
        f"• Nomor: <code>{escape(msisdn)}</code>\n"
        f"• ID Transaksi (lokal): <code>{escape(str(trx_id))}</code>\n"
        f"• Saldo sebelum: <b>{escape(prev_saldo_str)}</b>\n"
        f"• Jumlah refund: <b>{escape(refunded_str)}</b>\n"
        f"• Saldo saat ini: <b>{escape(saldo_str)}</b>\n"
        f"• Alasan: {escape(str(reason)) if reason else '-'}\n"
    )
    if xl_message:
        admin_msg += f"• Pesan API: <code>{escape(str(xl_message))}</code>\n"

    user_msg = (
        f"❗ <b>Transaksi Gagal</b>\n"
        f"• Waktu (Jakarta): <code>{escape(waktu)}</code>\n"
        f"• Produk: <b>{escape(produk_nama)}</b>\n"
        f"• Harga: <b>{escape(harga_str)}</b>\n"
        f"• Metode: <b>{escape(payment_method)}</b>\n"
    )
    if refunded_amount:
        user_msg += f"• Saldo sebelum: <b>{escape(prev_saldo_str)}</b>\n"
        user_msg += f"• Refund: <b>{escape(refunded_str)}</b>\n"
        user_msg += f"• Saldo saat ini: <b>{escape(saldo_str)}</b>\n"
    else:
        user_msg += f"• Saldo Anda: <b>{escape(saldo_str)}</b>\n"

    if xl_message:
        user_msg += f"• Alasan: {escape(str(xl_message))}\n"
    else:
        user_msg += f"• Alasan: {escape(str(reason)) if reason else '-'}\n"

    user_msg += f"• ID: <code>{escape(str(trx_id))}</code>\n"

    if payment_link and not payment_link_is_url:
        admin_msg += f"\n• Data QRIS: <code>{escape(str(payment_link))}</code>\n"
        user_msg += f"\n• Data QRIS: <code>{escape(str(payment_link))}</code>\n"

    reply_kb = None
    if payment_link_is_url:
        try:
            reply_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Buka Link Pembayaran", url=payment_link)]
            ])
        except Exception:
            reply_kb = None

    await _send_text_notifications(notif_token, admin_target, admin_msg, user_id, user_msg, reply_kb)

    # Only send QR image for QRIS + EMV payloads
    try:
        if payment_method and str(payment_method).upper() == "QRIS" and qr_string and _is_qr_emv(qr_string):
            await _upload_qr_and_notify(notif_token, admin_target, user_id, qr_string, produk_nama, harga, trx_id, payment_link)
        else:
            logger.debug("Skipping QR image for failed trx=%s: method=%s is_qr_emv=%s", trx_id, payment_method, bool(qr_string and _is_qr_emv(qr_string)))
    except Exception:
        logger.exception("Failed to upload QR and notify on failure for trx=%s", trx_id)


async def _process_tx(bot: AiogramBot, tx: dict, admin_target: Optional[str]):
    tx_id = tx.get("id")
    user_id = int(tx.get("userid") or 0)
    produk_id = tx.get("produk_id")
    produk_nama = tx.get("produk_nama") or produk_id
    harga = int(tx.get("harga_jual") or 0)
    metode = (tx.get("metode_pembayaran") or "").upper()
    msisdn = tx.get("msisdn") or "-"
    scheduled_raw = tx.get("waktu_pembelian") or tx.get("waktu_pembelian_iso") or tx.get("waktu")

    logger.info(
        "Processing scheduled tx id=%s user=%s product=%s method=%s msisdn=%s waktu=%s",
        tx_id, user_id, produk_id, metode, msisdn, scheduled_raw
    )

    setup = _read_setup()
    user_info = get_user(user_id) or {}

    if scheduled_raw:
        scheduled_dt = _parse_datetime_jakarta(str(scheduled_raw))
        if scheduled_dt:
            now_jkt = _now_jakarta_dt()
            grace_minutes = int(setup.get("jadwal_max_delay_minutes", 0) or 0)
            try:
                if scheduled_dt.tzinfo is not None and now_jkt.tzinfo is not None:
                    delta_seconds = (now_jkt - scheduled_dt).total_seconds()
                else:
                    delta_seconds = (now_jkt.replace(tzinfo=None) - scheduled_dt.replace(tzinfo=None)).total_seconds()
            except Exception:
                delta_seconds = 0

            threshold_seconds = grace_minutes * 60 + 59
            expired = delta_seconds > threshold_seconds

            if expired:
                try:
                    user_before = get_user(user_id) or {}
                    prev_saldo = int(user_before.get("saldo", 0))
                except Exception:
                    prev_saldo = None

                refunded_amount = 0
                if harga and harga > 0:
                    try:
                        update_user_saldo(user_id, harga)
                        refunded_amount = harga
                    except Exception:
                        logger.exception("Failed to refund saldo for user %s for expired scheduled tx %s", user_id, tx_id)
                try:
                    user_after = get_user(user_id) or {}
                    saldo_after = int(user_after.get("saldo", 0))
                except Exception:
                    saldo_after = 0

                try:
                    refund_trx_id = f"refund_{tx_id}_{int(datetime.utcnow().timestamp())}"
                    insert_riwayat(
                        user_id=str(user_id),
                        msisdn=msisdn,
                        produk_id=produk_id,
                        produk_nama=produk_nama,
                        kategori=tx.get("kategori", "-"),
                        harga_jual=harga,
                        metode_pembayaran=metode,
                        amount_charged=0,
                        saldo_tersisa=saldo_after,
                        trx_id=refund_trx_id,
                        status="failed",
                        keterangan=f"Refund karena waktu eksekusi terlewat untuk transaksi terjadwal id={tx_id}"
                    )
                except Exception:
                    logger.exception("Failed to insert riwayat refund for expired scheduled tx %s", tx_id)

                try:
                    update_status(tx_id, "failed")
                except Exception:
                    logger.exception("Failed to update scheduled tx status to failed for %s", tx_id)

                reason = "Waktu eksekusi terlewat; saldo dikembalikan."
                try:
                    await notify_admin_and_user_on_failure(
                        setup, user_id, user_info, produk_nama, harga, msisdn, tx_id, metode,
                        saldo_after, reason=reason, payment_link=None, qr_string=None, product_id=produk_id,
                        prev_saldo=prev_saldo, refunded_amount=refunded_amount, xl_message=None
                    )
                except Exception:
                    logger.exception("Failed to send expiry notifications for scheduled tx %s", tx_id)

                logger.info("Scheduled tx %s expired (delta_seconds=%s threshold=%s); marked failed and refunded user %s amount=%s",
                            tx_id, int(delta_seconds), threshold_seconds, user_id, refunded_amount)
                return

    logger.info("Calling settlement API for tx=%s produk=%s msisdn=%s metode=%s", tx_id, produk_id, msisdn, metode)
    try:
        result = await _call_settlement_in_thread(produk_id, msisdn, metode)
    except Exception:
        logger.exception("Settlement call failed for scheduled tx %s", tx_id)
        result = {"success": False, "error": "internal_call_failed"}

    try:
        data = result.get("data") or {}
    except Exception:
        data = {}

    xl_status, xl_code_detail, xl_description, xl_message, trx_from_api = _extract_xl_fields(result, data)
    trx_id_final = trx_from_api or f"scheduled_external_{tx_id}_{int(datetime.utcnow().timestamp())}"

    # Robust extraction of payment_link and qr_string from response
    payment_link = None
    qr_string = None
    try:
        if isinstance(data, dict):
            payment_link = data.get("payment_link") or data.get("link") or data.get("url") or data.get("link_pembayaran")
            qr_string = data.get("qr_string") or data.get("qr") or data.get("emv") or data.get("qr_payload") or data.get("link_pembayaran")
            payment_info = data.get("payment_info") or {}
            if isinstance(payment_info, dict):
                qr_string = qr_string or payment_info.get("qr_code") or payment_info.get("qr") or payment_info.get("emv")
                payment_link = payment_link or payment_info.get("payment_url") or payment_info.get("link") or payment_info.get("deeplink")
        payment_link = payment_link or result.get("payment_link") or result.get("link") or result.get("url") or result.get("link_pembayaran")
        qr_string = qr_string or result.get("qr_string") or result.get("qr") or result.get("emv") or result.get("qr_payload")
    except Exception:
        payment_link = payment_link or None
        qr_string = qr_string or None

    # Log API response BEFORE deciding success/failure
    try:
        logger.info(
            "API response for scheduled tx id=%s trx=%s product=%s msisdn=%s metode=%s waktu=%s response=%s",
            tx_id,
            trx_id_final,
            produk_id,
            msisdn,
            metode,
            scheduled_raw,
            _short_json(result, max_len=2000)
        )
    except Exception:
        logger.exception("Failed to log API response for tx %s", tx_id)

    api_success_flag = result.get("success") is True
    if data.get("xl_status") is not None and str(data.get("xl_status")).strip() != "":
        api_success = api_success_flag and (xl_status.upper() == "SUCCESS")
    else:
        api_success = api_success_flag

    http_status = result.get("_http_status")

    if api_success_flag and not api_success:
        logger.info("API returned success=True but xl_status=%s; treating as failed unless xl_status == 'SUCCESS'. tx=%s", xl_status, tx_id)

    try:
        user_db = get_user(user_id) or {}
        saldo_before = int(user_db.get("saldo", 0))
    except Exception:
        saldo_before = None

    if api_success:
        try:
            update_status(tx_id, "sukses")
        except Exception:
            logger.exception("Failed to update scheduled tx status for %s", tx_id)

        try:
            saldo_after = int((get_user(user_id) or {}).get("saldo", 0))
        except Exception:
            saldo_after = 0

        logger.info(
            "Scheduled tx %s: executed -> status=sukses (API). trx=%s user=%s msisdn=%s produk=%s metode=%s waktu=%s http_status=%s xl_status=%s",
            tx_id, trx_id_final, user_id, msisdn, produk_id, metode, scheduled_raw, http_status, xl_status
        )

        try:
            await notify_admin_and_user_on_success(
                setup, user_id, user_info, produk_nama, harga, msisdn, trx_id_final, metode, saldo_after,
                payment_link=payment_link,
                qr_string=qr_string,
                product_id=produk_id
            )
        except Exception:
            logger.exception("Failed to send success notifications for tx %s", tx_id)

        return

    # API failure -> refund etc.
    refunded_amount = 0
    if harga and harga > 0:
        try:
            update_user_saldo(user_id, harga)
            refunded_amount = harga
        except Exception:
            logger.exception("Failed to refund saldo for user %s after API failure for scheduled tx %s", user_id, tx_id)

    try:
        saldo_after = int((get_user(user_id) or {}).get("saldo", 0))
    except Exception:
        saldo_after = 0

    try:
        refund_trx_id = f"refund_{tx_id}_{int(datetime.utcnow().timestamp())}"
        insert_riwayat(
            user_id=str(user_id),
            msisdn=msisdn,
            produk_id=produk_id,
            produk_nama=produk_nama,
            kategori=tx.get("kategori", "-"),
            harga_jual=harga,
            metode_pembayaran=metode,
            amount_charged=0,
            saldo_tersisa=saldo_after,
            trx_id=refund_trx_id,
            status="failed",
            keterangan=f"Refund karena API gagal saat mengeksekusi transaksi terjadwal id={tx_id}; pesan API: {xl_message or xl_description or result.get('error')}"
        )
    except Exception:
        logger.exception("Failed to insert riwayat refund for API-failed scheduled tx %s", tx_id)

    try:
        update_status(tx_id, "failed")
    except Exception:
        logger.exception("Failed to update scheduled tx status to failed for %s", tx_id)

    logger.info(
        "Scheduled tx %s: API failure -> marked failed and refunded user %s amount=%s trx=%s xl_status=%s xl_message=%s http_status=%s",
        tx_id, user_id, refunded_amount, trx_id_final, xl_status, xl_message, http_status
    )

    try:
        reason = result.get("error") or xl_message or xl_description or "Pembayaran gagal"
        await notify_admin_and_user_on_failure(
            setup, user_id, user_info, produk_nama, harga, msisdn, trx_id_final, metode, saldo_after,
            reason=reason, payment_link=payment_link, qr_string=qr_string, product_id=produk_id,
            prev_saldo=saldo_before, refunded_amount=refunded_amount, xl_message=xl_message or None
        )
    except Exception:
        logger.exception("Failed to send failure notifications for tx %s", tx_id)


_worker_task: Optional[asyncio.Task] = None


async def _process_due_loop(bot: AiogramBot, interval_seconds: int = 30):
    setup = _read_setup()
    admin_cfg = setup.get("admin") or {}
    admin_target = None
    if admin_cfg.get("userid"):
        admin_target = str(admin_cfg.get("userid"))
    elif admin_cfg.get("username"):
        admin_target = f"@{admin_cfg.get('username').lstrip('@')}"

    logger.info("Scheduled transactions processor started (interval_seconds=%s) using timezone Asia/Jakarta", interval_seconds)

    while True:
        try:
            try:
                from zoneinfo import ZoneInfo  # Python 3.9+
                now = datetime.now(ZoneInfo("Asia/Jakarta"))
                now_iso = now.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                try:
                    import pytz  # type: ignore
                    tz = pytz.timezone("Asia/Jakarta")
                    now = datetime.now(tz)
                    now_iso = now.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    now_iso = (datetime.utcnow() + timedelta(hours=7)).strftime("%Y-%m-%d %H:%M:%S")

            due = list_pending_due(now_iso)
            if due:
                logger.info("Found %s scheduled transactions due at %s (Asia/Jakarta)", len(due), now_iso)
                for tx in due:
                    try:
                        await _process_tx(bot, tx, admin_target)
                    except Exception:
                        logger.exception("Error processing scheduled tx %s", tx.get("id"))
        except Exception:
            logger.exception("Scheduled worker loop exception")
        await asyncio.sleep(interval_seconds)


def start_transaksi_processor(bot: AiogramBot, interval_seconds: int = 30):
    global _worker_task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()

    if _worker_task is None or _worker_task.done():
        _worker_task = loop.create_task(_process_due_loop(bot, interval_seconds))
        logger.info("Scheduled transactions processor task created: %s", _worker_task)
    else:
        logger.info("Scheduled transactions processor already running: %s", _worker_task)
    return _worker_task


def stop_transaksi_processor():
    global _worker_task
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        _worker_task = None
        logger.info("Scheduled transactions processor stopped")