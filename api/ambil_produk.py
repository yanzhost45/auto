import requests
import json
import os

def get_token():
    token_path = os.path.join("core", "token.json")
    if not os.path.exists(token_path):
        raise Exception("Token file not found")
    with open(token_path, "r") as f:
        data = json.load(f)
    # GUNAKAN access_token!
    return data.get("access_token")

def get_base_url():
    setup_path = os.path.join("core", "setup.json")
    if not os.path.exists(setup_path):
        raise Exception("Setup file not found")
    with open(setup_path, "r") as f:
        data = json.load(f)
    api_info = data.get("api", {})
    base_url = api_info.get("base_url")
    if not base_url:
        raise Exception("base_url not found in setup.json")
    return base_url.rstrip("/")

def ambil_kategori_xl():
    base_url = get_base_url()
    url = f"{base_url}/api/xl/kategori"
    token = get_token()
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()

def ambil_produk_xl(kategori):
    from urllib.parse import quote_plus
    base_url = get_base_url()
    url = f"{base_url}/api/xl/produk-list?kategori={quote_plus(kategori)}"
    token = get_token()
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()

def simpan_produk_ke_db(produk_list):
    """
    Simpan produk (list of dict) ke database lewat models/produk_xl.py.
    Jika tabel belum ada, akan otomatis dibuat.
    """
    from models.produk_xl import insert_or_update_produk, init_db
    init_db()  # <-- Pastikan tabel sudah ada!
    for produk in produk_list:
        insert_or_update_produk(produk)