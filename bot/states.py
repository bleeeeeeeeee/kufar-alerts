from aiogram.fsm.state import State, StatesGroup


class NewAlertStates(StatesGroup):
    waiting_method = State()
    waiting_url = State()
    waiting_query = State()
    picking_category = State()
    picking_region = State()
    waiting_price = State()
    picking_extra = State()
    waiting_name = State()
    confirm = State()


class EditAlertStates(StatesGroup):
    waiting_name = State()
    waiting_query = State()
    waiting_url = State()
    waiting_price = State()
