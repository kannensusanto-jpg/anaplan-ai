import json

import httpx
from cryptography.fernet import Fernet

from app.core.redis_client import get_redis


class AnaplanAuthService:
    TOKEN_URL  = "https://auth.anaplan.com/token"
    TTL_BUFFER = 60  # refresh 60s before expiry

    def __init__(self, encryption_key: bytes):
        self.fernet = Fernet(encryption_key)

    async def get_token(self, client_id: str, encrypted_creds: str) -> str:
        redis     = get_redis()
        cache_key = f"anaplan_token:{client_id}"

        cached = await redis.get(cache_key)
        if cached:
            return cached.decode()

        creds = json.loads(self.fernet.decrypt(encrypted_creds.encode()))

        async with httpx.AsyncClient() as http:
            resp = await http.post(
                self.TOKEN_URL,
                data={
                    "grant_type":    "client_credentials",
                    "client_id":     creds["client_id"],
                    "client_secret": creds["client_secret"],
                },
            )
            resp.raise_for_status()
            payload = resp.json()

        token = payload["access_token"]
        ttl   = max(payload["expires_in"] - self.TTL_BUFFER, 30)
        await redis.set(cache_key, token.encode(), ex=ttl)
        return token
