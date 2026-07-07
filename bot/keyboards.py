from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

MAIN_MENU_BUTTONS = {
    "new": "➕ Новая подписка",
    "list": "📋 Мои подписки",
    "settings": "⚙️ Настройки",
    "help": "📖 Инструкция",
}

MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text=MAIN_MENU_BUTTONS["new"]),
            KeyboardButton(text=MAIN_MENU_BUTTONS["list"]),
        ],
        [
            KeyboardButton(text=MAIN_MENU_BUTTONS["settings"]),
            KeyboardButton(text=MAIN_MENU_BUTTONS["help"]),
        ],
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите действие",
)


def skip_keyboard(callback: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⏭ Пропустить", callback_data=callback)]]
    )
