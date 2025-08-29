from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from api.cek_pulsa import cek_pulsa_xl
from api.cek_kuota import cek_kuota_xl
from data.database import get_all_kategori, get_produk_by_kategori, get_produk_detail, get_user
from html import escape
from sessions import sessions
import typing

router = Router()

def get_back_keyboard(role="user"):
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

def get_daftar_produk_keyboard(role="user"):
    if role == "admin":
        kembali_btn = [InlineKeyboardButton(text="⬅️ Kembali ke Menu Admin", callback_data="back_to_admin_menu")]
    else:
        kembali_btn = [InlineKeyboardButton(text="⬅️ Kembali ke Menu Utama", callback_data="back_to_user_menu")]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Daftar Produk", callback_data="show_categories")],
            kembali_btn
        ]
    )

def get_category_keyboard(categories):
    keyboard = []
    # defensive: ensure categories is iterable
    if not categories:
        categories = []
    for cat in categories:
        keyboard.append([InlineKeyboardButton(text=cat, callback_data=f"category_{escape(cat)}")])
    keyboard.append([InlineKeyboardButton(text="⬅️ Kembali", callback_data="go_to_login")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_products_keyboard(products, kategori):
    keyboard = []
    # defensive: ensure products is iterable
    if not products:
        products = []
    for prod in products:
        # prod expected like (id, nama)
        keyboard.append([InlineKeyboardButton(
            text=f"{prod[1]}", callback_data=f"product_{prod[0]}")])
    keyboard.append([InlineKeyboardButton(text="⬅️ Kembali", callback_data=f"show_categories")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_product_detail_keyboard(produk_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Beli", callback_data=f"choose_payment_{produk_id}")],
            [InlineKeyboardButton(text="⬅️ Kembali ke Kategori", callback_data="show_categories")]
        ]
    )

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

def _render_kuota_from_api_data(data: dict) -> str:
    """
    Render kuota message safely from API data structure.
    The API structure may vary; this function defends against None and unexpected types.
    """
    kuota_msg = "📶 <b>Info Kuota XL</b>\n"
    if not isinstance(data, dict):
        return kuota_msg + "• Data kuota tidak tersedia.\n"

    kuota_msg += f"• Last Update: <code>{escape(str(data.get('lastUpdate', '-')))}</code>\n"

    package_info = data.get("packageInfo") or []
    # package_info might be a nested list, a dict, or empty/None.
    if not package_info:
        kuota_msg += "• Tidak ada paket aktif.\n"
        return kuota_msg

    kuota_msg += "• Paket Aktif:\n"
    # Normalize package_info to a list of groups
    if isinstance(package_info, dict):
        groups = [package_info]
    elif isinstance(package_info, list):
        groups = package_info
    else:
        # Unexpected type
        return kuota_msg + "• Format packageInfo tidak dikenali.\n"

    for package_group in groups:
        # package_group might itself be a list or dict
        items = []
        if isinstance(package_group, list):
            items = package_group
        elif isinstance(package_group, dict):
            # sometimes the API returns dict with keys being packages
            # attempt to find list-like values
            # Common expected structure: package_group -> list of package entries, but defend
            # We'll try to extract any iterable values inside dict
            possible = []
            for v in package_group.values():
                if isinstance(v, list):
                    possible.extend(v)
            if possible:
                items = possible
            else:
                # treat the dict itself as a single package entry
                items = [package_group]
        else:
            # skip unexpected group
            continue

        for package in items:
            if not isinstance(package, dict):
                continue
            # package may contain 'packages' key or be the package itself
            pkg = package.get("packages") or package.get("package") or package or {}
            # benefits can be None or list; normalize to list
            benefits = package.get("benefits") if "benefits" in package else (pkg.get("benefits") if isinstance(pkg, dict) else None)
            if benefits is None:
                benefits = []
            # pkg may not be dict
            pkg_name = "-"
            pkg_exp = "-"
            if isinstance(pkg, dict):
                pkg_name = pkg.get("name", "-")
                pkg_exp = pkg.get("expDate", "-")
            kuota_msg += f"  - <b>{escape(str(pkg_name))}</b> (Exp: {escape(str(pkg_exp))} )\n"

            # benefits may be list of dicts or dict of dicts
            if isinstance(benefits, dict):
                # convert to list of benefit entries
                benefits_iter = list(benefits.values())
            elif isinstance(benefits, list):
                benefits_iter = benefits
            else:
                benefits_iter = [benefits]

            for b in benefits_iter:
                if not isinstance(b, dict):
                    # try to render simple values
                    kuota_msg += f"    • {escape(str(b))}\n"
                    continue
                emoji = "🌐" if b.get("type", "") == "DATA" else "⭐️"
                bname = b.get("bname") or b.get("name") or "-"
                remaining = b.get("remaining", "-")
                quota = b.get("quota", "-")
                kuota_msg += f"    {emoji} {escape(str(bname))}: {escape(str(remaining))} / {escape(str(quota))}\n"
            kuota_msg += "    ────────────────\n"

    return kuota_msg

async def show_menu_login_xl(message_or_callback, state: FSMContext, msisdn, role="user"):
    # Cek pulsa dan kuota
    pulsa_result = cek_pulsa_xl(msisdn)
    if pulsa_result.get("success"):
        pulsa_info = pulsa_result.get("data") or {}
        # defensive access
        saldo = pulsa_info.get("remaining_balance") or pulsa_result.get("remaining_balance") or "-"
        expired = pulsa_info.get("expired_at") or pulsa_result.get("expired_at") or "-"
    else:
        saldo = "-"
        expired = "-"

    kuota_result = cek_kuota_xl(msisdn)
    if kuota_result.get("success"):
        # API may return multiple shapes, use helper to render safely
        data = kuota_result.get("result", {}) or {}
        data_payload = data.get("data") or data  # sometimes result is the data itself
        kuota_msg = _render_kuota_from_api_data(data_payload)
    else:
        kuota_msg = f"❗️ Gagal cek kuota: <code>{escape(str(kuota_result.get('error','-')))}</code>\n"

    # Simpan KE SESSIONS!
    # message_or_callback can be Message or CallbackQuery; unify
    if hasattr(message_or_callback, "from_user"):
        user_id = message_or_callback.from_user.id
    else:
        # callback query object
        user_id = message_or_callback.message.from_user.id

    sessions.update(user_id, {"msisdn": msisdn, "saldo": saldo, "expired": expired, "role": role})

    pulsa_msg = make_pulsa_msg(sessions.get(user_id))
    text = pulsa_msg + "\n" + kuota_msg + "\n\n🛒 <b>Ingin cek produk?</b>"
    markup = get_daftar_produk_keyboard(role)

    # send reply depending on object type
    if hasattr(message_or_callback, "answer"):
        await message_or_callback.answer(
            text, parse_mode="HTML",
            reply_markup=markup
        )
    else:
        await message_or_callback.message.answer(
            text, parse_mode="HTML",
            reply_markup=markup
        )

@router.callback_query(F.data == "show_categories")
async def show_categories(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    session_data = sessions.get(user_id)
    msisdn = session_data.get("msisdn")
    role = session_data.get("role", "user")
    if not msisdn:
        await callback.message.edit_text(
            "Nomor XL tidak ditemukan di sesi.\nSilakan login ulang!",
            parse_mode="HTML",
            reply_markup=get_back_keyboard(role)
        )
        return

    # Hanya cek pulsa (TANPA cek kuota)
    pulsa_result = cek_pulsa_xl(msisdn)
    if pulsa_result.get("success"):
        pulsa_info = pulsa_result.get("data") or {}
        saldo = pulsa_info.get("remaining_balance") or pulsa_result.get("remaining_balance") or "-"
        expired = pulsa_info.get("expired_at") or pulsa_result.get("expired_at") or "-"
    else:
        saldo = "-"
        expired = "-"

    # Update sessions
    sessions.update(user_id, {"msisdn": msisdn, "saldo": saldo, "expired": expired, "role": role})

    pulsa_msg = make_pulsa_msg(sessions.get(user_id))
    categories = get_all_kategori() or []
    await callback.message.edit_text(
        pulsa_msg + "\n\n📦 <b>Pilih Kategori Produk</b>:",
        parse_mode="HTML",
        reply_markup=get_category_keyboard(categories)
    )

@router.callback_query(F.data.regexp(r"^category_(.+)$"))
async def show_products_by_category(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    kategori = callback.data.split("_", 1)[1]
    products = get_produk_by_kategori(kategori) or []
    session_data = sessions.get(user_id)
    pulsa_msg = make_pulsa_msg(session_data)
    await callback.message.edit_text(
        pulsa_msg + f"\n\n🛍️ <b>Daftar Produk {escape(kategori)}</b>:",
        parse_mode="HTML",
        reply_markup=get_products_keyboard(products, kategori)
    )

@router.callback_query(F.data.regexp(r"^product_(.+)$"))
async def show_product_detail(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    produk_id = callback.data.split("_", 1)[1]
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
        reply_markup=get_product_detail_keyboard(produk_id)  # <-- penting, pass produk_id, bukan kategori
    )

@router.callback_query(F.data == "go_to_login")
async def menu_login_xl_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user = get_user(user_id)
    role = user["role"] if user else "user"
    session_data = sessions.get(user_id)
    msisdn = session_data.get("msisdn")
    if not msisdn:
        await callback.message.edit_text(
            "Nomor XL tidak ditemukan di sesi.\nSilakan login ulang!",
            parse_mode="HTML",
            reply_markup=get_back_keyboard(role)
        )
        sessions.clear(user_id)
        return

    # Di sini tampilkan pulsa + kuota (cek ulang)
    pulsa_result = cek_pulsa_xl(msisdn)
    if pulsa_result.get("success"):
        pulsa_info = pulsa_result.get("data") or {}
        saldo = pulsa_info.get("remaining_balance") or pulsa_result.get("remaining_balance") or "-"
        expired = pulsa_info.get("expired_at") or pulsa_result.get("expired_at") or "-"
    else:
        saldo = "-"
        expired = "-"

    kuota_result = cek_kuota_xl(msisdn)
    if kuota_result.get("success"):
        data = kuota_result.get("result", {}) or {}
        data_payload = data.get("data") or data
        kuota_msg = _render_kuota_from_api_data(data_payload)
    else:
        kuota_msg = f"❗️ Gagal cek kuota: <code>{escape(str(kuota_result.get('error','-')))}</code>\n"

    # Update sesi
    sessions.update(user_id, {"msisdn": msisdn, "saldo": saldo, "expired": expired, "role": role})

    pulsa_msg = make_pulsa_msg(sessions.get(user_id))
    text = pulsa_msg + "\n" + kuota_msg + "\n\n🛒 <b>Ingin cek produk?</b>"
    markup = get_daftar_produk_keyboard(role)

    await callback.message.edit_text(
        text, parse_mode="HTML",
        reply_markup=markup
    )