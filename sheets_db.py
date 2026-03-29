"""
База данных через Google Sheets.
Листы: Практика_Slots (id, date, time) | Практика_Bookings (slot_id, user_id, username, full_name, role, created_at)
"""
import base64
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime

# --- Auth ---

_token_cache = {"token": None, "expires": 0}


def _get_token() -> str:
    if _token_cache["token"] and time.time() < _token_cache["expires"] - 60:
        return _token_cache["token"]

    sa = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])

    try:
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.backends import default_backend
    except ImportError:
        raise RuntimeError("cryptography package required")

    now = int(time.time())
    claim = {
        "iss": sa["client_email"],
        "scope": "https://www.googleapis.com/auth/spreadsheets",
        "aud": "https://oauth2.googleapis.com/token",
        "exp": now + 3600,
        "iat": now,
    }

    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    h, p = b64({"alg": "RS256", "typ": "JWT"}), b64(claim)
    msg = f"{h}.{p}".encode()
    key = serialization.load_pem_private_key(sa["private_key"].encode(), password=None, backend=default_backend())
    sig = key.sign(msg, padding.PKCS1v15(), hashes.SHA256())
    jwt = f"{h}.{p}.{base64.urlsafe_b64encode(sig).rstrip(b'=').decode()}"

    data = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": jwt,
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    with urllib.request.urlopen(req) as r:
        resp = json.load(r)
        _token_cache["token"] = resp["access_token"]
        _token_cache["expires"] = now + resp["expires_in"]
        return _token_cache["token"]


def _sheets_get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {_get_token()}"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def _sheets_post(url: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {_get_token()}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)


SHEET_ID = os.environ.get("SPREADSHEET_ID", "1to83Pw9vjl6p1RnnrJT-qtHc85x5s2U_qYp6jSZKhYM")
BASE = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}"


# --- Helpers ---

def _read_range(range_: str) -> list[list]:
    url = f"{BASE}/values/{urllib.parse.quote(range_)}"
    data = _sheets_get(url)
    return data.get("values", [])


def _append_row(sheet: str, values: list):
    url = f"{BASE}/values/{urllib.parse.quote(sheet)}:append?valueInputOption=RAW&insertDataOption=INSERT_ROWS"
    _sheets_post(url, {"values": [values]})


def _update_range(range_: str, values: list[list]):
    url = f"{BASE}/values/{urllib.parse.quote(range_)}?valueInputOption=RAW"
    req = urllib.request.Request(
        url, data=json.dumps({"values": values}).encode(),
        headers={"Authorization": f"Bearer {_get_token()}", "Content-Type": "application/json"},
        method="PUT",
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def _next_slot_id() -> int:
    rows = _read_range("Практика_Slots!A2:A")
    if not rows:
        return 1
    ids = [int(r[0]) for r in rows if r and r[0].isdigit()]
    return max(ids) + 1 if ids else 1


# --- Публичный API ---

def init_headers():
    """Установить заголовки если листы пустые."""
    slots = _read_range("Практика_Slots!A1:C1")
    if not slots:
        _update_range("Практика_Slots!A1:C1", [["id", "date", "time"]])
    bookings = _read_range("Практика_Bookings!A1:F1")
    if not bookings:
        _update_range("Практика_Bookings!A1:F1", [["slot_id", "user_id", "username", "full_name", "role", "created_at"]])


def create_slots(date: str, times: list[str]) -> list[dict]:
    existing = get_slots_by_date(date)
    existing_times = {s["time"] for s in existing}
    created = []
    for t in times:
        if t not in existing_times:
            slot_id = _next_slot_id()
            _append_row("Практика_Slots", [slot_id, date, t])
            created.append({"id": slot_id, "date": date, "time": t})
    return created


def get_slots_by_date(date: str) -> list[dict]:
    slots_rows = _read_range("Практика_Slots!A2:C")
    booking_rows = _read_range("Практика_Bookings!A2:F")

    slots = []
    for row in slots_rows:
        if len(row) >= 3 and row[1] == date:
            slot_id = int(row[0])
            roles = {"coach": 0, "client": 0, "curator": 0, "viewer": 0}
            bookings_list = []
            for br in booking_rows:
                if len(br) >= 5 and int(br[0]) == slot_id:
                    r = br[4]
                    if r in roles:
                        roles[r] += 1
                    bookings_list.append({
                        "user_id": int(br[1]),
                        "username": br[2] if len(br) > 2 else "",
                        "full_name": br[3] if len(br) > 3 else "",
                        "role": r,
                    })
            slots.append({
                "id": slot_id,
                "date": row[1],
                "time": row[2],
                "roles": roles,
                "bookings": bookings_list,
            })
    return sorted(slots, key=lambda s: s["time"])


def get_days_with_slots(year: int, month: int) -> list[str]:
    slots_rows = _read_range("Практика_Slots!A2:C")
    prefix = f"{year}-{month:02d}-"
    days = set()
    for row in slots_rows:
        if len(row) >= 2 and row[1].startswith(prefix):
            days.add(row[1])
    return sorted(days)


def book_slot(slot_id: int, user_id: int, username: str, full_name: str, role: str) -> dict:
    booking_rows = _read_range("Практика_Bookings!A2:F")
    limited = {"coach": 1, "client": 1, "curator": 1}

    role_count = 0
    for br in booking_rows:
        if len(br) >= 5 and int(br[0]) == slot_id:
            if int(br[1]) == user_id:
                return {"error": "Ты уже записан на этот слот"}
            if br[4] == role:
                role_count += 1

    if role in limited and role_count >= limited[role]:
        return {"error": f"Роль '{role}' уже занята"}

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    _append_row("Практика_Bookings", [slot_id, user_id, username, full_name, role, now])
    return {"ok": True}


def cancel_booking(slot_id: int, user_id: int) -> bool:
    rows = _read_range("Практика_Bookings!A2:F")
    for i, row in enumerate(rows):
        if len(row) >= 2 and int(row[0]) == slot_id and int(row[1]) == user_id:
            # Очищаем строку (row index + 2 из-за заголовка)
            row_num = i + 2
            _update_range(f"Практика_Bookings!A{row_num}:F{row_num}", [["", "", "", "", "", ""]])
            return True
    return False


def get_bookings_by_date(date: str) -> list[dict]:
    slots_rows = _read_range("Практика_Slots!A2:C")
    booking_rows = _read_range("Практика_Bookings!A2:F")

    slot_map = {}
    for row in slots_rows:
        if len(row) >= 3 and row[1] == date:
            slot_map[int(row[0])] = row[2]

    result = []
    for br in booking_rows:
        if len(br) >= 5 and br[0] and int(br[0]) in slot_map:
            result.append({
                "slot_id": int(br[0]),
                "time": slot_map[int(br[0])],
                "user_id": int(br[1]),
                "username": br[2] if len(br) > 2 else "",
                "full_name": br[3] if len(br) > 3 else "",
                "role": br[4],
            })
    return sorted(result, key=lambda x: (x["time"], x["role"]))


def get_user_bookings(user_id: int) -> list[dict]:
    slots_rows = _read_range("Практика_Slots!A2:C")
    booking_rows = _read_range("Практика_Bookings!A2:F")

    slot_map = {int(r[0]): {"date": r[1], "time": r[2]} for r in slots_rows if len(r) >= 3}
    result = []
    from datetime import date
    today = date.today().isoformat()
    for br in booking_rows:
        if len(br) >= 5 and br[0] and int(br[1]) == user_id:
            sid = int(br[0])
            if sid in slot_map and slot_map[sid]["date"] >= today:
                result.append({
                    "slot_id": sid,
                    "date": slot_map[sid]["date"],
                    "time": slot_map[sid]["time"],
                    "role": br[4],
                })
    return sorted(result, key=lambda x: (x["date"], x["time"]))
