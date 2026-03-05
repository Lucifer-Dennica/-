import asyncio
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Update
from config import BOT_TOKEN, BASE_URL, PORT
from database import Database
from scheduler import ReminderScheduler
from handlers import common, appointment, cancel, admin

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Подключаем роутеры
dp.include_router(common.router)
dp.include_router(appointment.router)
dp.include_router(cancel.router)
dp.include_router(admin.router)

# База данных и планировщик
db = Database()
scheduler = ReminderScheduler(bot, db)

# Веб-обработчик для вебхуков Telegram
async def handle_webhook(request):
    update = await request.json()
    update = Update(**update)
    await dp.feed_update(bot, update)
    return web.Response(status=200)

# Эндпоинт для проверки здоровья (пинга)
async def health_check(request):
    return web.Response(text="OK", status=200)

async def on_startup():
    await db.connect()
    await db.create_tables()
    bot.db = db
    bot.scheduler = scheduler

    await scheduler.restore_reminders()
    scheduler.start()

    if BASE_URL:
        webhook_url = f"{BASE_URL}/webhook"
        await bot.set_webhook(webhook_url)
        logger.info(f"Webhook set to {webhook_url}")

async def on_shutdown():
    await bot.delete_webhook()
    await db.close()
    scheduler.shutdown()

async def main():
    app = web.Application()
    app.router.add_post('/webhook', handle_webhook)
    app.router.add_get('/health', health_check)   # добавленный эндпоинт
    app.on_startup.append(lambda _: asyncio.create_task(on_startup()))
    app.on_shutdown.append(lambda _: asyncio.create_task(on_shutdown()))

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    logger.info(f"Starting server on port {PORT}")
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
