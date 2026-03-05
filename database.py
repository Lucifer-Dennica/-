import asyncpg
from datetime import datetime, date, time
from config import DATABASE_URL
import logging

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        """Создаёт пул соединений с базой данных."""
        self.pool = await asyncpg.create_pool(DATABASE_URL)

    async def close(self):
        """Закрывает пул соединений."""
        if self.pool:
            await self.pool.close()

    # ----- Создание таблиц -----
    async def create_tables(self):
        """Создаёт необходимые таблицы, если они ещё не существуют."""
        async with self.pool.acquire() as conn:
            # Пользователи
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    phone TEXT,
                    registered_at TIMESTAMP DEFAULT NOW()
                )
            """)
            # Записи (активные брони)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS appointments (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    appointment_date DATE NOT NULL,
                    appointment_time TIME NOT NULL,
                    client_name TEXT NOT NULL,
                    client_phone TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(appointment_date, appointment_time)
                )
            """)
            # Рабочие слоты (доступное время)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS time_slots (
                    id SERIAL PRIMARY KEY,
                    slot_date DATE NOT NULL,
                    slot_time TIME NOT NULL,
                    is_available BOOLEAN DEFAULT TRUE,
                    UNIQUE(slot_date, slot_time)
                )
            """)
            # Напоминания (для восстановления после рестарта)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    appointment_id INTEGER PRIMARY KEY REFERENCES appointments(id) ON DELETE CASCADE,
                    remind_at TIMESTAMP NOT NULL
                )
            """)
            logger.info("Tables created or already exist")

    # ----- Слоты -----
    async def add_time_slot(self, slot_date: date, slot_time: time):
        """Добавляет новый доступный слот."""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO time_slots (slot_date, slot_time)
                VALUES ($1, $2)
                ON CONFLICT (slot_date, slot_time) DO NOTHING
            """, slot_date, slot_time)
            logger.debug(f"Slot added: {slot_date} {slot_time}")

    async def get_available_slots(self, slot_date: date):
        """Возвращает список доступного времени для указанной даты."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT slot_time FROM time_slots
                WHERE slot_date = $1 AND is_available = TRUE
                ORDER BY slot_time
            """, slot_date)
            slots = [row['slot_time'] for row in rows]
            logger.info(f"get_available_slots for {slot_date}: found {len(slots)} slots: {[s.strftime('%H:%M') for s in slots]}")
            return slots

    async def get_all_slots(self, slot_date: date):
        """Возвращает все слоты на дату (с доступностью)."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT slot_time, is_available FROM time_slots
                WHERE slot_date = $1
                ORDER BY slot_time
            """, slot_date)
            return rows

    async def delete_time_slot(self, slot_date: date, slot_time: time):
        """Удаляет конкретный слот (только если он свободен)."""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                DELETE FROM time_slots
                WHERE slot_date = $1 AND slot_time = $2 AND is_available = TRUE
            """, slot_date, slot_time)
            logger.debug(f"Slot deleted: {slot_date} {slot_time}")

    async def delete_time_range(self, slot_date: date, start_time: time, end_time: time):
        """Удаляет все доступные слоты в заданном временном диапазоне."""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                DELETE FROM time_slots
                WHERE slot_date = $1
                  AND slot_time >= $2
                  AND slot_time <= $3
                  AND is_available = TRUE
            """, slot_date, start_time, end_time)
            logger.debug(f"Slots deleted for {slot_date} from {start_time} to {end_time}")

    async def close_day(self, slot_date: date):
        """Помечает все слоты указанной даты как недоступные."""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE time_slots
                SET is_available = FALSE
                WHERE slot_date = $1
            """, slot_date)
            logger.info(f"Day closed: {slot_date}")

    async def open_day(self, slot_date: date):
        """Открывает день: все слоты становятся доступными."""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE time_slots
                SET is_available = TRUE
                WHERE slot_date = $1
            """, slot_date)
            logger.info(f"Day opened: {slot_date}")

    async def occupy_slot(self, slot_date: date, slot_time: time):
        """Помечает слот как занятый (после бронирования)."""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE time_slots
                SET is_available = FALSE
                WHERE slot_date = $1 AND slot_time = $2
            """, slot_date, slot_time)
            logger.debug(f"Slot occupied: {slot_date} {slot_time}")

    async def free_slot(self, slot_date: date, slot_time: time):
        """Освобождает слот (после отмены записи)."""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE time_slots
                SET is_available = TRUE
                WHERE slot_date = $1 AND slot_time = $2
            """, slot_date, slot_time)
            logger.debug(f"Slot freed: {slot_date} {slot_time}")

    # ----- Записи -----
    async def create_appointment(self, user_id: int, client_name: str, client_phone: str,
                                 app_date: date, app_time: time) -> int:
        """Создаёт новую запись и возвращает её ID."""
        async with self.pool.acquire() as conn:
            # Сохраняем пользователя
            await conn.execute("""
                INSERT INTO users (user_id, username, full_name, phone)
                VALUES ($1, '', $2, $3)
                ON CONFLICT (user_id) DO UPDATE SET
                    full_name = EXCLUDED.full_name,
                    phone = EXCLUDED.phone
            """, user_id, client_name, client_phone)
            # Создаём запись
            app_id = await conn.fetchval("""
                INSERT INTO appointments (user_id, appointment_date, appointment_time, client_name, client_phone)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
            """, user_id, app_date, app_time, client_name, client_phone)
            logger.info(f"Appointment created: ID {app_id} for user {user_id} at {app_date} {app_time}")
            return app_id

    async def get_user_appointment(self, user_id: int):
        """Возвращает последнюю активную запись пользователя (если есть)."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM appointments
                WHERE user_id = $1
                ORDER BY created_at DESC
                LIMIT 1
            """, user_id)
            return row

    async def cancel_appointment(self, appointment_id: int) -> bool:
        """Отменяет запись по ID и освобождает слот."""
        async with self.pool.acquire() as conn:
            # Получаем дату и время слота
            row = await conn.fetchrow("""
                SELECT appointment_date, appointment_time FROM appointments
                WHERE id = $1
            """, appointment_id)
            if row:
                # Освобождаем слот
                await self.free_slot(row['appointment_date'], row['appointment_time'])
                # Удаляем запись
                await conn.execute("DELETE FROM appointments WHERE id = $1", appointment_id)
                logger.info(f"Appointment cancelled: ID {appointment_id}")
                return True
            return False

    async def get_appointment_by_id(self, appointment_id: int):
        """Возвращает данные записи по ID."""
        async with self.pool.acquire() as conn:
            return await conn.fetchrow("SELECT * FROM appointments WHERE id = $1", appointment_id)

    # ----- Напоминания -----
    async def save_reminder(self, appointment_id: int, remind_at: datetime):
        """Сохраняет информацию о запланированном напоминании."""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO reminders (appointment_id, remind_at)
                VALUES ($1, $2)
                ON CONFLICT (appointment_id) DO UPDATE SET remind_at = EXCLUDED.remind_at
            """, appointment_id, remind_at)
            logger.debug(f"Reminder saved for appointment {appointment_id} at {remind_at}")

    async def delete_reminder(self, appointment_id: int):
        """Удаляет запись о напоминании."""
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM reminders WHERE appointment_id = $1", appointment_id)
            logger.debug(f"Reminder deleted for appointment {appointment_id}")

    async def get_all_reminders(self):
        """Возвращает все активные напоминания для восстановления после рестарта."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT r.appointment_id, r.remind_at,
                       a.user_id, a.appointment_date, a.appointment_time, a.client_name
                FROM reminders r
                JOIN appointments a ON r.appointment_id = a.id
            """)
            return rows

    # ----- Просмотр расписания для админа -----
    async def get_appointments_for_date(self, target_date: date):
        """Возвращает все записи на указанную дату."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT a.id, a.appointment_time, a.client_name, a.client_phone, u.user_id
                FROM appointments a
                JOIN users u ON a.user_id = u.user_id
                WHERE a.appointment_date = $1
                ORDER BY a.appointment_time
            """, target_date)
            return rows
