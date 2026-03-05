from aiogram.fsm.state import State, StatesGroup

# Состояния для записи на приём
class AppointmentStates(StatesGroup):
    choosing_date = State()
    choosing_time = State()
    choosing_services = State()
    entering_name = State()
    entering_phone = State()
    confirming = State()

# Состояния для админ-панели
class AdminStates(StatesGroup):
    adding_slots_date = State()
    adding_slots_time = State()
    removing_slot_date = State()
    removing_slot_time = State()
    closing_day_date = State()
    viewing_schedule_date = State()
    canceling_appointment = State()
    deleting_range_date = State()
    deleting_range_start = State()
    deleting_range_end = State()
    # Состояния для управления прайсом
    adding_service_name = State()
    adding_service_price = State()
    editing_service_price = State()
