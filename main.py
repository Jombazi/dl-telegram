from urllib.parse import urlparse, quote, urlencode
import datetime
from typing import Any, Optional, cast
from pathlib import Path
import subprocess
import telebot
try:
    import config  # type: ignore
except ModuleNotFoundError:
    import config_defaults as config

if not getattr(config, 'token', None):
    raise ValueError("BOT_TOKEN is required. Set BOT_TOKEN env var or supply config.py.")

BOT_TOKEN = cast(str, config.token)
import yt_dlp
from yt_dlp.utils import DownloadError
import re
from telebot.util import quick_markup
from telebot.apihelper import ApiTelegramException
from telebot import apihelper
import time
import requests


bot = telebot.TeleBot(BOT_TOKEN)
last_edited = {}
SUPPORTED_YT_HOSTS = {
    'www.youtube.com',
    'youtube.com',
    'youtu.be',
    'www.youtu.be',
    'm.youtube.com'
}
PROGRESS_UPDATE_INTERVAL = 5  # seconds
COOKIES_PATH = Path(getattr(config, 'cookies_file', 'cookies.txt'))
NEXTCLOUD_TIMEOUT = 30  # seconds
YTDLP_RETRIES = getattr(config, 'yt_dlp_retries', 10)
YTDLP_FRAGMENT_RETRIES = getattr(config, 'yt_dlp_fragment_retries', 25)
YTDLP_HTTP_CHUNK_SIZE = getattr(config, 'yt_dlp_http_chunk_size', 5 * 1024 * 1024)
ADMIN_IDS = {
    int(user_id)
    for user_id in getattr(config, 'admin_ids', [])
    if str(user_id).strip()
}
LOGIN_HELP_TEXT = (
    "To grab cookies easily:\n"
    "1. Install the 'Get cookies.txt' extension in your browser and export while logged in.\n"
    "2. Or run `yt-dlp --cookies-from-browser chrome` (or your browser name) to dump cookies.\n"
    "Send the exported text file contents back to me using /login."
)
BLACKLISTED_DOMAINS = {d.strip() for d in getattr(config, 'blacklisted_domains', '').split(',') if d.strip()}  # Load from config or .env
TELEGRAM_CUSTOM_API_URL = getattr(config, 'telegram_custom_api_url', None)
CUSTOM_TELEGRAM_API_URL = getattr(config, 'telegram_custom_api_url', None)
if TELEGRAM_CUSTOM_API_URL:
    apihelper.API_URL = TELEGRAM_CUSTOM_API_URL.strip()

def nextcloud_enabled() -> bool:
    return bool(
        getattr(config, 'nextcloud_base_url', '').strip() and
        getattr(config, 'nextcloud_username', '').strip() and
        getattr(config, 'nextcloud_password', '').strip()
    )


def _build_webdav_base() -> str:
    base = config.nextcloud_base_url.rstrip('/')
    return f"{base}/remote.php/dav/files/{config.nextcloud_username}"


def _build_remote_path(filename: str) -> str:
    folder = getattr(config, 'nextcloud_upload_folder', 'Telegram').strip('/')
    if folder:
        return f"{folder}/{filename}"
    return filename


def _encode_relative_path(path: str) -> str:
    parts = [quote(part, safe='') for part in path.split('/') if part]
    return '/'.join(parts)


def _serialize_params(fields: dict[str, Any]) -> str:
    normalized = {key: str(value) for key, value in fields.items() if value is not None}
    return urlencode(normalized, safe='/%', quote_via=quote)


def _request_with_timeout(session: requests.Session, method: str, url: str, **kwargs) -> requests.Response:
    timeout = kwargs.pop('timeout', NEXTCLOUD_TIMEOUT)
    try:
        return session.request(method, url, timeout=timeout, **kwargs)
    except requests.RequestException as exc:
        raise RuntimeError(f"Nextcloud request failed ({method} {url}): {exc}") from exc


def _parse_ocs_payload(resp: requests.Response) -> dict[str, Any]:
    try:
        payload = resp.json()
    except ValueError as exc:
        snippet = resp.text[:200]
        raise RuntimeError(f"Nextcloud returned invalid JSON: {snippet}") from exc

    ocs = payload.get('ocs')
    if not isinstance(ocs, dict):
        raise RuntimeError(f"Nextcloud response missing 'ocs' object: {payload}")

    meta = ocs.get('meta', {})
    status_code = meta.get('statuscode')
    if status_code not in (100, 200):
        raise RuntimeError(f"Nextcloud OCS meta indicates failure: {meta}")
    return ocs


def safe_unlink(path: Optional[Path]) -> None:
    if not path:
        return
    try:
        if path.exists():
            path.unlink()
    except Exception as exc:
        print(f"Cleanup error: {exc}")

def convert_to_mp4(source: Path) -> Path:
    """
    Convert any video file to an iPhone-friendly MP4 (H.264 + AAC).

    We ALWAYS re-encode, even if the source is already .mp4,
    because codecs/flags inside might still be incompatible
    with iOS editing (Photos, iMovie, etc.).
    """
    suffix = source.suffix.lower()

    # Write to a new file so we never corrupt the original
    if suffix == '.mp4':
        target = source.with_name(source.stem + '_ios.mp4')
    else:
        target = source.with_suffix('.mp4')

    cmd = [
        'ffmpeg', '-y', '-nostdin', '-loglevel', 'error',
        '-i', str(source),
        '-c:v', 'libx264', '-preset', 'veryfast',
        '-c:a', 'aac', '-b:a', '192k',
        '-movflags', '+faststart',
        str(target),
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed: {result.stderr.decode('utf-8', errors='ignore')[:400]}"
        )
    return target


def _ensure_webdav_dirs(session: requests.Session, remote_path: str) -> None:
    base = _build_webdav_base()
    parts = [part for part in remote_path.split('/')[:-1] if part]
    accumulated: list[str] = []
    for part in parts:
        accumulated.append(part)
        current = '/'.join(accumulated)
        encoded_current = _encode_relative_path(current)
        url = f"{base}/{encoded_current}"
        resp = _request_with_timeout(session, 'PROPFIND', url, headers={'Depth': '0'})
        if resp.status_code == 404:
            mkcol = _request_with_timeout(session, 'MKCOL', url)
            if mkcol.status_code not in (201, 405):
                raise RuntimeError(f"Failed to create folder {current}: {mkcol.text[:200]}")
        elif resp.status_code not in (200, 207):
            raise RuntimeError(f"Failed to access folder {current}: {resp.text[:200]}")


def upload_to_nextcloud(file_path: Path) -> str:
    if not nextcloud_enabled():
        raise RuntimeError('Nextcloud is not configured')

    remote_path = _build_remote_path(file_path.name)
    encoded_remote_path = _encode_relative_path(remote_path)

    with requests.Session() as session:
        session.auth = (config.nextcloud_username, config.nextcloud_password)
        _ensure_webdav_dirs(session, remote_path)

        url = f"{_build_webdav_base()}/{encoded_remote_path}"
        with file_path.open('rb') as f:
            resp = _request_with_timeout(session, 'PUT', url, data=f)
        if resp.status_code not in (201, 204):
            raise RuntimeError(f"Upload failed: {resp.status_code} {resp.text[:200]}")

        share_url = get_existing_share_link(session, remote_path)
        if not share_url:
            share_url = create_nextcloud_share(session, remote_path)
        return share_url


def get_existing_share_link(session: requests.Session, remote_path: str) -> Optional[str]:
    shares = list_nextcloud_shares(session, remote_path)
    for share in shares:
        if share.get('share_type') == 3 and share.get('url'):
            return share['url']
    return None


def list_nextcloud_shares(session: requests.Session, remote_path: str) -> list[dict]:
    base = config.nextcloud_base_url.rstrip('/')
    endpoint = f"{base}/ocs/v2.php/apps/files_sharing/api/v1/shares"
    headers = {'OCS-APIRequest': 'true'}
    encoded_params = _serialize_params({
        'format': 'json',
        'path': f"/{_encode_relative_path(remote_path)}",
        'reshares': 'true'
    })
    url = f"{endpoint}?{encoded_params}"

    resp = _request_with_timeout(session, 'GET', url, headers=headers)
    if resp.status_code >= 400:
        raise RuntimeError(f"Share list API error: {resp.status_code} {resp.text[:200]}")

    ocs = _parse_ocs_payload(resp)
    data = ocs.get('data', [])
    if isinstance(data, dict):
        data = [data]
    return data


def create_nextcloud_share(session: requests.Session, remote_path: str) -> str:
    base = config.nextcloud_base_url.rstrip('/')
    endpoint = f"{base}/ocs/v2.php/apps/files_sharing/api/v1/shares"
    headers = {
        'OCS-APIRequest': 'true',
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    data = {
        'format': 'json',
        'path': f"/{_encode_relative_path(remote_path)}",
        'shareType': 3,
        'permissions': getattr(config, 'nextcloud_permissions', 1)
    }

    if getattr(config, 'nextcloud_share_password', None):
        data['password'] = config.nextcloud_share_password
    if getattr(config, 'nextcloud_public_upload', False):
        data['publicUpload'] = 'true'
    if getattr(config, 'nextcloud_share_label', None):
        data['label'] = config.nextcloud_share_label

    payload = _serialize_params(data)

    resp = _request_with_timeout(session, 'POST', endpoint, data=payload, headers=headers)
    if resp.status_code >= 400:
        raise RuntimeError(f"Share API error: {resp.status_code} {resp.text[:200]}")

    ocs = _parse_ocs_payload(resp)
    data = ocs.get('data', {})
    link = data.get('url') if isinstance(data, dict) else None
    if not link:
        raise RuntimeError(f"Share link missing in response: {ocs}")
    return link


YOUTUBE_REGEX = re.compile(
    r'(https?://)?(www\.)?'
    r'(youtube|youtu|youtube-nocookie)\.(com|be)/'
    r'(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})')


def youtube_url_validation(url):
    return YOUTUBE_REGEX.match(url)


# Define is_youtube to check if the URL belongs to a YouTube domain
def is_youtube(url):
    url_info = urlparse(url)
    netloc = url_info.netloc.lower()
    return netloc in SUPPORTED_YT_HOSTS


@bot.message_handler(commands=['start', 'help'])
def test(message):
    if not ensure_authorized(message):
        return

    bot.reply_to(
        message, "*Send me a video link* and I'll download it for you, works with *YouTube*, *Twitter*, *TikTok*, *Reddit* and more.\n\n_Powered by_ [yt-dlp](https://github.com/yt-dlp/yt-dlp/)", parse_mode="MARKDOWN", disable_web_page_preview=True)


def download_video(message, url, audio: bool = False, format_id: str = "bestvideo+bestaudio"):
    if not url:
        bot.reply_to(message, 'Invalid URL')
        return

    url = url.strip()
    url_info = urlparse(url)
    if not url_info.scheme:
        bot.reply_to(message, 'Invalid URL')
        return

    netloc = url_info.netloc.lower()

    # Blacklist
    if netloc in BLACKLISTED_DOMAINS or any(
        netloc.endswith('.' + blacklisted) for blacklisted in BLACKLISTED_DOMAINS
    ):
        bot.reply_to(message, f"Downloads from {netloc} are not allowed.")
        return

    is_yt = is_youtube(url)

    msg = bot.reply_to(message, 'Downloading...')
    progress_key = f"{message.chat.id}-{msg.message_id}"

    def progress(d):
        if d.get('status') != 'downloading':
            return
        try:
            now = datetime.datetime.now()
            update = False

            if progress_key in last_edited:
                if (now - last_edited[progress_key]).total_seconds() >= PROGRESS_UPDATE_INTERVAL:
                    update = True
            else:
                update = True

            if not update:
                return

            total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
            downloaded = d.get('downloaded_bytes')
            if not total_bytes or not downloaded:
                return

            perc = round(downloaded * 100 / total_bytes)
            title = d.get('info_dict', {}).get('title', 'the file')
            bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=msg.message_id,
                text=f"Downloading {title}\n\n{perc}%",
            )
            last_edited[progress_key] = now
        except Exception as e:
            print(f"Progress error: {e}")

    output_dir = Path(config.output_folder)
    output_dir.mkdir(parents=True, exist_ok=True)

    ydl_opts: dict[str, Any] = {
        'format': format_id,
        'outtmpl': str(output_dir / '%(title).95B-%(id)s.%(ext)s'),
        'progress_hooks': [progress],
        'retries': YTDLP_RETRIES,
        'fragment_retries': YTDLP_FRAGMENT_RETRIES,
        'continuedl': True,
        'force_overwrites': True,
    }

    if YTDLP_HTTP_CHUNK_SIZE:
        ydl_opts['http_chunk_size'] = YTDLP_HTTP_CHUNK_SIZE

    if config.max_filesize:
        # You said you don’t use Nextcloud, so we always enforce max_filesize
        ydl_opts['max_filesize'] = config.max_filesize

    configured_js_runtimes = getattr(config, 'js_runtimes', None)
    deno_path = getattr(config, 'deno_path', None)
    if configured_js_runtimes:
        ydl_opts['js_runtimes'] = configured_js_runtimes
    elif deno_path:
        ydl_opts['js_runtimes'] = {'deno': {'executable': deno_path}}

    remote_components = getattr(config, 'remote_components', None)
    if remote_components:
        ydl_opts['remote_components'] = remote_components

    if getattr(config, 'yt_dlp_verbose', True):
        ydl_opts['verbose'] = True

    # Audio-only mode -> extract MP3
    if audio:
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
        }]

    # Cookies
    cookies_youtube_only = getattr(config, 'cookies_youtube_only', False)
    if ((cookies_youtube_only and is_yt) or (not cookies_youtube_only)) and \
        COOKIES_PATH.exists() and COOKIES_PATH.stat().st_size > 0:
        ydl_opts['cookiefile'] = str(COOKIES_PATH)

    # netrc
    if getattr(config, 'use_netrc', False):
        ydl_opts['netrc'] = True
        netrc_location = getattr(config, 'netrc_path', None)
        if netrc_location:
            ydl_opts['netrc_location'] = netrc_location

    netrc_cmd = getattr(config, 'netrc_cmd', None)
    if netrc_cmd:
        ydl_opts['netrc_cmd'] = netrc_cmd

    # Force iPhone-friendly formats for VIDEO (not for /audio)
    if not audio:
        preferred_format = (
            "bv*[vcodec^=avc1][ext=mp4]+ba[ext=m4a]/"
            "b[vcodec^=avc1][ext=mp4]/"
            "best[ext=mp4]/best"
        )

        if format_id == "bestvideo+bestaudio":
            ydl_opts['format'] = preferred_format
        else:
            # keep custom choice but fall back to safe MP4 chain
            ydl_opts['format'] = f"{format_id}/{preferred_format}"

        ydl_opts['merge_output_format'] = 'mp4'

    downloaded_file: Optional[Path] = None
    final_file: Optional[Path] = None

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # type: ignore[arg-type]
            info = ydl.extract_info(url, download=True)

            # Figure out which file yt-dlp wrote
            requested = info.get('requested_downloads') or []
            if requested:
                downloaded_file = Path(requested[0]['filepath'])
            else:
                downloaded_file = Path(ydl.prepare_filename(info))
                if audio:
                    downloaded_file = downloaded_file.with_suffix('.mp3')

            if not downloaded_file:
                raise RuntimeError('Downloaded file path missing')

            # Re-encode for iPhone if this is video
            if audio:
                final_file = downloaded_file
            else:
                bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=msg.message_id,
                    text='Processing file with ffmpeg...',
                )
                final_file = convert_to_mp4(downloaded_file)

            # Send to Telegram
            with final_file.open('rb') as f:
                if audio:
                    bot.send_audio(
                        message.chat.id,
                        f,
                        reply_to_message_id=message.message_id,
                    )
                else:
                    width = info.get('width')
                    height = info.get('height')
                    if not (width and height) and requested:
                        width = width or requested[0].get('width')
                        height = height or requested[0].get('height')

                    bot.send_video(
                        message.chat.id,
                        f,
                        reply_to_message_id=message.message_id,
                        width=width,
                        height=height,
                    )

            bot.delete_message(message.chat.id, msg.message_id)

    except DownloadError:
        bot.edit_message_text('Invalid URL or download error', message.chat.id, msg.message_id)
    except Exception as e:
        print(f"Download/Send error: {e}")
        bot.edit_message_text(
            f"There was an error downloading your video, make sure it doesn't exceed *{round(config.max_filesize / 1000000)}MB*",
            message.chat.id,
            msg.message_id,
            parse_mode="MARKDOWN",
        )
    finally:
        if progress_key in last_edited:
            del last_edited[progress_key]

        safe_unlink(downloaded_file if downloaded_file and downloaded_file != final_file else None)
        safe_unlink(final_file if final_file and final_file != downloaded_file else None)



def log(message, text: str, media: str):
    if not config.logs:
        return

    if message.chat.type == 'private':
        chat_info = "Private chat"
    else:
        chat_title = message.chat.title or 'Unknown group'
        chat_info = f"Group: *{chat_title}* (`{message.chat.id}`)"

    username = message.from_user.username or 'unknown'
    payload = (
        f"Download request ({media}) from @{username} ({message.from_user.id})"
        f"\n\n{chat_info}\n\n{text}"
    )

    try:
        bot.send_message(config.logs, payload)
    except ApiTelegramException as exc:
        # Log but do not crash if the logging chat is invalid or unreachable
        print(f"Logging failed ({exc})")


def get_text(message):
    raw_text = (message.text or '').strip()

    if raw_text:
        parts = raw_text.split(maxsplit=1)
        if len(parts) == 2:
            return parts[1].strip()

    if message.reply_to_message:
        fallback = message.reply_to_message.text or message.reply_to_message.caption
        return fallback.strip() if fallback else None

    return None


def is_authorized_user(user_id: Optional[int]) -> bool:
    if not ADMIN_IDS:
        return True
    return user_id in ADMIN_IDS


def ensure_authorized(message) -> bool:
    user = getattr(message, 'from_user', None)
    user_id = getattr(user, 'id', None)
    if is_authorized_user(user_id):
        return True

    bot.reply_to(message, 'You are not authorized to use this bot.')
    return False


def _extract_login_payload(message):
    payload = get_text(message)
    if payload:
        return payload

    if message.reply_to_message:
        fallback = message.reply_to_message.text or message.reply_to_message.caption
        if fallback:
            return fallback.strip()

    return None


@bot.message_handler(commands=['login'])
def login_command(message):
    if not ensure_authorized(message):
        return

    if message.chat.type != 'private':
        bot.reply_to(message, 'Please DM me to share login information.')
        return

    payload = _extract_login_payload(message)
    if not payload:
        bot.reply_to(
            message,
            'Send `/login <cookies>` or reply `/login` to a cookies message.\n\n'
            f"{LOGIN_HELP_TEXT}",
            parse_mode="MARKDOWN",
        )
        return

    try:
        COOKIES_PATH.parent.mkdir(parents=True, exist_ok=True)
        COOKIES_PATH.write_text(payload.strip() + '\n', encoding='utf-8')
    except OSError as exc:
        bot.reply_to(message, f"Couldn't save cookies: {exc}")
        return

    bot.reply_to(message, 'Cookies saved. Try your members-only download again.')


@bot.message_handler(commands=['download'])
def download_command(message):
    if not ensure_authorized(message):
        return

    text = get_text(message)
    if not text:
        bot.reply_to(
            message, 'Invalid usage, use `/download url`', parse_mode="MARKDOWN")
        return

    log(message, text, 'video')
    download_video(message, text)


@bot.message_handler(commands=['audio'])
def download_audio_command(message):
    if not ensure_authorized(message):
        return

    text = get_text(message)
    if not text:
        bot.reply_to(
            message, 'Invalid usage, use `/audio url`', parse_mode="MARKDOWN")
        return

    log(message, text, 'audio')
    download_video(message, text, True)


@bot.message_handler(commands=['custom'])
def custom(message):
    if not ensure_authorized(message):
        return

    text = get_text(message)
    if not text:
        bot.reply_to(
            message, 'Invalid usage, use `/custom url`', parse_mode="MARKDOWN")
        return

    msg = bot.reply_to(message, 'Getting formats...')

    with yt_dlp.YoutubeDL() as ydl:
        info = ydl.extract_info(text, download=False)

    formats = info.get('formats') or []
    data = {
        f"{x.get('resolution', 'unknown')}.{x.get('ext', 'mp4')}": {
            'callback_data': f"{x.get('format_id')}"
        }
        for x in formats
        if x.get('video_ext') != 'none' and x.get('format_id')
    }

    markup = quick_markup(data, row_width=2)

    bot.delete_message(msg.chat.id, msg.message_id)
    bot.reply_to(message, "Choose a format", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    if not is_authorized_user(getattr(call.from_user, 'id', None)):
        bot.answer_callback_query(call.id, "You are not authorized to use this bot.")
        return

    if call.from_user.id == call.message.reply_to_message.from_user.id:
        url = get_text(call.message.reply_to_message)
        bot.delete_message(call.message.chat.id, call.message.message_id)
        download_video(call.message.reply_to_message, url,
                       format_id=f"{call.data}+bestaudio")
    else:
        bot.answer_callback_query(call.id, "You didn't send the request")


@bot.message_handler(func=lambda m: True, content_types=["text", "pinned_message", "photo", "audio", "video", "location", "contact", "voice", "document"])
def handle_private_messages(message):
    if not ensure_authorized(message):
        return

    text = (message.text or message.caption or '').strip()

    if message.chat.type == 'private':
        if not text:
            return
        if text.startswith('/'):
            return
        log(message, text, 'video')
        download_video(message, text)

if __name__ == '__main__':
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=20)
        except Exception as e:
            print(f"[polling error] {e!r}")
            time.sleep(2)
