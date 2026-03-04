import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from database import Database
from scheduler import ReminderScheduler
from keyboards import main_menu
from config import ADMIN_ID

router = Router()
logger = logging.getLogger(__name__)

@router.message(F.text == "❌ Отменить запись")
async def cancel_appointment_user(message: Message, bot):
    user_id = message.from_user.id
    db: Database = bot.db
    logger.info(f"User {user_id} requested to cancel appointment")

    try:
        appointment = await db.get_user_appointment(user_id)
    except Exception as e:
        logger.error(f"Error fetching appointment for user {user_id}: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте позже.")
        return

    if not appointment:
        await message.answer("У вас нет активной записи.")
        return

    # Спрашиваем подтверждение
    text = (
        f"Вы хотите отменить запись:\n"
        f"📅 {appointment['appointment_date']} в {appointment['appointment_time']}\n\n"
        f"Подтвердите отмену."
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, отменить", callback_data=f"confirm_cancel_{appointment['id']}")],
        [InlineKeyboardButton(text="❌ Нет", callback_data="cancel_cancel")]
    ])
    await message.answer(text, reply_markup=markup)

@router.callback_query(F.data.startswith("confirm_cancel_"))
async def confirm_cancel(callback: CallbackQuery, bot):
    appointment_id = int(callback.data.split("_")[2])
    db: Database = bot.db
    scheduler: ReminderScheduler = bot.scheduler
    logger.info(f"Confirming cancellation of appointment {appointment_id}")

    try:
        # Получаем информацию о записи до удаления (для сообщения)
        app = await db.get_appointment_by_id(appointment_id)
        if not app:
            await callback.answer("Запись не найдена", show_alert=True)
            return

        # Отменяем запись (освобождаем слот, удаляем из БД)
        success = await db.cancel_appointment(appointment_id)
        if success:
            # Удаляем напоминание
            try:
                await scheduler.remove_reminder(appointment_id)
            except Exception as e:
                logger.error(f"Failed to remove reminder for appointment {appointment_id}: {e}")

            await callback.message.edit_text("✅ Запись успешно отменена.")

            # Уведомляем админа
            try:
                await bot.send_message(
                    ADMIN_ID,
                    f"❌ Клиент отменил запись:\n"
                    f"Дата: {app['appointment_date']} {app['appointment_time']}\n"
                    f"Клиент: {app['client_name']}"
                )
            except Exception as e:
                logger.error(f"Failed to notify admin about cancellation: {e}")

            # Уведомляем пользователя дополнительно (уже есть edit_text, но можно и отдельно)
        else:
            await callback.message.edit_text("❌ Не удалось отменить запись.")
    except Exception as e:
        logger.error(f"Error during cancellation of appointment {appointment_id}: {e}")
        await callback.message.edit_text("❌ Произошла ошибка при отмене.")

    await callback.answer()

@router.callback_query(F.data == "cancel_cancel")
async def no_cancel(callback: CallbackQuery):
    await callback.message.edit_text("Отмена не выполнена.")
    await callback.message.answer("Выберите действие:", reply_markup=main_menu())
    await callback.answer()
