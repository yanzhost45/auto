import requests
import json
import os

SETUP_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "core", "setup.json")
TOKEN_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "core", "token.json")

def load_api_config():
    with open(SETUP_PATH, "r") as f:
        setup = json.load(f)
    return setup["api"]["base_url"], setup["api"]["email"], setup["api"]["password"]

def ambil_token():
    base_url, email, password = load_api_config()
    url = f"{base_url}/api/auth/ambil-token"
    payload = {
        "email": email,
        "password": password
    }
    response = requests.post(url, json=payload)
    if response.status_code == 200:
        result = response.json()
        with open(TOKEN_PATH, "w") as f_token:
            json.dump(result, f_token, indent=2)
        print("Token berhasil diambil dan disimpan di core/token.json")
    else:
        print(f"Error: {response.status_code} - {response.text}")

if __name__ == "__main__":
    ambil_token()