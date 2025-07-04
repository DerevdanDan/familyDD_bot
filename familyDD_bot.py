import logging
import json
from datetime import datetime, timedelta
import os
import asyncio # For scheduled tasks

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
from telegram.error import BadRequest

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
HISTORY_PURGE_INTERVAL_DAYS = 14 # Delete history entries older than 14 days

# --- Conversation States ---
# Unique integer values for each state in our ConversationHandler
MAIN_MENU_CHOICE = 0
SELECT_MEMBER_ADD, ENTER_AMOUNT_ADD, ENTER_REASON_ADD, CONFIRM_ADD = range(1, 5)
SELECT_MEMBER_SUBTRACT, ENTER_AMOUNT_SUBTRACT, ENTER_REASON_SUBTRACT, CONFIRM_SUBTRACT = range(5, 9)
SELECT_FROM_TRANSFER, SELECT_TO_TRANSFER, ENTER_AMOUNT_TRANSFER, ENTER_REASON_TRANSFER, CONFIRM_TRANSFER = range(9, 14)


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
save_data(current_points, activity_history) # Ensure initial state is saved

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
    save_data(current_points, activity_history) # Save immediately after recording

def purge_old_history():
    """Deletes history entries older than HISTORY_PURGE_INTERVAL_DAYS."""
    global activity_history # Declare global to modify the list in place
    
    cutoff_date = datetime.now() - timedelta(days=HISTORY_PURGE_INTERVAL_DAYS)
    
    initial_length = len(activity_history)
    activity_history = [
        entry for entry in activity_history 
        if datetime.strptime(entry["timestamp"], "%Y-%m-%d %H:%M:%S") >= cutoff_date
    ]
    
    if len(activity_history) < initial_length:
        logger.info(f"Purged {initial_length - len(activity_history)} old history entries.")
        save_data(current_points, activity_history)
    else:
        logger.info("No history entries to purge.")

# --- Helper Functions for Buttons ---
def get_main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("➕ Add Points", callback_data="add")],
        [InlineKeyboardButton("➖ Subtract Points", callback_data="subtract")],
        [InlineKeyboardButton("↔️ Transfer Points", callback_data="transfer")],
        [InlineKeyboardButton("📊 Leaderboard", callback_data="leaderboard")],
        [InlineKeyboardButton("📜 History", callback_data="history")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_member_selection_keyboard(exclude_id=None):
    keyboard = []
    # Sort members alphabetically for consistent display
    sorted_members = sorted(FAMILY_MEMBERS.items(), key=lambda item: item[1])
    for uid, name in sorted_members:
        if uid != exclude_id:
            keyboard.append([InlineKeyboardButton(name, callback_data=f"select_member_{uid}")])
    keyboard.append([InlineKeyboardButton("↩️ Back to Main Menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

def get_confirmation_keyboard():
    keyboard = [
        [InlineKeyboardButton("✅ Confirm", callback_data="confirm")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")],
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Conversation Flow Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Sends a welcome message and presents main action buttons."""
    if update.message:
        await update.message.reply_text(
            "Hello! I'm your Family Points Tracker bot. How can I help you?",
            reply_markup=get_main_menu_keyboard()
        )
    elif update.callback_query: # If returning from a cancelled action via Main Menu button
        query = update.callback_query
        await query.answer()
        try:
            await query.edit_message_text(
                "Welcome back! What would you like to do?",
                reply_markup=get_main_menu_keyboard()
            )
        except BadRequest as e:
            logger.warning(f"Failed to edit message in start_command: {e}")
            await update.effective_chat.send_message(
                "Welcome back! What would you like to do?",
                reply_markup=get_main_menu_keyboard()
            )
    context.user_data.clear() # Clear any previous conversation data
    return MAIN_MENU_CHOICE

async def handle_main_menu_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the choice of main action from the menu."""
    query = update.callback_query
    await query.answer() # Acknowledge the button press

    choice = query.data
    context.user_data['action_type'] = choice # Store the chosen action type (add, subtract, transfer, leaderboard, history)

    if choice == "leaderboard":
        await display_leaderboard(update, context)
        return ConversationHandler.END # End the conversation
    elif choice == "history":
        await display_history(update, context)
        return ConversationHandler.END # End the conversation
    elif choice == "add":
        await query.edit_message_text(
            "Who do you want to add points to?",
            reply_markup=get_member_selection_keyboard()
        )
        return SELECT_MEMBER_ADD
    elif choice == "subtract":
        await query.edit_message_text(
            "Who do you want to subtract points from?",
            reply_markup=get_member_selection_keyboard()
        )
        return SELECT_MEMBER_SUBTRACT
    elif choice == "transfer":
        await query.edit_message_text(
            "Who do you want to transfer points FROM?",
            reply_markup=get_member_selection_keyboard()
        )
        return SELECT_FROM_TRANSFER
    else:
        await query.edit_message_text("Invalid choice. Please select from the menu:", reply_markup=get_main_menu_keyboard())
        return MAIN_MENU_CHOICE

# --- ADD POINTS FLOW ---
async def select_member_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "main_menu":
        return await start_command(update, context) # Go back to main menu

    target_id = int(query.data.split('_')[-1]) # e.g., 'select_member_123' -> 123
    target_name = get_user_name(target_id)

    context.user_data['target_id'] = target_id
    context.user_data['target_name'] = target_name

    await query.edit_message_text(f"How many points do you want to add to {target_name}? (Enter a number)")
    return ENTER_AMOUNT_ADD

async def enter_amount_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_input = update.message.text
    try:
        amount = int(user_input)
        if amount <= 0:
            await update.message.reply_text("Amount must be a positive number. Please enter a valid number:")
            return ENTER_AMOUNT_ADD
        context.user_data['amount'] = amount
    except ValueError:
        await update.message.reply_text("That's not a number. Please enter the amount in digits (e.g., 10):")
        return ENTER_AMOUNT_ADD

    target_name = context.user_data['target_name']
    await update.message.reply_text(f"Please provide a reason for adding {context.user_data['amount']} points to {target_name}. (e.g., 'for cleaning their room')")
    return ENTER_REASON_ADD

async def enter_reason_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    reason = update.message.text.strip()
    if not reason or reason.isdigit():
        await update.message.reply_text("Please provide a descriptive reason (text, not just numbers):")
        return ENTER_REASON_ADD
    
    context.user_data['reason'] = reason

    target_name = context.user_data['target_name']
    amount = context.user_data['amount']

    confirmation_message = (
        f"You are about to ADD {amount} points to {target_name}.\n"
        f"Reason: {reason}\n\n"
        "Do you confirm?"
    )
    await update.message.reply_text(confirmation_message, reply_markup=get_confirmation_keyboard())
    return CONFIRM_ADD

async def confirm_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "confirm":
        performer_id = update.effective_user.id
        target_id = context.user_data['target_id']
        amount = context.user_data['amount']
        reason = context.user_data['reason']
        target_name = context.user_data['target_name']

        if str(target_id) not in current_points:
            current_points[str(target_id)] = 0
        current_points[str(target_id)] += amount
        record_activity(performer_id, "add", amount, target_id=target_id, reason=reason)
        save_data(current_points, activity_history)

        msg = (
            f"✅ {get_user_name(performer_id)} added {amount} points to {target_name} "
            f"(Reason: {reason}).\n"
            f"New total for {target_name}: {current_points[str(target_id)]} points."
        )
        await query.edit_message_text(msg, reply_markup=get_main_menu_keyboard())
    else: # Cancel
        await query.edit_message_text("❌ Add points action cancelled.", reply_markup=get_main_menu_keyboard())
    
    context.user_data.clear()
    return ConversationHandler.END

# --- SUBTRACT POINTS FLOW ---
async def select_member_subtract(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "main_menu":
        return await start_command(update, context)

    target_id = int(query.data.split('_')[-1])
    target_name = get_user_name(target_id)

    context.user_data['target_id'] = target_id
    context.user_data['target_name'] = target_name

    await query.edit_message_text(f"How many points do you want to subtract from {target_name}? (Enter a number)")
    return ENTER_AMOUNT_SUBTRACT

async def enter_amount_subtract(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_input = update.message.text
    try:
        amount = int(user_input)
        if amount <= 0:
            await update.message.reply_text("Amount must be a positive number. Please enter a valid number:")
            return ENTER_AMOUNT_SUBTRACT
        context.user_data['amount'] = amount
    except ValueError:
        await update.message.reply_text("That's not a number. Please enter the amount in digits (e.g., 5):")
        return ENTER_AMOUNT_SUBTRACT

    target_name = context.user_data['target_name']
    await update.message.reply_text(f"Please provide a reason for subtracting {context.user_data['amount']} points from {target_name}. (e.g., 'for not doing chores')")
    return ENTER_REASON_SUBTRACT

async def enter_reason_subtract(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    reason = update.message.text.strip()
    if not reason or reason.isdigit():
        await update.message.reply_text("Please provide a descriptive reason (text, not just numbers):")
        return ENTER_REASON_SUBTRACT
    
    context.user_data['reason'] = reason

    target_id = context.user_data['target_id']
    target_name = context.user_data['target_name']
    amount = context.user_data['amount']

    if str(target_id) not in current_points or current_points[str(target_id)] < amount:
        await update.message.reply_text(
            f"🛑 {target_name} doesn't have enough points ({current_points.get(str(target_id), 0)}). Action cancelled.",
            reply_markup=get_main_menu_keyboard()
        )
        context.user_data.clear()
        return ConversationHandler.END

    confirmation_message = (
        f"You are about to SUBTRACT {amount} points from {target_name}.\n"
        f"Reason: {reason}\n\n"
        "Do you confirm?"
    )
    await update.message.reply_text(confirmation_message, reply_markup=get_confirmation_keyboard())
    return CONFIRM_SUBTRACT

async def confirm_subtract(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "confirm":
        performer_id = update.effective_user.id
        target_id = context.user_data['target_id']
        amount = context.user_data['amount']
        reason = context.user_data['reason']
        target_name = context.user_data['target_name']
        
        current_points[str(target_id)] -= amount
        record_activity(performer_id, "subtract", amount, target_id=target_id, reason=reason)
        save_data(current_points, activity_history)

        msg = (
            f"✅ {get_user_name(performer_id)} subtracted {amount} points from {target_name} "
            f"(Reason: {reason}).\n"
            f"New total for {target_name}: {current_points[str(target_id)]} points."
        )
        await query.edit_message_text(msg, reply_markup=get_main_menu_keyboard())
    else: # Cancel
        await query.edit_message_text("❌ Subtract points action cancelled.", reply_markup=get_main_menu_keyboard())
    
    context.user_data.clear()
    return ConversationHandler.END

# --- TRANSFER POINTS FLOW ---
async def select_from_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "main_menu":
        return await start_command(update, context)

    from_id = int(query.data.split('_')[-1])
    from_name = get_user_name(from_id)

    context.user_data['from_id'] = from_id
    context.user_data['from_name'] = from_name

    await query.edit_message_text(
        f"Who do you want to transfer points TO from {from_name}?",
        reply_markup=get_member_selection_keyboard(exclude_id=from_id) # Exclude the 'from' user
    )
    return SELECT_TO_TRANSFER

async def select_to_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "main_menu":
        return await start_command(update, context)

    to_id = int(query.data.split('_')[-1])
    to_name = get_user_name(to_id)

    from_id = context.user_data['from_id']
    if from_id == to_id: # Self-transfer prevention
        await query.edit_message_text("You cannot transfer points to yourself! Please select a different recipient.", reply_markup=get_member_selection_keyboard(exclude_id=from_id))
        return SELECT_TO_TRANSFER
        
    context.user_data['to_id'] = to_id
    context.user_data['to_name'] = to_name

    await query.edit_message_text(f"How many points do you want to transfer from {context.user_data['from_name']} to {to_name}? (Enter a number)")
    return ENTER_AMOUNT_TRANSFER

async def enter_amount_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_input = update.message.text
    try:
        amount = int(user_input)
        if amount <= 0:
            await update.message.reply_text("Amount must be a positive number. Please enter a valid number:")
            return ENTER_AMOUNT_TRANSFER
        context.user_data['amount'] = amount
    except ValueError:
        await update.message.reply_text("That's not a number. Please enter the amount in digits (e.g., 20):")
        return ENTER_AMOUNT_TRANSFER

    from_id = context.user_data['from_id']
    from_name = context.user_data['from_name']
    amount = context.user_data['amount']

    # Check if sender has enough points
    if str(from_id) not in current_points or current_points[str(from_id)] < amount:
        await update.message.reply_text(
            f"🛑 {from_name} doesn't have enough points ({current_points.get(str(from_id), 0)}) to transfer. Action cancelled.",
            reply_markup=get_main_menu_keyboard()
        )
        context.user_data.clear()
        return ConversationHandler.END

    to_name = context.user_data['to_name']
    await update.message.reply_text(f"Please provide a reason for this transfer from {from_name} to {to_name}. (e.g., 'for buying me lunch')")
    return ENTER_REASON_TRANSFER

async def enter_reason_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    reason = update.message.text.strip()
    if not reason or reason.isdigit():
        await update.message.reply_text("Please provide a descriptive reason (text, not just numbers):")
        return ENTER_REASON_TRANSFER
    
    context.user_data['reason'] = reason

    from_name = context.user_data['from_name']
    to_name = context.user_data['to_name']
    amount = context.user_data['amount']

    confirmation_message = (
        f"You are about to TRANSFER {amount} points from {from_name} to {to_name}.\n"
        f"Reason: {reason}\n\n"
        "Do you confirm?"
    )
    await update.message.reply_text(confirmation_message, reply_markup=get_confirmation_keyboard())
    return CONFIRM_TRANSFER

async def confirm_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "confirm":
        performer_id = update.effective_user.id
        from_id = context.user_data['from_id']
        to_id = context.user_data['to_id']
        amount = context.user_data['amount']
        reason = context.user_data['reason']
        from_name = context.user_data['from_name']
        to_name = context.user_data['to_name']

        current_points[str(from_id)] -= amount
        current_points[str(to_id)] += amount
        record_activity(performer_id, "transfer", amount, source_id=from_id, target_id=to_id, reason=reason)
        save_data(current_points, activity_history)

        msg = (
            f"✅ {get_user_name(performer_id)} transferred {amount} points from {from_name} to {to_name} "
            f"(Reason: {reason}).\n"
            f"New totals:\n"
            f"{from_name}: {current_points[str(from_id)]} points\n"
            f"{to_name}: {current_points[str(to_id)]} points."
        )
        await query.edit_message_text(msg, reply_markup=get_main_menu_keyboard())
    else: # Cancel
        await query.edit_message_text("❌ Transfer points action cancelled.", reply_markup=get_main_menu_keyboard())
    
    context.user_data.clear()
    return ConversationHandler.END


# --- DISPLAY COMMANDS (can be called from main menu or direct command) ---
async def display_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays the current point totals for all members."""
    # Logic to handle if it came from a button (callback_query) or a direct command (message)
    is_callback = bool(update.callback_query)
    
    if not current_points:
        msg = "No points tracked yet. Start adding some!"
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
        msg = leaderboard_msg
    
    try:
        if is_callback:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(msg, parse_mode='Markdown', reply_markup=get_main_menu_keyboard())
        else:
            await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=get_main_menu_keyboard())
    except BadRequest as e:
        logger.warning(f"Failed to edit message in leaderboard (likely message too old/deleted): {e}")
        await update.effective_chat.send_message(msg, parse_mode='Markdown', reply_markup=get_main_menu_keyboard())


async def display_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays recent activity history."""
    is_callback = bool(update.callback_query)

    if not activity_history:
        msg = "No activity recorded yet."
    else:
        history_msg = "📜 **Recent Point Activity** 📜\n\n"
        # Show last 10 activities for brevity, oldest first
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
        msg = history_msg

    try:
        if is_callback:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(msg, parse_mode='Markdown', reply_markup=get_main_menu_keyboard())
        else:
            await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=get_main_menu_keyboard())
    except BadRequest as e:
        logger.warning(f"Failed to edit message in history (likely message too old/deleted): {e}")
        await update.effective_chat.send_message(msg, parse_mode='Markdown', reply_markup=get_main_menu_keyboard())


# --- Fallbacks and Error Handlers ---
async def cancel_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the current action in a conversation."""
    query = update.callback_query
    if query:
        await query.answer()
        try:
            await query.edit_message_text(
                "❌ Action cancelled. What would you like to do next?",
                reply_markup=get_main_menu_keyboard()
            )
        except BadRequest as e:
            logger.warning(f"Failed to edit message in cancel_action: {e}")
            await update.effective_chat.send_message(
                "❌ Action cancelled. What would you like to do next?",
                reply_markup=get_main_menu_keyboard()
            )
    else: # If triggered by /cancel command
        await update.message.reply_text(
            "❌ Action cancelled. What would you like to do next?",
            reply_markup=get_main_menu_keyboard()
        )
    context.user_data.clear() # Clear any stored data
    return ConversationHandler.END

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles unknown commands."""
    await update.message.reply_text(
        "Sorry, I don't understand that command. Please use the buttons or type /start to begin.",
        reply_markup=get_main_menu_keyboard()
    )

async def handle_text_not_in_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responds to text messages that are not part of an active conversation."""
    if update.message.chat.type == "private":
        await update.message.reply_text(
            "I'm a bot that works with buttons and specific commands! "
            "Please type /start to see what I can do.",
            reply_markup=get_main_menu_keyboard()
        )
    else: # Group chat
        # In a group, we might want to be less verbose for random messages
        # unless it's a reply to the bot or mentions the bot.
        # For simplicity, we'll still prompt, but you could make this silent.
        # For this bot, it's safer to always reply, so users know how to interact.
        await update.message.reply_text(
            "Please use the provided buttons or type /start to interact with me.",
            reply_markup=get_main_menu_keyboard()
        )


# --- Scheduled History Purge ---
async def history_purge_job(context: ContextTypes.DEFAULT_TYPE):
    """Job to periodically purge old history entries."""
    logger.info("Running history purge job...")
    purge_old_history()
    # Optionally notify a specific chat or user that purge ran
    # You might want to get chat_id from an environment variable or config
    # if 'ADMIN_CHAT_ID' in os.environ:
    #     await context.bot.send_message(chat_id=os.environ['ADMIN_CHAT_ID'], text="Old history purged.")


def main() -> None:
    """Starts the bot."""
    application = Application.builder().token(TOKEN).build()

    # Define the conversation handler
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start_command),
            CommandHandler("points", start_command) # Alias for /start
        ],
        states={
            MAIN_MENU_CHOICE: [
                CallbackQueryHandler(handle_main_menu_choice, pattern='^(add|subtract|transfer|leaderboard|history)$')
            ],
            # ADD POINTS FLOW
            SELECT_MEMBER_ADD: [
                CallbackQueryHandler(select_member_add, pattern='^select_member_[0-9]+$'),
                CallbackQueryHandler(start_command, pattern='^main_menu$') # Back to main menu
            ],
            ENTER_AMOUNT_ADD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_amount_add)
            ],
            ENTER_REASON_ADD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_reason_add)
            ],
            CONFIRM_ADD: [
                CallbackQueryHandler(confirm_add, pattern='^(confirm|cancel_action)$')
            ],
            # SUBTRACT POINTS FLOW
            SELECT_MEMBER_SUBTRACT: [
                CallbackQueryHandler(select_member_subtract, pattern='^select_member_[0-9]+$'),
                CallbackQueryHandler(start_command, pattern='^main_menu$')
            ],
            ENTER_AMOUNT_SUBTRACT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_amount_subtract)
            ],
            ENTER_REASON_SUBTRACT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_reason_subtract)
            ],
            CONFIRM_SUBTRACT: [
                CallbackQueryHandler(confirm_subtract, pattern='^(confirm|cancel_action)$')
            ],
            # TRANSFER POINTS FLOW
            SELECT_FROM_TRANSFER: [
                CallbackQueryHandler(select_from_transfer, pattern='^select_member_[0-9]+$'),
                CallbackQueryHandler(start_command, pattern='^main_menu$')
            ],
            SELECT_TO_TRANSFER: [
                CallbackQueryHandler(select_to_transfer, pattern='^select_member_[0-9]+$'),
                CallbackQueryHandler(start_command, pattern='^main_menu$')
            ],
            ENTER_AMOUNT_TRANSFER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_amount_transfer)
            ],
            ENTER_REASON_TRANSFER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_reason_transfer)
            ],
            CONFIRM_TRANSFER: [
                CallbackQueryHandler(confirm_transfer, pattern='^(confirm|cancel_action)$')
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_action), # Direct /cancel command
            CallbackQueryHandler(cancel_action, pattern='^cancel_action$'), # From buttons
            CallbackQueryHandler(start_command, pattern='^main_menu$'), # Back to main menu from any state
            # Catch any text that doesn't match an expected input in a state
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_not_in_conversation)
        ],
        # Per-user conversation, so other users don't interfere with each other's flow
        # In a group chat, each user's conversation state is managed independently.
        per_user=True
    )

    application.add_handler(conv_handler)

    # Add stand-alone command handlers for leaderboard/history if desired, though buttons are primary
    application.add_handler(CommandHandler("leaderboard", display_leaderboard))
    application.add_handler(CommandHandler("history", display_history))

    # Catch all other unhandled messages and commands
    application.add_handler(MessageHandler(filters.COMMAND, unknown))
    application.add_handler(MessageHandler(filters.TEXT, handle_text_not_in_conversation))

    # Schedule the history purge job
    # Run daily (every 24 hours). You can adjust the interval.
    application.job_queue.run_repeating(history_purge_job, interval=timedelta(hours=24), first=datetime.now() + timedelta(minutes=5))


    logger.info("Bot is polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()