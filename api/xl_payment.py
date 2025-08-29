import requests
import os
import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# limit how many characters of response body we show in info logs
_MAX_LOG_BODY = 2000


def get_api_base_url_and_token():
    setup_path = os.path.join("core", "setup.json")
    if not os.path.exists(setup_path):
        raise Exception("setup.json not found.")
    with open(setup_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        api = data.get("api", {})
        token_path = os.path.join("core", "token.json")
        if not os.path.exists(token_path):
            raise Exception("token.json not found.")
        with open(token_path, "r", encoding="utf-8") as tf:
            token_data = json.load(tf)
            access_token = token_data.get("access_token")
        base_url = api.get("base_url")
        if not base_url or not access_token:
            raise Exception("API base_url atau access_token tidak ditemukan.")
        return base_url, access_token


def _safe_log_body(prefix: str, body: Any, level: int = logging.INFO) -> None:
    """
    Log response body safely: a short summary at INFO, full body at DEBUG.
    """
    try:
        if isinstance(body, (dict, list)):
            body_text = json.dumps(body, ensure_ascii=False)
        else:
            body_text = str(body)
    except Exception:
        body_text = repr(body)

    # info: truncated
    short = (body_text[:_MAX_LOG_BODY] + "...(truncated)") if len(body_text) > _MAX_LOG_BODY else body_text
    logger.log(level, "%s %s", prefix, short)

    # debug: full
    logger.debug("%s full body: %s", prefix, body_text)


def xl_payment_settlement(produk_id: str, msisdn: str, metode_pembayaran: str) -> Dict[str, Any]:
    """
    Kirim request pembayaran XL ke endpoint settlement.

    Return: dict with at least 'success': bool and optionally other fields from API.
    Also includes '_http_status' when HTTP response available.

    This function logs:
    - request URL, payload (at DEBUG)
    - response HTTP status and truncated body (at INFO)
    - full response body and headers (at DEBUG)
    - network / exception info (at ERROR)
    """
    try:
        base_url, access_token = get_api_base_url_and_token()
        url = f"{base_url}/api/xl/payment-settlement"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "produk_id": produk_id,
            "msisdn": msisdn,
            "metode_pembayaran": metode_pembayaran
        }

        logger.debug("xl_payment_settlement -> POST %s", url)
        logger.debug("xl_payment_settlement payload: %s", json.dumps(payload, ensure_ascii=False))

        resp = requests.post(url, json=payload, headers=headers, timeout=30)

        # Log HTTP status and small preview of response text
        resp_text_preview = (resp.text[:_MAX_LOG_BODY] + "...(truncated)") if len(resp.text or "") > _MAX_LOG_BODY else (resp.text or "")
        logger.info("xl_payment_settlement HTTP %s for produk=%s msisdn=%s -> %s", resp.status_code, produk_id, msisdn, resp_text_preview)
        logger.debug("xl_payment_settlement response headers: %s", dict(resp.headers))

        # Try parse JSON body even for non-2xx
        try:
            body = resp.json()
            _safe_log_body("xl_payment_settlement parsed JSON response:", body, level=logging.INFO)
        except ValueError:
            # Non-JSON body
            text = resp.text or resp.reason or ""
            logger.info("xl_payment_settlement non-JSON response (HTTP %s): %s", resp.status_code, resp_text_preview)
            logger.debug("xl_payment_settlement non-JSON full response: %s", text)
            return {"success": False, "error": f"HTTP {resp.status_code}: {text}", "_http_status": resp.status_code}

        # If server returned JSON, ensure 'success' is explicit
        if isinstance(body, dict):
            # default success to False for HTTP >= 400 unless body explicitly sets success True
            body.setdefault("success", False if resp.status_code >= 400 else body.get("success", False))
            body["_http_status"] = resp.status_code
            # log a clear summary at INFO and full JSON at DEBUG
            logger.info("xl_payment_settlement parsed JSON (http=%s) keys: %s", resp.status_code, list(body.keys()))
            logger.debug("xl_payment_settlement JSON body: %s", json.dumps(body, ensure_ascii=False))
            return body

        # fallback when parsed JSON is not a dict
        logger.info("xl_payment_settlement unexpected JSON type: %s", type(body))
        return {"success": False, "error": f"Unexpected JSON type: {type(body)}", "raw": body, "_http_status": resp.status_code}

    except requests.RequestException as e:
        # jaringan / timeout / DNS error dll.
        logger.exception("RequestException in xl_payment_settlement: %s", e)
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.exception("Unexpected error in xl_payment_settlement: %s", e)
        return {"success": False, "error": str(e)}