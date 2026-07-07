from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from bot.navigation import home_row

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


def skip_keyboard(callback: str, *, with_home: bool = True) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="⏭ Пропустить", callback_data=callback)],
    ]
    if with_home:
        rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def step_nav_keyboard(
    skip_callback: str | None = None,
    *,
    extra_rows: list[list[InlineKeyboardButton]] | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if skip_callback:
        rows.append([InlineKeyboardButton(text="⏭ Пропустить", callback_data=skip_callback)])
    if extra_rows:
        rows.extend(extra_rows)
    rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)
