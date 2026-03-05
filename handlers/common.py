import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from keyboards import (
    main_menu, subscription_check_keyboard, portfolio_keyboard
)
from utils import check_subscription
from config import CHANNEL_LINK, CHANNEL_ID, ADMIN_ID
from database import Database

router = Router()
logger = logging.getLogger(__name__)

# Команда /start
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot):
    await state.clear()
    user_id = message.from_user.id

    # Проверяем подписку (если канал задан)
    if CHANNEL_ID:
        try:
            subscribed = await check_subscription(bot, user_id)
        except Exception as e:
            logger.error(f"Subscription check error: {e}")
            subscribed = False
        if not subscribed:
            await message.answer(
                "🔒 Для записи необходимо подписаться на канал",
                reply_markup=subscription_check_keyboard(CHANNEL_LINK)
            )
            return

    await message.answer(
        "👋 Добро пожаловать! Я бот для записи на маникюр.\n"
        "Выберите действие:",
        reply_markup=main_menu()
    )

# Кнопка "Прайсы" — теперь показывает услуги из базы данных
@router.message(F.text == "💰 Прайсы")
async def show_prices(message: Message, bot):
    db: Database = bot.db
    services = await db.get_all_services()
    if not services:
        text = "📋 Прайс-лист пуст."
    else:
        text = "💅 <b>Прайс-лист</b>\n\n"
        for s in services:
            text += f"• {s['name']} — {s['price']} BYN\n"
    await message.answer(text, parse_mode="HTML")

# Кнопка "Портфолио"
@router.message(F.text == "📷 Портфолио")
async def show_portfolio(message: Message):
    await message.answer(
        "Нажмите кнопку ниже, чтобы посмотреть портфолио:",
        reply_markup=portfolio_keyboard()
    )

# Кнопка "Проверить подписку" (из инлайн-клавиатуры)
@router.callback_query(F.data == "check_subscription")
async def check_sub(callback: CallbackQuery, bot):
    user_id = callback.from_user.id
    try:
        subscribed = await check_subscription(bot, user_id)
    except Exception as e:
        logger.error(f"Subscription check error in callback: {e}")
        subscribed = False
    if subscribed:
        try:
            await callback.message.edit_text(
                "✅ Подписка подтверждена! Теперь вы можете записаться.\n"
                "Нажмите /start для продолжения."
            )
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                pass
            else:
                raise
        await callback.message.answer("Выберите действие:", reply_markup=main_menu())
    else:
        await callback.answer("❌ Вы ещё не подписались!", show_alert=True)
    try:
        await callback.answer()
    except TelegramBadRequest as e:
        if "query is too old" in str(e):
            logger.warning("Callback query too old in check_sub")

# Команда /admin (если нужна, но уже есть в admin.py, можно оставить)
# Здесь не дублируем, так как она уже обработана в admin.py
