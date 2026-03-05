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
from keyboards import (
    admin_panel, cancel_keyboard, admin_calendar_keyboard,
    admin_prices_keyboard, admin_services_list_keyboard
)
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
            try:
                await callback.message.edit_text("Действие не определено. Начните заново.")
            except TelegramBadRequest as e:
                if "message is not modified" in str(e):
                    pass
                else:
                    raise
            await callback.message.answer("Панель администратора:", reply_markup=admin_panel())
            await state.clear()
            await callback.answer()
            return

        if action == 'add_slots':
            await state.update_data(slot_date=date_str)
            await state.set_state(AdminStates.adding_slots_time)
            try:
                await callback.message.edit_text(
                    "Введите время слота в формате ЧЧ:ММ (например, 10:00).\n"
                    "Когда закончите, введите /done",
                    reply_markup=cancel_keyboard()
                )
            except TelegramBadRequest as e:
                if "message is not modified" in str(e):
                    pass
                else:
                    raise
        elif action == 'remove_slot':
            db: Database = bot.db
            slots = await db.get_all_slots(selected_date)
            if not slots:
                try:
                    await callback.message.edit_text("На этот день нет слотов.")
                except TelegramBadRequest as e:
                    if "message is not modified" in str(e):
                        pass
                    else:
                        raise
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
                try:
                    await callback.message.edit_text("Нет доступных слотов для удаления.")
                except TelegramBadRequest as e:
                    if "message is not modified" in str(e):
                        pass
                    else:
                        raise
                await state.clear()
                await callback.message.answer("Панель администратора:", reply_markup=admin_panel())
                await callback.answer()
                return
            builder.adjust(3)
            builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_fsm"))
            try:
                await callback.message.edit_text("Выберите слот для удаления:", reply_markup=builder.as_markup())
            except TelegramBadRequest as e:
                if "message is not modified" in str(e):
                    pass
                else:
                    raise
            await state.clear()
        elif action == 'close_day':
            db: Database = bot.db
            await db.close_day(selected_date)
            try:
                await callback.message.edit_text(f"День {date_str} закрыт (все слоты помечены как недоступные).")
            except TelegramBadRequest as e:
                if "message is not modified" in str(e):
                    pass
                else:
                    raise
            await state.clear()
            await callback.message.answer("Панель администратора:", reply_markup=admin_panel())
        elif action == 'open_day':
            db: Database = bot.db
            await db.open_day(selected_date)
            try:
                await callback.message.edit_text(f"День {date_str} открыт (все слоты помечены как доступные).")
            except TelegramBadRequest as e:
                if "message is not modified" in str(e):
                    pass
                else:
                    raise
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
            try:
                await callback.message.edit_text(text)
            except TelegramBadRequest as e:
                if "message is not modified" in str(e):
                    pass
                else:
                    raise
            apps = await db.get_appointments_for_date(selected_date)
            if apps:
                text2 = "📝 Записи:\n"
                for app in apps:
                    services = await db.get_appointment_services(app['id'])
                    services_str = ", ".join([s['name'] for s in services]) if services else "нет услуг"
                    text2 += f"{app['appointment_time']} - {app['client_name']} ({app['client_phone']}) ID {app['id']}\n   Услуги: {services_str}\n"
                await callback.message.answer(text2)
            await state.clear()
            await callback.message.answer("Панель администратора:", reply_markup=admin_panel())
        elif action == 'delete_range':
            await state.update_data(range_date=date_str)
            await state.set_state(AdminStates.deleting_range_start)
            try:
                await callback.message.edit_text(
                    "Введите начало интервала (ЧЧ:ММ), например 15:00:",
                    reply_markup=cancel_keyboard()
                )
            except TelegramBadRequest as e:
                if "message is not modified" in str(e):
                    pass
                else:
                    raise
        elif action == 'view_clients':
            db: Database = bot.db
            apps = await db.get_appointments_for_date(selected_date)
            if not apps:
                try:
                    await callback.message.edit_text(f"На {date_str} записей нет.")
                except TelegramBadRequest as e:
                    if "message is not modified" in str(e):
                        pass
                    else:
                        raise
            else:
                text = f"📋 Клиенты на {date_str}:\n\n"
                for app in apps:
                    services = await db.get_appointment_services(app['id'])
                    services_str = ", ".join([s['name'] for s in services]) if services else "нет услуг"
                    text += f"⏰ {app['appointment_time']} – {app['client_name']}, {app['client_phone']} (ID {app['id']})\n   Услуги: {services_str}\n"
                try:
                    await callback.message.edit_text(text)
                except TelegramBadRequest as e:
                    if "message is not modified" in str(e):
                        pass
                    else:
                        raise
            await state.clear()
            await callback.message.answer("Панель администратора:", reply_markup=admin_panel())
        else:
            logger.warning(f"Unknown action: {action}")
            try:
                await callback.message.edit_text("Неизвестное действие.")
            except TelegramBadRequest as e:
                if "message is not modified" in str(e):
                    pass
                else:
                    raise
            await state.clear()
            await callback.message.answer("Панель администратора:", reply_markup=admin_panel())

    except Exception as e:
        logger.error(f"Error in admin_date_selected: {e}", exc_info=True)
        try:
            await callback.message.edit_text("❌ Произошла внутренняя ошибка. Попробуйте снова.")
        except:
            pass
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
        # Разбираем callback_data: например "admin_add_slots" -> action = "add", но у нас есть "admin_manage_prices" -> action = "manage"
        parts = callback.data.split("_")
        if len(parts) < 2:
            await callback.answer("Неизвестная команда")
            return
        prefix = parts[0]  # "admin"
        action = parts[1]  # например "add", "remove", "manage"
        logger.info(f"Admin action: {action}")

        now = datetime.now()

        if action == "add":
            await state.update_data(admin_action='add_slots')
            try:
                await callback.message.edit_text(
                    "Выберите дату для добавления слотов:",
                    reply_markup=admin_calendar_keyboard(now.year, now.month)
                )
            except TelegramBadRequest as e:
                if "message is not modified" in str(e):
                    pass
                else:
                    raise
        elif action == "remove":
            await state.update_data(admin_action='remove_slot')
            try:
                await callback.message.edit_text(
                    "Выберите дату, на которой нужно удалить слот:",
                    reply_markup=admin_calendar_keyboard(now.year, now.month)
                )
            except TelegramBadRequest as e:
                if "message is not modified" in str(e):
                    pass
                else:
                    raise
        elif action == "close":
            await state.update_data(admin_action='close_day')
            try:
                await callback.message.edit_text(
                    "Выберите дату, которую нужно закрыть:",
                    reply_markup=admin_calendar_keyboard(now.year, now.month)
                )
            except TelegramBadRequest as e:
                if "message is not modified" in str(e):
                    pass
                else:
                    raise
        elif action == "open":
            await state.update_data(admin_action='open_day')
            try:
                await callback.message.edit_text(
                    "Выберите дату, которую нужно открыть:",
                    reply_markup=admin_calendar_keyboard(now.year, now.month)
                )
            except TelegramBadRequest as e:
                if "message is not modified" in str(e):
                    pass
                else:
                    raise
        elif action == "view":
            await state.update_data(admin_action='view_schedule')
            try:
                await callback.message.edit_text(
                    "Выберите дату для просмотра расписания:",
                    reply_markup=admin_calendar_keyboard(now.year, now.month)
                )
            except TelegramBadRequest as e:
                if "message is not modified" in str(e):
                    pass
                else:
                    raise
        elif action == "cancel":
            await state.set_state(AdminStates.canceling_appointment)
            try:
                await callback.message.edit_text(
                    "Введите ID записи, которую нужно отменить:",
                    reply_markup=cancel_keyboard()
                )
            except TelegramBadRequest as e:
                if "message is not modified" in str(e):
                    pass
                else:
                    raise
        elif action == "delete":
            await state.update_data(admin_action='delete_range')
            try:
                await callback.message.edit_text(
                    "Выберите дату для удаления диапазона:",
                    reply_markup=admin_calendar_keyboard(now.year, now.month)
                )
            except TelegramBadRequest as e:
                if "message is not modified" in str(e):
                    pass
                else:
                    raise
        elif action == "view_clients":
            await state.update_data(admin_action='view_clients')
            try:
                await callback.message.edit_text(
                    "Выберите дату для просмотра клиентов:",
                    reply_markup=admin_calendar_keyboard(now.year, now.month)
                )
            except TelegramBadRequest as e:
                if "message is not modified" in str(e):
                    pass
                else:
                    raise
        elif action == "manage":
            # Открываем меню управления прайсом
            try:
                await callback.message.edit_text(
                    "Управление прайс-листом:",
                    reply_markup=admin_prices_keyboard()
                )
            except TelegramBadRequest as e:
                if "message is not modified" in str(e):
                    pass
                else:
                    raise
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

# ----- Управление прайсом -----
@router.callback_query(F.data == "admin_manage_prices")
async def manage_prices(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    try:
        await callback.message.edit_text(
            "Управление прайс-листом:",
            reply_markup=admin_prices_keyboard()
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            pass
        else:
            logger.error(f"Error in manage_prices: {e}")
    await callback.answer()

@router.callback_query(F.data == "admin_prices_back")
async def prices_back(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    try:
        await callback.message.edit_text(
            "Управление прайс-листом:",
            reply_markup=admin_prices_keyboard()
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            pass
        else:
            logger.error(f"Error in prices_back: {e}")
    await callback.answer()

@router.callback_query(F.data == "admin_add_service")
async def add_service_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    await state.set_state(AdminStates.adding_service_name)
    try:
        await callback.message.edit_text(
            "Введите название новой услуги (например, 'Френч'):",
            reply_markup=cancel_keyboard()
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            pass
        else:
            raise
    await callback.answer()

@router.message(AdminStates.adding_service_name)
async def add_service_name(message: Message, state: FSMContext, bot):
    name = message.text.strip()
    if not name:
        await message.answer("Название не может быть пустым. Введите название:")
        return
    await state.update_data(service_name=name)
    await state.set_state(AdminStates.adding_service_price)
    await message.answer(
        f"Введите цену для услуги '{name}' в BYN (только число):",
        reply_markup=cancel_keyboard()
    )

@router.message(AdminStates.adding_service_price)
async def add_service_price(message: Message, state: FSMContext, bot):
    try:
        price = int(message.text.strip())
        if price <= 0:
            raise ValueError
    except:
        await message.answer("Цена должна быть положительным числом. Введите цену:")
        return
    data = await state.get_data()
    name = data['service_name']
    db: Database = bot.db
    success = await db.add_service(name, price)
    if success:
        await message.answer(f"✅ Услуга '{name}' добавлена с ценой {price} BYN.")
    else:
        await message.answer(f"❌ Услуга с таким названием уже существует.")
    await state.clear()
    await message.answer("Управление прайс-листом:", reply_markup=admin_prices_keyboard())

@router.callback_query(F.data == "admin_list_services")
async def list_services(callback: CallbackQuery, bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    db: Database = bot.db
    services = await db.get_all_services()
    if not services:
        text = "📋 Прайс-лист пуст."
    else:
        text = "📋 Текущие услуги:\n\n"
        for s in services:
            text += f"• {s['name']} — {s['price']} BYN (ID {s['id']})\n"
    try:
        await callback.message.edit_text(text, reply_markup=admin_prices_keyboard())
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            pass
        else:
            logger.error(f"Error listing services: {e}")
    await callback.answer()

@router.callback_query(F.data == "admin_edit_service")
async def edit_service_start(callback: CallbackQuery, bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    db: Database = bot.db
    services = await db.get_all_services()
    if not services:
        await callback.answer("Нет услуг для редактирования", show_alert=True)
        return
    try:
        await callback.message.edit_text(
            "Выберите услугу для редактирования:",
            reply_markup=admin_services_list_keyboard(services, "edit_")
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            pass
        else:
            raise
    await callback.answer()

@router.callback_query(F.data.startswith("edit_"))
async def edit_service_price(callback: CallbackQuery, state: FSMContext, bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    service_id = int(callback.data.split("_")[1])
    db: Database = bot.db
    services = await db.get_all_services()
    service = next((s for s in services if s['id'] == service_id), None)
    if not service:
        await callback.answer("Услуга не найдена", show_alert=True)
        return
    await state.update_data(edit_service_id=service_id, edit_service_name=service['name'])
    await state.set_state(AdminStates.editing_service_price)
    try:
        await callback.message.edit_text(
            f"Текущая цена услуги '{service['name']}': {service['price']} BYN.\n"
            "Введите новую цену:",
            reply_markup=cancel_keyboard()
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            pass
        else:
            raise
    await callback.answer()

@router.message(AdminStates.editing_service_price)
async def edit_service_price_finish(message: Message, state: FSMContext, bot):
    try:
        new_price = int(message.text.strip())
        if new_price <= 0:
            raise ValueError
    except:
        await message.answer("Цена должна быть положительным числом. Введите новую цену:")
        return
    data = await state.get_data()
    service_id = data['edit_service_id']
    service_name = data['edit_service_name']
    db: Database = bot.db
    await db.update_service_price(service_id, new_price)
    await message.answer(f"✅ Цена услуги '{service_name}' изменена на {new_price} BYN.")
    await state.clear()
    await message.answer("Управление прайс-листом:", reply_markup=admin_prices_keyboard())

@router.callback_query(F.data == "admin_delete_service")
async def delete_service_start(callback: CallbackQuery, bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    db: Database = bot.db
    services = await db.get_all_services()
    if not services:
        await callback.answer("Нет услуг для удаления", show_alert=True)
        return
    try:
        await callback.message.edit_text(
            "Выберите услугу для удаления:",
            reply_markup=admin_services_list_keyboard(services, "delete_")
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            pass
        else:
            raise
    await callback.answer()

@router.callback_query(F.data.startswith("delete_"))
async def delete_service_confirm(callback: CallbackQuery, bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    service_id = int(callback.data.split("_")[1])
    db: Database = bot.db
    await db.delete_service(service_id)
    await callback.answer("Услуга удалена", show_alert=False)
    # Обновляем список
    services = await db.get_all_services()
    if services:
        try:
            await callback.message.edit_text(
                "Выберите услугу для удаления:",
                reply_markup=admin_services_list_keyboard(services, "delete_")
            )
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                pass
            else:
                raise
    else:
        try:
            await callback.message.edit_text(
                "Прайс-лист пуст.",
                reply_markup=admin_prices_keyboard()
            )
        except:
            pass
    await callback.answer()

@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    await state.clear()
    try:
        await callback.message.edit_text(
            "Панель администратора:",
            reply_markup=admin_panel()
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            pass
        else:
            raise
    await callback.answer()

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
