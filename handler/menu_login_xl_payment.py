from aiogram import Router, F, Bot as AiogramBot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputFile
from aiogram.fsm.context import FSMContext
from data.database import get_produk_detail, get_user, update_user_saldo
from sessions import sessions
from html import escape
import re
import io
import os
import json
import logging
import tempfile
import aiohttp

# API payment settlement
from api.xl_payment import xl_payment_settlement

# Tambah qrcode
import qrcode

# Import riwayat transaksi
from models.riwayat_transaksi import insert_riwayat

logger = logging.getLogger(__name__)
router = Router()

PAYMENT_METHODS = [
    ("BALANCE", "Pulsa"),
    ("DANA", "DANA"),
    ("GOPAY", "GoPay"),
    ("SHOPEEPAY", "ShopeePay"),
    ("QRIS", "QRIS"),
]

def make_pulsa_msg(session_data):
    msisdn = session_data.get("msisdn", "-")
    saldo = session_data.get("saldo", "-")
    expired = session_data.get("expired", "-")
    return (
        f"💰 <b>Info Pulsa XL</b>\n"
        f"• Nomor: <code>{escape(msisdn)}</code>\n"
        f"• Sisa Pulsa: <b>{escape(str(saldo))}</b>\n"
        f"• Expired: <code>{escape(str(expired))}</code>\n"
    )

def get_product_detail_keyboard(produk_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Beli", callback_data=f"choose_payment_{produk_id}")],
            [InlineKeyboardButton(text="⬅️ Kembali ke Kategori", callback_data="show_categories")]
        ]
    )

def get_payment_methods_keyboard(product_id):
    keyboard = []
    for code, label in PAYMENT_METHODS:
        keyboard.append([InlineKeyboardButton(text=label, callback_data=f"paymethod_{code}_{product_id}")])
    keyboard.append([InlineKeyboardButton(text="⬅️ Kembali ke Detail Produk", callback_data=f"product_{product_id}")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_confirm_payment_keyboard(method_code, product_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Konfirmasi Pembayaran", callback_data=f"confirm_payment_{method_code}_{product_id}")],
            [InlineKeyboardButton(text="⬅️ Kembali Pilih Metode", callback_data=f"choose_payment_{product_id}")]
        ]
    )

def read_setup():
    """
    Read core/setup.json and return dict with keys possibly: token, notifikasi, admin (dict)
    """
    try:
        setup_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "core", "setup.json")
        if not os.path.exists(setup_path):
            return {}
        with open(setup_path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception as e:
        logger.exception("Failed to read setup.json: %s", e)
        return {}

def insufficient_funds_keyboard(product_id):
    setup = read_setup()
    admin = (setup.get("admin") or {}) if isinstance(setup, dict) else {}
    keyboard = []
    if admin.get("username"):
        keyboard.append([InlineKeyboardButton(text="💳 Deposit via Admin", url=f"https://t.me/{admin['username']}")])
    elif admin.get("userid"):
        keyboard.append([InlineKeyboardButton(text="💳 Minta Deposit ke Admin", callback_data="contact_admin")])
    keyboard.append([InlineKeyboardButton(text="⬅️ Kembali Pilih Metode", callback_data=f"choose_payment_{product_id}")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def failure_with_xl_info_keyboard(product_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Kembali Pilih Metode", callback_data=f"choose_payment_{product_id}")]
        ]
    )

def success_return_to_methods_keyboard(product_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Kembali Pilih Metode", callback_data=f"choose_payment_{product_id}")]
        ]
    )


async def notify_admin_and_user_on_success(setup: dict, user_id: int, user_info: dict, produk_nama: str,
                                           harga: int, msisdn: str, trx_id: str, payment_method: str, saldo_akhir,
                                           payment_link: str = None, qr_string: str = None, product_id: str = None):
    """
    Robust notification:
    - Send text notifications via notification bot token (setup['notifikasi']) to admin and user.
    - If qr_string provided, upload QR image to both admin and user via Telegram Bot API using notif_token.
    - Handles admin provided as userid or username (fallback).
    - Only treat payment_link as URL if it's a valid http(s) URL; otherwise include raw QR data as text.
    """
    import urllib.parse

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
        logger.warning("No notification token configured in setup.json, skipping notifications.")
        return

    # normalize link: treat empty/'-'/'None' as None
    if payment_link and str(payment_link).strip() in ("", "-", "None", "null"):
        payment_link = None

    # determine whether payment_link is a real URL
    payment_link_is_url = is_http_url(payment_link)

    # admin target: prefer userid (numeric), else username (@username)
    admin_userid = admin.get("userid")
    admin_username = admin.get("username")
    admin_target = None
    if admin_userid:
        admin_target = str(admin_userid)
    elif admin_username:
        admin_target = f"@{admin_username.lstrip('@')}"

    # Prepare messages
    user_display = user_info.get("username") if user_info else "-"
    admin_msg = (
        f"🔔 <b>Notifikasi Transaksi Baru</b>\n"
        f"• User: @{escape(str(user_display))} (<code>{escape(str(user_id))}</code>)\n"
        f"• Produk: <b>{escape(produk_nama)}</b>\n"
        f"• Harga: <b>Rp{escape(str(harga))}</b>\n"
        f"• Metode: <b>{escape(payment_method)}</b>\n"
        f"• Nomor XL: <code>{escape(msisdn)}</code>\n"
        f"• ID Transaksi: <code>{escape(str(trx_id))}</code>\n"
        f"• Saldo user: <b>Rp{escape(str(saldo_akhir))}</b>\n"
    )
    user_msg = (
        f"🔔 <b>Transaksi Berhasil</b>\n"
        f"• Produk: <b>{escape(produk_nama)}</b>\n"
        f"• Harga: <b>Rp{escape(str(harga))}</b>\n"
        f"• Metode: <b>{escape(payment_method)}</b>\n"
        f"• ID Transaksi: <code>{escape(str(trx_id))}</code>\n"
        f"• Saldo tersisa: <b>Rp{escape(str(saldo_akhir))}</b>\n"
        f"Terima kasih telah bertransaksi."
    )

    # If payment_link is an actual http(s) URL, append as HTML anchor.
    # If payment_link exists but is NOT a URL (likely EMV QR payload), include it as raw code text instead.
    if payment_link:
        if payment_link_is_url:
            link_html = f"\n• Link Pembayaran: <a href=\"{escape(payment_link)}\">Klik di sini untuk membayar</a>\n"
            admin_msg += link_html
            user_msg += link_html
        else:
            # raw QR data (do not attempt to use as URL)
            admin_msg += f"\n• Data QRIS: <code>{escape(str(payment_link))}</code>\n"
            # optional: include for user too if desired (or omit to avoid exposing long payload)
            user_msg += f"\n• Data QRIS: <code>{escape(str(payment_link))}</code>\n"

    # Send text notifications via notification bot (Aiogram)
    try:
        async with AiogramBot(token=notif_token) as notif_bot:
            if admin_target:
                try:
                    await notif_bot.send_message(chat_id=admin_target, text=admin_msg, parse_mode="HTML", disable_web_page_preview=False)
                except Exception as e:
                    logger.exception("Failed to notify admin (text): %s", e)
            try:
                await notif_bot.send_message(chat_id=int(user_id), text=user_msg, parse_mode="HTML", disable_web_page_preview=False)
            except Exception as e:
                logger.exception("Failed to notify user (text): %s", e)
    except Exception as e:
        logger.exception("Notification bot failure (text): %s", e)

    # If there's no QR to send, we're done
    if not qr_string:
        return

    # Generate QR image
    try:
        qr_img = qrcode.make(qr_string)
    except Exception:
        logger.exception("Failed to generate QR image for notification")
        return

    # Write to temp file and upload via Telegram HTTP API (notif_token)
    buffer = io.BytesIO()
    tmp_path = None
    try:
        qr_img.save(buffer, format="PNG")
        buffer.seek(0)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(buffer.getvalue())
            tmp_path = tmp.name

        caption = (
            f"🧾 Scan QRIS untuk pembayaran:\n"
            f"• Produk: <b>{escape(produk_nama)}</b>\n"
            f"• Harga: <b>Rp{escape(str(harga))}</b>\n"
            f"• ID Transaksi: <code>{escape(str(trx_id))}</code>\n"
        )

        url = f"https://api.telegram.org/bot{notif_token}/sendPhoto"
        async with aiohttp.ClientSession() as session:
            # ADMIN upload (if admin_target present)
            if admin_target:
                try:
                    with open(tmp_path, "rb") as fh_admin:
                        form = aiohttp.FormData()
                        form.add_field("chat_id", str(admin_target))
                        form.add_field("caption", caption)
                        form.add_field("parse_mode", "HTML")
                        # only include reply_markup button if payment_link is a valid http(s) URL
                        if payment_link and payment_link_is_url:
                            form.add_field("reply_markup", json.dumps({"inline_keyboard": [[{"text": "Buka Link Pembayaran", "url": payment_link}]]}))
                        form.add_field("photo", fh_admin, filename="qris.png", content_type="image/png")
                        async with session.post(url, data=form, timeout=30) as resp_admin:
                            body = await resp_admin.text()
                            if resp_admin.status != 200:
                                logger.error("Upload QR to admin failed: %s %s", resp_admin.status, body)
                            else:
                                logger.debug("Upload QR to admin OK: %s", body)
                except Exception:
                    logger.exception("Exception while uploading QR to admin")

            # USER upload
            try:
                with open(tmp_path, "rb") as fh_user:
                    form = aiohttp.FormData()
                    form.add_field("chat_id", str(user_id))
                    form.add_field("caption", caption)
                    form.add_field("parse_mode", "HTML")
                    if payment_link and payment_link_is_url:
                        form.add_field("reply_markup", json.dumps({"inline_keyboard": [[{"text": "Buka Link Pembayaran", "url": payment_link}]]}))
                    form.add_field("photo", fh_user, filename="qris.png", content_type="image/png")
                    async with session.post(url, data=form, timeout=30) as resp_user:
                        body = await resp_user.text()
                        if resp_user.status != 200:
                            logger.error("Upload QR to user failed: %s %s", resp_user.status, body)
                        else:
                            logger.debug("Upload QR to user OK: %s", body)
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

def _deep_find_value(obj, target_keys):
    """
    Recursively search obj (dict/list) for any of keys in target_keys (case-insensitive).
    Return a dict mapping found key -> value for the first dictionary that contains any of them.
    If a JSON string is encountered, try to parse and continue searching.
    """
    if obj is None:
        return {}

    # If it's a JSON string, try parse
    if isinstance(obj, str):
        s = obj.strip()
        if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
            try:
                parsed = json.loads(s)
                return _deep_find_value(parsed, target_keys)
            except Exception:
                return {}

    if isinstance(obj, dict):
        # check current dict for any target keys
        lower_map = {k.lower(): k for k in obj.keys()}
        found = {}
        for tk in target_keys:
            # search insensitive
            for candidate_lower, orig_key in lower_map.items():
                if candidate_lower == tk.lower():
                    found[tk] = obj.get(orig_key)
        if found:
            return found
        # otherwise recurse into values
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

    # other types
    return {}


def _extract_xl_fields(result: dict, data: dict):
    """
    Robust extractor: search result and data recursively for xl fields.
    Returns (xl_status, xl_code_detail, xl_description, xl_message, trx_id)
    """
    target_keys = [
        "xl_status", "xl_code_detail", "xl_code",
        "xl_description", "xl_title", "xl_message",
        "trx_id", "transaction_id", "transactionId"
    ]

    # Try search in data first, then whole result
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

    # Normalize values
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


@router.callback_query(F.data.regexp(r"^product_(.+)$"))
async def show_product_detail(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    match = re.match(r"^product_(.+)$", callback.data)
    if not match:
        await callback.message.edit_text("❗️ Produk tidak valid.", parse_mode="HTML")
        return
    produk_id = match.group(1)
    product = get_produk_detail(produk_id)
    if not product:
        await callback.message.edit_text(
            "❗️ Produk tidak ditemukan atau sudah tidak aktif.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Kembali ke Kategori", callback_data="show_categories")]
                ]
            )
        )
        return
    kategori = product.get("kategori", "-")
    session_data = sessions.get(user_id)
    pulsa_msg = make_pulsa_msg(session_data)
    text = (
        pulsa_msg +
        f"\n\n🛒 <b>{escape(product['nama_produk'])}</b>\n"
        f"Kategori: <b>{escape(kategori)}</b>\n"
        f"Harga: <b>Rp{escape(str(product['harga_jual']))}</b>\n"
        f"Deskripsi: {escape(product.get('deskripsi','-'))}\n"
    )
    await callback.message.edit_text(
        text, parse_mode="HTML",
        reply_markup=get_product_detail_keyboard(produk_id)
    )

@router.callback_query(F.data.regexp(r"^choose_payment_(.+)$"))
async def choose_payment_method(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    match = re.match(r"^choose_payment_(.+)$", callback.data)
    if not match:
        await callback.message.edit_text("❗️ Produk tidak valid.", parse_mode="HTML")
        return
    product_id = match.group(1)
    session_data = sessions.get(user_id)
    product = get_produk_detail(product_id)
    if not product:
        await callback.message.edit_text("❗️ Produk tidak ditemukan atau sudah tidak aktif.", parse_mode="HTML")
        return

    pulsa_msg = make_pulsa_msg(session_data)
    text = (
        pulsa_msg +
        f"\n\n💳 <b>Pilih Metode Pembayaran</b> untuk <b>{escape(product['nama_produk'])}</b>:\n"
        f"Harga: <b>Rp{escape(str(product['harga_jual']))}</b>\n"
    )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=get_payment_methods_keyboard(product_id)
    )

@router.callback_query(F.data.regexp(r"^paymethod_([A-Z]+)_(.+)$"))
async def confirm_payment_screen(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    match = re.match(r"^paymethod_([A-Z]+)_(.+)$", callback.data)
    if not match:
        await callback.message.edit_text("❗️ Data pembayaran tidak valid.", parse_mode="HTML")
        return
    method_code = match.group(1)
    product_id = match.group(2)

    session_data = sessions.get(user_id)
    product = get_produk_detail(product_id)
    if not product:
        await callback.message.edit_text("❗️ Produk tidak ditemukan atau sudah tidak aktif.", parse_mode="HTML")
        return

    method_label = next((label for code, label in PAYMENT_METHODS if code == method_code), method_code)
    pulsa_msg = make_pulsa_msg(session_data)
    text = (
        pulsa_msg +
        f"\n\n<b>Konfirmasi Pembayaran</b>\n"
        f"Produk: <b>{escape(product['nama_produk'])}</b>\n"
        f"Harga: <b>Rp{escape(str(product['harga_jual']))}</b>\n"
        f"Metode: <b>{escape(method_label)}</b>\n\n"
        f"Tekan <b>Konfirmasi</b> untuk melanjutkan pembayaran."
    )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=get_confirm_payment_keyboard(method_code, product_id)
    )

@router.callback_query(F.data.regexp(r"^confirm_payment_([A-Z]+)_(.+)$"))
async def confirm_payment_action(callback: CallbackQuery, state: FSMContext):
    match = re.match(r"^confirm_payment_([A-Z]+)_(.+)$", callback.data)
    if not match:
        await callback.message.edit_text("❗️ Data pembayaran tidak valid.", parse_mode="HTML")
        return

    method_code = match.group(1)
    product_id = match.group(2)

    user_id = callback.from_user.id
    session_data = sessions.get(user_id)
    msisdn = session_data.get("msisdn")
    if not msisdn:
        await callback.message.edit_text("❗️ Nomor XL tidak ditemukan di sesi.", parse_mode="HTML")
        return

    produk = get_produk_detail(product_id)
    if not produk:
        await callback.message.edit_text("❗️ Produk tidak ditemukan.", parse_mode="HTML")
        return
    produk_nama = produk.get("nama_produk", "-")
    kategori = produk.get("kategori", "-")
    harga_jual = produk.get("harga_jual", 0)
    amount = harga_jual

    # Ambil saldo user TERBARU dari database
    user_db = get_user(user_id)
    saldo_tersisa = user_db["saldo"] if user_db and "saldo" in user_db else 0

    # Cek saldo user
    if saldo_tersisa < harga_jual:
        await callback.message.edit_text(
            f"❗️ Saldo Anda tidak cukup untuk melakukan transaksi ini.\n"
            f"Saldo: <b>Rp{escape(str(saldo_tersisa))}</b> | Harga: <b>Rp{escape(str(harga_jual))}</b>",
            parse_mode="HTML",
            reply_markup=insufficient_funds_keyboard(product_id)
        )
        return

    await callback.message.edit_text("<b>Memproses pembayaran ...</b>", parse_mode="HTML")
    result = xl_payment_settlement(
        produk_id=product_id,
        msisdn=msisdn,
        metode_pembayaran=method_code
    )

    data = result.get("data") or {}
    trx_id = data.get("trx_id") or data.get("transaction_id", "-")
    payment_method = data.get("payment_method", method_code)
    payment_link = data.get("link_pembayaran")
    deeplink = (data.get("payment_info", {}) or {}).get("deeplink")
    xl_status = (data.get("xl_status") or "").upper()

    # Determine final success: response success flag AND xl_status == SUCCESS (if xl_status provided)
    api_success_flag = bool(result.get("success"))
    if data.get("xl_status") is not None and data.get("xl_status") != "":
        api_success_flag = api_success_flag and (xl_status == "SUCCESS")

    # Status transaksi for storage
    status_trx = "success" if api_success_flag else "failed"
    keterangan = result.get("message") or result.get("error") or None

    # Jika transaksi berhasil menurut API (mempertimbangkan xl_status jika ada), potong saldo user
    saldo_akhir = saldo_tersisa
    if api_success_flag:
        try:
            update_user_saldo(user_id, -harga_jual)  # potong saldo
        except Exception:
            # jangan crash jika update gagal, tetap lanjutkan dan catat keterangan
            keterangan = (keterangan or "") + " | failed to update user saldo"
            logger.exception("Failed to update user saldo for user %s", user_id)
        # Ambil saldo terbaru user
        user_db_after = get_user(user_id)
        saldo_akhir = user_db_after["saldo"] if user_db_after and "saldo" in user_db_after else saldo_tersisa

    # Simpan riwayat transaksi (selalu simpan, sukses atau gagal)
    insert_riwayat(
        user_id=str(user_id),
        msisdn=msisdn,
        produk_id=product_id,
        produk_nama=produk_nama,
        kategori=kategori,
        harga_jual=harga_jual,
        metode_pembayaran=payment_method,
        amount_charged=amount,
        saldo_tersisa=saldo_akhir,
        trx_id=trx_id,
        status=status_trx,
        keterangan=keterangan
    )

    # read setup for notifications
    setup = read_setup()

    # --- lanjutkan flow tampilan ---
    # Jika sukses dan metode BALANCE -> tampilkan sukses dan kirim notifikasi
    if api_success_flag and payment_method == "BALANCE":
        msg = (
            f"<b>✅ Pembayaran berhasil!</b>\n"
            f"• Nomor: <code>{escape(msisdn)}</code>\n"
            f"• Produk: <b>{escape(produk_nama)}</b>\n"
            f"• Harga: <b>Rp{escape(str(amount))}</b>\n"
            f"• Saldo tersisa: <b>Rp{escape(str(saldo_akhir))}</b>\n"
            f"• ID Transaksi: <code>{escape(str(trx_id))}</code>\n"
            f"Silakan cek status transaksi di menu utama."
        )
        # send notification to admin and user (notification bot)
        try:
            await notify_admin_and_user_on_success(
                setup=setup,
                user_id=user_id,
                user_info=user_db,
                produk_nama=produk_nama,
                harga=amount,
                msisdn=msisdn,
                trx_id=trx_id,
                payment_method=payment_method,
                saldo_akhir=saldo_akhir,
                payment_link=None,
                qr_string=None,
                product_id=product_id
            )
        except Exception:
            logger.exception("Failed while sending notifications after successful transaction.")
        # include button to go back to payment methods
        await callback.message.edit_text(msg, parse_mode="HTML", reply_markup=success_return_to_methods_keyboard(product_id))
        return

    # Jika sukses dan metode eksternal -> tampilkan link (tambahkan tombol kembali ke metode)
    if api_success_flag and payment_method in ("DANA", "GOPAY", "SHOPEEPAY"):
        link = payment_link or deeplink or "-"
        method_show = payment_method
        msg = (
            f"<b>🔗 Silakan lanjutkan pembayaran via {escape(method_show)}:</b>\n"
            f"• Produk: <b>{escape(produk_nama)}</b>\n"
            f"• Nomor: <code>{escape(msisdn)}</code>\n"
            f"• Harga: <b>Rp{escape(str(amount))}</b>\n"
            f"• <a href=\"{escape(link)}\">Klik di sini untuk membayar</a>\n"
            f"• ID Transaksi: <code>{escape(str(trx_id))}</code>\n"
            f"Jika sudah membayar, cek status transaksi di menu utama."
        )
        # send notification to admin and user (notification bot)
        try:
            await notify_admin_and_user_on_success(
                setup=setup,
                user_id=user_id,
                user_info=user_db,
                produk_nama=produk_nama,
                harga=amount,
                msisdn=msisdn,
                trx_id=trx_id,
                payment_method=payment_method,
                saldo_akhir=saldo_akhir,
                payment_link=link,
                qr_string=None,
                product_id=product_id
            )
        except Exception:
            logger.exception("Failed while sending notifications after successful transaction.")
        await callback.message.edit_text(msg, parse_mode="HTML", disable_web_page_preview=False,
                                         reply_markup=success_return_to_methods_keyboard(product_id))
        return

    # --- QRIS sending ---
    if api_success_flag and payment_method == "QRIS":
        qr_string = payment_link or deeplink
        if not qr_string:
            await callback.message.edit_text("❗️ QR string tidak ditemukan.", parse_mode="HTML")
            return

        try:
            qr_img = qrcode.make(qr_string)  # requires Pillow
        except Exception as e:
            logger.exception("Failed to generate QR image: %s", e)
            await callback.message.edit_text("❗️ Gagal membuat QR. Silakan hubungi admin.", parse_mode="HTML")
            return

        buffer = io.BytesIO()
        tmp_path = None
        try:
            # Tulis image ke buffer lalu file sementara
            qr_img.save(buffer, format="PNG")
            buffer.seek(0)

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp.write(buffer.getvalue())
                tmp_path = tmp.name

            caption = (
                f"<b>🧾 Scan QRIS untuk pembayaran:</b>\n"
                f"• Produk: <b>{escape(produk_nama)}</b>\n"
                f"• Nomor: <code>{escape(msisdn)}</code>\n"
                f"• Harga: <b>Rp{escape(str(amount))}</b>\n"
                f"• ID Transaksi: <code>{escape(str(trx_id))}</code>\n"
                f"Jika sudah membayar, paket akan otomatis aktif."
            )
            qr_for_notify = payment_link or deeplink
            try:
                await notify_admin_and_user_on_success(
                    setup=setup,
                    user_id=user_id,
                    user_info=user_db,
                    produk_nama=produk_nama,
                    harga=amount,
                    msisdn=msisdn,
                    trx_id=trx_id,
                    payment_method=payment_method,
                    saldo_akhir=saldo_akhir,
                    payment_link=payment_link or deeplink,
                    qr_string=qr_for_notify,
                    product_id=product_id
                )
            except Exception:
                logger.exception("Failed while sending notifications (QRIS) after successful transaction.")

            # NEW BEHAVIOR: send photo FIRST WITHOUT any inline buttons, then send a SEPARATE text message containing details + back button.
            bot_token = getattr(callback.bot, "token", None)
            if not bot_token:
                logger.error("Bot token not available on callback.bot")
                await callback.message.answer("❗️ Gagal mengirim QR (token tidak tersedia).", parse_mode="HTML")
                return

            url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"

            # 1) upload photo WITHOUT reply_markup so the image has no inline buttons
            async with aiohttp.ClientSession() as session:
                with open(tmp_path, "rb") as fh:
                    data = aiohttp.FormData()
                    data.add_field("chat_id", str(callback.message.chat.id))
                    data.add_field("caption", "QRIS (scan untuk membayar)")
                    data.add_field("parse_mode", "HTML")
                    # DO NOT add reply_markup here
                    data.add_field("photo", fh, filename="qris.png", content_type="image/png")

                    try:
                        async with session.post(url, data=data, timeout=30) as resp:
                            text = await resp.text()
                            if resp.status != 200:
                                logger.exception("Telegram upload failed: %s %s", resp.status, text)
                                await callback.message.answer("❗️ Gagal mengirim QR. Silakan hubungi admin.", parse_mode="HTML")
                            else:
                                logger.debug("QR uploaded OK: %s", text)
                    except Exception as e:
                        logger.exception("Exception while uploading QR to Telegram: %s", e)
                        await callback.message.answer("❗️ Gagal mengirim QR (jaringan). Silakan hubungi admin.", parse_mode="HTML")
                        # still attempt to send text message so user has info/buttons below

            # 2) send a separate text message with the caption details and the "Kembali Pilih Metode" button
            try:
                await callback.message.reply(caption, parse_mode="HTML", reply_markup=success_return_to_methods_keyboard(product_id))
            except Exception:
                logger.exception("Failed to send QR info text message (will try edit_text fallback)")
                try:
                    await callback.message.edit_text(caption, parse_mode="HTML", reply_markup=success_return_to_methods_keyboard(product_id))
                except Exception:
                    logger.exception("Fallback failed to display QR text message")

            return

        finally:
            try:
                buffer.close()
            except Exception:
                pass
            try:
                if tmp_path and os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                logger.exception("Failed to remove temporary QR file")

    # --- FAILURE BRANCH: extract xl fields robustly and display them ---
    data = result.get("data") or {}
    xl_status, xl_code_detail, xl_description, xl_message, trx_id_extracted = _extract_xl_fields(result, data)

    # prefer trx_id previously parsed (from data) else extracted
    trx_id_display = trx_id if trx_id and trx_id != "-" else (trx_id_extracted or "-")

    text = (
        f"❗️ <b>Pembayaran gagal</b>\n"
        f"• Produk: <b>{escape(produk_nama)}</b>\n"
        f"• Nomor: <code>{escape(msisdn)}</code>\n"
        f"• Harga: <b>Rp{escape(str(amount))}</b>\n"
        f"• ID Transaksi: <code>{escape(str(trx_id_display))}</code>\n\n"
        f"<b>Detail XL</b>\n"
        f"• message: {escape(str(xl_message) or '-')}\n\n"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=failure_with_xl_info_keyboard(product_id))