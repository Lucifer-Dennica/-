from aiogram import Bot
from aiogram.types import ChatMember
from config import CHANNEL_ID

async def check_subscription(bot: Bot, user_id: int) -> bool:
    """Проверяет, подписан ли пользователь на канал"""
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        # Статусы, при которых считаем подписку активной
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        # Если канал недоступен или бот не админ, лучше вернуть True, чтобы не блокировать
        print(f"Subscription check error: {e}")
        return True  # или False, в зависимости от политики
