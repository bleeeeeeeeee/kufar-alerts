from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

MAIN_MENU_BUTTONS = {
    "new": "➕ Новая подписка",
    "list": "📋 Мои подписки",
    "edit": "✏️ Редактировать",
    "help": "📖 Инструкция",
    "clear": "🧹 Очистить чат",
}

MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text=MAIN_MENU_BUTTONS["new"]),
            KeyboardButton(text=MAIN_MENU_BUTTONS["list"]),
        ],
        [
            KeyboardButton(text=MAIN_MENU_BUTTONS["edit"]),
            KeyboardButton(text=MAIN_MENU_BUTTONS["help"]),
        ],
        [KeyboardButton(text=MAIN_MENU_BUTTONS["clear"])],
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите действие или введите команду",
)


def skip_keyboard(callback: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⏭ Пропустить", callback_data=callback)]]
    )
