import logging
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from database import Database
from scheduler import ReminderScheduler
from keyboards import (
    calendar_keyboard, time_slots_keyboard, services_keyboard,
    confirm_services_keyboard, cancel_keyboard, main_menu, subscription_check_keyboard
)
from states import AppointmentStates
from utils import check_subscription
from config import CHANNEL_ID, ADMIN_ID, CHANNEL_LINK

router = Router()
logger = logging.getLogger(__name__)

# Начало записи (кнопка "Записаться")
@router.message(F.text == "📅 Записаться")
async def start_appointment(message: Message, state: FSMContext, bot):
    # Проверка подписки
    if CHANNEL_ID:
        try:
            subscribed = await check_subscription(bot, message.from_user.id)
        except Exception as e:
            logger.error(f"Subscription check error: {e}")
            subscribed = False
        if not subscribed:
            await message.answer(
                "🔒 Для записи необходимо подписаться на канал",
                reply_markup=subscription_check_keyboard(CHANNEL_LINK)
            )
            return

    # Проверка существующей записи
    db: Database = bot.db
    try:
        existing = await db.get_user_appointment(message.from_user.id)
    except Exception as e:
        logger.error(f"Error checking existing appointment: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте позже.")
        return

    if existing:
        await message.answer(
            "❌ У вас уже есть активная запись. Вы можете отменить её в разделе «Отменить запись»."
        )
        return

    # Показываем календарь
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
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            pass
        else:
            logger.error(f"Calendar nav error: {e}")
    except Exception as e:
        logger.error(f"Calendar nav error: {e}")
    finally:
        try:
            await callback.answer()
        except TelegramBadRequest as e:
            if "query is too old" in str(e):
                logger.warning("Callback query too old in calendar nav")

# Закрытие календаря
@router.callback_query(F.data == "cancel_calendar")
async def cancel_calendar(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.delete()
    except Exception as e:
        logger.error(f"Error deleting message: {e}")
    await callback.message.answer("Выберите действие:", reply_markup=main_menu())
    try:
        await callback.answer()
    except TelegramBadRequest as e:
        if "query is too old" in str(e):
            logger.warning("Callback query too old in cancel_calendar")

# Выбор даты
@router.callback_query(F.data.startswith("date_"))
async def process_date_selection(callback: CallbackQuery, state: FSMContext, bot):
    date_str = callback.data.split("_")[1]
    try:
        selected_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        try:
            await callback.answer("Неверный формат даты", show_alert=True)
        except TelegramBadRequest as e:
            if "query is too old" in str(e):
                await callback.message.answer("❌ Неверный формат даты.")
            else:
                logger.error(f"Error in callback.answer: {e}")
        return

    if selected_date < datetime.now().date():
        try:
            await callback.answer("❌ Нельзя выбрать прошедшую дату", show_alert=True)
        except TelegramBadRequest as e:
            if "query is too old" in str(e):
                await callback.message.answer("❌ Нельзя выбрать прошедшую дату.")
            else:
                logger.error(f"Error in callback.answer: {e}")
        return

    await state.update_data(appointment_date=date_str)

    db: Database = bot.db
    try:
        slots = await db.get_available_slots(selected_date)
        logger.info(f"Date {date_str}: found {len(slots)} available slots")
    except Exception as e:
        logger.error(f"Database error in get_available_slots: {e}")
        await callback.message.answer("❌ Ошибка при получении слотов. Попробуйте позже.")
        try:
            await callback.answer()
        except:
            pass
        return

    if not slots:
        try:
            await callback.message.edit_text(
                "На выбранный день нет свободных слотов. Выберите другую дату.",
                reply_markup=calendar_keyboard(selected_date.year, selected_date.month)
            )
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                pass
            else:
                logger.error(f"Error editing message: {e}")
        try:
            await callback.answer()
        except:
            pass
        return

    await state.set_state(AppointmentStates.choosing_time)
    try:
        await callback.message.edit_text(
            f"Выберите время на {date_str}:",
            reply_markup=time_slots_keyboard(slots, date_str)
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            pass
        else:
            logger.error(f"Error editing message: {e}")
    try:
        await callback.answer()
    except TelegramBadRequest as e:
        if "query is too old" in str(e):
            logger.warning("Callback query too old in process_date_selection")

# Назад к календарю
@router.callback_query(F.data == "back_to_calendar")
async def back_to_calendar(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AppointmentStates.choosing_date)
    now = datetime.now()
    try:
        await callback.message.edit_text(
            "Выберите дату:",
            reply_markup=calendar_keyboard(now.year, now.month)
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            pass
        else:
            logger.error(f"Error editing message: {e}")
    try:
        await callback.answer()
    except TelegramBadRequest as e:
        if "query is too old" in str(e):
            logger.warning("Callback query too old in back_to_calendar")

# Выбор времени
@router.callback_query(F.data.startswith("time_"))
async def process_time_selection(callback: CallbackQuery, state: FSMContext, bot):
    parts = callback.data.split("_")
    if len(parts) != 3:
        try:
            await callback.answer("Неверные данные")
        except:
            pass
        return
    _, date_str, time_str = parts
    await state.update_data(appointment_date=date_str, appointment_time=time_str)

    # Получаем список услуг для выбора
    db: Database = bot.db
    services = await db.get_all_services()
    if not services:
        # Если услуг нет, пропускаем выбор и переходим к вводу имени
        await state.set_state(AppointmentStates.entering_name)
        try:
            await callback.message.edit_text(
                "Введите ваше имя:",
                reply_markup=cancel_keyboard()
            )
        except Exception as e:
            logger.error(f"Error editing message: {e}")
        await callback.answer()
        return

    # Сохраняем выбранные услуги (пока пустой список)
    await state.update_data(selected_services=[])
    await state.set_state(AppointmentStates.choosing_services)
    try:
        await callback.message.edit_text(
            "Выберите услуги (можно несколько, нажимая на кнопки):",
            reply_markup=services_keyboard(services, date_str, time_str)
        )
    except Exception as e:
        logger.error(f"Error showing services: {e}")
    try:
        await callback.answer()
    except:
        pass

# Выбор услуги
@router.callback_query(F.data.startswith("service_"), AppointmentStates.choosing_services)
async def process_service_selection(callback: CallbackQuery, state: FSMContext, bot):
    parts = callback.data.split("_")
    if len(parts) != 4:
        await callback.answer()
        return
    _, service_id_str, date_str, time_str = parts
    service_id = int(service_id_str)

    data = await state.get_data()
    selected = data.get('selected_services', [])
    if service_id in selected:
        # Убираем из выбранных
        selected.remove(service_id)
        action_text = "услуга убрана"
    else:
        selected.append(service_id)
        action_text = "услуга добавлена"

    await state.update_data(selected_services=selected)

    db: Database = bot.db
    services = await db.get_all_services()
    # Показываем обновлённый список
    try:
        await callback.message.edit_reply_markup(
            reply_markup=services_keyboard(services, date_str, time_str)
        )
    except Exception as e:
        logger.error(f"Error updating services keyboard: {e}")
    await callback.answer(action_text, show_alert=False)

# Продолжить без услуг
@router.callback_query(F.data.startswith("noservice_"), AppointmentStates.choosing_services)
async def process_no_service(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    if len(parts) != 3:
        await callback.answer()
        return
    _, date_str, time_str = parts
    await state.update_data(selected_services=[])
    # Переходим к вводу имени
    await state.set_state(AppointmentStates.entering_name)
    try:
        await callback.message.edit_text(
            "Введите ваше имя:",
            reply_markup=cancel_keyboard()
        )
    except Exception as e:
        logger.error(f"Error editing message: {e}")
    await callback.answer()

# Подтверждение выбранных услуг (кнопка "Подтвердить запись" после выбора услуг)
@router.callback_query(F.data.startswith("confirm_appointment_"), AppointmentStates.choosing_services)
async def confirm_services(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    if len(parts) != 4:
        await callback.answer()
        return
    _, _, date_str, time_str = parts
    data = await state.get_data()
    selected_ids = data.get('selected_services', [])

    db: Database = callback.bot.db
    services = await db.get_all_services()
    selected_services = [s for s in services if s['id'] in selected_ids]
    if selected_services:
        total_price = sum(s['price'] for s in selected_services)
        services_text = "\n".join([f"• {s['name']} — {s['price']} BYN" for s in selected_services])
        text = (
            f"📝 Вы выбрали услуги:\n{services_text}\n\n"
            f"💵 Общая стоимость: {total_price} BYN\n\n"
            f"Теперь введите ваше имя."
        )
    else:
        text = "Вы не выбрали ни одной услуги. Введите ваше имя."

    await state.set_state(AppointmentStates.entering_name)
    try:
        await callback.message.edit_text(text, reply_markup=cancel_keyboard())
    except Exception as e:
        logger.error(f"Error editing message: {e}")
    await callback.answer()

# Выбор других услуг (возврат к списку)
@router.callback_query(F.data.startswith("reselect_services_"), AppointmentStates.choosing_services)
async def reselect_services(callback: CallbackQuery, state: FSMContext, bot):
    parts = callback.data.split("_")
    if len(parts) != 4:
        await callback.answer()
        return
    _, _, date_str, time_str = parts
    db: Database = bot.db
    services = await db.get_all_services()
    await state.set_state(AppointmentStates.choosing_services)
    try:
        await callback.message.edit_text(
            "Выберите услуги:",
            reply_markup=services_keyboard(services, date_str, time_str)
        )
    except Exception as e:
        logger.error(f"Error editing message: {e}")
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

    data = await state.get_data()
    date_str = data.get('appointment_date')
    time_str = data.get('appointment_time')
    name = data.get('client_name')
    phone = data.get('client_phone')
    selected_ids = data.get('selected_services', [])

    if not all([date_str, time_str, name, phone]):
        await message.answer("❌ Сессия истекла. Начните запись заново.")
        await state.clear()
        return

    db: Database = message.bot.db
    services = await db.get_all_services()
    selected_services = [s for s in services if s['id'] in selected_ids]

    text = f"📝 Проверьте данные:\n\n📅 Дата: {date_str}\n⏰ Время: {time_str}\n👤 Имя: {name}\n📞 Телефон: {phone}\n"
    if selected_services:
        total_price = sum(s['price'] for s in selected_services)
        services_text = "\n".join([f"• {s['name']} — {s['price']} BYN" for s in selected_services])
        text += f"\n💅 Услуги:\n{services_text}\n💵 Итого: {total_price} BYN\n"
    text += "\nВсё верно?"

    await state.set_state(AppointmentStates.confirming)
    await message.answer(
        text,
        reply_markup=confirm_services_keyboard(date_str, time_str)  # используем ту же клавиатуру подтверждения
    )

# Подтверждение записи (финальное)
@router.callback_query(F.data.startswith("confirm_appointment_"), AppointmentStates.confirming)
async def confirm_appointment(callback: CallbackQuery, state: FSMContext, bot):
    parts = callback.data.split("_")
    if len(parts) != 4:
        await callback.answer()
        return
    _, _, date_str, time_str = parts

    try:
        slot_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        slot_time = datetime.strptime(time_str, "%H:%M").time()
    except ValueError:
        await callback.answer("Неверный формат даты или времени")
        return

    user_id = callback.from_user.id
    data = await state.get_data()
    client_name = data.get('client_name')
    client_phone = data.get('client_phone')
    selected_ids = data.get('selected_services', [])

    if not client_name or not client_phone:
        await callback.message.edit_text("❌ Сессия истекла, начните запись заново.")
        await state.clear()
        await callback.answer()
        return

    db: Database = bot.db

    # Проверка доступности слота
    try:
        available = await db.get_available_slots(slot_date)
    except Exception as e:
        logger.error(f"Error checking available slots: {e}")
        await callback.message.answer("❌ Ошибка при проверке доступности. Попробуйте позже.")
        await state.clear()
        await callback.answer()
        return

    if slot_time not in available:
        await callback.message.edit_text("❌ К сожалению, это время уже занято. Попробуйте выбрать другое.")
        await state.clear()
        await callback.answer()
        return

    # Создание записи
    try:
        app_id = await db.create_appointment(
            user_id=user_id,
            client_name=client_name,
            client_phone=client_phone,
            app_date=slot_date,
            app_time=slot_time
        )
        await db.occupy_slot(slot_date, slot_time)

        # Привязываем выбранные услуги
        if selected_ids:
            await db.add_services_to_appointment(app_id, selected_ids)

        # Планируем напоминание
        appointment_datetime = datetime.combine(slot_date, slot_time)
        now = datetime.now()
        delta = appointment_datetime - now
        if delta.total_seconds() > 24 * 3600:
            remind_at = appointment_datetime - timedelta(hours=24)
            scheduler: ReminderScheduler = bot.scheduler
            try:
                await scheduler.schedule_reminder(app_id, remind_at)
            except Exception as e:
                logger.error(f"Failed to schedule reminder: {e}")

        # Уведомление админу с услугами
        services_info = ""
        if selected_ids:
            services = await db.get_all_services()
            selected = [s for s in services if s['id'] in selected_ids]
            services_info = "\n".join([f"• {s['name']} — {s['price']} BYN" for s in selected])
        admin_text = (
            f"✅ Новая запись!\n\n"
            f"👤 Клиент: {client_name}\n"
            f"📞 Телефон: {client_phone}\n"
            f"📅 Дата: {date_str}\n"
            f"⏰ Время: {time_str}\n"
            f"💅 Услуги:\n{services_info if services_info else 'Не выбраны'}\n"
            f"🆔 ID: {app_id}"
        )
        try:
            await bot.send_message(ADMIN_ID, admin_text)
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")

        # Отправка в канал
        if CHANNEL_ID:
            try:
                channel_text = f"📅 Запись на {date_str} в {time_str}\n👤 Клиент: {client_name}"
                await bot.send_message(CHANNEL_ID, channel_text)
            except Exception as e:
                logger.error(f"Failed to send to channel: {e}")

        # Подтверждение пользователю
        await callback.message.edit_text(
            f"✅ Вы успешно записаны!\nДата: {date_str}\nВремя: {time_str}\nЖдём вас ❤️"
        )
        await state.clear()

    except Exception as e:
        logger.error(f"Error creating appointment: {e}", exc_info=True)
        await callback.message.edit_text("❌ Произошла ошибка. Попробуйте позже.")
        await state.clear()

    try:
        await callback.answer()
    except TelegramBadRequest as e:
        if "query is too old" in str(e):
            logger.warning("Callback query too old in confirm_appointment")

# Отмена FSM через inline-кнопку
@router.callback_query(F.data == "cancel_fsm")
async def cancel_fsm(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.edit_text("Действие отменено.")
    except:
        pass
    await callback.message.answer("Выберите действие:", reply_markup=main_menu())
    try:
        await callback.answer()
    except:
        pass
