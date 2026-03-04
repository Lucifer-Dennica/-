# handlers/admin.py
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from datetime import datetime, date, time
import re
from database import Database
from states import AdminStates
from keyboards import admin_panel, cancel_keyboard, calendar_keyboard, time_slots_keyboard
from config import ADMIN_ID
import logging
from aiogram.exceptions import TelegramBadRequest  # добавили импорт

router = Router()
logger = logging.getLogger(__name__)

# Фильтр на админа
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

# Обработка кнопок админ-панели
@router.callback_query(F.data.startswith("admin_"))
async def admin_actions(callback: CallbackQuery, state: FSMContext, bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    action = callback.data.split("_")[1]

    try:
        if action == "add":
            await state.set_state(AdminStates.adding_slots_date)
            await callback.message.edit_text(
                "Введите дату в формате ГГГГ-ММ-ДД (например, 2026-03-10):",
                reply_markup=cancel_keyboard()
            )
        elif action == "remove":
            await state.set_state(AdminStates.removing_slot_date)
            await callback.message.edit_text(
                "Введите дату для удаления слота (ГГГГ-ММ-ДД):",
                reply_markup=cancel_keyboard()
            )
        elif action == "close":
            await state.set_state(AdminStates.closing_day_date)
            await callback.message.edit_text(
                "Введите дату, которую нужно закрыть (ГГГГ-ММ-ДД):",
                reply_markup=cancel_keyboard()
            )
        elif action == "view":
            await state.set_state(AdminStates.viewing_schedule_date)
            await callback.message.edit_text(
                "Введите дату для просмотра расписания (ГГГГ-ММ-ДД):",
                reply_markup=cancel_keyboard()
            )
        elif action == "cancel":
            await state.set_state(AdminStates.canceling_appointment)
            await callback.message.edit_text(
                "Введите ID записи, которую нужно отменить:",
                reply_markup=cancel_keyboard()
            )
        elif action == "delete":
            await state.set_state(AdminStates.deleting_range_date)
            await callback.message.edit_text(
                "Введите дату, в которой нужно удалить диапазон (ГГГГ-ММ-ДД):",
                reply_markup=cancel_keyboard()
            )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            await callback.answer()
            return
        else:
            raise

    await callback.answer()

# ----- Добавление слотов (дата) -----
@router.message(AdminStates.adding_slots_date)
async def add_slots_date(message: Message, state: FSMContext):
    date_str = message.text.strip()
    try:
        slot_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        if slot_date < datetime.now().date():
            await message.answer("Дата не может быть в прошлом. Введите другую:")
            return
    except:
        await message.answer("Неверный формат. Используйте ГГГГ-ММ-ДД:")
        return

    await state.update_data(slot_date=date_str)
    await state.set_state(AdminStates.adding_slots_time)
    await message.answer(
        "Введите время слота в формате ЧЧ:ММ (например, 10:00).\n"
        "Когда закончите, введите /done",
        reply_markup=cancel_keyboard()
    )

# Добавление слотов (время) - цикл
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

# ----- Удаление слота (дата) -----
@router.message(AdminStates.removing_slot_date)
async def remove_slot_date(message: Message, state: FSMContext, bot):
    date_str = message.text.strip()
    try:
        slot_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except:
        await message.answer("Неверный формат. Введите ГГГГ-ММ-ДД:")
        return

    db: Database = bot.db
    slots = await db.get_all_slots(slot_date)
    if not slots:
        await message.answer("На этот день нет слотов.")
        await state.clear()
        return

    await state.update_data(remove_date=date_str)
    await state.set_state(AdminStates.removing_slot_time)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    for slot in slots:
        if slot['is_available']:
            time_str = slot['slot_time'].strftime("%H:%M")
            builder.button(text=time_str, callback_data=f"remove_{date_str}_{time_str}")
    if not builder.buttons:
        await message.answer("Нет доступных слотов для удаления (все заняты?).")
        await state.clear()
        return
    builder.adjust(3)
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_fsm"))
    await message.answer("Выберите слот для удаления:", reply_markup=builder.as_markup())

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
    await callback.answer()

# ----- Закрытие дня -----
@router.message(AdminStates.closing_day_date)
async def close_day(message: Message, state: FSMContext, bot):
    date_str = message.text.strip()
    try:
        slot_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except:
        await message.answer("Неверный формат. Введите ГГГГ-ММ-ДД:")
        return

    db: Database = bot.db
    await db.close_day(slot_date)
    await message.answer(f"День {date_str} закрыт (все слоты помечены как недоступные).")
    await state.clear()

# ----- Просмотр расписания -----
@router.message(AdminStates.viewing_schedule_date)
async def view_schedule(message: Message, state: FSMContext, bot):
    date_str = message.text.strip()
    try:
        view_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except:
        await message.answer("Неверный формат. Введите ГГГГ-ММ-ДД:")
        return

    db: Database = bot.db
    slots = await db.get_all_slots(view_date)
    if not slots:
        await message.answer("На этот день нет слотов.")
    else:
        text = f"📅 Расписание на {date_str}:\n\n"
        for slot in slots:
            status = "✅" if slot['is_available'] else "❌"
            text += f"{slot['slot_time'].strftime('%H:%M')} {status}\n"
        await message.answer(text)

    apps = await db.get_appointments_for_date(view_date)
    if apps:
        text = "📝 Записи:\n"
        for app in apps:
            text += f"{app['appointment_time']} - {app['client_name']} ({app['client_phone']}) ID {app['id']}\n"
        await message.answer(text)
    else:
        await message.answer("Записей на этот день нет.")

    await state.clear()

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

# ----- Удаление диапазона времени -----
@router.message(AdminStates.deleting_range_date)
async def delete_range_date(message: Message, state: FSMContext):
    date_str = message.text.strip()
    try:
        slot_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except:
        await message.answer("Неверный формат. Введите ГГГГ-ММ-ДД:")
        return

    await state.update_data(range_date=date_str)
    await state.set_state(AdminStates.deleting_range_start)
    await message.answer(
        "Введите начало интервала (ЧЧ:ММ), например 15:00:",
        reply_markup=cancel_keyboard()
    )

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
    await message.answer("Введите конец интервала (ЧЧ:ММ):")

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

#Fix edit_text exception
