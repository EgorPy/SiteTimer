from ved3v_ascii_art import art

from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi import FastAPI
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.oid import NameOID
from cryptography import x509
import uiautomation as auto
import uvicorn

from datetime import datetime, timedelta
import threading
import asyncio
import ctypes
import json
import time
import os

HOSTS_PATH = r"C:\Windows\System32\drivers\etc\hosts"
REDIRECT = "127.0.0.1"

SITES_TO_BLOCK = [
    {"name": "YouTube", "domain": "youtube.com", "hosts": ["youtube.com", "www.youtube.com"], "match": ["youtube.com"]},
    {"name": "Instagram", "domain": "instagram.com", "hosts": ["instagram.com", "www.instagram.com"], "match": ["instagram.com"]},
    {"name": "Spotify", "domain": "open.spotify.com", "hosts": ["open.spotify.com"],
     "match": ["open.spotify.com", "spotify.com"]},
]

DAILY_LIMIT_MINUTES = 0
CHECK_INTERVAL_SECONDS = 2
USAGE_FILE = "usage_data.json"
SITE_LOG_FILE = "site_log.json"

MARKER_START = "# BLOCK_START"
MARKER_END = "# BLOCK_END"

CERT_FILE = "block_cert.pem"
KEY_FILE = "block_key.pem"

ADDRESS_BAR_NAMES = [
    "Address and search bar",  # Chrome, Edge (EN)
    "Search or enter address",  # Firefox (EN)
    "Адресная строка и строка поиска",  # Chrome, Edge (RU)
    "Поиск или введите адрес",  # Firefox (RU)
]

user32 = ctypes.windll.user32


def get_active_window_title():
    hwnd = user32.GetForegroundWindow()
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value.lower()


def get_active_tab_url():
    try:
        top = auto.GetForegroundControl()
        if top is None:
            return ""
        for name in ADDRESS_BAR_NAMES:
            edit = top.EditControl(searchDepth=10, Name=name)
            if edit.Exists(0, 0):
                value = edit.GetValuePattern().Value
                if value:
                    return value.lower()
    except Exception:
        pass
    return ""


def match_site(url, title):
    if url:
        for site in SITES_TO_BLOCK:
            if any(m in url for m in site["match"]):
                return site
        return None

    for site in SITES_TO_BLOCK:
        if any(m in title for m in site["match"]):
            return site
    return None


_last_debug_signal = None


def debug_log_signal(signal, matched):
    global _last_debug_signal
    if signal != _last_debug_signal:
        print(f"[сигнал] '{signal}' -> {matched['name'] if matched else 'нет совпадения'}")
        _last_debug_signal = signal


state_lock = threading.Lock()
state = {
    "minutes_used": 0.0,
    "blocked": False,
    "updated_at": None,
}


def load_usage():
    today = datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(USAGE_FILE):
        with open(USAGE_FILE, "r") as f:
            data = json.load(f)
        if data.get("date") == today:
            return data
    return {"date": today, "minutes_used": 0}


def save_usage(data):
    with open(USAGE_FILE, "w") as f:
        json.dump(data, f)


def load_site_log():
    today = datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(SITE_LOG_FILE):
        with open(SITE_LOG_FILE, "r") as f:
            data = json.load(f)
        if data.get("date") == today:
            return data
    return {"date": today, "sites": {}}


def save_site_log(data):
    with open(SITE_LOG_FILE, "w") as f:
        json.dump(data, f)


def is_blocked():
    with open(HOSTS_PATH, "r") as f:
        return MARKER_START in f.read()


def all_blocked_hosts():
    hosts = []
    for site in SITES_TO_BLOCK:
        hosts.extend(site["hosts"])
    return hosts


def block_sites():
    if is_blocked():
        return
    with open(HOSTS_PATH, "a") as f:
        f.write(f"\n{MARKER_START}\n")
        for host in all_blocked_hosts():
            f.write(f"{REDIRECT} {host}\n")
        f.write(f"{MARKER_END}\n")
    print(f"[{datetime.now().strftime('%H:%M')}] Limit exceeded, sites blocked.")


def unblock_sites():
    if not is_blocked():
        return
    with open(HOSTS_PATH, "r") as f:
        lines = f.readlines()

    new_lines, inside = [], False
    for line in lines:
        if MARKER_START in line:
            inside = True
            continue
        if MARKER_END in line:
            inside = False
            continue
        if not inside:
            new_lines.append(line)

    with open(HOSTS_PATH, "w") as f:
        f.writelines(new_lines)


def monitor_loop():
    ctypes.windll.ole32.CoInitialize(None)
    print("Checking screen time...")
    last_tick = time.monotonic()
    while True:
        now = time.monotonic()
        elapsed_seconds = now - last_tick
        last_tick = now

        usage = load_usage()
        site_log = load_site_log()

        url = get_active_tab_url()
        signal = url if url else get_active_window_title()
        site = match_site(url, signal)
        debug_log_signal(signal, site)

        if usage["minutes_used"] < DAILY_LIMIT_MINUTES:
            unblock_sites()
            if site is not None:
                usage["minutes_used"] += elapsed_seconds / 60
                save_usage(usage)

                entry = site_log["sites"].setdefault(
                    site["domain"], {"minutes": 0, "last_active_at": None}
                )
                entry["minutes"] += elapsed_seconds / 60
                entry["last_active_at"] = datetime.now().isoformat()
                save_site_log(site_log)
            blocked = False
        else:
            block_sites()
            blocked = True

        with state_lock:
            state["minutes_used"] = usage["minutes_used"]
            state["blocked"] = blocked
            state["active_domain"] = site["domain"] if site else None
            state["site_log"] = site_log["sites"]
            state["updated_at"] = datetime.now().isoformat()

        time.sleep(CHECK_INTERVAL_SECONDS)


app = FastAPI()
pages = Jinja2Templates(directory="pages")

BLOCK_PAGE_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>заблокировано</title>
<style>
  body{
    background:#0a0a0a;color:#dcdcdc;
    font-family:'JetBrains Mono','Consolas',monospace;
    display:flex;align-items:center;justify-content:center;
    height:100vh;margin:0;text-align:center;
  }
  div{max-width:420px;padding:24px}
  h1{font-size:20px;color:#c0503c;margin-bottom:12px}
  p{font-size:14px;color:#767676;line-height:1.5}
  a{color:#dcdcdc}
</style>
</head>
<body>
  <div>
    <h1>сайт заблокирован</h1>
    <p>дневной лимит экранного времени исчерпан.<br>доступ откроется завтра.</p>
    <p><a href="http://localhost:4000">открыть дашборд</a></p>
  </div>
</body>
</html>"""


def ensure_self_signed_cert():
    """Один раз генерирует самоподписанный сертификат на заблокированные
    домены (pip install cryptography). Браузер всё равно покажет
    предупреждение о безопасности, пока вы вручную не добавите
    block_cert.pem в доверенные корневые сертификаты Windows
    (certmgr.msc -> Доверенные корневые центры сертификации -> Импорт)."""
    if os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE):
        return

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "site-blocker-local")])
    domains = all_blocked_hosts()

    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.utcnow())
        .not_valid_after(datetime.utcnow() + timedelta(days=825))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(d) for d in domains]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    with open(CERT_FILE, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(KEY_FILE, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
    print(f"Сгенерирован {CERT_FILE}. Установите его в доверенные корневые "
          f"сертификаты Windows, иначе браузер продолжит показывать предупреждение.")


@app.middleware("http")
async def block_page_middleware(request: Request, call_next):
    host = request.headers.get("host", "").split(":")[0].lower()
    if host not in ("localhost", "127.0.0.1"):
        with state_lock:
            blocked = state["blocked"]
        if blocked:
            return RedirectResponse(url="http://localhost:4000")
    return await call_next(request)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return pages.TemplateResponse(name="index.html", request=request)


@app.get("/api/status", response_class=JSONResponse)
def status(request: Request):
    with state_lock:
        minutes_used = state["minutes_used"]
        blocked = state["blocked"]
        active_domain = state.get("active_domain")
        site_log = state.get("site_log", {})

    return {
        "minutesUsed": round(minutes_used, 1),
        "dailyLimit": DAILY_LIMIT_MINUTES,
        "blocked": blocked,
        "sites": [
            {
                "name": s["name"],
                "domain": s["domain"],
                "blocked": blocked,
                "active": s["domain"] == active_domain,
                "todayMinutes": round(site_log.get(s["domain"], {}).get("minutes", 0), 1),
                "lastActive": site_log.get(s["domain"], {}).get("last_active_at"),
            }
            for s in SITES_TO_BLOCK
        ],
    }


async def run_servers():
    dashboard = uvicorn.Server(uvicorn.Config(app, host="localhost", port=4000, log_level="info"))
    https_catcher = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=443,
        ssl_certfile=CERT_FILE, ssl_keyfile=KEY_FILE,
        log_level="warning",
    ))
    await asyncio.gather(dashboard.serve(), https_catcher.serve())


if __name__ == "__main__":
    print(art)
    ensure_self_signed_cert()
    threading.Thread(target=monitor_loop, daemon=True).start()
    asyncio.run(run_servers())
