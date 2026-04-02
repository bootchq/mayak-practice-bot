from __future__ import annotations

import aiosqlite
import os

DB_PATH = os.getenv("DB_PATH", "practice.db")


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                UNIQUE(date, time)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slot_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT,
                full_name TEXT,
                role TEXT NOT NULL CHECK(role IN ('coach', 'client', 'curator', 'viewer')),
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(slot_id, user_id),
                FOREIGN KEY(slot_id) REFERENCES slots(id)
            )
        """)
        await db.commit()


async def create_slots(date: str, times: list[str]) -> list[dict]:
    """Создать слоты на дату. Возвращает список созданных слотов."""
    created = []
    async with aiosqlite.connect(DB_PATH) as db:
        for t in times:
            try:
                cursor = await db.execute(
                    "INSERT INTO slots (date, time) VALUES (?, ?)", (date, t)
                )
                await db.commit()
                created.append({"id": cursor.lastrowid, "date": date, "time": t})
            except aiosqlite.IntegrityError:
                pass  # слот уже существует
    return created


async def get_slots_by_date(date: str) -> list[dict]:
    """Получить все слоты на дату с количеством записанных по ролям."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM slots WHERE date = ? ORDER BY time", (date,)
        )
        slots = await cursor.fetchall()
        result = []
        for slot in slots:
            cursor2 = await db.execute(
                """SELECT role, COUNT(*) as cnt FROM bookings
                   WHERE slot_id = ? GROUP BY role""",
                (slot["id"],)
            )
            roles_rows = await cursor2.fetchall()
            roles = {r["role"]: r["cnt"] for r in roles_rows}
            result.append({
                "id": slot["id"],
                "date": slot["date"],
                "time": slot["time"],
                "roles": {
                    "coach": roles.get("coach", 0),
                    "client": roles.get("client", 0),
                    "curator": roles.get("curator", 0),
                    "viewer": roles.get("viewer", 0),
                }
            })
        return result


async def get_days_with_slots(year: int, month: int) -> list[str]:
    """Вернуть список дней в месяце, где есть хотя бы один слот."""
    prefix = f"{year}-{month:02d}-%"
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT DISTINCT date FROM slots WHERE date LIKE ? ORDER BY date", (prefix,)
        )
        rows = await cursor.fetchall()
        return [r[0] for r in rows]


async def book_slot(slot_id: int, user_id: int, username: str, full_name: str, role: str) -> dict:
    """Забронировать место. Возвращает {'ok': True} или {'error': '...'}."""
    # Проверяем лимиты ролей (кроме viewer)
    limited_roles = {"coach": 1, "client": 1, "curator": 1}
    async with aiosqlite.connect(DB_PATH) as db:
        # Проверить что пользователь ещё не записан на этот слот
        cursor = await db.execute(
            "SELECT id FROM bookings WHERE slot_id = ? AND user_id = ?", (slot_id, user_id)
        )
        existing = await cursor.fetchone()
        if existing:
            return {"error": "Ты уже записан на этот слот"}

        if role in limited_roles:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM bookings WHERE slot_id = ? AND role = ?", (slot_id, role)
            )
            count = (await cursor.fetchone())[0]
            if count >= limited_roles[role]:
                return {"error": f"Роль '{role}' уже занята"}

        try:
            await db.execute(
                """INSERT INTO bookings (slot_id, user_id, username, full_name, role)
                   VALUES (?, ?, ?, ?, ?)""",
                (slot_id, user_id, username, full_name, role)
            )
            await db.commit()
            return {"ok": True}
        except aiosqlite.IntegrityError:
            return {"error": "Ты уже записан на этот слот"}


async def cancel_booking(slot_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM bookings WHERE slot_id = ? AND user_id = ?", (slot_id, user_id)
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_bookings_by_date(date: str) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT s.time, b.full_name, b.username, b.role, b.user_id, s.id as slot_id
               FROM bookings b JOIN slots s ON b.slot_id = s.id
               WHERE s.date = ?
               ORDER BY s.time, b.role""",
            (date,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def mark_noshow(slot_id: int, user_id: int) -> dict | None:
    """Вернуть данные пользователя для отправки сообщения о неявке."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM bookings WHERE slot_id = ? AND user_id = ?", (slot_id, user_id)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
