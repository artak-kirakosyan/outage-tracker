"""
Telegram bot: address CRUD (menu-driven, no address IDs typed by the
user) + notification history. Delivery of computed notifications is
separate (notifications/send.py) -- this app only handles the
user-facing conversation.
"""
from asgiref.sync import sync_to_async
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from accounts.models import format_house_number
from bot import services
from common.enums import Region

REGION, CITY, STREET, NUMBER, SUB, LABEL, CONFIRM = range(7)
FORM_KEY = "address_form"


def _main_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("My addresses", callback_data="menu:addresses")],
        [InlineKeyboardButton("Add address", callback_data="menu:add")],
        [InlineKeyboardButton("Notifications", callback_data="menu:notifications")],
    ])


def _address_label(address) -> str:
    base = f"{address.street} {format_house_number(address.house_number, address.house_number_sub)}"
    return f"{base} — {address.label}" if address.label else base


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await sync_to_async(services.get_or_create_user)(str(update.effective_user.id))
    await update.message.reply_text("Welcome. What would you like to do?", reply_markup=_main_menu_markup())


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.edit_message_text("What would you like to do?", reply_markup=_main_menu_markup())


async def list_addresses(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await sync_to_async(services.get_or_create_user)(str(update.effective_user.id))
    addresses = await sync_to_async(services.list_addresses)(user)
    if not addresses:
        buttons = [
            [InlineKeyboardButton("Add address", callback_data="menu:add")],
            [InlineKeyboardButton("« Main menu", callback_data="menu:main")],
        ]
        await update.callback_query.edit_message_text("You have no addresses yet.", reply_markup=InlineKeyboardMarkup(buttons))
        return
    buttons = [[InlineKeyboardButton(_address_label(a), callback_data=f"addr:view:{a.id}")] for a in addresses]
    buttons.append([InlineKeyboardButton("« Main menu", callback_data="menu:main")])
    await update.callback_query.edit_message_text("Your addresses:", reply_markup=InlineKeyboardMarkup(buttons))


async def view_address(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    address_id = int(update.callback_query.data.split(":")[2])
    user = await sync_to_async(services.get_or_create_user)(str(update.effective_user.id))
    address = await sync_to_async(services.get_address)(user, address_id)
    if address is None:
        await update.callback_query.answer("That address no longer exists.", show_alert=True)
        return await list_addresses(update, context)

    text = f"{address.get_region_display()}, {address.district_or_city}\n{_address_label(address)}"
    buttons = [
        [InlineKeyboardButton("Edit", callback_data=f"addr:edit:{address.id}"),
         InlineKeyboardButton("Delete", callback_data=f"addr:delete:{address.id}")],
        [InlineKeyboardButton("« My addresses", callback_data="menu:addresses")],
        [InlineKeyboardButton("« Main menu", callback_data="menu:main")],
    ]
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))


async def confirm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    address_id = int(update.callback_query.data.split(":")[2])
    buttons = [[
        InlineKeyboardButton("Yes, delete", callback_data=f"addr:delete_yes:{address_id}"),
        InlineKeyboardButton("Cancel", callback_data=f"addr:view:{address_id}"),
    ]]
    await update.callback_query.edit_message_text("Delete this address?", reply_markup=InlineKeyboardMarkup(buttons))


async def do_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    address_id = int(update.callback_query.data.split(":")[2])
    user = await sync_to_async(services.get_or_create_user)(str(update.effective_user.id))
    address = await sync_to_async(services.get_address)(user, address_id)
    if address is not None:
        await sync_to_async(services.delete_address)(address)
    await update.callback_query.answer("Address deleted.")
    await list_addresses(update, context)


async def list_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await sync_to_async(services.get_or_create_user)(str(update.effective_user.id))
    logs = await sync_to_async(services.list_recent_notifications)(user)
    text = "\n".join(f"• {log.address}: {log.outage_announcement} ({log.status})" for log in logs) or "No notifications yet."
    buttons = [[InlineKeyboardButton("« Main menu", callback_data="menu:main")]]
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))


# --- Add / edit address conversation ---

def _region_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=f"region:{value}")] for value, label in Region.choices])


async def start_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data[FORM_KEY] = {}
    await update.callback_query.edit_message_text("Choose a region:", reply_markup=_region_keyboard())
    return REGION


async def start_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    address_id = int(update.callback_query.data.split(":")[2])
    user = await sync_to_async(services.get_or_create_user)(str(update.effective_user.id))
    address = await sync_to_async(services.get_address)(user, address_id)
    if address is None:
        await update.callback_query.answer("That address no longer exists.", show_alert=True)
        await list_addresses(update, context)
        return ConversationHandler.END

    context.user_data[FORM_KEY] = {"editing_id": address.id}
    await update.callback_query.edit_message_text("Choose a region:", reply_markup=_region_keyboard())
    return REGION


async def receive_region(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data[FORM_KEY]["region"] = update.callback_query.data.split(":", 1)[1]
    await update.callback_query.edit_message_text("City / settlement?")
    return CITY


async def receive_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data[FORM_KEY]["district_or_city"] = update.message.text.strip()
    await update.message.reply_text("Street?")
    return STREET


async def receive_street(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data[FORM_KEY]["street"] = update.message.text.strip()
    await update.message.reply_text("House number?")
    return NUMBER


async def receive_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("Please send a plain number.")
        return NUMBER
    context.user_data[FORM_KEY]["house_number"] = int(text)
    await update.message.reply_text(
        "Any sub-number (e.g. 'A')? Send it, or press Skip.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Skip", callback_data="skip:sub")]]),
    )
    return SUB


async def receive_sub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data[FORM_KEY]["house_number_sub"] = update.message.text.strip()
    return await _ask_label(update, context)


async def skip_sub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data[FORM_KEY]["house_number_sub"] = ""
    await update.callback_query.answer()
    return await _ask_label(update, context)


async def _ask_label(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("Skip", callback_data="skip:label")]])
    text = "A label for this address (e.g. 'Home')? Send it, or press Skip."
    if update.message:
        await update.message.reply_text(text, reply_markup=markup)
    else:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    return LABEL


async def receive_label(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data[FORM_KEY]["label"] = update.message.text.strip()
    return await _ask_confirm(update, context)


async def skip_label(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data[FORM_KEY]["label"] = ""
    await update.callback_query.answer()
    return await _ask_confirm(update, context)


async def _ask_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    form = context.user_data[FORM_KEY]
    region_label = dict(Region.choices).get(form["region"], form["region"])
    house_display = format_house_number(form["house_number"], form["house_number_sub"])
    text = (
        f"{region_label}, {form['district_or_city']}\n"
        f"{form['street']} {house_display}"
        + (f" — {form['label']}" if form["label"] else "")
        + "\n\nSave this address?"
    )
    buttons = InlineKeyboardMarkup([[
        InlineKeyboardButton("Save", callback_data="confirm:save"),
        InlineKeyboardButton("Cancel", callback_data="confirm:cancel"),
    ]])
    if update.message:
        await update.message.reply_text(text, reply_markup=buttons)
    else:
        await update.callback_query.edit_message_text(text, reply_markup=buttons)
    return CONFIRM


async def save_address(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    form = context.user_data.pop(FORM_KEY)
    user = await sync_to_async(services.get_or_create_user)(str(update.effective_user.id))
    fields = {
        "region": form["region"],
        "district_or_city": form["district_or_city"],
        "street": form["street"],
        "house_number": form["house_number"],
        "house_number_sub": form["house_number_sub"],
        "label": form["label"],
    }
    editing_id = form.get("editing_id")
    if editing_id:
        address = await sync_to_async(services.get_address)(user, editing_id)
        await sync_to_async(services.update_address)(address, **fields)
    else:
        await sync_to_async(services.create_address)(user, **fields)

    await update.callback_query.answer("Saved.")
    await list_addresses(update, context)
    return ConversationHandler.END


async def cancel_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop(FORM_KEY, None)
    await update.callback_query.answer("Cancelled.")
    await show_main_menu(update, context)
    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop(FORM_KEY, None)
    await update.message.reply_text("Cancelled.", reply_markup=_main_menu_markup())
    return ConversationHandler.END


def build_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_add, pattern="^menu:add$"),
            CallbackQueryHandler(start_edit, pattern="^addr:edit:"),
        ],
        states={
            REGION: [CallbackQueryHandler(receive_region, pattern="^region:")],
            CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_city)],
            STREET: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_street)],
            NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_number)],
            SUB: [
                CallbackQueryHandler(skip_sub, pattern="^skip:sub$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_sub),
            ],
            LABEL: [
                CallbackQueryHandler(skip_label, pattern="^skip:label$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_label),
            ],
            CONFIRM: [
                CallbackQueryHandler(save_address, pattern="^confirm:save$"),
                CallbackQueryHandler(cancel_button, pattern="^confirm:cancel$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
    )


def register_handlers(application) -> None:
    application.add_handler(CommandHandler("start", start))
    application.add_handler(build_conversation_handler())
    application.add_handler(CallbackQueryHandler(show_main_menu, pattern="^menu:main$"))
    application.add_handler(CallbackQueryHandler(list_addresses, pattern="^menu:addresses$"))
    application.add_handler(CallbackQueryHandler(list_notifications, pattern="^menu:notifications$"))
    application.add_handler(CallbackQueryHandler(view_address, pattern="^addr:view:"))
    application.add_handler(CallbackQueryHandler(confirm_delete, pattern=r"^addr:delete:\d+$"))
    application.add_handler(CallbackQueryHandler(do_delete, pattern="^addr:delete_yes:"))
