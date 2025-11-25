"""Fallback configuration that reads all settings from environment variables.

This module mirrors the optional user-provided config.py so code can run even
when that file is excluded from version control or container builds.
"""
from __future__ import annotations

import json
import os

DEFAULT_TOKEN: str | None = None
DEFAULT_LOGS_CHAT_ID: int | None = None
DEFAULT_MAX_FILESIZE = 10_000_000_000  # 10 GB
DEFAULT_OUTPUT_FOLDER = "downloads"
DEFAULT_DENO_PATH: str | None = None
DEFAULT_COOKIES_FILE = "cookies.txt"
DEFAULT_ADMIN_IDS: list[int] = []
DEFAULT_JS_RUNTIMES: dict[str, dict[str, str]] | None = None
DEFAULT_REMOTE_COMPONENTS: list[str] | None = None
DEFAULT_YT_DLP_VERBOSE = True
DEFAULT_USE_NETRC = False
DEFAULT_NETRC_PATH: str | None = None
DEFAULT_NETRC_CMD: str | None = None
DEFAULT_NEXTCLOUD_BASE_URL = ""
DEFAULT_NEXTCLOUD_USERNAME = ""
DEFAULT_NEXTCLOUD_PASSWORD = ""
DEFAULT_NEXTCLOUD_UPLOAD_FOLDER = "Downloads"
DEFAULT_NEXTCLOUD_SHARE_PASSWORD: str | None = None
DEFAULT_NEXTCLOUD_SHARE_LABEL: str | None = None
DEFAULT_NEXTCLOUD_PUBLIC_UPLOAD = False
DEFAULT_NEXTCLOUD_PERMISSIONS = 1


def _env_int(var_name: str, default: int | None = None) -> int | None:
    raw = os.getenv(var_name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(var_name: str, default: bool) -> bool:
    raw = os.getenv(var_name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(var_name: str) -> list[str]:
    raw = os.getenv(var_name)
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


token = os.getenv("BOT_TOKEN") or DEFAULT_TOKEN
logs = _env_int("BOT_LOGS_CHAT_ID", DEFAULT_LOGS_CHAT_ID)
max_filesize = _env_int("BOT_MAX_FILESIZE", DEFAULT_MAX_FILESIZE) or DEFAULT_MAX_FILESIZE
output_folder = os.getenv("BOT_OUTPUT_FOLDER", DEFAULT_OUTPUT_FOLDER)
deno_path = os.getenv("BOT_DENO_PATH", DEFAULT_DENO_PATH)
cookies_file = os.getenv("BOT_COOKIES_FILE", DEFAULT_COOKIES_FILE)
use_netrc = _env_bool("BOT_NETRC", DEFAULT_USE_NETRC)
netrc_path = os.getenv("BOT_NETRC_PATH", DEFAULT_NETRC_PATH)
netrc_cmd = os.getenv("BOT_NETRC_CMD", DEFAULT_NETRC_CMD)

nextcloud_base_url = os.getenv("BOT_NEXTCLOUD_BASE_URL", DEFAULT_NEXTCLOUD_BASE_URL)
nextcloud_username = os.getenv("BOT_NEXTCLOUD_USERNAME", DEFAULT_NEXTCLOUD_USERNAME)
nextcloud_password = os.getenv("BOT_NEXTCLOUD_PASSWORD", DEFAULT_NEXTCLOUD_PASSWORD)
nextcloud_upload_folder = os.getenv("BOT_NEXTCLOUD_UPLOAD_FOLDER", DEFAULT_NEXTCLOUD_UPLOAD_FOLDER)
nextcloud_share_password = os.getenv("BOT_NEXTCLOUD_SHARE_PASSWORD", DEFAULT_NEXTCLOUD_SHARE_PASSWORD)
nextcloud_share_label = os.getenv("BOT_NEXTCLOUD_SHARE_LABEL", DEFAULT_NEXTCLOUD_SHARE_LABEL)
nextcloud_public_upload = _env_bool("BOT_NEXTCLOUD_PUBLIC_UPLOAD", DEFAULT_NEXTCLOUD_PUBLIC_UPLOAD)
nextcloud_permissions = _env_int("BOT_NEXTCLOUD_PERMISSIONS", DEFAULT_NEXTCLOUD_PERMISSIONS) or DEFAULT_NEXTCLOUD_PERMISSIONS

js_runtimes_raw_env = os.getenv("BOT_JS_RUNTIMES")
js_runtimes = None
if js_runtimes_raw_env:
    try:
        js_runtimes = json.loads(js_runtimes_raw_env)
    except json.JSONDecodeError:
        js_runtimes = None
elif DEFAULT_JS_RUNTIMES:
    js_runtimes = DEFAULT_JS_RUNTIMES

remote_components_list = _env_list("BOT_REMOTE_COMPONENTS")
if not remote_components_list and DEFAULT_REMOTE_COMPONENTS:
    remote_components_list = DEFAULT_REMOTE_COMPONENTS
remote_components = remote_components_list or None

yt_dlp_verbose = _env_bool("BOT_YTDLP_VERBOSE", DEFAULT_YT_DLP_VERBOSE)

admin_id_values = _env_list("BOT_ADMIN_IDS")
if not admin_id_values and DEFAULT_ADMIN_IDS:
    admin_id_values = [str(x) for x in DEFAULT_ADMIN_IDS]
admin_ids: list[int] = []
for value in admin_id_values:
    try:
        admin_ids.append(int(value))
    except ValueError:
        continue

# (Validation for token removed; handled in main.py)
