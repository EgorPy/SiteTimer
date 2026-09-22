from ved3v_ascii_art import art

from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi import FastAPI
import uvicorn

from datetime import datetime
import threading
import ctypes
import json
import time
import os

HOSTS_PATH = r"C:\Windows\System32\drivers\etc\hosts"
REDIRECT = "localhost"

SITES_TO_BLOCK = [
    {"name": "YouTube", "domain": "youtube.com", "hosts": ["youtube.com", "www.youtube.com"], "keywords": ["youtube"]},
    {"name": "Instagram", "domain": "instagram.com", "hosts": ["instagram.com", "www.instagram.com"], "keywords": ["instagram"]},
    {"name": "Spotify", "domain": "open.spotify.com", "hosts": ["open.spotify.com"], "keywords": ["spotify"]},
]

DAILY_LIMIT_MINUTES = 60
CHECK_INTERVAL_SECONDS = 2
USAGE_FILE = "usage_data.json"
SITE_LOG_FILE = "site_log.json"

MARKER_START = "# BLOCK_START"
MARKER_END = "# BLOCK_END"

user32 = ctypes.windll.user32


def get_active_window_title():
    hwnd = user32.GetForegroundWindow()
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value.lower()


def active_site():
    title = get_active_window_title()
    for site in SITES_TO_BLOCK:
        if any(kw in title for kw in site["keywords"]):
            return site
    return None


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
    print("Running")
    print("Checking screen time")
    while True:
        usage = load_usage()
        site_log = load_site_log()
        site = active_site()

        if usage["minutes_used"] < DAILY_LIMIT_MINUTES:
            unblock_sites()
            if site is not None:
                usage["minutes_used"] += CHECK_INTERVAL_SECONDS / 60
                save_usage(usage)

                entry = site_log["sites"].setdefault(
                    site["domain"], {"minutes": 0, "last_active_at": None}
                )
                entry["minutes"] += CHECK_INTERVAL_SECONDS / 60
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


if __name__ == "__main__":
    print(art)
    threading.Thread(target=monitor_loop, daemon=True).start()
    uvicorn.run(app, host="localhost", port=4000)
