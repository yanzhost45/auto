import os
import json
from typing import Optional, Tuple, Any, Dict

import requests


def _setup_paths() -> Tuple[str, str]:
    """
    Return paths for core/setup.json and core/token.json relative to repo root
    (assumes this file lives in api/).
    """
    repo_root = os.path.dirname(os.path.dirname(__file__))
    setup_path = os.path.join(repo_root, "core", "setup.json")
    token_path = os.path.join(repo_root, "core", "token.json")
    return setup_path, token_path


def get_api_base_url_and_token() -> Tuple[Optional[str], Optional[str]]:
    """
    Read core/setup.json to get API base_url and core/token.json to get access_token.

    Returns (base_url, access_token) or (None, None) on missing values.
    """
    setup_path, token_path = _setup_paths()

    if not os.path.exists(setup_path):
        return None, None

    with open(setup_path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except Exception:
            return None, None

    api = data.get("api", {})
    base_url = api.get("base_url")

    if not os.path.exists(token_path):
        return base_url, None

    with open(token_path, "r", encoding="utf-8") as tf:
        try:
            token_data = json.load(tf)
        except Exception:
            return base_url, None
        access_token = token_data.get("access_token")

    return base_url, access_token


def create_deposit(amount: int, timeout: int = 30) -> Dict[str, Any]:
    """
    Create a deposit by calling POST {base_url}/api/payment/deposit
    with header "Authorization: Bearer <access_token>" and JSON body {"amount": amount}.

    Returns parsed JSON on success, or a dict with "success": False and "error" containing details.
    """
    base_url, access_token = get_api_base_url_and_token()
    if not base_url:
        return {"success": False, "error": "API base_url not configured (core/setup.json missing or invalid)."}
    if not access_token:
        return {"success": False, "error": "Access token not found (core/token.json missing or invalid)."}

    url = base_url.rstrip("/") + "/api/payment/deposit"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    payload = {"amount": int(amount)}

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except requests.RequestException as e:
        return {"success": False, "error": f"Request failed: {str(e)}"}

    # Try to parse JSON if available
    text = resp.text or ""
    try:
        data = resp.json()
    except ValueError:
        # Non-JSON response
        return {"success": False, "error": "Non-JSON response from API", "status_code": resp.status_code, "body": text}

    # If HTTP status is not OK, include status and body
    if not resp.ok:
        return {"success": False, "error": "API returned error", "status_code": resp.status_code, "body": data}

    return data