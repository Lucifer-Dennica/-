import logging
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from database import Database
from scheduler import ReminderScheduler
from keyboards import (
    calendar_keyboard, time_slots_keyboard, confirm_appointment_keyboard,
    cancel_keyboard, main_menu, subscription_check_keyboard
)
from states import AppointmentStates
from utils import check_subscription
from config import CHANNEL_ID, ADMIN_ID, CHANNEL_LINK

router = Router()
logger = logging.getLogger(__name__)

# Начало записи (кнопка "Записаться")
@router.message(F.text == "📅 Записаться")
async def start_appointment(message: Message, state: FSMContext, bot):
    # Проверяем подписку
    if CHANNEL_ID:
        subscribed = await check_subscription(bot, message.from_user.id)
        if not subscribed:
            await message.answer(
                "🔒 Для записи необходимо подписаться на канал",
                reply_markup=subscription_check_keyboard(CHANNEL_LINK)
            )
            return

    # Проверяем, нет ли уже активной записи у пользователя
    db: Database = bot.db
    existing = await db.get_user_appointment(message.from_user.id)
    if existing:
        await message.answer(
            "❌ У вас уже есть активная запись. Вы можете отменить её в разделе «Отменить запись»."
        )
        return

    # Показываем календарь (текущий месяц)
    now = datetime.now()
    await state.set_state(AppointmentStates.choosing_date)
    await message.answer(
        "Выберите дату:",
        reply_markup=calendar_keyboard(now.year, now.month)
    )

# Обработка навигации по календарю
@router.callback_query(F.data.startswith("month_"))
async def process_calendar_nav(callback: CallbackQuery, state: FSMContext):
    try:
        _, year, month = callback.data.split("_")
        await callback.message.edit_reply_markup(
            reply_markup=calendar_keyboard(int(year), int(month))
        )
    except Exception as e:
        logger.error(f"Calendar nav error: {e}")
    await callback.answer()

# Закрытие календаря
@router.callback_query(F.data == "cancel_calendar")
async def cancel_calendar(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.message.answer("Выберите действие:", reply_markup=main_menu())
    await callback.answer()

# Выбор даты
@router.callback_query(F.data.startswith("date_"))
async def process_date_selection(callback: CallbackQuery, state: FSMContext, bot):
    date_str = callback.data.split("_")[1]
    try:
        selected_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        await callback.answer("Неверный формат даты", show_alert=True)
        return

    # Проверяем, что дата не в прошлом
    if selected_date < datetime.now().date():
        await callback.answer("❌ Нельзя выбрать прошедшую дату", show_alert=True)
        return

    # Сохраняем дату в состоянии
    await state.update_data(appointment_date=date_str)

    # Получаем доступные слоты
    db: Database = bot.db
    slots = await db.get_available_slots(selected_date)

    if not slots:
        await callback.message.edit_text(
            "На выбранный день нет свободных слотов. Выберите другую дату.",
            reply_markup=calendar_keyboard(selected_date.year, selected_date.month)
        )
        await callback.answer()
        return

    # Показываем слоты
    await state.set_state(AppointmentStates.choosing_time)
    await callback.message.edit_text(
        f"Выберите время на {date_str}:",
        reply_markup=time_slots_keyboard(slots, date_str)
    )
    await callback.answer()

# Назад к календарю
@router.callback_query(F.data == "back_to_calendar")
async def back_to_calendar(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AppointmentStates.choosing_date)
    now = datetime.now()
    await callback.message.edit_text(
        "Выберите дату:",
        reply_markup=calendar_keyboard(now.year, now.month)
    )
    await callback.answer()

# Выбор времени
@router.callback_query(F.data.startswith("time_"))
async def process_time_selection(callback: CallbackQuery, state: FSMContext, bot):
    parts = callback.data.split("_")
    if len(parts) != 3:
        await callback.answer("Неверные данные")
        return
    _, date_str, time_str = parts
    # Сохраняем дату и время
    await state.update_data(appointment_date=date_str, appointment_time=time_str)

    # Переходим к запросу имени
    await state.set_state(AppointmentStates.entering_name)
    await callback.message.edit_text(
        "Введите ваше имя:",
        reply_markup=cancel_keyboard()
    )
    await callback.answer()

# Ввод имени
@router.message(AppointmentStates.entering_name)
async def process_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("Имя не может быть пустым. Введите имя:")
        return
    await state.update_data(client_name=name)
    await state.set_state(AppointmentStates.entering_phone)
    await message.answer(
        "Введите ваш номер телефона (в любом формате):",
        reply_markup=cancel_keyboard()
    )

# Ввод телефона
@router.message(AppointmentStates.entering_phone)
async def process_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    if not phone:
        await message.answer("Телефон не может быть пустым. Введите номер:")
        return
    await state.update_data(client_phone=phone)

    # Показываем подтверждение
    data = await state.get_data()
    date_str = data['appointment_date']
    time_str = data['appointment_time']
    name = data['client_name']
    phone = data['client_phone']

    text = (
        f"📝 Проверьте данные:\n\n"
        f"📅 Дата: {date_str}\n"
        f"⏰ Время: {time_str}\n"
        f"👤 Имя: {name}\n"
        f"📞 Телефон: {phone}\n\n"
        f"Всё верно?"
    )
    await state.set_state(AppointmentStates.confirming)
    await message.answer(
        text,
        reply_markup=confirm_appointment_keyboard(date_str, time_str)
    )

# Подтверждение записи
@router.callback_query(F.data.startswith("confirm_"))
async def confirm_appointment(callback: CallbackQuery, state: FSMContext, bot):
    # Извлекаем дату и время из callback
    parts = callback.data.split("_")
    if len(parts) != 3:
        await callback.answer("Неверные данные")
        return
    _, date_str, time_str = parts

    # Защита от левых данных (например, "cancel")
    if date_str == "cancel" or time_str == "cancel":
        await callback.answer()
        return

    try:
        slot_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        slot_time = datetime.strptime(time_str, "%H:%M").time()
    except ValueError:
        await callback.answer("Неверный формат даты или времени")
        return

    user_id = callback.from_user.id

    # Получаем данные из состояния (имя, телефон)
    data = await state.get_data()
    client_name = data.get('client_name')
    client_phone = data.get('client_phone')

    if not client_name or not client_phone:
        await callback.message.edit_text("❌ Сессия истекла, начните запись заново.")
        await state.clear()
        await callback.answer()
        return

    db: Database = bot.db

    # Проверяем доступность слота (на случай двойного бронирования)
    available = await db.get_available_slots(slot_date)
    if slot_time not in available:
        await callback.message.edit_text(
            "❌ К сожалению, это время уже занято. Попробуйте выбрать другое."
        )
        await state.clear()
        await callback.answer()
        return

    # Создаём запись
    try:
        app_id = await db.create_appointment(
            user_id=user_id,
            client_name=client_name,
            client_phone=client_phone,
            app_date=slot_date,
            app_time=slot_time
        )
        # Помечаем слот как занятый
        await db.occupy_slot(slot_date, slot_time)

        # Планируем напоминание, если до визита больше 24 часов
        appointment_datetime = datetime.combine(slot_date, slot_time)
        now = datetime.now()
        delta = appointment_datetime - now
        if delta.total_seconds() > 24 * 3600:
            remind_at = appointment_datetime - timedelta(hours=24)
            scheduler: ReminderScheduler = bot.scheduler
            await scheduler.schedule_reminder(app_id, remind_at)

        # Отправляем уведомление админу
        try:
            admin_text = (
                f"✅ Новая запись!\n\n"
                f"👤 Клиент: {client_name}\n"
                f"📞 Телефон: {client_phone}\n"
                f"📅 Дата: {date_str}\n"
                f"⏰ Время: {time_str}\n"
                f"🆔 ID: {app_id}"
            )
            await bot.send_message(ADMIN_ID, admin_text)
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")

        # Отправляем в канал, если он указан
        if CHANNEL_ID:
            try:
                channel_text = (
                    f"📅 Запись на {date_str} в {time_str}\n"
                    f"👤 Клиент: {client_name}"
                )
                await bot.send_message(CHANNEL_ID, channel_text)
            except Exception as e:
                logger.error(f"Failed to send to channel: {e}")

        # Подтверждение пользователю
        await callback.message.edit_text(
            f"✅ Вы успешно записаны!\n"
            f"Дата: {date_str}\n"
            f"Время: {time_str}\n\n"
            f"Ждём вас ❤️"
        )
        await state.clear()

    except Exception as e:
        logger.error(f"Error creating appointment: {e}")
        await callback.message.edit_text("❌ Произошла ошибка. Попробуйте позже.")
        await state.clear()

    await callback.answer()

# Отмена FSM через inline-кнопку
@router.callback_query(F.data == "cancel_fsm")
async def cancel_fsm(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Действие отменено.")
    await callback.message.answer("Выберите действие:", reply_markup=main_menu())
    await callback.answer()
