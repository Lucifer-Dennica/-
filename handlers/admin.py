import logging
from datetime import datetime, date, time
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
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
    except Exception as e:
        logger.error(f"Calendar nav error: {e}")
    await callback.answer()

# Закрытие календаря
@router.callback_query(F.data == "cancel_calendar")
async def cancel_calendar(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.message.answer("Панель администратора:", reply_markup=admin_panel())
    await callback.answer()

# Общий обработчик для выбора даты в админке (префикс admin_date_)
@router.callback_query(F.data.startswith("admin_date_"))
async def admin_date_selected(callback: CallbackQuery, state: FSMContext, bot):
    # Извлекаем дату
    date_str = callback.data.split("_")[2]
    try:
        selected_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        await callback.answer("Неверный формат даты")
        return

    # Получаем текущее состояние, чтобы понять, какое действие выполняется
    current_state = await state.get_state()
    data = await state.get_data()
    action = data.get('admin_action')

    if not action:
        await callback.answer("Действие не определено")
        return

    # В зависимости от действия выполняем нужную логику
    if action == 'add_slots':
        # Сохраняем дату и переходим к вводу времени
        await state.update_data(slot_date=date_str)
        await state.set_state(AdminStates.adding_slots_time)
        await callback.message.edit_text(
            "Введите время слота в формате ЧЧ:ММ (например, 10:00).\n"
            "Когда закончите, введите /done",
            reply_markup=cancel_keyboard()
        )
    elif action == 'remove_slot':
        # Показываем список слотов для удаления
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
        await state.clear()  # дальше обработаем remove_ отдельно
    elif action == 'close_day':
        db: Database = bot.db
        await db.close_day(selected_date)
        await callback.message.edit_text(f"День {date_str} закрыт (все слоты помечены как недоступные).")
        await state.clear()
        await callback.message.answer("Панель администратора:", reply_markup=admin_panel())
    elif action == 'view_schedule':
        # Показываем расписание на выбранную дату
        db: Database = bot.db
        slots = await db.get_all_slots(selected_date)
        if slots:
            text = f"📅 Расписание на {date_str}:\n\n"
            for slot in slots:
                status = "✅" if slot['is_available'] else "❌"
                text += f"{slot['slot_time'].strftime('%H:%M')} {status}\n"
            await callback.message.edit_text(text)
        else:
            await callback.message.edit_text(f"На {date_str} нет слотов.")
        apps = await db.get_appointments_for_date(selected_date)
        if apps:
            text = "📝 Записи:\n"
            for app in apps:
                text += f"{app['appointment_time']} - {app['client_name']} ({app['client_phone']}) ID {app['id']}\n"
            await callback.message.answer(text)
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
        # Показываем записи на выбранную дату в виде списка
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

    await callback.answer()

# Обработка кнопок админ-панели
@router.callback_query(F.data.startswith("admin_"))
async def admin_actions(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    action = callback.data.split("_")[1]
    now = datetime.now()

    # Для действий, требующих выбора даты, показываем календарь и сохраняем действие в состоянии
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
    elif action == "view":
        await state.update_data(admin_action='view_schedule')
        await callback.message.edit_text(
            "Выберите дату для просмотра расписания:",
            reply_markup=admin_calendar_keyboard(now.year, now.month)
        )
    elif action == "cancel":
        # Отмена записи клиента по ID (без календаря)
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
    elif action == "view":
        # Кнопка "Клиенты" (используем тот же action, но отдельно)
        await state.update_data(admin_action='view_clients')
        await callback.message.edit_text(
            "Выберите дату для просмотра клиентов:",
            reply_markup=admin_calendar_keyboard(now.year, now.month)
        )

    await callback.answer()

# ----- Удаление конкретного слота (выбранного из списка) -----
@router.callback_query(F.data.startswith("remove_"))
async def remove_slot_confirm(callback: CallbackQuery, bot):
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
    await callback.answer()

# ----- Добавление слотов (ввод времени) -----
@router.message(AdminStates.adding_slots_time)
async def add_slots_time(message: Message, state: FSMContext, bot):
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

# ----- Удаление диапазона времени (ввод начала и конца) -----
@router.message(AdminStates.deleting_range_start)
async def delete_range_start(message: Message, state: FSMContext):
    time_str = message.text.strip()
    try:
        start_time = datetime.strptime(time_str, "%H:%M").time()
    except:
        await message.answer("Неверный формат времени. Используйте ЧЧ:ММ:")
        return
    await state.update_data(range_start=time_str)
    await state.set_state(AdminStates.deleting_range_end)
    await message.answer("Введите конец интервала (ЧЧ:ММ):", reply_markup=cancel_keyboard())

@router.message(AdminStates.deleting_range_end)
async def delete_range_end(message: Message, state: FSMContext, bot):
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

# ----- Отмена записи клиента по ID -----
@router.message(AdminStates.canceling_appointment)
async def cancel_appointment_admin(message: Message, state: FSMContext, bot):
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
