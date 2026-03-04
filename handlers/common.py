from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from keyboards import main_menu, subscription_check_keyboard, portfolio_keyboard
from utils import check_subscription
from config import CHANNEL_LINK, CHANNEL_ID
import logging

router = Router()
logger = logging.getLogger(__name__)

# Команда /start
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot):
    await state.clear()
    user_id = message.from_user.id

    # Проверяем подписку (если канал задан)
    if CHANNEL_ID:
        subscribed = await check_subscription(bot, user_id)
        if not subscribed:
            await message.answer(
                "🔒 Для записи необходимо подписаться на канал",
                reply_markup=subscription_check_keyboard(CHANNEL_LINK)
            )
            return

    # Если подписан или проверка отключена
    await message.answer(
        "👋 Добро пожаловать! Я бот для записи на маникюр.\n"
        "Выберите действие:",
        reply_markup=main_menu()
    )

# Кнопка "Прайсы"
@router.message(F.text == "💰 Прайсы")
async def show_prices(message: Message):
    text = (
        "💅 <b>Прайс-лист</b>\n\n"
        "Френч — 1000₽\n"
        "Квадрат — 500₽"
    )
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
    subscribed = await check_subscription(bot, user_id)
    if subscribed:
        await callback.message.edit_text(
            "✅ Подписка подтверждена! Теперь вы можете записаться.\n"
            "Нажмите /start для продолжения."
        )
        # Отправим также главное меню
        await callback.message.answer("Выберите действие:", reply_markup=main_menu())
    else:
        await callback.answer("❌ Вы ещё не подписались!", show_alert=True)
    await callback.answer()
