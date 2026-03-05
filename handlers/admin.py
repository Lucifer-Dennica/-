import logging
from datetime import datetime, date, time
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database import Database
from states import AdminStates
from keyboards import admin_panel, cancel_keyboard, admin_calendar_keyboard, time_slots_keyboard
from config import ADMIN_ID

router = Router()
logger = logging.getLogger(__name__)

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

# Команда /admin
@router.message(Command("admin"))
async def admin_cmd(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Доступ запрещён.")
        return
    await message.answer(
        "Панель администратора:",
        reply_markup=admin_panel()
    )

# Обработка навигации по календарю (для всех админ-действий)
@router.callback_query(F.data.startswith("month_"))
async def process_calendar_nav(callback: CallbackQuery, state: FSMContext):
    try:
        _, year, month = callback.data.split("_")
        await callback.message.edit_reply_markup(
            reply_markup=admin_calendar_keyboard(int(year), int(month))
        )
        logger.debug(f"Calendar nav to {year}-{month}")
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
                logger.warning(f"Callback query too old in calendar nav")

# Закрытие календаря
@router.callback_query(F.data == "cancel_calendar")
async def cancel_calendar(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.delete()
    except Exception as e:
        logger.error(f"Error deleting message: {e}")
    await callback.message.answer("Панель администратора:", reply_markup=admin_panel())
    try:
        await callback.answer()
    except TelegramBadRequest as e:
        if "query is too old" in str(e):
            logger.warning("Callback query too old in cancel_calendar")

# Общий обработчик для выбора даты в админке (префикс admin_date_)
@router.callback_query(F.data.startswith("admin_date_"))
async def admin_date_selected(callback: CallbackQuery, state: FSMContext, bot):
    try:
        parts = callback.data.split("_")
        if len(parts) != 3:
            logger.warning(f"Invalid admin_date callback: {callback.data}")
            await callback.answer("Неверный формат данных")
            return
        date_str = parts[2]
        try:
            selected_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            logger.warning(f"Invalid date format: {date_str}")
            await callback.answer("Неверный формат даты")
            return

        current_state = await state.get_state()
        data = await state.get_data()
        action = data.get('admin_action')
        logger.info(f"Admin date selected: {date_str}, action={action}, state={current_state}")

        if not action:
            logger.warning("No admin_action in state")
            await callback.message.edit_text("Действие не определено. Начните заново.")
            await callback.message.answer("Панель администратора:", reply_markup=admin_panel())
            await state.clear()
            await callback.answer()
            return

        if action == 'add_slots':
            await state.update_data(slot_date=date_str)
            await state.set_state(AdminStates.adding_slots_time)
            await callback.message.edit_text(
                "Введите время слота в формате ЧЧ:ММ (например, 10:00).\n"
                "Когда закончите, введите /done",
                reply_markup=cancel_keyboard()
            )
        elif action == 'remove_slot':
            db: Database = bot.db
            slots = await db.get_all_slots(selected_date)
            if not slots:
                await callback.message.edit_text("На этот день нет слотов.")
                await state.clear()
                await callback.message.answer("Панель администратора:", reply_markup=admin_panel())
                await callback.answer()
                return
            builder = InlineKeyboardBuilder()
            for slot in slots:
                if slot['is_available']:
                    time_str = slot['slot_time'].strftime("%H:%M")
                    builder.button(text=time_str, callback_data=f"remove_{date_str}_{time_str}")
            if not builder.buttons:
                await callback.message.edit_text("Нет доступных слотов для удаления.")
                await state.clear()
                await callback.message.answer("Панель администратора:", reply_markup=admin_panel())
                await callback.answer()
                return
            builder.adjust(3)
            builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_fsm"))
            await callback.message.edit_text("Выберите слот для удаления:", reply_markup=builder.as_markup())
            await state.clear()
        elif action == 'close_day':
            db: Database = bot.db
            await db.close_day(selected_date)
            await callback.message.edit_text(f"День {date_str} закрыт (все слоты помечены как недоступные).")
            await state.clear()
            await callback.message.answer("Панель администратора:", reply_markup=admin_panel())
        elif action == 'open_day':  # Новая функция
            db: Database = bot.db
            await db.open_day(selected_date)
            await callback.message.edit_text(f"День {date_str} открыт (все слоты помечены как доступные).")
            await state.clear()
            await callback.message.answer("Панель администратора:", reply_markup=admin_panel())
        elif action == 'view_schedule':
            db: Database = bot.db
            slots = await db.get_all_slots(selected_date)
            text = f"📅 Расписание на {date_str}:\n\n"
            if slots:
                for slot in slots:
                    status = "✅" if slot['is_available'] else "❌"
                    text += f"{slot['slot_time'].strftime('%H:%M')} {status}\n"
            else:
                text += "Нет слотов.\n"
            await callback.message.edit_text(text)
            apps = await db.get_appointments_for_date(selected_date)
            if apps:
                text2 = "📝 Записи:\n"
                for app in apps:
                    text2 += f"{app['appointment_time']} - {app['client_name']} ({app['client_phone']}) ID {app['id']}\n"
                await callback.message.answer(text2)
            await state.clear()
            await callback.message.answer("Панель администратора:", reply_markup=admin_panel())
        elif action == 'delete_range':
            await state.update_data(range_date=date_str)
            await state.set_state(AdminStates.deleting_range_start)
            await callback.message.edit_text(
                "Введите начало интервала (ЧЧ:ММ), например 15:00:",
                reply_markup=cancel_keyboard()
            )
        elif action == 'view_clients':
            db: Database = bot.db
            apps = await db.get_appointments_for_date(selected_date)
            if not apps:
                await callback.message.edit_text(f"На {date_str} записей нет.")
            else:
                text = f"📋 Клиенты на {date_str}:\n\n"
                for app in apps:
                    text += f"⏰ {app['appointment_time']} – {app['client_name']}, {app['client_phone']} (ID {app['id']})\n"
                await callback.message.edit_text(text)
            await state.clear()
            await callback.message.answer("Панель администратора:", reply_markup=admin_panel())
        else:
            logger.warning(f"Unknown action: {action}")
            await callback.message.edit_text("Неизвестное действие.")
            await state.clear()
            await callback.message.answer("Панель администратора:", reply_markup=admin_panel())

    except Exception as e:
        logger.error(f"Error in admin_date_selected: {e}", exc_info=True)
        await callback.message.edit_text("❌ Произошла внутренняя ошибка. Попробуйте снова.")
        await state.clear()
        await callback.message.answer("Панель администратора:", reply_markup=admin_panel())
    finally:
        try:
            await callback.answer()
        except TelegramBadRequest as e:
            if "query is too old" in str(e):
                logger.warning("Callback query too old in admin_date_selected")

# Обработка кнопок админ-панели
@router.callback_query(F.data.startswith("admin_"))
async def admin_actions(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    try:
        action = callback.data.split("_")[1]
        now = datetime.now()
        logger.info(f"Admin action: {action}")

        if action == "add":
            await state.update_data(admin_action='add_slots')
            await callback.message.edit_text(
                "Выберите дату для добавления слотов:",
                reply_markup=admin_calendar_keyboard(now.year, now.month)
            )
        elif action == "remove":
            await state.update_data(admin_action='remove_slot')
            await callback.message.edit_text(
                "Выберите дату, на которой нужно удалить слот:",
                reply_markup=admin_calendar_keyboard(now.year, now.month)
            )
        elif action == "close":
            await state.update_data(admin_action='close_day')
            await callback.message.edit_text(
                "Выберите дату, которую нужно закрыть:",
                reply_markup=admin_calendar_keyboard(now.year, now.month)
            )
        elif action == "open":  # Новая кнопка
            await state.update_data(admin_action='open_day')
            await callback.message.edit_text(
                "Выберите дату, которую нужно открыть:",
                reply_markup=admin_calendar_keyboard(now.year, now.month)
            )
        elif action == "view":
            await state.update_data(admin_action='view_schedule')
            await callback.message.edit_text(
                "Выберите дату для просмотра расписания:",
                reply_markup=admin_calendar_keyboard(now.year, now.month)
            )
        elif action == "cancel":
            await state.set_state(AdminStates.canceling_appointment)
            await callback.message.edit_text(
                "Введите ID записи, которую нужно отменить:",
                reply_markup=cancel_keyboard()
            )
        elif action == "delete":
            await state.update_data(admin_action='delete_range')
            await callback.message.edit_text(
                "Выберите дату для удаления диапазона:",
                reply_markup=admin_calendar_keyboard(now.year, now.month)
            )
        elif action == "view":  # Дубликат? Это для клиентов, но уже есть выше. Лучше переименовать колбэк для клиентов.
            # В admin_panel есть кнопка "Клиенты" с callback_data "admin_view_clients". Проверим.
            pass
        elif action == "view_clients":  # Правильный обработчик для кнопки "Клиенты"
            await state.update_data(admin_action='view_clients')
            await callback.message.edit_text(
                "Выберите дату для просмотра клиентов:",
                reply_markup=admin_calendar_keyboard(now.year, now.month)
            )
        else:
            logger.warning(f"Unknown admin action: {action}")
            await callback.answer("Неизвестная команда")
    except Exception as e:
        logger.error(f"Error in admin_actions: {e}", exc_info=True)
        await callback.answer("Ошибка")
    finally:
        try:
            await callback.answer()
        except TelegramBadRequest as e:
            if "query is too old" in str(e):
                logger.warning("Callback query too old in admin_actions")

# ----- Удаление конкретного слота (выбранного из списка) -----
@router.callback_query(F.data.startswith("remove_"))
async def remove_slot_confirm(callback: CallbackQuery, bot):
    try:
        _, date_str, time_str = callback.data.split("_")
        db: Database = bot.db
        slot_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        slot_time = datetime.strptime(time_str, "%H:%M").time()

        await db.delete_time_slot(slot_date, slot_time)
        try:
            await callback.message.edit_text(f"Слот {time_str} удалён.")
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                pass
            else:
                raise
        await callback.message.answer("Панель администратора:", reply_markup=admin_panel())
    except Exception as e:
        logger.error(f"Error removing slot: {e}", exc_info=True)
        await callback.message.answer("❌ Ошибка при удалении слота.")
    finally:
        try:
            await callback.answer()
        except TelegramBadRequest as e:
            if "query is too old" in str(e):
                logger.warning("Callback query too old in remove_slot_confirm")

# ----- Добавление слотов (ввод времени) -----
@router.message(AdminStates.adding_slots_time)
async def add_slots_time(message: Message, state: FSMContext, bot):
    try:
        if message.text == "/done":
            await state.clear()
            await message.answer("Добавление слотов завершено.", reply_markup=admin_panel())
            return

        time_str = message.text.strip()
        try:
            slot_time = datetime.strptime(time_str, "%H:%M").time()
        except:
            await message.answer("Неверный формат времени. Используйте ЧЧ:ММ:")
            return

        data = await state.get_data()
        slot_date = datetime.strptime(data['slot_date'], "%Y-%m-%d").date()

        db: Database = bot.db
        await db.add_time_slot(slot_date, slot_time)
        await message.answer(f"Слот {time_str} добавлен. Введите следующий или /done")
    except Exception as e:
        logger.error(f"Error adding slot: {e}", exc_info=True)
        await message.answer("❌ Ошибка при добавлении слота.")
        await state.clear()

# ----- Удаление диапазона времени (ввод начала и конца) -----
@router.message(AdminStates.deleting_range_start)
async def delete_range_start(message: Message, state: FSMContext):
    try:
        time_str = message.text.strip()
        try:
            start_time = datetime.strptime(time_str, "%H:%M").time()
        except:
            await message.answer("Неверный формат времени. Используйте ЧЧ:ММ:")
            return
        await state.update_data(range_start=time_str)
        await state.set_state(AdminStates.deleting_range_end)
        await message.answer("Введите конец интервала (ЧЧ:ММ):", reply_markup=cancel_keyboard())
    except Exception as e:
        logger.error(f"Error in delete_range_start: {e}", exc_info=True)
        await message.answer("❌ Ошибка")
        await state.clear()

@router.message(AdminStates.deleting_range_end)
async def delete_range_end(message: Message, state: FSMContext, bot):
    try:
        time_str = message.text.strip()
        try:
            end_time = datetime.strptime(time_str, "%H:%M").time()
        except:
            await message.answer("Неверный формат времени. Используйте ЧЧ:ММ:")
            return

        data = await state.get_data()
        date_str = data['range_date']
        start_str = data['range_start']
        start_time = datetime.strptime(start_str, "%H:%M").time()
        end_time = datetime.strptime(time_str, "%H:%M").time()

        if start_time >= end_time:
            await message.answer("Начало интервала должно быть раньше конца.")
            return

        slot_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        db: Database = bot.db
        await db.delete_time_range(slot_date, start_time, end_time)
        await message.answer(f"Все доступные слоты с {start_str} по {time_str} на {date_str} удалены.")
        await state.clear()
        await message.answer("Панель администратора:", reply_markup=admin_panel())
    except Exception as e:
        logger.error(f"Error in delete_range_end: {e}", exc_info=True)
        await message.answer("❌ Ошибка при удалении диапазона.")
        await state.clear()

# ----- Отмена записи клиента по ID -----
@router.message(AdminStates.canceling_appointment)
async def cancel_appointment_admin(message: Message, state: FSMContext, bot):
    try:
        try:
            app_id = int(message.text.strip())
        except:
            await message.answer("Введите число (ID записи):")
            return

        db: Database = bot.db
        scheduler = bot.scheduler

        app = await db.get_appointment_by_id(app_id)
        if not app:
            await message.answer("Запись с таким ID не найдена.")
            return

        success = await db.cancel_appointment(app_id)
        if success:
            await scheduler.remove_reminder(app_id)
            await message.answer(f"Запись ID {app_id} отменена.")
            try:
                await bot.send_message(
                    app['user_id'],
                    "❌ Ваша запись была отменена администратором."
                )
            except:
                pass
        else:
            await message.answer("Не удалось отменить запись.")
        await state.clear()
        await message.answer("Панель администратора:", reply_markup=admin_panel())
    except Exception as e:
        logger.error(f"Error canceling appointment: {e}", exc_info=True)
        await message.answer("❌ Ошибка при отмене записи.")
        await state.clear()
