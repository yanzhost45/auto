import aiohttp
import json
import os
import asyncio

SETUP_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "core", "setup.json")
TOKEN_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "core", "token.json")

def load_base_url():
    with open(SETUP_PATH, "r") as f:
        setup = json.load(f)
    return setup["api"]["base_url"]

def get_refresh_token():
    with open(TOKEN_PATH, "r") as f:
        token_data = json.load(f)
    return token_data.get("refresh_token")

def update_token_json(access_token, refresh_token):
    with open(TOKEN_PATH, "r") as f:
        token_data = json.load(f)
    token_data["access_token"] = access_token
    token_data["refresh_token"] = refresh_token
    with open(TOKEN_PATH, "w") as f:
        json.dump(token_data, f, indent=2)

async def refresh_token_loop():
    while True:
        try:
            base_url = load_base_url()
            refresh_token_val = get_refresh_token()
            url = f"{base_url}/api/auth/refresh"
            payload = {"refresh_token": refresh_token_val}
            headers = {"Content-Type": "application/json"}
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        update_token_json(result["access_token"], result["refresh_token"])
                        print("Token berhasil diperbarui.")
                    else:
                        print(f"Error refresh: {resp.status} - {await resp.text()}")
        except Exception as e:
            print(f"Error saat refresh token: {e}")
        await asyncio.sleep(300)  # 5 menit