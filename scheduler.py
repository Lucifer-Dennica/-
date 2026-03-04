from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.triggers.date import DateTrigger
from datetime import datetime, timedelta
from pytz import timezone
from aiogram import Bot
from database import Database
import logging

logger = logging.getLogger(__name__)

class ReminderScheduler:
    def __init__(self, bot: Bot, db: Database):
        self.bot = bot
        self.db = db
        self.scheduler = AsyncIOScheduler(timezone=timezone('Europe/Moscow'))
        self.scheduler.add_jobstore(MemoryJobStore(), 'default')

    def start(self):
        self.scheduler.start()
        logger.info("Scheduler started")

    def shutdown(self):
        self.scheduler.shutdown()

    async def schedule_reminder(self, appointment_id: int, remind_at: datetime):
        """Добавляет задачу напоминания"""
        job_id = f"reminder_{appointment_id}"
        self.scheduler.add_job(
            self.send_reminder,
            trigger=DateTrigger(run_date=remind_at),
            args=[appointment_id],
            id=job_id,
            replace_existing=True
        )
        # Сохраняем в БД для восстановления после рестарта
        await self.db.save_reminder(appointment_id, remind_at)
        logger.info(f"Scheduled reminder {job_id} at {remind_at}")

    async def remove_reminder(self, appointment_id: int):
        """Удаляет задачу напоминания"""
        job_id = f"reminder_{appointment_id}"
        self.scheduler.remove_job(job_id)
        await self.db.delete_reminder(appointment_id)
        logger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.triggers.date import DateTrigger
from datetime import datetime, timedelta
from pytz import timezone
from aiogram import Bot
from database import Database
import logging

logger = logging.getLogger(__name__)

class ReminderScheduler:
    def __init__(self, bot: Bot, db: Database):
        self.bot = bot
        self.db = db
        self.scheduler = AsyncIOScheduler(timezone=timezone('Europe/Moscow'))
        self.scheduler.add_jobstore(MemoryJobStore(), 'default')

    def start(self):
        self.scheduler.start()
        logger.info("Scheduler started")

    def shutdown(self):
        self.scheduler.shutdown()

    async def schedule_reminder(self, appointment_id: int, remind_at: datetime):
        """Добавляет задачу напоминания"""
        job_id = f"reminder_{appointment_id}"
        self.scheduler.add_job(
            self.send_reminder,
            trigger=DateTrigger(run_date=remind_at),
            args=[appointment_id],
            id=job_id,
            replace_existing=True
        )
        # Сохраняем в БД для восстановления после рестарта
        await self.db.save_reminder(appointment_id, remind_at)
        logger.info(f"Scheduled reminder {job_id} at {remind_at}")

    async def remove_reminder(self, appointment_id: int):
        """Удаляет задачу напоминания"""
        job_id = f"reminder_{appointment_id}"
        try:
            self.scheduler.remove_job(job_id)
        except:
            pass
        await self.db.delete_reminder(appointment_id)
        logger.info(f"Removed reminder {job_id}")

    async def send_reminder(self, appointment_id: int):
        """Отправляет напоминание клиенту"""
        # Получаем данные записи
        appointment = await self.db.get_appointment_by_id(appointment_id)
        if not appointment:
            return
        user_id = appointment['user_id']
        app_time = appointment['appointment_time'].strftime('%H:%M')
        text = (
            f"⏰ Напоминаем, что вы записаны на завтра в {app_time}.\n"
            f"Ждём вас ❤️"
        )
        try:
            await self.bot.send_message(user_id, text)
            logger.info(f"Reminder sent to user {user_id}")
        except Exception as e:
            logger.error(f"Failed to send reminder: {e}")

    async def restore_reminders(self):
        """Восстанавливает все напоминания из БД (при старте)"""
        reminders = await self.db.get_all_reminders()
        for r in reminders:
            # Проверяем, что время напоминания ещё не прошло
            if r['remind_at'] > datetime.now(timezone('Europe/Moscow')):
                job_id = f"reminder_{r['appointment_id']}"
                self.scheduler.add_job(
                    self.send_reminder,
                    trigger=DateTrigger(run_date=r['remind_at']),
                    args=[r['appointment_id']],
                    id=job_id,
                    replace_existing=True
                )
                logger.info(f"Restored reminder {job_id}")
