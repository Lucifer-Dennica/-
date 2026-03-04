# handlers/cancel.py
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from database import Database
from scheduler import ReminderScheduler
from keyboards import main_menu
import logging
from aiogram.exceptions import TelegramBadRequest
from config import ADMIN_ID

router = Router()
logger = logging.getLogger(__name__)

@router.message(F.text == "❌ Отменить запись")
async def cancel_appointment_user(message: Message, bot):
    user_id = message.from_user.id
    db: Database = bot.db
    appointment = await db.get_user_appointment(user_id)

    if not appointment:
        await message.answer("У вас нет активной записи.")
        return

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, отменить", callback_data=f"confirm_cancel_{appointment['id']}")],
        [InlineKeyboardButton(text="❌ Нет", callback_data="cancel_cancel")]
    ])
    await message.answer(
        f"Вы хотите отменить запись:\n"
        f"📅 {appointment['appointment_date']} в {appointment['appointment_time']}\n\n"
        f"Подтвердите отмену.",
        reply_markup=markup
    )

@router.callback_query(F.data.startswith("confirm_cancel_"))
async def confirm_cancel(callback: CallbackQuery, bot):
    appointment_id = int(callback.data.split("_")[2])
    db: Database = bot.db
    scheduler: ReminderScheduler = bot.scheduler

    app = await db.get_appointment_by_id(appointment_id)
    if not app:
        await callback.answer("Запись не найдена", show_alert=True)
        return

    success = await db.cancel_appointment(appointment_id)
    if success:
        await scheduler.remove_reminder(appointment_id)

        try:
            await callback.message.edit_text("✅ Запись успешно отменена.")
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                pass
            else:
                raise

        await bot.send_message(
            ADMIN_ID,
            f"❌ Клиент отменил запись:\n"
            f"Дата: {app['appointment_date']} {app['appointment_time']}\n"
            f"Клиент: {app['client_name']}"
        )
    else:
        await callback.message.edit_text("❌ Не удалось отменить запись.")
    await callback.answer()

@router.callback_query(F.data == "cancel_cancel")
async def no_cancel(callback: CallbackQuery):
    await callback.message.edit_text("Отмена не выполнена.")
    await callback.message.answer("Выберите действие:", reply_markup=main_menu())
    await callback.answer()
