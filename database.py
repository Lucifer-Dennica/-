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
        logger.info("Connected to database")

    async def close(self):
        """Закрывает пул соединений."""
        if self.pool:
            await self.pool.close()
            logger.info("Database connection closed")

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
            # Услуги (прайс-лист)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS services (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    price INTEGER NOT NULL
                )
            """)
            # Связь записей с услугами (многие ко многим)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS appointment_services (
                    appointment_id INTEGER REFERENCES appointments(id) ON DELETE CASCADE,
                    service_id INTEGER REFERENCES services(id) ON DELETE CASCADE,
                    PRIMARY KEY (appointment_id, service_id)
                )
            """)
            logger.info("Tables created or already exist")

    # ----- Слоты (без изменений) -----
    async def add_time_slot(self, slot_date: date, slot_time: time):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO time_slots (slot_date, slot_time)
                VALUES ($1, $2)
                ON CONFLICT (slot_date, slot_time) DO NOTHING
            """, slot_date, slot_time)
            logger.debug(f"Slot added: {slot_date} {slot_time}")

    async def get_available_slots(self, slot_date: date):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT slot_time FROM time_slots
                WHERE slot_date = $1 AND is_available = TRUE
                ORDER BY slot_time
            """, slot_date)
            slots = [row['slot_time'] for row in rows]
            logger.info(f"get_available_slots for {slot_date}: found {len(slots)} slots")
            return slots

    async def get_all_slots(self, slot_date: date):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT slot_time, is_available FROM time_slots
                WHERE slot_date = $1
                ORDER BY slot_time
            """, slot_date)
            return rows

    async def delete_time_slot(self, slot_date: date, slot_time: time):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                DELETE FROM time_slots
                WHERE slot_date = $1 AND slot_time = $2 AND is_available = TRUE
            """, slot_date, slot_time)
            logger.debug(f"Slot deleted: {slot_date} {slot_time}")

    async def delete_time_range(self, slot_date: date, start_time: time, end_time: time):
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
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE time_slots
                SET is_available = FALSE
                WHERE slot_date = $1
            """, slot_date)
            logger.info(f"Day closed: {slot_date}")

    async def open_day(self, slot_date: date):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE time_slots
                SET is_available = TRUE
                WHERE slot_date = $1
            """, slot_date)
            logger.info(f"Day opened: {slot_date}")

    async def occupy_slot(self, slot_date: date, slot_time: time):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE time_slots
                SET is_available = FALSE
                WHERE slot_date = $1 AND slot_time = $2
            """, slot_date, slot_time)
            logger.debug(f"Slot occupied: {slot_date} {slot_time}")

    async def free_slot(self, slot_date: date, slot_time: time):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE time_slots
                SET is_available = TRUE
                WHERE slot_date = $1 AND slot_time = $2
            """, slot_date, slot_time)
            logger.debug(f"Slot freed: {slot_date} {slot_time}")

    # ----- Записи (апдейт: добавим получение услуг по записи) -----
    async def create_appointment(self, user_id: int, client_name: str, client_phone: str,
                                 app_date: date, app_time: time) -> int:
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (user_id, username, full_name, phone)
                VALUES ($1, '', $2, $3)
                ON CONFLICT (user_id) DO UPDATE SET
                    full_name = EXCLUDED.full_name,
                    phone = EXCLUDED.phone
            """, user_id, client_name, client_phone)
            app_id = await conn.fetchval("""
                INSERT INTO appointments (user_id, appointment_date, appointment_time, client_name, client_phone)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
            """, user_id, app_date, app_time, client_name, client_phone)
            logger.info(f"Appointment created: ID {app_id} for user {user_id} at {app_date} {app_time}")
            return app_id

    async def add_services_to_appointment(self, appointment_id: int, service_ids: list[int]):
        """Привязывает выбранные услуги к записи."""
        async with self.pool.acquire() as conn:
            for sid in service_ids:
                await conn.execute("""
                    INSERT INTO appointment_services (appointment_id, service_id)
                    VALUES ($1, $2)
                    ON CONFLICT DO NOTHING
                """, appointment_id, sid)
            logger.info(f"Services {service_ids} added to appointment {appointment_id}")

    async def get_appointment_services(self, appointment_id: int):
        """Возвращает список услуг для конкретной записи."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT s.id, s.name, s.price
                FROM appointment_services aps
                JOIN services s ON aps.service_id = s.id
                WHERE aps.appointment_id = $1
            """, appointment_id)
            return rows

    async def get_user_appointment(self, user_id: int):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM appointments
                WHERE user_id = $1
                ORDER BY created_at DESC
                LIMIT 1
            """, user_id)
            return row

    async def cancel_appointment(self, appointment_id: int) -> bool:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT appointment_date, appointment_time FROM appointments
                WHERE id = $1
            """, appointment_id)
            if row:
                await self.free_slot(row['appointment_date'], row['appointment_time'])
                await conn.execute("DELETE FROM appointments WHERE id = $1", appointment_id)
                logger.info(f"Appointment cancelled: ID {appointment_id}")
                return True
            return False

    async def get_appointment_by_id(self, appointment_id: int):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow("SELECT * FROM appointments WHERE id = $1", appointment_id)

    # ----- Напоминания (без изменений) -----
    async def save_reminder(self, appointment_id: int, remind_at: datetime):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO reminders (appointment_id, remind_at)
                VALUES ($1, $2)
                ON CONFLICT (appointment_id) DO UPDATE SET remind_at = EXCLUDED.remind_at
            """, appointment_id, remind_at)
            logger.debug(f"Reminder saved for appointment {appointment_id} at {remind_at}")

    async def delete_reminder(self, appointment_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM reminders WHERE appointment_id = $1", appointment_id)
            logger.debug(f"Reminder deleted for appointment {appointment_id}")

    async def get_all_reminders(self):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT r.appointment_id, r.remind_at,
                       a.user_id, a.appointment_date, a.appointment_time, a.client_name
                FROM reminders r
                JOIN appointments a ON r.appointment_id = a.id
            """)
            return rows

    # ----- Услуги (прайс-лист) -----
    async def get_all_services(self):
        """Возвращает список всех услуг."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM services ORDER BY id")
            return rows

    async def add_service(self, name: str, price: int):
        """Добавляет новую услугу."""
        async with self.pool.acquire() as conn:
            try:
                await conn.execute("""
                    INSERT INTO services (name, price)
                    VALUES ($1, $2)
                """, name, price)
                logger.info(f"Service added: {name} - {price} BYN")
                return True
            except asyncpg.exceptions.UniqueViolationError:
                logger.warning(f"Service {name} already exists")
                return False

    async def delete_service(self, service_id: int):
        """Удаляет услугу по ID."""
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM services WHERE id = $1", service_id)
            logger.info(f"Service deleted: ID {service_id}")

    async def update_service_price(self, service_id: int, new_price: int):
        """Обновляет цену услуги."""
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE services SET price = $1 WHERE id = $2", new_price, service_id)
            logger.info(f"Service {service_id} price updated to {new_price}")

    # ----- Просмотр расписания для админа (с услугами) -----
    async def get_appointments_for_date(self, target_date: date):
        """Возвращает все записи на указанную дату с услугами."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT a.id, a.appointment_time, a.client_name, a.client_phone, u.user_id
                FROM appointments a
                JOIN users u ON a.user_id = u.user_id
                WHERE a.appointment_date = $1
                ORDER BY a.appointment_time
            """, target_date)
            # Для каждой записи добавим услуги
            result = []
            for r in rows:
                services = await self.get_appointment_services(r['id'])
                result.append({**r, 'services': services})
            return result
