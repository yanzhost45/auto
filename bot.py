from __future__ import annotations
import asyncio
import json
import os
import logging
import random
from typing import List, Optional

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from data.database import add_user
from models.users import init_db

# Ensure token.json exists (older code path)
TOKEN_PATH = os.path.join("core", "token.json")
if not os.path.exists(TOKEN_PATH):
    from api.ambil_token import ambil_token  # type: ignore
    ambil_token()

def load_token_admin():
    with open("core/setup.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    token = data["token"]
    admin = data.get("admin")
    return token, admin

BOT_TOKEN, ADMIN = load_token_admin()

# Initialize DB and admin user
init_db()
if ADMIN:
    try:
        add_user(ADMIN["userid"], ADMIN["username"], role="admin")
    except Exception:
        # logging removed per request
        pass

# Create bot and dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- Register routers ---
from handler.start import router as start_router
from handler.admin_set_user import router as admin_set_user_router
from handler.admin_set_produk import router as admin_set_produk_router
from handler.admin_set_bot import router as admin_set_bot_router
from setup.admin_daftar_user import router as admin_daftar_user_router
from setup.admin_tambah_user import router as admin_tambah_user_router
from setup.admin_edit_user import router as admin_edit_user_router
from setup.admin_hapus_user import router as admin_hapus_user_router
from setup.admin_edit_produk import router as admin_edit_produk_router
from setup.admin_daftar_produk import router as admin_daftar_produk_router
from setup.admin_hapus_produk import router as admin_hapus_produk_router
from setup.admin_perbarui_produk import router as admin_perbarui_produk_router
from setup.admin_bot_status import router as admin_bot_status_router
from setup.admin_set_cara_pembelian import router as admin_set_cara_pembelian_router
from setup.admin_set_cara_deposit import router as admin_set_cara_deposit_router
from setup.admin_kirim_notif import router as admin_kirim_notif_router
from handler.sidompul import router as sidompul_router
from handler.otp_login import router as otp_login_router
from handler.menu_login_xl import router as menu_login_xl_router
from handler.menu_login_xl_payment import router as menu_login_xl_payment
from handler.admin_deposit_api import router as admin_deposit_api_router
from handler.cara_pembelian_dan_deposit import router as cara_pembelian_dan_deposit_router
from handler.deposit_user import router as deposit_user_router
from handler.transaksi_terjadwal import router as transaksi_terjadwal_router
from handler.cek_pending_transaksi_terjadwal import router as cek_pending_transaksi_terjadwal_router

dp.include_router(admin_daftar_user_router)
dp.include_router(admin_tambah_user_router)
dp.include_router(admin_set_produk_router)
dp.include_router(admin_edit_user_router)
dp.include_router(admin_hapus_user_router)
dp.include_router(start_router)
dp.include_router(admin_set_user_router)
dp.include_router(admin_edit_produk_router)
dp.include_router(admin_daftar_produk_router)
dp.include_router(admin_hapus_produk_router)
dp.include_router(admin_perbarui_produk_router)
dp.include_router(admin_set_bot_router)
dp.include_router(admin_bot_status_router)
dp.include_router(admin_set_cara_pembelian_router)
dp.include_router(admin_set_cara_deposit_router)
dp.include_router(admin_kirim_notif_router)
dp.include_router(sidompul_router)
dp.include_router(otp_login_router)
dp.include_router(menu_login_xl_router)
dp.include_router(menu_login_xl_payment)
dp.include_router(admin_deposit_api_router)
dp.include_router(cara_pembelian_dan_deposit_router)
dp.include_router(deposit_user_router)
dp.include_router(transaksi_terjadwal_router)
dp.include_router(cek_pending_transaksi_terjadwal_router)
# ---------------------------------

from api.refresh_token import get_refresh_token, refresh_token_loop  # type: ignore
from api.ambil_produk import ambil_kategori_xl, ambil_produk_xl, simpan_produk_ke_db  # type: ignore
from models.produk_xl import init_db as init_produk_db  # type: ignore

# helper processor for scheduled transactions
from helper.transaksi_terjadwal import start_transaksi_processor, stop_transaksi_processor  # type: ignore

# Keep references to background tasks so we can cancel them on shutdown
_background_tasks: List[asyncio.Task] = []

# Basic logger for this module
logger = logging.getLogger("bot")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(h)
logger.setLevel(logging.INFO)


async def update_produk_xl_periodik():
    init_produk_db()
    from api.ambil_token import ambil_token  # type: ignore
    while True:
        try:
            try:
                get_refresh_token()
            except Exception:
                # attempt to re-fetch token if refresh fails
                ambil_token()
            kategori_list = ambil_kategori_xl()["data"]
            for kategori in kategori_list:
                produk_response = ambil_produk_xl(kategori)
                simpan_produk_ke_db(produk_response["data"])
        except Exception:
            # logging removed
            logger.exception("Error in update_produk_xl_periodik (ignored)")
        await asyncio.sleep(60 * 60 * 12)  # 12 jam


async def _on_shutdown():
    # logging removed
    # stop scheduled-transactions processor
    try:
        stop_transaksi_processor()
    except Exception:
        pass

    # cancel other background tasks we started
    for t in list(_background_tasks):
        try:
            if not t.done():
                t.cancel()
        except Exception:
            pass

    # Await cancellation with timeout
    for t in list(_background_tasks):
        try:
            await asyncio.wait_for(t, timeout=5.0)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    _background_tasks.clear()

    # try close bot resources cleanly
    try:
        sess = getattr(bot, "session", None)
        if sess:
            try:
                await sess.close()
            except Exception:
                pass
        try:
            await bot.close()
        except Exception:
            pass
    except Exception:
        pass


async def main():
    # start the long-running background maintenance tasks and keep references
    try:
        t_refresh = asyncio.create_task(refresh_token_loop(), name="refresh_token_loop")
        _background_tasks.append(t_refresh)
    except Exception:
        logger.exception("Failed to start refresh_token_loop (ignored)")

    try:
        t_update_produk = asyncio.create_task(update_produk_xl_periodik(), name="update_produk_xl_periodik")
        _background_tasks.append(t_update_produk)
    except Exception:
        logger.exception("Failed to start update_produk_xl_periodik (ignored)")

    # start scheduled-transactions processor here while event loop is running
    try:
        task_trans = start_transaksi_processor(bot)
        if task_trans:
            _background_tasks.append(task_trans)
    except Exception:
        logger.exception("Failed to start transaksi processor (ignored)")

    # start periodic backup loop (runs immediately then every 6 hours by default)
    try:
        from tasks.backup_database_to_drive import start_backup_loop  # type: ignore
        t_backup = start_backup_loop(bot)
        _background_tasks.append(t_backup)
    except Exception:
        logger.exception("Failed to start backup loop (ignored)")

    # Resilient polling loop: don't let transient network errors stop the whole process.
    # Use exponential backoff with jitter on failures.
    backoff = 1.0
    max_backoff = 300.0
    while True:
        try:
            logger.info("Starting polling (this call blocks until stopped or fails)")
            # start_polling will run until shutdown or raises; it will call on_shutdown when stopping normally
            await dp.start_polling(bot, on_shutdown=_on_shutdown)
            # If start_polling returned normally, break the loop and finish
            logger.info("Polling finished normally, exiting polling loop")
            break
        except asyncio.CancelledError:
            # allow cancellation to propagate so shutdown can proceed
            logger.info("Polling task cancelled, exiting")
            raise
        except Exception as exc:
            # Log and keep the process alive; retry after backoff
            logger.exception("Polling failed with exception (will retry after backoff): %s", exc)
            # attempt a graceful small delay with jitter
            sleep_for = min(max_backoff, backoff) + random.uniform(0, 1.0)
            logger.info("Waiting %.1f seconds before retrying polling", sleep_for)
            try:
                await asyncio.sleep(sleep_for)
            except asyncio.CancelledError:
                logger.info("Sleep cancelled during polling retry, exiting")
                raise
            # exponential backoff increase
            backoff = min(max_backoff, backoff * 2.0)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # logging removed per request
        pass