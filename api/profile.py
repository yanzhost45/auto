import requests
import json
import os

def get_base_url():
    setup_path = os.path.join("core", "setup.json")
    if not os.path.exists(setup_path):
        raise Exception("setup.json not found")
    with open(setup_path, "r") as f:
        data = json.load(f)
    api = data.get("api", {})
    base_url = api.get("base_url")
    if not base_url:
        raise Exception("base_url not found in setup.json")
    return base_url.rstrip("/")

def update_user_profile():
    """
    Ambil data profile user terbaru dari API dan update field "user" di core/token.json.
    """
    token_path = os.path.join("core", "token.json")
    if not os.path.exists(token_path):
        raise Exception("Token file not found")

    # Ambil access token
    with open(token_path, "r") as f:
        token_data = json.load(f)
    access_token = token_data.get("access_token")
    if not access_token:
        raise Exception("Access token not found in token.json")

    # Request profile ke API
    base_url = get_base_url()
    url = f"{base_url}/api/auth/me"
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        raise Exception(f"Gagal mengambil data profile dari API: {e}")

    # Pastikan response sesuai
    if not data.get("success") or "user" not in data:
        raise Exception(f"Response API tidak sesuai: {data}")

    # Update field "user" di token.json
    token_data["user"] = data["user"]
    with open(token_path, "w") as f:
        json.dump(token_data, f, indent=2)
    return data["user"]