import hashlib
import hmac
import json
import os
import urllib.parse
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db

BOT_TOKEN = os.getenv("BOT_TOKEN", "")


def verify_telegram_data(init_data: str) -> dict | None:
    """Проверяет подпись Telegram Mini App initData."""
    parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(parsed.items())
    )
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        return None

    user_json = parsed.get("user")
    if user_json:
        return json.loads(user_json)
    return {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_user(request: Request) -> dict:
    """Извлекает и проверяет пользователя из заголовка X-Init-Data."""
    init_data = request.headers.get("X-Init-Data", "")
    # В dev-режиме пропускаем проверку
    if os.getenv("DEV_MODE") == "1":
        return {"id": 0, "first_name": "Dev", "username": "dev"}
    user = verify_telegram_data(init_data)
    if user is None:
        raise HTTPException(status_code=401, detail="Неверная подпись Telegram")
    return user


# --- Эндпоинты ---

@app.get("/api/calendar/{year}/{month}")
async def get_calendar(year: int, month: int, request: Request):
    get_user(request)
    days = await db.get_days_with_slots(year, month)
    return {"days": days}


@app.get("/api/slots/{date}")
async def get_slots(date: str, request: Request):
    get_user(request)
    slots = await db.get_slots_by_date(date)
    return {"slots": slots}


class BookRequest(BaseModel):
    slot_id: int
    role: str  # coach / client / curator / viewer


@app.post("/api/book")
async def book(payload: BookRequest, request: Request):
    user = get_user(request)
    if payload.role not in ("coach", "client", "curator", "viewer"):
        raise HTTPException(status_code=400, detail="Неверная роль")
    result = await db.book_slot(
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
    ok = await db.cancel_booking(slot_id, user.get("id", 0))
    if not ok:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    return {"ok": True}


# Статика Mini App
app.mount("/", StaticFiles(directory="webapp", html=True), name="webapp")
