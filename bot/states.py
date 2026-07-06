from aiogram.fsm.state import State, StatesGroup


class NewAlertStates(StatesGroup):
    waiting_method = State()
    waiting_url = State()
    waiting_query = State()
    waiting_category = State()
    waiting_region = State()
    waiting_price_min = State()
    waiting_price_max = State()
    waiting_name = State()
    confirm = State()
