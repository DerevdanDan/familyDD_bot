import logging
import json
from datetime import datetime
import os

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
    ConversationHandler,
)
from telegram.error import BadRequest # Import for handling deleted messages

# --- Configuration ---
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set. Please set it for deployment.")

FAMILY_MEMBERS = {
    15260416: "Papa",
    441113371: "Mama",
    1059153162: "Danya",
    5678069063: "Vlad",
    5863747570: "Tima",
}
NAME_TO_ID = {name.lower(): uid for uid, name in FAMILY_MEMBERS.items()}

DATA_FILE = 'points_data.json'

# --- Conversation States ---
# These are arbitrary numbers, just need to be unique integers
START_CHOICE, SELECT_TARGET, ENTER_AMOUNT, ENTER_REASON = range(4)
SELECT_FROM_TRANSFER, SELECT_TO_TRANSFER, ENTER_TRANSFER_AMOUNT, ENTER_TRANSFER_REASON = range(4, 8)
# We can add more states if needed for other actions

# --- Logging Setup ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Data Management Functions ---
def load_data():
    """Loads points and history from the JSON file."""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            try:
                data = json.load(f)
                return data.get('points', {}), data.get('history', [])
            except json.JSONDecodeError:
                logger.warning(f"Error decoding {DATA_FILE}. Starting with empty data.")
                return {}, []
    return {}, []

def save_data(points, history):
    """Saves points and history to the JSON file."""
    with open(DATA_FILE, 'w') as f:
        json.dump({'points': points, 'history': history}, f, indent=4)

current_points, activity_history = load_data()

for uid, name in FAMILY_MEMBERS.items():
    if str(uid) not in current_points:
        current_points[str(uid)] = 0
save_data(current_points, activity_history)

def get_user_name(user_id):
    """Returns the friendly name for a given user ID."""
    return FAMILY_MEMBERS.get(user_id, f"Unknown User ({user_id})")

def get_user_id_by_name(name):
    """Returns the user ID for a given friendly name (case-insensitive)."""
    return NAME_TO_ID.get(name.lower())

def record_activity(performer_id, action, amount, target_id=None, source_id=None, reason=""):
    """Records an activity in the history."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    performer_name = get_user_name(performer_id)
    entry = {
        "timestamp": timestamp,
        "performer": performer_name,
        "performer_id": performer_id,
        "action": action,
        "amount": amount,
        "reason": reason
    }
    if target_id:
        entry["target"] = get_user_name(target_id)
        entry["target_id"] = target_id
    if source_id:
        entry["source"] = get_user_name(source_id)
        entry["source_id"] = source_id

    activity_history.append(entry)
    if len(activity_history) > 100: # Keep history to a reasonable size
        activity_history.pop(0)
    save_data(current_points, activity_history)

# --- Helper Functions for Buttons ---
def get_main_keyboard():
    keyboard = [
        [InlineKeyboardButton("➕ Add Points", callback_data="action_add")],
        [InlineKeyboardButton("➖ Subtract Points", callback_data="action_subtract")],
        [InlineKeyboardButton("↔️ Transfer Points", callback_data="action_transfer")],
        [InlineKeyboardButton("📊 Leaderboard", callback_data="action_leaderboard")],
        [InlineKeyboardButton("📜 History", callback_data="action_history")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_member_keyboard(exclude_id=None):
    keyboard = []
    for uid, name in FAMILY_MEMBERS.items():
        if uid != exclude_id:
            # Callback data format: actiontype_targetuid (e.g., 'add_12345')
            keyboard.append([InlineKeyboardButton(name, callback_data=f"{uid}")])
    return InlineKeyboardMarkup(keyboard)

# --- Conversation Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the conversation and presents main action buttons."""
    await update.message.reply_text(
        "Hello! I'm your Family Points Tracker bot. "
        "What would you like to do?",
        reply_markup=get_main_keyboard()
    )
    return START_CHOICE

async def handle_main_action_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the choice of main action (Add, Subtract, Transfer, Leaderboard, History)."""
    query = update.callback_query
    await query.answer() # Acknowledge the button press

    action = query.data.split('_')[1] # e.g., 'add', 'subtract'

    context.user_data['action'] = action # Store the chosen action

    if action == "leaderboard":
        await leaderboard_command(update, context) # Call the command directly
        return ConversationHandler.END # End the conversation
    elif action == "history":
        await history_command(update, context) # Call the command directly
        return ConversationHandler.END # End the conversation
    elif action in ["add", "subtract"]:
        await query.edit_message_text(
            f"Who do you want to {action} points { 'to' if action == 'add' else 'from' }?",
            reply_markup=get_member_keyboard()
        )
        return SELECT_TARGET # Move to select target
    elif action == "transfer":
        await query.edit_message_text(
            "Who do you want to transfer points FROM?",
            reply_markup=get_member_keyboard()
        )
        return SELECT_FROM_TRANSFER # Move to select source for transfer

async def select_target(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the selection of the target user for add/subtract."""
    query = update.callback_query
    await query.answer()

    target_id = int(query.data)
    target_name = get_user_name(target_id)

    context.user_data['target_id'] = target_id
    context.user_data['target_name'] = target_name

    action = context.user_data['action']

    await query.edit_message_text(f"How many points do you want to {action} {target_name}?")
    return ENTER_AMOUNT # Move to enter amount

async def enter_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the input of the amount."""
    user_input = update.message.text
    performer_id = update.message.from_user.id

    try:
        amount = int(user_input)
        if amount <= 0:
            await update.message.reply_text("Amount must be a positive number. Please enter a valid number:")
            return ENTER_AMOUNT # Stay in this state
        context.user_data['amount'] = amount
    except ValueError:
        await update.message.reply_text("That's not a number. Please enter the amount in digits (e.g., 10):")
        return ENTER_AMOUNT # Stay in this state

    target_name = context.user_data['target_name']
    action = context.user_data['action']

    await update.message.reply_text(f"Please provide a reason for this {action} action for {target_name}.")
    return ENTER_REASON # Move to enter reason

async def enter_reason_and_finalize(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the input of the reason and finalizes the add/subtract action."""
    reason = update.message.text
    performer_id = update.message.from_user.id
    target_id = context.user_data['target_id']
    amount = context.user_data['amount']
    action = context.user_data['action']
    target_name = context.user_data['target_name']

    # Simple check for numbers-only string for reason
    if reason.strip().isdigit():
        await update.message.reply_text("Reasons should be descriptive, not just numbers. Please provide a proper reason:")
        return ENTER_REASON # Stay in this state

    if not reason: # Basic check for empty reason
        await update.message.reply_text("Please provide a reason for the action:")
        return ENTER_REASON # Stay in this state

    # Perform the action based on 'action'
    if action == "add":
        if str(target_id) not in current_points:
            current_points[str(target_id)] = 0
        current_points[str(target_id)] += amount
        record_activity(performer_id, "add", amount, target_id=target_id, reason=reason)
        msg = (
            f"{get_user_name(performer_id)} added {amount} points to {target_name} "
            f"(Reason: {reason}).\n"
            f"New total for {target_name}: {current_points[str(target_id)]} points."
        )
    elif action == "subtract":
        if str(target_id) not in current_points or current_points[str(target_id)] < amount:
            await update.message.reply_text(
                f"{target_name} doesn't have enough points. "
                f"Current: {current_points.get(str(target_id), 0)} points. "
                "Action cancelled."
            )
            return ConversationHandler.END # End conversation due to insufficient funds

        current_points[str(target_id)] -= amount
        record_activity(performer_id, "subtract", amount, target_id=target_id, reason=reason)
        msg = (
            f"{get_user_name(performer_id)} subtracted {amount} points from {target_name} "
            f"(Reason: {reason}).\n"
            f"New total for {target_name}: {current_points[str(target_id)]} points."
        )
    else:
        # This case should ideally not be reached with the current flow
        msg = "An unexpected error occurred."

    save_data(current_points, activity_history)
    await update.message.reply_text(msg)
    return ConversationHandler.END # End the conversation

async def select_from_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the selection of the source user for transfer."""
    query = update.callback_query
    await query.answer()

    from_id = int(query.data)
    from_name = get_user_name(from_id)

    context.user_data['from_id'] = from_id
    context.user_data['from_name'] = from_name

    await query.edit_message_text(
        f"Who do you want to transfer points TO from {from_name}?",
        reply_markup=get_member_keyboard(exclude_id=from_id) # Exclude the 'from' user
    )
    return SELECT_TO_TRANSFER # Move to select target for transfer

async def select_to_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the selection of the target user for transfer."""
    query = update.callback_query
    await query.answer()

    to_id = int(query.data)
    to_name = get_user_name(to_id)

    from_id = context.user_data['from_id']
    if from_id == to_id:
        await query.edit_message_text("Cannot transfer points to yourself! Please select a different recipient.", reply_markup=get_member_keyboard(exclude_id=from_id))
        return SELECT_TO_TRANSFER # Stay in this state
        
    context.user_data['to_id'] = to_id
    context.user_data['to_name'] = to_name

    await query.edit_message_text(f"How many points do you want to transfer from {context.user_data['from_name']} to {to_name}?")
    return ENTER_TRANSFER_AMOUNT # Move to enter transfer amount

async def enter_transfer_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the input of the transfer amount."""
    user_input = update.message.text
    performer_id = update.message.from_user.id

    try:
        amount = int(user_input)
        if amount <= 0:
            await update.message.reply_text("Amount must be a positive number. Please enter a valid number:")
            return ENTER_TRANSFER_AMOUNT
        context.user_data['amount'] = amount
    except ValueError:
        await update.message.reply_text("That's not a number. Please enter the amount in digits (e.g., 20):")
        return ENTER_TRANSFER_AMOUNT

    from_id = context.user_data['from_id']
    to_id = context.user_data['to_id']
    from_name = context.user_data['from_name']
    to_name = context.user_data['to_name']

    # Check if sender has enough points
    if str(from_id) not in current_points or current_points[str(from_id)] < amount:
        await update.message.reply_text(
            f"{from_name} doesn't have enough points to transfer. "
            f"Current: {current_points.get(str(from_id), 0)} points. "
            "Transfer cancelled."
        )
        return ConversationHandler.END # End conversation due to insufficient funds

    await update.message.reply_text(f"Please provide a reason for this transfer from {from_name} to {to_name}.")
    return ENTER_TRANSFER_REASON # Move to enter transfer reason

async def enter_transfer_reason_and_finalize(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the input of the transfer reason and finalizes the action."""
    reason = update.message.text
    performer_id = update.message.from_user.id
    from_id = context.user_data['from_id']
    to_id = context.user_data['to_id']
    amount = context.user_data['amount']
    from_name = context.user_data['from_name']
    to_name = context.user_data['to_name']

    # Simple check for numbers-only string for reason
    if reason.strip().isdigit():
        await update.message.reply_text("Reasons should be descriptive, not just numbers. Please provide a proper reason:")
        return ENTER_TRANSFER_REASON # Stay in this state

    if not reason:
        await update.message.reply_text("Please provide a reason for the transfer:")
        return ENTER_TRANSFER_REASON

    # Perform transfer
    current_points[str(from_id)] -= amount
    current_points[str(to_id)] += amount
    record_activity(performer_id, "transfer", amount, source_id=from_id, target_id=to_id, reason=reason)
    save_data(current_points, activity_history)

    await update.message.reply_text(
        f"{get_user_name(performer_id)} transferred {amount} points from {from_name} to {to_name} "
        f"(Reason: {reason}).\n"
        f"New totals:\n"
        f"{from_name}: {current_points[str(from_id)]} points\n"
        f"{to_name}: {current_points[str(to_id)]} points."
    )
    return ConversationHandler.END

async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays the current point totals for all members."""
    # This function is called directly by handle_main_action_choice,
    # or it can be called by a separate command handler if you want a /leaderboard command too.
    # We edit the message if it's from a callback query, or reply if it's a direct command.
    try:
        query = update.callback_query
        if query:
            await query.answer()
            if not current_points:
                await query.edit_message_text("No points tracked yet. Start adding some!", reply_markup=get_main_keyboard())
                return
            else:
                sorted_members = sorted(
                    [(uid, points) for uid, points in current_points.items()],
                    key=lambda item: item[1],
                    reverse=True
                )
                leaderboard_msg = "🏆 **Family Points Leaderboard** 🏆\n\n"
                for uid_str, points in sorted_members:
                    user_name = get_user_name(int(uid_str))
                    leaderboard_msg += f"• {user_name}: {points} points\n"
                await query.edit_message_text(leaderboard_msg, parse_mode='Markdown', reply_markup=get_main_keyboard())
        else: # Direct command
            if not current_points:
                await update.message.reply_text("No points tracked yet. Start adding some!")
                return

            sorted_members = sorted(
                [(uid, points) for uid, points in current_points.items()],
                key=lambda item: item[1],
                reverse=True
            )
            leaderboard_msg = "🏆 **Family Points Leaderboard** 🏆\n\n"
            for uid_str, points in sorted_members:
                user_name = get_user_name(int(uid_str))
                leaderboard_msg += f"• {user_name}: {points} points\n"
            await update.message.reply_text(leaderboard_msg, parse_mode='Markdown')
    except BadRequest as e:
        # This handles cases where the message might have been deleted or edited by another user
        logger.warning(f"Failed to edit message in leaderboard: {e}")
        # Optionally, send a new message instead if edit fails
        await update.effective_chat.send_message("Here's the leaderboard:\n" + leaderboard_msg, parse_mode='Markdown', reply_markup=get_main_keyboard())


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays recent activity history."""
    try:
        query = update.callback_query
        if query:
            await query.answer()
            if not activity_history:
                await query.edit_message_text("No activity recorded yet.", reply_markup=get_main_keyboard())
                return
            else:
                history_msg = "📜 **Recent Point Activity** 📜\n\n"
                for entry in activity_history[-10:]: # Show last 10 activities
                    msg_parts = [
                        f"*{entry['timestamp']}*",
                        f"Performer: {entry['performer']}"
                    ]
                    if entry['action'] == 'add':
                        msg_parts.append(f"Action: Added *{entry['amount']}* to {entry['target']}")
                    elif entry['action'] == 'subtract':
                        msg_parts.append(f"Action: Subtracted *{entry['amount']}* from {entry['target']}")
                    elif entry['action'] == 'transfer':
                        msg_parts.append(
                            f"Action: Transferred *{entry['amount']}* from {entry['source']} to {entry['target']}"
                        )
                    msg_parts.append(f"Reason: _{entry['reason']}_")
                    history_msg += "\n".join(msg_parts) + "\n\n"
                await query.edit_message_text(history_msg, parse_mode='Markdown', reply_markup=get_main_keyboard())
        else: # Direct command
            if not activity_history:
                await update.message.reply_text("No activity recorded yet.")
                return

            history_msg = "📜 **Recent Point Activity** 📜\n\n"
            for entry in activity_history[-10:]:
                msg_parts = [
                    f"*{entry['timestamp']}*",
                    f"Performer: {entry['performer']}"
                ]
                if entry['action'] == 'add':
                    msg_parts.append(f"Action: Added *{entry['amount']}* to {entry['target']}")
                elif entry['action'] == 'subtract':
                    msg_parts.append(f"Action: Subtracted *{entry['amount']}* from {entry['target']}")
                elif entry['action'] == 'transfer':
                    msg_parts.append(
                        f"Action: Transferred *{entry['amount']}* from {entry['source']} to {entry['target']}"
                    )
                msg_parts.append(f"Reason: _{entry['reason']}_")
                history_msg += "\n".join(msg_parts) + "\n\n"
            await update.message.reply_text(history_msg, parse_mode='Markdown')
    except BadRequest as e:
        logger.warning(f"Failed to edit message in history: {e}")
        await update.effective_chat.send_message("Here's the activity history:\n" + history_msg, parse_mode='Markdown', reply_markup=get_main_keyboard())


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    await update.message.reply_text(
        "Operation cancelled. What would you like to do next?",
        reply_markup=get_main_keyboard()
    )
    context.user_data.clear() # Clear any stored data
    return ConversationHandler.END

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles unknown commands."""
    await update.message.reply_text(
        "Sorry, I don't understand that command. Please use the buttons or type /start to begin.",
        reply_markup=get_main_keyboard()
    )

async def handle_text_not_in_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responds to text messages that are not part of an active conversation."""
    # This handler catches messages that are not commands and not part of an ongoing conversation.
    await update.message.reply_text(
        "I'm a bot that works with buttons and specific commands! "
        "Please use the buttons or type /start to see what I can do.",
        reply_markup=get_main_keyboard()
    )


def main() -> None:
    """Starts the bot."""
    application = Application.builder().token(TOKEN).build()

    # Define the conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start_command), CommandHandler("points", start_command)], # /points is an alias
        states={
            START_CHOICE: [
                CallbackQueryHandler(handle_main_action_choice, pattern='^action_')
            ],
            SELECT_TARGET: [
                CallbackQueryHandler(select_target, pattern='^[0-9]+$') # Match UIDs
            ],
            ENTER_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_amount)
            ],
            ENTER_REASON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_reason_and_finalize)
            ],
            SELECT_FROM_TRANSFER: [
                CallbackQueryHandler(select_from_transfer, pattern='^[0-9]+$')
            ],
            SELECT_TO_TRANSFER: [
                CallbackQueryHandler(select_to_transfer, pattern='^[0-9]+$')
            ],
            ENTER_TRANSFER_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_transfer_amount)
            ],
            ENTER_TRANSFER_REASON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_transfer_reason_and_finalize)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            # Catch all text messages that don't match specific states to prompt user
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_not_in_conversation)
        ]
    )

    application.add_handler(conv_handler)

    # Add stand-alone command handlers for leaderboard/history, in case users prefer them directly
    # These will also redirect to the conversation flow if needed.
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(CommandHandler("history", history_command))

    # Handles unknown commands not caught by the ConversationHandler's fallbacks
    application.add_handler(MessageHandler(filters.COMMAND, unknown))
    
    # Catch any other text not handled by conversation or command (e.g. random text in group chat)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_not_in_conversation))


    logger.info("Bot is polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()