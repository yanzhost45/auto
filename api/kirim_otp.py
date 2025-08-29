import requests
import os
import json

def get_api_base_url_and_token():
    setup_path = os.path.join("core", "setup.json")
    if not os.path.exists(setup_path):
        raise Exception("setup.json not found.")
    with open(setup_path, "r") as f:
        data = json.load(f)
        api = data.get("api", {})
        token_path = os.path.join("core", "token.json")
        if not os.path.exists(token_path):
            raise Exception("token.json not found.")
        with open(token_path, "r") as tf:
            token_data = json.load(tf)
            access_token = token_data.get("access_token")
        return api.get("base_url"), access_token

def kirim_otp_xl(msisdn: str):
    base_url, access_token = get_api_base_url_and_token()
    url = f"{base_url}/api/xl/otp"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    data = {
        "msisdn": msisdn
    }
    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"success": False, "error": str(e)}