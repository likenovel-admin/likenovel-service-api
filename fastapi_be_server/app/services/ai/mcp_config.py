import json
import os
import stat
from pathlib import Path
from urllib.parse import urlsplit

from app.const import settings


def load() -> dict:
    path = Path(os.environ.get(
        "LIKENOVEL_MCP_CONFIG_FILE", "/home/ln-admin/likenovel/mcp/config.json",
    ))
    if not path.is_file():
        return {}
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise RuntimeError("MCP configuration must be private")
    config = json.loads(path.read_text())
    resource = urlsplit(config.get("resource", ""))
    if resource.scheme != "https" or resource.path != "/mcp" or not resource.hostname \
            or resource.query or resource.fragment or resource.username or resource.password:
        raise RuntimeError("Invalid MCP resource configuration")
    if config.get("issuer") != settings.KC_ISSUER_BASE_URL:
        return {}  # Never expose production MCP configuration in another environment.
    if config.get("environment_db_host") != settings.DB_IP:
        return {}
    callback = urlsplit(config.get("oauth_callback", ""))
    if callback.scheme != "https" or callback.hostname != "chatgpt.com" \
            or not callback.path.startswith("/connector/oauth/") \
            or callback.query or callback.fragment:
        raise RuntimeError("MCP callback must be the exact ChatGPT connector callback")
    from cryptography.fernet import Fernet
    Fernet(config["token_encryption_key"].encode())
    return config
