from __future__ import annotations
import os
import json
import asyncio
import logging
import shutil
import subprocess
import zipfile
import tempfile
from datetime import datetime
from typing import Optional, Dict, Any

import requests

# Logging
logger = logging.getLogger("tasks.backup-db")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(h)
logger.setLevel(logging.INFO)

# Paths / defaults
ROOT_DIR = os.path.dirname(os.path.dirname(__file__))  # assume tasks/ is under repo root
LOCAL_DB_PATH = os.path.join(ROOT_DIR, "data", "database.db")
SERVICE_ACCOUNT_PATH = os.path.join(ROOT_DIR, "core", "backup.json")
SETUP_JSON_PATH = os.path.join(ROOT_DIR, "core", "setup.json")

# Config from env
GDRIVE_FOLDER_ID = os.environ.get("GDRIVE_FOLDER_ID")  # optional
INTERVAL_HOURS = float(os.environ.get("INTERVAL_HOURS", "6"))
RCLONE_BIN = shutil.which("rclone")  # None if not installed
# Optionally override notification token
NOTIFY_OVERRIDE_TOKEN = os.environ.get("NOTIFY_VIA_BOT_TOKEN")

# Safety helper - minimal check to avoid logging secrets
def _service_account_valid(path: str) -> bool:
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return bool(data.get("client_email") and data.get("private_key"))
    except Exception:
        return False

# Setup.json reader
def _load_setup() -> Dict[str, Any]:
    if not os.path.exists(SETUP_JSON_PATH):
        return {}
    try:
        with open(SETUP_JSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        logger.exception("Failed to read core/setup.json")
        return {}

# Telegram helpers (uses requests so it doesn't depend on aiogram being available)
def _send_telegram_text(token: str, chat_id: int, text: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=30)
        if r.status_code == 200:
            return True
        else:
            logger.warning("Telegram sendMessage failed: %s %s", r.status_code, r.text)
            return False
    except Exception:
        logger.exception("Exception sending Telegram message")
        return False

def _send_telegram_document(token: str, chat_id: int, file_path: str, caption: Optional[str] = None) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    try:
        with open(file_path, "rb") as fh:
            files = {"document": fh}
            data = {"chat_id": chat_id}
            if caption:
                data["caption"] = caption
                data["parse_mode"] = "HTML"
            r = requests.post(url, data=data, files=files, timeout=120)
        if r.status_code == 200:
            return True
        else:
            logger.warning("Telegram sendDocument failed: %s %s", r.status_code, r.text)
            return False
    except Exception:
        logger.exception("Exception sending Telegram document")
        return False

# rclone upload function (uploads the zip file)
def _rclone_upload(local_path: str, service_account_json: str, folder_id: Optional[str] = None) -> bool:
    """
    Attempt to upload using rclone. Expects user to have a remote named 'gdrive' configured
    OR will pass --drive-root-folder-id to target a specific folder. Return True on success.
    """
    if not RCLONE_BIN:
        logger.debug("rclone binary not available")
        return False
    if not os.path.exists(local_path):
        logger.error("Local file does not exist: %s", local_path)
        return False

    # Build rclone args:
    # Example command:
    # rclone copy /path/to/database-...zip gdrive: --drive-service-account-file /path/to/backup.json --drive-root-folder-id <folder_id> --no-traverse
    remote_target = "gdrive:"
    args = [RCLONE_BIN, "copy", local_path, remote_target, "--drive-service-account-file", service_account_json, "--no-traverse"]
    if folder_id:
        args += ["--drive-root-folder-id", folder_id]
    logger.info("Running rclone copy (remote=%s folder_id=%s)...", remote_target, "provided" if folder_id else "none")
    try:
        proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
        out = proc.stdout.decode(errors="ignore").strip()
        err = proc.stderr.decode(errors="ignore").strip()
        if proc.returncode == 0:
            logger.info("rclone upload succeeded")
            if out:
                logger.debug("rclone stdout: %s", out)
            return True
        else:
            logger.warning("rclone returned non-zero (%s). stderr: %s", proc.returncode, err)
            return False
    except Exception:
        logger.exception("Exception while running rclone")
        return False

def _human_readable_size(num: int) -> str:
    """
    Convert bytes to human readable string, e.g. 1234567 -> '1.18 MB'
    """
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num) < 1024.0:
            return f"{num:3.2f} {unit}"
        num /= 1024.0
    return f"{num:.2f} PB"

async def _perform_backup_and_notify(bot=None) -> bool:
    """
    Perform one backup run:
      - Zip the database to a timestamped zip file
      - If rclone available and backup.json valid: upload zip via rclone
      - Else: send the zip as document to Telegram notification chat
      - Send notification message with date, filename and size
    Returns True on success (either rclone upload or telegram send), False otherwise.
    """
    setup = _load_setup()
    admin_cfg = setup.get("admin") or {}
    admin_chat = admin_cfg.get("userid")
    notify_token = setup.get("notifikasi") or NOTIFY_OVERRIDE_TOKEN
    notify_token_present = bool(notify_token)

    # notification helper functions
    async def _notify_text(msg: str):
        if notify_token_present and admin_chat:
            ok = _send_telegram_text(notify_token, int(admin_chat), msg)
            if ok:
                return
        if bot is not None:
            try:
                await bot.send_message(admin_chat, msg, parse_mode="HTML")
            except Exception:
                logger.exception("Failed to send notify via aiogram.Bot")
        else:
            logger.info("No notify method available for message: %s", msg)

    async def _notify_file(msg: str, file_path: str):
        if notify_token_present and admin_chat:
            ok = _send_telegram_document(notify_token, int(admin_chat), file_path, caption=msg)
            if ok:
                return
        if bot is not None:
            try:
                with open(file_path, "rb") as fh:
                    await bot.send_document(int(admin_chat), fh, caption=msg, parse_mode="HTML")
            except Exception:
                logger.exception("Failed to send document via aiogram.Bot")
        else:
            logger.info("No notify method available to send file: %s", file_path)

    # Ensure local DB exists
    if not os.path.exists(LOCAL_DB_PATH):
        logger.error("Local DB file not found: %s", LOCAL_DB_PATH)
        await _notify_text("Backup gagal: file database tidak ditemukan di server.")
        return False

    # Create zip file in a temp location
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    timestamp_display = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    zip_filename = f"database-{ts}.zip"
    tmp_dir = tempfile.mkdtemp(prefix="db_backup_")
    zip_path = os.path.join(tmp_dir, zip_filename)

    try:
        logger.info("Creating zip archive %s (from %s)", zip_path, LOCAL_DB_PATH)
        with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            # Store database file with base name only
            zf.write(LOCAL_DB_PATH, arcname=os.path.basename(LOCAL_DB_PATH))
        zip_size = os.path.getsize(zip_path)
        size_hr = _human_readable_size(zip_size)
        logger.info("Zip created: %s (%s)", zip_path, size_hr)

        # Branch: rclone + backup.json
        sa_ok = _service_account_valid(SERVICE_ACCOUNT_PATH)
        if RCLONE_BIN and sa_ok:
            logger.info("rclone installed and service account JSON present -> attempting rclone upload of zip")
            success = _rclone_upload(zip_path, SERVICE_ACCOUNT_PATH, folder_id=GDRIVE_FOLDER_ID)
            if success:
                msg = (
                    f"Backup berhasil via rclone\n"
                    f"• Tanggal: <code>{timestamp_display}</code>\n"
                    f"• File: <code>{zip_filename}</code>\n"
                    f"• Ukuran: <code>{size_hr}</code>"
                )
                await _notify_text(msg)
                logger.info("Backup via rclone completed and notification attempted")
                return True
            else:
                logger.warning("rclone upload failed; will fallback to sending zip via Telegram")
        else:
            if not RCLONE_BIN:
                logger.info("rclone not installed on system (skipping rclone path)")
            if not sa_ok:
                logger.info("service account JSON missing or invalid at %s (skipping rclone path)", SERVICE_ACCOUNT_PATH)

        # Fallback: send zip via Telegram
        caption = (
            f"Backup DB (fallback)\n"
            f"• Tanggal: <code>{timestamp_display}</code>\n"
            f"• File: <code>{zip_filename}</code>\n"
            f"• Ukuran: <code>{size_hr}</code>"
        )
        send_ok = False
        try:
            await _notify_file(caption, zip_path)
            logger.info("Fallback telegram document send attempted")
            send_ok = True
        except Exception:
            logger.exception("Fallback sending of zip failed")

        if not send_ok:
            await _notify_text("Backup gagal: tidak dapat mengirim file ke Telegram.")
            return False
        return True

    finally:
        # Clean up temporary zip and dir
        try:
            if os.path.exists(zip_path):
                os.remove(zip_path)
            if os.path.isdir(tmp_dir):
                shutil.rmtree(tmp_dir, ignore_errors=True)
            logger.debug("Cleaned up temp files")
        except Exception:
            logger.exception("Failed to remove temporary backup files")

async def _loop_backup(interval_hours: float, bot=None):
    interval = max(0.1, float(interval_hours)) * 3600.0
    # Run immediately, then sleep loop
    while True:
        try:
            logger.info("Starting scheduled DB backup run")
            await _perform_backup_and_notify(bot=bot)
        except asyncio.CancelledError:
            logger.info("Backup loop cancelled")
            raise
        except Exception:
            logger.exception("Unexpected error during backup run")
        logger.info("Backup run complete, sleeping %.1f seconds (%.2f hours)", interval, interval / 3600.0)
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("Backup loop cancelled during sleep")
            raise

def start_backup_loop(bot=None) -> asyncio.Task:
    """
    Start the background backup loop as an asyncio.Task and return it.
    Pass aiogram.Bot instance if available (used as fallback for notifications).
    """
    task = asyncio.create_task(_loop_backup(INTERVAL_HOURS, bot=bot), name="backup_database_loop")
    logger.info("Started backup loop task (interval %.2f hours)", INTERVAL_HOURS)
    return task

# Allow one-shot run for manual testing
if __name__ == "__main__":
    import asyncio as _asyncio
    logger.info("Running one-shot backup test (invoked directly)")
    _asyncio.run(_perform_backup_and_notify(bot=None))