from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.database import Database
from bot.navigation import home_row
from bot.notification_cleanup import purge_notifications
from bot.notifier import (
    NOTIFY_CLEAR_ALERT_MENU_PREFIX,
    NOTIFY_CLEAR_ALERT_PREFIX,
    NOTIFY_CLEAR_ALL,
    NOTIFY_CLEAR_MENU,
    NOTIFY_DELETE_CB,
)
from bot.ui import alert_detail_keyboard, format_alert_card

router = Router()

CLEAR_MENU_TITLE = "🧹 Очистка уведомлений"
BUTTON_TEXT_MAX = 60


def _truncate_button_label(text: str, *, max_len: int = BUTTON_TEXT_MAX) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


async def clear_notifications_menu_keyboard(db: Database, user_id: int) -> InlineKeyboardMarkup:
    total = await db.count_notification_messages(user_id)
    counts = await db.get_notification_counts_by_alert(user_id)
    rows: list[list[InlineKeyboardButton]] = []

    if counts:
        alerts = await db.get_user_alerts(user_id)
        alert_by_id = {alert.id: alert for alert in alerts}
        for alert_id in sorted(
            counts,
            key=lambda aid: (alert_by_id.get(aid).name if alert_by_id.get(aid) else "", aid),
        ):
            count = counts[alert_id]
            if count <= 0:
                continue
            alert = alert_by_id.get(alert_id)
            name = alert.name if alert else f"Подписка #{alert_id}"
            label = _truncate_button_label(f"🧹 {name} ({count})")
            rows.append(
                [
                    InlineKeyboardButton(
                        text=label,
                        callback_data=f"{NOTIFY_CLEAR_ALERT_MENU_PREFIX}{alert_id}",
                    )
                ]
            )

    if total > 0:
        rows.append(
            [InlineKeyboardButton(text=f"🧹 Удалить все ({total})", callback_data=NOTIFY_CLEAR_ALL)]
        )
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="settings:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def clear_notifications_menu_text(db: Database, user_id: int) -> str:
    total = await db.count_notification_messages(user_id)
    if total:
        return (
            f"<b>{CLEAR_MENU_TITLE}</b>\n\n"
            f"В чате отслеживается <b>{total}</b> уведомлений от бота.\n"
            "Можно удалить по подписке или все сразу — меню и сами подписки останутся."
        )
    return (
        f"<b>{CLEAR_MENU_TITLE}</b>\n\n"
        "Сейчас нет сохранённых уведомлений для удаления."
    )


async def show_clear_notifications_menu(callback: CallbackQuery, db: Database) -> None:
    user_id = callback.from_user.id
    await callback.message.edit_text(
        await clear_notifications_menu_text(db, user_id),
        parse_mode="HTML",
        reply_markup=await clear_notifications_menu_keyboard(db, user_id),
    )


@router.callback_query(F.data == NOTIFY_DELETE_CB)
async def delete_notification(callback: CallbackQuery, db: Database) -> None:
    try:
        await callback.message.delete()
    except Exception:
        pass
    await db.forget_notification(callback.from_user.id, callback.message.message_id)
    await callback.answer("Удалено")


@router.callback_query(F.data == NOTIFY_CLEAR_MENU)
async def clear_notifications_menu(callback: CallbackQuery, db: Database) -> None:
    await show_clear_notifications_menu(callback, db)
    await callback.answer()


@router.callback_query(F.data == NOTIFY_CLEAR_ALL)
async def clear_all_notifications(callback: CallbackQuery, db: Database) -> None:
    deleted = await purge_notifications(callback.message.bot, db, callback.from_user.id)
    await callback.answer(f"Удалено: {deleted}")
    await callback.message.edit_text(
        f"<b>{CLEAR_MENU_TITLE}</b>\n\n"
        f"Удалено сообщений: <b>{deleted}</b>.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[home_row()]),
    )


@router.callback_query(F.data.startswith(NOTIFY_CLEAR_ALERT_MENU_PREFIX))
async def clear_alert_notifications_from_menu(callback: CallbackQuery, db: Database) -> None:
    alert_id = int(callback.data.removeprefix(NOTIFY_CLEAR_ALERT_MENU_PREFIX))
    alert = await db.get_alert(alert_id, callback.from_user.id)
    if not alert:
        await callback.answer("Подписка не найдена", show_alert=True)
        return

    deleted = await purge_notifications(
        callback.message.bot,
        db,
        callback.from_user.id,
        alert_id=alert_id,
    )
    await callback.answer(f"Удалено: {deleted}")
    await show_clear_notifications_menu(callback, db)


@router.callback_query(F.data.startswith(NOTIFY_CLEAR_ALERT_PREFIX))
async def clear_alert_notifications(callback: CallbackQuery, db: Database) -> None:
    alert_id = int(callback.data.removeprefix(NOTIFY_CLEAR_ALERT_PREFIX))
    alert = await db.get_alert(alert_id, callback.from_user.id)
    if not alert:
        await callback.answer("Подписка не найдена", show_alert=True)
        return

    deleted = await purge_notifications(
        callback.message.bot,
        db,
        callback.from_user.id,
        alert_id=alert_id,
    )
    await callback.answer(f"Удалено: {deleted}")
    await callback.message.edit_text(
        format_alert_card(alert),
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=alert_detail_keyboard(alert),
    )
