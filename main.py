import asyncio
import logging
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

import db

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])
WEBAPP_URL = os.environ["WEBAPP_URL"]

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

ROLE_LABELS = {
    "coach": "коуч",
    "client": "клиент",
    "curator": "куратор",
    "viewer": "зритель",
}


# --- Команды студентов ---

@dp.message(Command("start"))
async def cmd_start(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="📅 Записаться на практику",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )
    ]])
    await message.answer(
        "Привет! Здесь можно записаться на практические сессии Маяка.\n\n"
        "Нажми кнопку, выбери день и слот — и забронируй своё место.",
        reply_markup=keyboard
    )


@dp.message(Command("my"))
async def cmd_my(message: Message):
    """Показать свои записи."""
    user_id = message.from_user.id
    # Ищем записи по всем слотам
    async with __import__("aiosqlite").connect(db.DB_PATH) as conn:
        conn.row_factory = __import__("aiosqlite").Row
        cursor = await conn.execute(
            """SELECT s.date, s.time, b.role, s.id as slot_id
               FROM bookings b JOIN slots s ON b.slot_id = s.id
               WHERE b.user_id = ? AND s.date >= date('now')
               ORDER BY s.date, s.time""",
            (user_id,)
        )
        rows = await cursor.fetchall()

    if not rows:
        await message.answer("У тебя нет активных записей.")
        return

    lines = ["Твои записи:\n"]
    for r in rows:
        lines.append(f"• {r['date']} {r['time']} — {ROLE_LABELS[r['role']]}")
    await message.answer("\n".join(lines))


# --- Команды админа ---

def admin_only(message: Message) -> bool:
    return message.from_user.id == ADMIN_ID


@dp.message(Command("newslot"), F.from_user.id == ADMIN_ID)
async def cmd_newslot(message: Message):
    """
    /newslot 2026-04-01 10:00 15:00 19:00
    """
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("Формат: /newslot YYYY-MM-DD HH:MM HH:MM ...")
        return

    date = parts[1]
    times = parts[2:]

    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        await message.answer("Неверный формат даты. Нужно YYYY-MM-DD")
        return

    created = await db.create_slots(date, times)
    if created:
        times_str = ", ".join(s["time"] for s in created)
        await message.answer(f"Создано {len(created)} слота(ов) на {date}: {times_str}")
    else:
        await message.answer("Слоты уже существуют или ошибка.")


@dp.message(Command("list"), F.from_user.id == ADMIN_ID)
async def cmd_list(message: Message):
    """
    /list 2026-04-01
    """
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Формат: /list YYYY-MM-DD")
        return

    date = parts[1]
    bookings = await db.get_bookings_by_date(date)

    if not bookings:
        await message.answer(f"На {date} записей нет.")
        return

    # Группируем по времени
    by_time = {}
    for b in bookings:
        t = b["time"]
        if t not in by_time:
            by_time[t] = []
        by_time[t].append(b)

    lines = [f"Записи на {date}:\n"]
    for t in sorted(by_time):
        lines.append(f"🕐 {t}")
        for b in by_time[t]:
            name = b["full_name"] or b["username"] or str(b["user_id"])
            lines.append(f"  • {ROLE_LABELS[b['role']]} — {name}")
    await message.answer("\n".join(lines))


@dp.message(Command("noshow"), F.from_user.id == ADMIN_ID)
async def cmd_noshow(message: Message):
    """
    /noshow USER_ID SLOT_ID
    Отметить неявку и отправить напоминание про фонд.
    """
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("Формат: /noshow USER_ID SLOT_ID")
        return

    try:
        user_id = int(parts[1])
        slot_id = int(parts[2])
    except ValueError:
        await message.answer("USER_ID и SLOT_ID должны быть числами")
        return

    booking = await db.mark_noshow(slot_id, user_id)
    if not booking:
        await message.answer("Запись не найдена.")
        return

    try:
        await bot.send_message(
            user_id,
            "Привет. Ты был(а) записан(а) на практическую сессию, но не пришёл(ла).\n\n"
            "Помни о нашей договорённости — неявка без отмены предполагает донат "
            "в благотворительный фонд. Пожалуйста, сделай это."
        )
        await message.answer(f"Сообщение отправлено пользователю {user_id}.")
    except Exception as e:
        await message.answer(f"Не удалось отправить сообщение: {e}")


@dp.message(Command("delslot"), F.from_user.id == ADMIN_ID)
async def cmd_delslot(message: Message):
    """
    /delslot SLOT_ID
    """
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Формат: /delslot SLOT_ID")
        return
    slot_id = int(parts[1])
    async with __import__("aiosqlite").connect(db.DB_PATH) as conn:
        await conn.execute("DELETE FROM bookings WHERE slot_id = ?", (slot_id,))
        await conn.execute("DELETE FROM slots WHERE id = ?", (slot_id,))
        await conn.commit()
    await message.answer(f"Слот {slot_id} удалён.")


async def main():
    await db.init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
