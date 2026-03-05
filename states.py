from aiogram.fsm.state import State, StatesGroup

# Состояния для записи на приём
class AppointmentStates(StatesGroup):
    choosing_date = State()      # Выбор даты
    choosing_time = State()      # Выбор времени
    choosing_services = State()  # Выбор услуг (новое)
    entering_name = State()      # Ввод имени
    entering_phone = State()     # Ввод телефона
    confirming = State()         # Подтверждение

# Состояния для админ-панели
class AdminStates(StatesGroup):
    # Добавление слотов
    adding_slots_date = State()          # Ввод даты
    adding_slots_time = State()          # Ввод времени (циклически)
    # Удаление слота
    removing_slot_date = State()         # Выбор даты
    removing_slot_time = State()         # Выбор времени
    # Закрытие дня
    closing_day_date = State()           # Ввод даты
    # Просмотр расписания
    viewing_schedule_date = State()      # Ввод даты
    # Отмена записи клиента
    canceling_appointment = State()      # Ввод ID записи
    # Удаление диапазона времени
    deleting_range_date = State()        # Ввод даты
    deleting_range_start = State()       # Ввод начала интервала
    deleting_range_end = State()         # Ввод конца интервала
    # Управление прайсом
    adding_service_name = State()        # Ввод названия услуги
    adding_service_price = State()       # Ввод цены
    editing_service_select = State()     # Выбор услуги для редактирования
    editing_service_price = State()      # Ввод новой цены
    deleting_service_select = State()    # Выбор услуги для удаления
