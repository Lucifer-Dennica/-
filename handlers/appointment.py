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
    confirm_services_keyboard, cancel_keyboard, main_menu,
    subscription_check_keyboard
)
from states import AppointmentStates
from utils import check_subscription
from config import CHANNEL_ID, ADMIN_ID, CHANNEL_LINK

router = Router()
logger = logging.getLogger(__name__)

# Начало записи (кнопка "Записаться")
@router.message(F.text == "📅 Записаться")
async def start_appointment(message: Message, state: FSMContext, bot):
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

    # Показываем список услуг для выбора
    db: Database = bot.db
    services = await db.get_all_services()
    if not services:
        # Если услуг нет, пропускаем выбор
        await state.set_state(AppointmentStates.entering_name)
        try:
            await callback.message.edit_text(
                "Введите ваше имя:",
                reply_markup=cancel_keyboard()
            )
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                pass
            else:
                logger.error(f"Error editing message: {e}")
        await callback.answer()
        return

    await state.set_state(AppointmentStates.choosing_services)
    # Инициализируем пустой список выбранных услуг
    await state.update_data(selected_services=[])
    try:
        await callback.message.edit_text(
            "Выберите услуги (можно несколько):",
            reply_markup=services_keyboard(services, [], date_str, time_str)
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
            logger.warning("Callback query too old in process_time_selection")

# Переключение выбора услуги
@router.callback_query(F.data.startswith("toggle_service_"))
async def toggle_service(callback: CallbackQuery, state: FSMContext, bot):
    parts = callback.data.split("_")
    if len(parts) < 5:
        try:
            await callback.answer("Неверные данные")
        except:
            pass
        return
    service_id = int(parts[2])
    date_str = parts[3]
    time_str = parts[4]

    data = await state.get_data()
    selected = data.get('selected_services', [])
    if service_id in selected:
        selected.remove(service_id)
        action = "убрана"
    else:
        selected.append(service_id)
        action = "добавлена"
    await state.update_data(selected_services=selected)

    db: Database = bot.db
    services = await db.get_all_services()
    try:
        await callback.message.edit_reply_markup(
            reply_markup=services_keyboard(services, selected, date_str, time_str)
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            logger.debug("Keyboard not modified, skipping update")
        else:
            raise
    try:
        await callback.answer(f"Услуга {action}", show_alert=False)
    except TelegramBadRequest as e:
        if "query is too old" in str(e):
            logger.warning("Callback query too old in toggle_service")
        else:
            raise

# Подтверждение выбранных услуг (переход к имени)
@router.callback_query(F.data.startswith("confirm_services_"))
async def confirm_services(callback: CallbackQuery, state: FSMContext, bot):
    parts = callback.data.split("_")
    if len(parts) < 4:
        await callback.answer("Неверные данные")
        return
    date_str = parts[2]
    time_str = parts[3]
    await state.set_state(AppointmentStates.entering_name)
    try:
        await callback.message.edit_text(
            "Введите ваше имя:",
            reply_markup=cancel_keyboard()
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            pass
        else:
            logger.error(f"Error editing message: {e}")
    await callback.answer()

# Продолжить без услуг
@router.callback_query(F.data.startswith("noservice_"))
async def no_service(callback: CallbackQuery, state: FSMContext, bot):
    parts = callback.data.split("_")
    if len(parts) < 3:
        await callback.answer("Неверные данные")
        return
    date_str = parts[1]
    time_str = parts[2]
    await state.update_data(selected_services=[])
    await state.set_state(AppointmentStates.entering_name)
    try:
        await callback.message.edit_text(
            "Введите ваше имя:",
            reply_markup=cancel_keyboard()
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            pass
        else:
            logger.error(f"Error editing message: {e}")
    await callback.answer()

# Повторный выбор услуг (при возврате с этапа подтверждения)
@router.callback_query(F.data.startswith("reselect_services_"))
async def reselect_services(callback: CallbackQuery, state: FSMContext, bot):
    parts = callback.data.split("_")
    if len(parts) < 4:
        await callback.answer("Неверные данные")
        return
    date_str = parts[2]
    time_str = parts[3]

    db: Database = bot.db
    services = await db.get_all_services()
    await state.set_state(AppointmentStates.choosing_services)
    await state.update_data(selected_services=[])
    try:
        await callback.message.edit_text(
            "Выберите услуги (можно несколько):",
            reply_markup=services_keyboard(services, [], date_str, time_str)
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            pass
        else:
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
    selected_services = data.get('selected_services', [])

    if not all([date_str, time_str, name, phone]):
        await message.answer("❌ Сессия истекла. Начните запись заново.")
        await state.clear()
        return

    # Получаем названия выбранных услуг
    db: Database = message.bot.db
    services_list = []
    total_price = 0
    if selected_services:
        all_services = await db.get_all_services()
        services_by_id = {s['id']: s for s in all_services}
        for sid in selected_services:
            if sid in services_by_id:
                services_list.append(services_by_id[sid]['name'])
                total_price += services_by_id[sid]['price']

    text = (
        f"📝 Проверьте данные:\n\n"
        f"📅 Дата: {date_str}\n"
        f"⏰ Время: {time_str}\n"
        f"👤 Имя: {name}\n"
        f"📞 Телефон: {phone}\n"
    )
    if services_list:
        text += f"💅 Услуги: {', '.join(services_list)}\n"
        text += f"💰 Сумма: {total_price} BYN\n"
    else:
        text += f"💅 Услуги: не выбраны\n"

    text += f"\nВсё верно?"

    await state.set_state(AppointmentStates.confirming)
    await message.answer(
        text,
        reply_markup=confirm_services_keyboard(date_str, time_str)
    )

# Финальное подтверждение (старый обработчик confirm_ оставляем для совместимости)
@router.callback_query(F.data.startswith("confirm_"))
async def final_confirm(callback: CallbackQuery, state: FSMContext, bot):
    parts = callback.data.split("_")
    if len(parts) != 3:
        await callback.answer("Неверные данные")
        return
    date_str = parts[1]
    time_str = parts[2]

    # Проверка на "cancel"
    if date_str == "cancel" or time_str == "cancel":
        try:
            await callback.answer()
        except:
            pass
        return

    try:
        slot_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        slot_time = datetime.strptime(time_str, "%H:%M").time()
    except ValueError:
        try:
            await callback.answer("Неверный формат даты или времени")
        except:
            pass
        return

    user_id = callback.from_user.id
    data = await state.get_data()
    client_name = data.get('client_name')
    client_phone = data.get('client_phone')
    selected_services = data.get('selected_services', [])

    if not client_name or not client_phone:
        try:
            await callback.message.edit_text("❌ Сессия истекла, начните запись заново.")
        except:
            pass
        await state.clear()
        try:
            await callback.answer()
        except:
            pass
        return

    db: Database = bot.db

    try:
        available = await db.get_available_slots(slot_date)
        logger.info(f"Checking slot {slot_date} {slot_time}. Available: {[s.strftime('%H:%M') for s in available]}")
    except Exception as e:
        logger.error(f"Error checking available slots: {e}")
        await callback.message.answer("❌ Ошибка при проверке доступности. Попробуйте позже.")
        await state.clear()
        try:
            await callback.answer()
        except:
            pass
        return

    if slot_time not in available:
        try:
            await callback.message.edit_text(
                "❌ К сожалению, это время уже занято. Попробуйте выбрать другое."
            )
        except:
            pass
        await state.clear()
        try:
            await callback.answer()
        except:
            pass
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

        # Привязываем услуги
        if selected_services:
            await db.add_services_to_appointment(app_id, selected_services)

        # Планируем напоминание
        appointment_datetime = datetime.combine(slot_date, slot_time)
        now = datetime.now()
        delta = appointment_datetime - now
        if delta.total_seconds() > 24 * 3600:
            remind_at = appointment_datetime - timedelta(hours=24)
            scheduler: ReminderScheduler = bot.scheduler
            try:
                await scheduler.schedule_reminder(app_id, remind_at)
                logger.info(f"Reminder scheduled for appointment {app_id} at {remind_at}")
            except Exception as e:
                logger.error(f"Failed to schedule reminder: {e}")

        # Уведомление админу
        try:
            admin_text = (
                f"✅ Новая запись!\n\n"
                f"👤 Клиент: {client_name}\n"
                f"📞 Телефон: {client_phone}\n"
                f"📅 Дата: {date_str}\n"
                f"⏰ Время: {time_str}\n"
            )
            if selected_services:
                all_services = await db.get_all_services()
                services_by_id = {s['id']: s for s in all_services}
                services_names = [services_by_id[sid]['name'] for sid in selected_services if sid in services_by_id]
                admin_text += f"💅 Услуги: {', '.join(services_names)}\n"
            admin_text += f"🆔 ID: {app_id}"
            await bot.send_message(ADMIN_ID, admin_text)
            logger.info(f"Admin notified for appointment {app_id}")
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")

        # Отправка в канал
        if CHANNEL_ID:
            try:
                channel_text = (
                    f"📅 Запись на {date_str} в {time_str}\n"
                    f"👤 Клиент: {client_name}"
                )
                if selected_services:
                    all_services = await db.get_all_services()
                    services_by_id = {s['id']: s for s in all_services}
                    services_names = [services_by_id[sid]['name'] for sid in selected_services if sid in services_by_id]
                    channel_text += f"\n💅 Услуги: {', '.join(services_names)}"
                await bot.send_message(CHANNEL_ID, channel_text)
                logger.info(f"Channel notified for appointment {app_id}")
            except Exception as e:
                logger.error(f"Failed to send to channel: {e}")

        # Подтверждение пользователю
        try:
            await callback.message.edit_text(
                f"✅ Вы успешно записаны!\n"
                f"Дата: {date_str}\n"
                f"Время: {time_str}\n\n"
                f"Ждём вас ❤️"
            )
        except Exception as e:
            logger.error(f"Error sending confirmation: {e}")
        await state.clear()

    except Exception as e:
        logger.error(f"Error creating appointment: {e}", exc_info=True)
        try:
            await callback.message.edit_text("❌ Произошла ошибка. Попробуйте позже.")
        except:
            pass
        await state.clear()

    try:
        await callback.answer()
    except TelegramBadRequest as e:
        if "query is too old" in str(e):
            logger.warning("Callback query too old in final_confirm")

# Отмена FSM
@router.callback_query(F.data == "cancel_fsm")
async def cancel_fsm(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.edit_text("Действие отменено.")
    except Exception as e:
        logger.error(f"Error editing message in cancel_fsm: {e}")
    await callback.message.answer("Выберите действие:", reply_markup=main_menu())
    try:
        await callback.answer()
    except TelegramBadRequest as e:
        if "query is too old" in str(e):
            logger.warning("Callback query too old in cancel_fsm")
