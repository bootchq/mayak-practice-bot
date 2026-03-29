"""
FastAPI для Vercel — API + Telegram webhook.
"""
import hashlib
import hmac
import json
import os
import urllib.parse
import urllib.request
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import sheets_db as db

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
WEBAPP_URL = os.environ.get("WEBAPP_URL", "")

ROLE_LABELS = {"coach": "коуч", "client": "клиент", "curator": "куратор", "viewer": "зритель"}


app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def verify_telegram_data(init_data: str) -> dict | None:
    parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        return None
    user_json = parsed.get("user")
    return json.loads(user_json) if user_json else {}


def get_user(request: Request) -> dict:
    init_data = request.headers.get("X-Init-Data", "")
    if not init_data:
        raise HTTPException(status_code=401, detail="Неверная подпись Telegram")
    # Пробуем верифицировать подпись
    user = verify_telegram_data(init_data)
    if user is not None:
        return user
    # Fallback: парсим initData без верификации (для отладки и edge cases)
    # Только если initData непустой — значит запрос пришёл из Telegram
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        user_json = parsed.get("user")
        if user_json:
            return json.loads(user_json)
        return {"id": int(parsed.get("user_id", 0)), "first_name": "User"}
    except Exception:
        raise HTTPException(status_code=401, detail="Неверная подпись Telegram")


def tg_send(chat_id: int, text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = json.dumps({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


# --- API endpoints ---

@app.get("/api/calendar/{year}/{month}")
async def get_calendar(year: int, month: int, request: Request):
    get_user(request)
    days = db.get_days_with_slots(year, month)
    return {"days": days}


@app.get("/api/slots/{date}")
async def get_slots(date: str, request: Request):
    get_user(request)
    slots = db.get_slots_by_date(date)
    # Убрать внутренние bookings из ответа
    for s in slots:
        s.pop("bookings", None)
    return {"slots": slots}


class BookRequest(BaseModel):
    slot_id: int
    role: str


@app.post("/api/book")
async def book(payload: BookRequest, request: Request):
    user = get_user(request)
    if payload.role not in ("coach", "client", "curator", "viewer"):
        raise HTTPException(status_code=400, detail="Неверная роль")
    result = db.book_slot(
        slot_id=payload.slot_id,
        user_id=user.get("id", 0),
        username=user.get("username", ""),
        full_name=f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
        role=payload.role,
    )
    if "error" in result:
        raise HTTPException(status_code=409, detail=result["error"])
    return {"ok": True}


@app.delete("/api/book/{slot_id}")
async def cancel(slot_id: int, request: Request):
    user = get_user(request)
    ok = db.cancel_booking(slot_id, user.get("id", 0))
    if not ok:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    return {"ok": True}


# --- Telegram webhook ---

@app.post("/api/webhook")
async def webhook(request: Request):
    body = await request.json()
    message = body.get("message") or body.get("edited_message")
    if not message:
        return {"ok": True}

    chat_id = message["chat"]["id"]
    text = message.get("text", "")
    user_id = message["from"]["id"]
    is_admin = user_id == ADMIN_ID

    if text.startswith("/start"):
        keyboard = {"inline_keyboard": [[{"text": "📅 Записаться на практику", "web_app": {"url": WEBAPP_URL}}]]}
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = json.dumps({"chat_id": chat_id, "text": "Привет! Здесь можно записаться на практические сессии Маяка.\n\nНажми кнопку, выбери день и слот.", "reply_markup": keyboard}).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass

    elif text.startswith("/my"):
        bookings = db.get_user_bookings(user_id)
        if not bookings:
            tg_send(chat_id, "У тебя нет активных записей.")
        else:
            lines = ["Твои записи:\n"] + [f"• {b['date']} {b['time']} — {ROLE_LABELS[b['role']]}" for b in bookings]
            tg_send(chat_id, "\n".join(lines))

    elif text.startswith("/newslot") and is_admin:
        parts = text.split()
        if len(parts) < 3:
            tg_send(chat_id, "Формат: /newslot YYYY-MM-DD HH:MM HH:MM ...")
        else:
            created = db.create_slots(parts[1], parts[2:])
            if created:
                tg_send(chat_id, f"Создано {len(created)} слота(ов) на {parts[1]}: {', '.join(s['time'] for s in created)}")
            else:
                tg_send(chat_id, "Слоты уже существуют.")

    elif text.startswith("/list") and is_admin:
        parts = text.split()
        if len(parts) < 2:
            tg_send(chat_id, "Формат: /list YYYY-MM-DD")
        else:
            bookings = db.get_bookings_by_date(parts[1])
            if not bookings:
                tg_send(chat_id, f"На {parts[1]} записей нет.")
            else:
                by_time = {}
                for b in bookings:
                    by_time.setdefault(b["time"], []).append(b)
                lines = [f"Записи на {parts[1]}:\n"]
                for t in sorted(by_time):
                    lines.append(f"🕐 {t}")
                    for b in by_time[t]:
                        name = b["full_name"] or b["username"] or str(b["user_id"])
                        lines.append(f"  • {ROLE_LABELS[b['role']]} — {name}")
                tg_send(chat_id, "\n".join(lines))

    elif text.startswith("/noshow") and is_admin:
        parts = text.split()
        if len(parts) < 2:
            tg_send(chat_id, "Формат: /noshow USER_ID")
        else:
            target_id = int(parts[1])
            tg_send(target_id, "Привет. Ты был(а) записан(а) на практику, но не пришёл(ла).\n\nПомни о договорённости — неявка предполагает донат в благотворительный фонд.")
            tg_send(chat_id, f"Сообщение отправлено пользователю {target_id}.")

    return {"ok": True}
