from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from datetime import datetime, timedelta
import calendar

# ----- Главное меню (Reply-кнопки) -----
def main_menu():
    kb = [
        [KeyboardButton(text="📅 Записаться")],
        [KeyboardButton(text="💰 Прайсы"), KeyboardButton(text="📷 Портфолио")],
        [KeyboardButton(text="❌ Отменить запись")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# ----- Общий календарь (для клиентов) -----
def calendar_keyboard(year: int, month: int, prefix: str = "date"):
    """
    prefix: "date" для клиентов, "admin_date" для админки
    """
    builder = InlineKeyboardBuilder()
    month_name = calendar.month_name[month]
    builder.row(InlineKeyboardButton(text=f"{month_name} {year}", callback_data="ignore"))
    week_days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    builder.row(*[InlineKeyboardButton(text=day, callback_data="ignore") for day in week_days])
    month_calendar = calendar.monthcalendar(year, month)
    for week in month_calendar:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data="ignore"))
            else:
                date_str = f"{year}-{month:02d}-{day:02d}"
                row.append(InlineKeyboardButton(text=str(day), callback_data=f"{prefix}_{date_str}"))
        builder.row(*row)
    # Кнопки навигации
    prev_month = datetime(year, month, 1) - timedelta(days=1)
    next_month = datetime(year, month, 28) + timedelta(days=4)
    nav_row = []
    if prev_month > datetime(2020, 1, 1):
        nav_row.append(InlineKeyboardButton(text="◀", callback_data=f"month_{prev_month.year}_{prev_month.month}"))
    else:
        nav_row.append(InlineKeyboardButton(text=" ", callback_data="ignore"))
    nav_row.append(InlineKeyboardButton(text="❌ Закрыть", callback_data="cancel_calendar"))
    if next_month < datetime(2030, 1, 1):
        nav_row.append(InlineKeyboardButton(text="▶", callback_data=f"month_{next_month.year}_{next_month.month}"))
    else:
        nav_row.append(InlineKeyboardButton(text=" ", callback_data="ignore"))
    builder.row(*nav_row)
    return builder.as_markup()

# ----- Календарь для админки (с другим префиксом) -----
def admin_calendar_keyboard(year: int, month: int):
    return calendar_keyboard(year, month, prefix="admin_date")

# ----- Кнопки выбора времени (слоты) -----
def time_slots_keyboard(slots, date_str):
    builder = InlineKeyboardBuilder()
    for slot in slots:
        time_str = slot.strftime("%H:%M")
        builder.button(text=time_str, callback_data=f"time_{date_str}_{time_str}")
    builder.adjust(3)
    builder.row(InlineKeyboardButton(text="🔙 Назад к календарю", callback_data="back_to_calendar"))
    return builder.as_markup()

# ----- Админ-панель (обновлённая) -----
def admin_panel():
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить слоты", callback_data="admin_add_slots")
    builder.button(text="➖ Удалить слот", callback_data="admin_remove_slot")
    builder.button(text="📅 Закрыть день", callback_data="admin_close_day")
    builder.button(text="🔓 Открыть день", callback_data="admin_open_day")   # Новая кнопка
    builder.button(text="📋 Просмотр расписания", callback_data="admin_view_schedule")
    builder.button(text="❌ Отменить запись клиента", callback_data="admin_cancel_appointment")
    builder.button(text="🗑 Удалить диапазон времени", callback_data="admin_delete_range")
    builder.button(text="📋 Клиенты", callback_data="admin_view_clients")
    builder.adjust(2)
    return builder.as_markup()

# ----- Кнопка отмены для FSM -----
def cancel_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="cancel_fsm")
    return builder.as_markup()

# ----- Кнопка подтверждения записи -----
def confirm_appointment_keyboard(date_str, time_str):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data=f"confirm_{date_str}_{time_str}")
    builder.button(text="❌ Отмена", callback_data="cancel_fsm")
    return builder.as_markup()

# ----- Кнопка "Проверить подписку" -----
def subscription_check_keyboard(link: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="🔔 Подписаться", url=link)
    builder.button(text="✅ Проверить подписку", callback_data="check_subscription")
    return builder.as_markup()

# ----- Кнопка портфолио (одна ссылка) -----
def portfolio_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📸 Смотреть портфолио", url="https://ru.pinterest.com/crystalwithluv/_created/")
    return builder.as_markup()
