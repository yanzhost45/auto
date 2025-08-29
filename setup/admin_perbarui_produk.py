from aiogram import Router, F
from aiogram.types import CallbackQuery
from button.admin_set_produk import get_admin_set_produk_keyboard
from api.ambil_produk import ambil_kategori_xl, ambil_produk_xl, simpan_produk_ke_db
from models.produk_xl import get_produk_by_kategori as get_produk_db_by_kategori

router = Router()

def perbarui_semua_produk_xl():
    """
    Ambil semua kategori dari API, ambil semua produk per kategori, lalu simpan ke DB.
    Bandingkan dengan data sebelumnya dan tampilkan ringkasan perubahan.
    """
    summary = []
    kategori_list = ambil_kategori_xl().get("data", [])
    total_produk_awal = 0
    total_produk_akhir = 0
    perubahan_semua = []

    for kategori in kategori_list:
        # Produk sebelum update
        db_produk = {str(row[0]): row[1] for row in get_produk_db_by_kategori(kategori)}
        produk_awal = set(db_produk.keys())

        # Produk dari API
        api_produk = ambil_produk_xl(kategori).get("data", [])
        api_produk_dict = {str(prod['id']): prod['nama_produk'] for prod in api_produk}
        produk_akhir = set(api_produk_dict.keys())

        # Simpan ke DB
        simpan_produk_ke_db(api_produk)

        # Hitung perubahan
        baru = produk_akhir - produk_awal
        hilang = produk_awal - produk_akhir

        perubahan = []
        if baru:
            perubahan.append("➕ Baru: " + ", ".join([f"{api_produk_dict[i]} (ID:{i})" for i in baru]))
        if hilang:
            perubahan.append("❌ Dihapus: " + ", ".join([f"{db_produk[i]} (ID:{i})" for i in hilang]))
        if not perubahan:
            perubahan.append("✅ Tidak ada perubahan data produk.")

        summary.append(
            f"Kategori <b>{kategori}</b>:\n"
            f"• Sebelum: {len(produk_awal)} produk, Sesudah: {len(produk_akhir)} produk\n"
            + "\n".join(perubahan)
        )
        total_produk_awal += len(produk_awal)
        total_produk_akhir += len(produk_akhir)
        perubahan_semua.extend(perubahan)

    header = (f"<b>Perbarui produk selesai.</b>\n"
              f"Total kategori: <b>{len(kategori_list)}</b>\n"
              f"Total produk sebelum: <b>{total_produk_awal}</b>\n"
              f"Total produk sesudah: <b>{total_produk_akhir}</b>\n")
    return header + "\n\n" + "\n\n".join(summary)
    
@router.callback_query(F.data == "perbarui_produk")
async def handle_perbarui_produk(callback: CallbackQuery):
    msg = await callback.message.edit_text("Memperbarui produk, mohon tunggu...")
    try:
        result = perbarui_semua_produk_xl()
    except Exception as e:
        await msg.edit_text(f"Gagal memperbarui produk:\n{e}", reply_markup=get_admin_set_produk_keyboard())
        await callback.answer()
        return
    await msg.edit_text(result, parse_mode="HTML", reply_markup=get_admin_set_produk_keyboard())
    await callback.answer()