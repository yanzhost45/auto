#!/usr/bin/env python3
"""
helper.image_to_string

Decode QR/QRIS from an image file and return the payload string.

Also includes helper functions to convert a "static" QRIS payload into a
"dynamic" QRIS payload by injecting/changing the amount (tag 54) and optional
service fee (tag 55...) and recalculating the CRC16 (same logic as the PHP
example provided).

Do not change the file name: helper/image_to_string.py
"""
from typing import Optional, Union
import io
import os
import sys
import argparse
import json
import shutil  # kept for directory creation via _save_setup
from base64 import b64decode

# Note: no backup is performed per your request (no .bak files)

try:
    from PIL import Image
except Exception as e:
    raise RuntimeError("Pillow is required: pip install Pillow") from e

# Try to import pyzbar (preferred). If not available, fall back to OpenCV.
_pyzbar_available = False
_cv2_available = False
try:
    from pyzbar.pyzbar import decode as _pyzbar_decode  # type: ignore
    _pyzbar_available = True
except Exception:
    _pyzbar_available = False

if not _pyzbar_available:
    try:
        import cv2  # type: ignore
        import numpy as _np  # type: ignore
        _cv2_available = True
    except Exception:
        _cv2_available = False


def _open_image(source: Union[str, bytes, io.BytesIO, Image.Image]) -> Image.Image:
    """
    Open a source into a PIL.Image.Image (RGB).

    Accepts:
      - PIL Image instance
      - raw bytes / bytearray (image bytes)
      - io.BytesIO
      - filesystem path (absolute or relative)
      - data URI base64 string like "data:image/png;base64,...."

    Raises FileNotFoundError for unknown path, TypeError for unsupported type.
    """
    if isinstance(source, Image.Image):
        return source.convert("RGB")
    if isinstance(source, (bytes, bytearray)):
        return Image.open(io.BytesIO(source)).convert("RGB")
    if isinstance(source, io.BytesIO):
        return Image.open(source).convert("RGB")
    if isinstance(source, str):
        s = source.strip()
        # support data URI base64: data:[<mediatype>][;base64],<data>
        if s.startswith("data:") and "base64," in s:
            try:
                base64_data = s.split(",", 1)[1]
                b = b64decode(base64_data)
                return Image.open(io.BytesIO(b)).convert("RGB")
            except Exception as e:
                raise ValueError("Invalid data URI / base64 image") from e

        # accept absolute path or relative to cwd; also try relative to this file
        if os.path.exists(s):
            return Image.open(s).convert("RGB")
        alt = os.path.join(os.path.dirname(__file__), s)
        if os.path.exists(alt):
            return Image.open(alt).convert("RGB")
        raise FileNotFoundError(f"No such file: {source}")
    raise TypeError("Unsupported source type for image. Use file path, bytes, BytesIO, data URI or PIL Image.")


def image_to_string(source: Union[str, bytes, io.BytesIO, Image.Image]) -> Optional[str]:
    """
    Decode QR/QRIS content from an image and return the decoded string.
    Returns the first decoded payload (as UTF-8 string) or None if nothing decoded.

    source may be:
      - a filesystem path (str)
      - raw image bytes (bytes)
      - a BytesIO instance
      - a PIL.Image.Image instance
      - a data URI base64 string (data:image/png;base64,...)

    Examples:
      image_to_string("core/qris.png")
      image_to_string(image_bytes)
      image_to_string(qris_data['qris_image'])  # if qris_image is data URI base64
    """
    img = _open_image(source)

    # Try pyzbar first (most robust)
    if _pyzbar_available:
        try:
            decoded = _pyzbar_decode(img)
            if decoded:
                payload = decoded[0].data
                try:
                    return payload.decode("utf-8")
                except Exception:
                    return payload.decode(errors="ignore")
        except Exception:
            pass

    # Fallback to OpenCV QRCodeDetector
    if _cv2_available:
        try:
            import cv2
            import numpy as _np
            arr = _np.array(img)  # RGB
            bgr = arr[:, :, ::-1].copy()  # convert RGB -> BGR
            detector = cv2.QRCodeDetector()
            data, points, _ = detector.detectAndDecode(bgr)
            if data:
                return data
        except Exception:
            pass

    return None


# --- QRIS dynamic builder helpers (PHP-compatible) -------------------------

def _crc16_ccitt_hex(data: str) -> str:
    """
    Compute CRC16-CCITT (polynomial 0x1021) with initial value 0xFFFF.
    Return uppercase 4-hex-string (no '0x' prefix), same behavior as PHP ConvertCRC16.
    """
    crc = 0xFFFF
    for ch in data:
        crc ^= (ord(ch) & 0xFF) << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) & 0xFFFF) ^ 0x1021
            else:
                crc = (crc << 1) & 0xFFFF
    hexstr = format(crc & 0xFFFF, "04X")
    return hexstr


def make_qris_dynamic(static_qris: str, amount: Union[int, str], fee_value: Optional[Union[int, str]] = None, fee_is_percent: bool = False) -> str:
    """
    Convert a static QRIS payload into a dynamic one by injecting tag 54 (amount)
    and optional tag 55 (service fee) then recalculating the CRC16.

    Parameters:
      - static_qris: original QRIS payload string (expected to include trailing CRC)
      - amount: numeric amount or string, e.g. 10000
      - fee_value: optional fee value (string or number)
      - fee_is_percent: if True, treat fee_value as percent and use tag for percent (as in PHP example)

    Behavior mirrors the provided PHP example:
      - remove last 4 chars (assumes original payload already contains '63' '04' tag prefix)
      - replace "010211" with "010212"
      - find first occurrence of "5802ID" and inject the 54.. amount block before it
      - if fee provided, build fee tag:
          rupiah -> "55020256" + len + fee
          percent -> "55020357" + len + fee
      - reassemble and append CRC16 hex (4 chars, uppercase)
    """
    if static_qris is None:
        raise ValueError("static_qris must be provided")

    q = str(static_qris).strip()
    amt = str(amount)

    if len(q) < 4:
        raise ValueError("static_qris too short to contain CRC")

    # remove final 4 characters (existing CRC hex)
    base = q[:-4]

    # mirror PHP: replace all occurrences of "010211" -> "010212"
    step1 = base.replace("010211", "010212")

    # split at first "5802ID"
    parts = step1.split("5802ID", 1)
    if len(parts) == 1:
        # couldn't find expected marker, try to continue by appending at end
        left = step1
        right = ""
    else:
        left, right = parts[0], parts[1]

    # build amount tag 54
    uang = "54" + f"{len(amt):02d}" + amt

    # build fee tag if present
    if fee_value is not None and str(fee_value) != "":
        fee = str(fee_value)
        if fee_is_percent:
            # PHP used "55020357" prefix for percent
            tax = "55020357" + f"{len(fee):02d}" + fee
        else:
            # PHP used "55020256" prefix for rupiah
            tax = "55020256" + f"{len(fee):02d}" + fee
        uang = uang + tax + "5802ID"
    else:
        uang = uang + "5802ID"

    fix = (left + uang + right).strip()

    # compute CRC16 over the full payload (fix) and append hex (4 chars)
    crc = _crc16_ccitt_hex(fix)
    result = fix + crc
    return result


# --- setup.json helpers -----------------------------------------------------
PROJECT_ROOT = os.path.abspath(os.getcwd())
CORE_DIR = os.path.join(PROJECT_ROOT, "core")
SETUP_PATH = os.path.join(CORE_DIR, "setup.json")


def _load_setup(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f) or {}
        except Exception:
            return {}


def _save_setup(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_qris_to_setup(qris_string: str, qris_path: str = "core/qris.png") -> None:
    """
    Write qris_string and qris_path to core/setup.json without creating backups.
    """
    setup = _load_setup(SETUP_PATH)
    setup["qris_string"] = qris_string
    setup["qris_path"] = qris_path
    _save_setup(SETUP_PATH, setup)
    print(f"Updated {SETUP_PATH} with qris_string and qris_path.")


# --- CLI --------------------------------------------------------------------
def _cli(argv=None) -> int:
    p = argparse.ArgumentParser(description="Decode QR/QRIS image and save into core/setup.json")
    p.add_argument("file", nargs="?", default="core/qris.png", help="Path to image file (default: core/qris.png)")
    p.add_argument("--no-save", action="store_true", help="Decode and print only; do not write core/setup.json")
    p.add_argument("--print-only", action="store_true", help="Alias for --no-save")

    # optional helpers to build dynamic QRIS from a static payload
    p.add_argument("--make-dynamic", action="store_true", help="Build dynamic QRIS from decoded/loaded payload (will print result)")
    p.add_argument("--amount", help="Amount to inject (required with --make-dynamic)")
    p.add_argument("--fee", help="Optional fee value (rupiah or percent depending on --fee-percent)")
    p.add_argument("--fee-percent", action="store_true", help="Treat --fee as percent (otherwise rupiah)")

    args = p.parse_args(argv)

    try:
        result = image_to_string(args.file)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Error while decoding image: {e}", file=sys.stderr)
        return 3

    if result:
        # print decoded string
        print(result)

        # If requested, build dynamic QRIS from decoded result
        if args.make_dynamic:
            if not args.amount:
                print("Error: --amount is required when using --make-dynamic", file=sys.stderr)
                return 5
            try:
                dynamic = make_qris_dynamic(result, args.amount, fee_value=args.fee, fee_is_percent=args.fee_percent)
                print("\n[+] Dynamic QRIS Result:\n")
                print(dynamic)
            except Exception as e:
                print(f"Failed to build dynamic QRIS: {e}", file=sys.stderr)
                return 6

        # save into core/setup.json unless user disabled saving
        if not args.no_save and not args.print_only:
            try:
                # store qris_path relative to project root (consistent)
                rel_path = os.path.relpath(os.path.abspath(args.file), PROJECT_ROOT)
                rel_path = rel_path.replace("\\", "/")
                save_qris_to_setup(result, rel_path)
                return 0
            except Exception as e:
                print(f"Failed to save to {SETUP_PATH}: {e}", file=sys.stderr)
                return 4
        else:
            return 0
    else:
        hints = []
        if not _pyzbar_available:
            hints.append("pyzbar not installed")
        if not _cv2_available:
            hints.append("opencv (cv2) not installed")
        hint_msg = f" ({', '.join(hints)})" if hints else ""
        print(f"No QR data detected{hint_msg}.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(_cli())