import asyncio
import logging
import os
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Update
from aiohttp import web
from config import BOT_TOKEN, BASE_URL, PORT
from database import Database
from scheduler import ReminderScheduler
from handlers import common, appointment, cancel, admin

logging.basicConfig(level=logging.INFO)

# Инициализация
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Подключаем роутеры
dp.include_router(common.router)
dp.include_router(appointment.router)
dp.include_router(cancel.router)
dp.include_router(admin.router)

# База данных и планировщик (будут прикреплены к bot)
db = Database()
scheduler = ReminderScheduler(bot, db)

# Веб-сервер для приёма вебхуков
async def handle_webhook(request):
    update = await request.json()
    update = Update(**update)
    await dp.feed_update(bot, update)
    return web.Response(status=200)

async def on_startup():
    # Подключаем БД и создаём таблицы
    await db.connect()
    await db.create_tables()
    # Прикрепляем к bot
    bot.db = db
    bot.scheduler = scheduler

    # Восстанавливаем напоминания
    await scheduler.restore_reminders()
    scheduler.start()

    # Устанавливаем вебхук (если есть BASE_URL)
    if BASE_URL:
        webhook_url = f"{BASE_URL}/webhook"
        await bot.set_webhook(webhook_url)
        logging.info(f"Webhook set to {webhook_url}")

async def on_shutdown():
    # Удаляем вебхук (опционально)
    await bot.delete_webhook()
    await db.close()
    scheduler.shutdown()

async def main():
    # Запуск веб-приложения
    app = web.Application()
    app.router.add_post('/webhook', handle_webhook)
    app.on_startup.append(lambda _: asyncio.create_task(on_startup()))
    app.on_shutdown.append(lambda _: asyncio.create_task(on_shutdown()))

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    logging.info(f"Starting server on port {PORT}")
    await site.start()

    # Ожидаем завершения
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        await runner.cleanup()

if __name__ == '__main__':
    asyncio.run(main())
