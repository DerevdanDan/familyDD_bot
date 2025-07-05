import logging
import json
from datetime import datetime, timedelta
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
from telegram.error import BadRequest

# --- Configuration ---
# Set these as environment variables in your Railway deployment!
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set. Please set it for deployment.")

# Replace 123456789 with your actual Telegram User ID for admin features
ADMIN_ID = int(os.getenv("TELEGRAM_ADMIN_ID", "123456789"))
if ADMIN_ID == 123456789: # Placeholder check
    logging.warning("TELEGRAM_ADMIN_ID environment variable not set or is placeholder. Admin features might not work as expected.")

DATA_FILE = 'points_data.json'
HISTORY_PURGE_INTERVAL_DAYS = 14 # Delete history entries older than 14 days

# --- Conversation States ---
# Unique integer values for each state in our ConversationHandler
MAIN_MENU_CHOICE = 0
SELECT_MEMBER_ADD, ENTER_AMOUNT_ADD, ENTER_REASON_ADD, CONFIRM_ADD = range(1, 5)
SELECT_MEMBER_SUBTRACT, ENTER_AMOUNT_SUBTRACT, ENTER_REASON_SUBTRACT, CONFIRM_SUBTRACT = range(5, 9)
SELECT_FROM_TRANSFER, SELECT_TO_TRANSFER, ENTER_AMOUNT_TRANSFER, ENTER_REASON_TRANSFER, CONFIRM_TRANSFER = range(9, 14)
ADD_MEMBER_NAME, ADD_MEMBER_ID, CONFIRM_ADD_MEMBER = range(14, 17)


# --- Logging Setup ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# --- Data Management Functions ---
# IMPORTANT: These functions MUST be defined before global data initialization.
def load_data():
    """Loads points, history, and family members from the JSON file."""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            try:
                data = json.load(f)
                loaded_family_members = data.get('family_members', {})
                # Convert string keys back to int for FAMILY_MEMBERS if saved as strings
                converted_family_members = {int(k): v for k, v in loaded_family_members.items()}
                return data.get('points', {}), data.get('history', []), converted_family_members
            except json.JSONDecodeError:
                logger.error(f"Error decoding {DATA_FILE}. Starting with empty data.")
                return {}, [], {}
    logger.info(f"{DATA_FILE} not found. Starting with empty data.")
    return {}, [], {}

def save_data(points, history, family_members):
    """Saves points, history, and family members to the JSON file."""
    # Ensure family_members are saved with string keys if they are ints, for JSON compatibility
    string_keyed_family_members = {str(k): v for k, v in family_members.items()}
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump({'points': points, 'history': history, 'family_members': string_keyed_family_members}, f, indent=4)
    except IOError as e:
        logger.error(f"Failed to save data to {DATA_FILE}: {e}")

# --- Global Data Initialization ---
# Initial hardcoded family members for first run or if file is empty
_initial_hardcoded_members = {
    15260416: "Papa",
    441113371: "Mama",
    1059153162: "Danya",
    5678069063: "Vlad",
    5863747570: "Tima",
}

# Load initial data and merge family members
initial_points, initial_history, loaded_family_members_from_file = load_data()

# Start with hardcoded members, then update with any loaded from file
FAMILY_MEMBERS = _initial_hardcoded_members.copy()
FAMILY_MEMBERS.update(loaded_family_members_from_file)

# Build NAME_TO_ID based on the combined FAMILY_MEMBERS
NAME_TO_ID = {name.lower(): uid for uid, name in FAMILY_MEMBERS.items()}

# Initialize current_points and activity_history
current_points = initial_points
activity_history = initial_history

# Ensure all current members have an entry in points, and then save
for uid_str in current_points: # Check existing points data
    if int(uid_str) not in FAMILY_MEMBERS:
        # Remove points for members no longer in FAMILY_MEMBERS
        logger.warning(f"Removing points for deleted member ID: {uid_str}")
current_points = {str(uid): current_points.get(str(uid), 0) for uid, name in FAMILY_MEMBERS.items()}

save_data(current_points, activity_history, FAMILY_MEMBERS)


# --- Helper Functions for Bot Logic ---
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
    save_data(current_points, activity_history, FAMILY_MEMBERS) # Save immediately after recording

def purge_old_history():
    """Deletes history entries older than HISTORY_PURGE_INTERVAL_DAYS."""
    global activity_history # Declare global to modify the list in place
    
    cutoff_date = datetime.now() - timedelta(days=HISTORY_PURGE_INTERVAL_DAYS)
    
    initial_length = len(activity_history)
    # Filter entries that are newer than or equal to the cutoff date
    activity_history = [
        entry for entry in activity_history 
        if datetime.strptime(entry["timestamp"], "%Y-%m-%d %H:%M:%S") >= cutoff_date
    ]
    
    if len(activity_history) < initial_length:
        logger.info(f"Purged {initial_length - len(activity_history)} old history entries.")
        save_data(current_points, activity_history, FAMILY_MEMBERS)
    else:
        logger.info("No history entries to purge.")

def add_new_family_member(user_id: int, user_name: str):
    """Adds a new family member to the global dictionary and saves."""
    global FAMILY_MEMBERS, NAME_TO_ID, current_points # Declare global to modify
    
    if user_id in FAMILY_MEMBERS:
        logger.info(f"User {user_name} (ID: {user_id}) already exists in FAMILY_MEMBERS.")
        return False, "User already exists."

    # Add to main dict
    FAMILY_MEMBERS[user_id] = user_name
    # Update lookup dict
    NAME_TO_ID[user_name.lower()] = user_id
    # Initialize points for new member if they don't have any
    if str(user_id) not in current_points:
        current_points[str(user_id)] = 0 

    save_data(current_points, activity_history, FAMILY_MEMBERS)
    logger.info(f"Added new family member: {user_name} (ID: {user_id})")
    return True, "Member added successfully!"


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
    message_text = "Hello! I'm your Family Points Tracker bot. How can I help you?"
    reply_markup = get_main_menu_keyboard()

    # Determine if it's a new command or a callback from a button
    if update.message:
        await update.message.reply_text(message_text, reply_markup=reply_markup)
    elif update.callback_query:
        query = update.callback_query
        await query.answer() # Acknowledge the callback
        try:
            # Try to edit the message the button was on
            await query.edit_message_text(message_text, reply_markup=reply_markup)
        except BadRequest as e:
            # If editing fails (e.g., message too old, or user deleted it), send a new one
            logger.warning(f"Failed to edit message in start_command: {e}. Sending new message.")
            await update.effective_chat.send_message(message_text, reply_markup=reply_markup)
    
    context.user_data.clear() # Clear any previous conversation data specific to the user
    return MAIN_MENU_CHOICE # Always return to the main menu state

async def handle_main_menu_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the choice of main action from the menu."""
    query = update.callback_query
    await query.answer() # Acknowledge the button press

    choice = query.data
    context.user_data['action_type'] = choice # Store the chosen action type

    if choice == "add":
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
    # Leaderboard and history are directly handled by their respective functions
    # and return MAIN_MENU_CHOICE, so no special handling here beyond the initial choice.
    else:
        # Fallback for unexpected choices
        await query.edit_message_text("Invalid choice. Please select from the menu:", reply_markup=get_main_menu_keyboard())
        return MAIN_MENU_CHOICE


# --- ADD POINTS FLOW ---
async def select_member_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "main_menu":
        return await start_command(update, context) # Go back to main menu

    target_id = int(query.data.split('_')[-1]) # Extract ID from callback_data (e.g., 'select_member_123')
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
    if not reason or reason.isdigit(): # Basic validation: not empty and not just numbers
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

        # Ensure target_id is a string key for current_points dictionary
        current_points[str(target_id)] = current_points.get(str(target_id), 0) + amount
        record_activity(performer_id, "add", amount, target_id=target_id, reason=reason)

        msg = (
            f"✅ {get_user_name(performer_id)} added {amount} points to {target_name} "
            f"(Reason: {reason}).\n"
            f"New total for {target_name}: {current_points[str(target_id)]} points."
        )
        try:
            await query.edit_message_text(msg, reply_markup=get_main_menu_keyboard())
        except BadRequest as e:
            logger.warning(f"Failed to edit message in confirm_add: {e}. Sending new message.")
            await update.effective_chat.send_message(msg, reply_markup=get_main_menu_keyboard())
    else: # Cancel
        try:
            await query.edit_message_text("❌ Add points action cancelled.", reply_markup=get_main_menu_keyboard())
        except BadRequest as e:
            logger.warning(f"Failed to edit message for add cancellation: {e}. Sending new message.")
            await update.effective_chat.send_message("❌ Add points action cancelled.", reply_markup=get_main_menu_keyboard())
    
    context.user_data.clear()
    return MAIN_MENU_CHOICE

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

    # Check if target has enough points before confirming
    if current_points.get(str(target_id), 0) < amount:
        await update.message.reply_text(
            f"🛑 {target_name} doesn't have enough points ({current_points.get(str(target_id), 0)}). Action cancelled.",
            reply_markup=get_main_menu_keyboard()
        )
        context.user_data.clear()
        return MAIN_MENU_CHOICE

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
        
        # Ensure target_id is a string key
        current_points[str(target_id)] -= amount
        record_activity(performer_id, "subtract", amount, target_id=target_id, reason=reason)

        msg = (
            f"✅ {get_user_name(performer_id)} subtracted {amount} points from {target_name} "
            f"(Reason: {reason}).\n"
            f"New total for {target_name}: {current_points[str(target_id)]} points."
        )
        try:
            await query.edit_message_text(msg, reply_markup=get_main_menu_keyboard())
        except BadRequest as e:
            logger.warning(f"Failed to edit message in confirm_subtract: {e}. Sending new message.")
            await update.effective_chat.send_message(msg, reply_markup=get_main_menu_keyboard())
    else: # Cancel
        try:
            await query.edit_message_text("❌ Subtract points action cancelled.", reply_markup=get_main_menu_keyboard())
        except BadRequest as e:
            logger.warning(f"Failed to edit message for subtract cancellation: {e}. Sending new message.")
            await update.effective_chat.send_message("❌ Subtract points action cancelled.", reply_markup=get_main_menu_keyboard())
    
    context.user_data.clear()
    return MAIN_MENU_CHOICE

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
    if current_points.get(str(from_id), 0) < amount:
        await update.message.reply_text(
            f"🛑 {from_name} doesn't have enough points ({current_points.get(str(from_id), 0)}) to transfer. Action cancelled.",
            reply_markup=get_main_menu_keyboard()
        )
        context.user_data.clear()
        return MAIN_MENU_CHOICE

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

        # Ensure string keys for dictionary access
        current_points[str(from_id)] -= amount
        current_points[str(to_id)] = current_points.get(str(to_id), 0) + amount # Use .get() to initialize if new recipient
        record_activity(performer_id, "transfer", amount, source_id=from_id, target_id=to_id, reason=reason)

        msg = (
            f"✅ {get_user_name(performer_id)} transferred {amount} points from {from_name} to {to_name} "
            f"(Reason: {reason}).\n"
            f"New totals:\n"
            f"{from_name}: {current_points[str(from_id)]} points\n"
            f"{to_name}: {current_points[str(to_id)]} points."
        )
        try:
            await query.edit_message_text(msg, reply_markup=get_main_menu_keyboard())
        except BadRequest as e:
            logger.warning(f"Failed to edit message in confirm_transfer: {e}. Sending new message.")
            await update.effective_chat.send_message(msg, reply_markup=get_main_menu_keyboard())
    else: # Cancel
        try:
            await query.edit_message_text("❌ Transfer points action cancelled.", reply_markup=get_main_menu_keyboard())
        except BadRequest as e:
            logger.warning(f"Failed to edit message for transfer cancellation: {e}. Sending new message.")
            await update.effective_chat.send_message("❌ Transfer points action cancelled.", reply_markup=get_main_menu_keyboard())
    
    context.user_data.clear()
    return MAIN_MENU_CHOICE


# --- ADD MEMBER FLOW ---
async def add_member_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the conversation to add a new family member."""
    # Ensure this command is only available in private chat or if a reply to the bot in group
    # For simplicity, we'll keep it admin-only and rely on filters.
    
    # The filters=filters.User(ADMIN_ID) on the command handler already restricts who can initiate this.
    await update.message.reply_text("Okay, let's add a new family member. What is their name (e.g., 'Sara')?")
    context.user_data['temp_performer_id'] = update.effective_user.id # Store who initiated
    return ADD_MEMBER_NAME

async def enter_new_member_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gets the name of the new member."""
    name = update.message.text.strip()
    if not name or any(char.isdigit() for char in name): # Ensure name is not empty and contains no digits
        await update.message.reply_text("Please enter a valid name (text only):")
        return ADD_MEMBER_NAME
    
    context.user_data['new_member_name'] = name
    await update.message.reply_text(
        f"Great! Now, what is {name}'s Telegram User ID? "
        "They can find it by forwarding any message to @userinfobot and looking for 'ID:'."
    )
    return ADD_MEMBER_ID

async def enter_new_member_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gets the Telegram ID of the new member."""
    user_input = update.message.text
    try:
        member_id = int(user_input)
        if member_id <= 0: # IDs are positive
            await update.message.reply_text("Telegram User ID must be a positive number. Please enter a valid ID:")
            return ADD_MEMBER_ID
        context.user_data['new_member_id'] = member_id
    except ValueError:
        await update.message.reply_text("That's not a valid number for a Telegram ID. Please enter digits only:")
        return ADD_MEMBER_ID

    new_member_name = context.user_data['new_member_name']
    new_member_id = context.user_data['new_member_id']

    confirmation_message = (
        f"You are about to add a new family member:\n"
        f"Name: *{new_member_name}*\n"
        f"Telegram ID: `{new_member_id}`\n\n"
        "Do you confirm?"
    )
    await update.message.reply_text(confirmation_message, parse_mode='Markdown', reply_markup=get_confirmation_keyboard())
    return CONFIRM_ADD_MEMBER

async def confirm_add_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Confirms and adds the new member."""
    query = update.callback_query
    await query.answer()

    if query.data == "confirm":
        new_member_id = context.user_data['new_member_id']
        new_member_name = context.user_data['new_member_name']
        performer_id = context.user_data.get('temp_performer_id', update.effective_user.id) # Use stored performer if available

        success, message = add_new_family_member(new_member_id, new_member_name)
        
        if success:
            record_activity(performer_id, "add_member", 0, target_id=new_member_id, reason=f"Added new member: {new_member_name}")
            msg = f"🎉 {new_member_name} (ID: `{new_member_id}`) has been successfully added with 0 points!"
        else:
            msg = f"⚠️ Could not add member: {message}"

        try:
            await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=get_main_menu_keyboard())
        except BadRequest as e:
            logger.warning(f"Failed to edit message in confirm_add_member: {e}. Sending new message.")
            await update.effective_chat.send_message(msg, parse_mode='Markdown', reply_markup=get_main_menu_keyboard())
    else: # Cancel
        try:
            await query.edit_message_text("❌ Adding new family member cancelled.", reply_markup=get_main_menu_keyboard())
        except BadRequest as e:
            logger.warning(f"Failed to edit message for add_member cancellation: {e}. Sending new message.")
            await update.effective_chat.send_message("❌ Adding new family member cancelled.", reply_markup=get_main_menu_keyboard())
    
    context.user_data.clear()
    return MAIN_MENU_CHOICE # Ensure it returns to main menu state


# --- DISPLAY COMMANDS (can be called from main menu or direct command) ---
async def display_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Displays the current point totals for all members."""
    is_callback = bool(update.callback_query)
    
    if not current_points or all(points == 0 for points in current_points.values()):
        msg = "No points tracked yet or all members have 0 points. Start adding some!"
    else:
        # Filter out members with 0 points if you prefer a cleaner leaderboard, or keep them
        display_members = [(uid, points) for uid, points in current_points.items() if points != 0]
        if not display_members: # If all members have 0 points after filtering
            msg = "All members currently have 0 points!"
        else:
            sorted_members = sorted(
                display_members,
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
        else: # Direct command
            await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=get_main_menu_keyboard())
    except BadRequest as e:
        logger.warning(f"Failed to edit message in leaderboard (likely message too old/deleted): {e}. Sending new message.")
        await update.effective_chat.send_message(msg, parse_mode='Markdown', reply_markup=get_main_menu_keyboard())
    
    return MAIN_MENU_CHOICE


async def display_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Displays recent activity history."""
    is_callback = bool(update.callback_query)

    if not activity_history:
        msg = "No activity recorded yet."
    else:
        history_msg = "📜 **Recent Point Activity** 📜\n\n"
        # Show last 10 activities for brevity, newest first
        for entry in reversed(activity_history[-10:]): 
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
        else: # Direct command
            await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=get_main_menu_keyboard())
    except BadRequest as e:
        logger.warning(f"Failed to edit message in history (likely message too old/deleted): {e}. Sending new message.")
        await update.effective_chat.send_message(msg, parse_mode='Markdown', reply_markup=get_main_menu_keyboard())
    
    return MAIN_MENU_CHOICE


# --- Fallbacks and Error Handlers ---
async def cancel_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the current action in a conversation."""
    query = update.callback_query
    
    message_text = "❌ Action cancelled. What would you like to do next?"
    reply_markup = get_main_menu_keyboard()

    if query: # If called from an inline keyboard button
        await query.answer()
        try:
            await query.edit_message_text(message_text, reply_markup=reply_markup)
        except BadRequest as e:
            logger.warning(f"Failed to edit message in cancel_action: {e}. Sending new message.")
            await update.effective_chat.send_message(message_text, reply_markup=reply_markup)
    else: # If triggered by a direct /cancel command
        await update.message.reply_text(message_text, reply_markup=reply_markup)
    
    context.user_data.clear() # Clear any stored data for the cancelled conversation
    return MAIN_MENU_CHOICE # Return to the main menu state

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles unknown commands."""
    await update.message.reply_text(
        "Sorry, I don't understand that command. Please use the buttons or type /start to begin.",
        reply_markup=get_main_menu_keyboard()
    )

async def handle_text_not_in_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responds to text messages that are not part of an active conversation state."""
    # This handler acts as a catch-all for text inputs when the bot isn't expecting specific data.
    # It guides the user back to the main interaction method.
    if update.message and update.message.chat.type == "private":
        await update.message.reply_text(
            "I'm a bot that works with buttons and specific commands! "
            "Please type /start to see what I can do.",
            reply_markup=get_main_menu_keyboard()
        )
    elif update.message: # In group chat, if not private
        await update.message.reply_text(
            "Please use the provided buttons or type /start to interact with me.",
            reply_markup=get_main_menu_keyboard()
        )


# --- Scheduled History Purge ---
async def history_purge_job(context: ContextTypes.DEFAULT_TYPE):
    """Job to periodically purge old history entries."""
    logger.info("Running history purge job...")
    purge_old_history()
    # You could optionally send a notification to the admin here:
    # if ADMIN_ID:
    #     try:
    #         await context.bot.send_message(chat_id=ADMIN_ID, text="Old history purged from points bot data.")
    #     except Exception as e:
    #         logger.error(f"Failed to send admin notification for history purge: {e}")


def main() -> None:
    """Starts the bot."""
    application = Application.builder().token(TOKEN).build()

    # Define the conversation handler
    # The entry_points define how a conversation can start.
    # The states define what handlers are active in each state.
    # The fallbacks define what to do if an unexpected input is received in any state.
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start_command),
            CommandHandler("points", start_command), # Alias for /start
            CommandHandler("add_member", add_member_command, filters=filters.User(ADMIN_ID)) # Admin-only command entry
        ],
        states={
            MAIN_MENU_CHOICE: [
                # Handlers for main menu button choices
                CallbackQueryHandler(handle_main_menu_choice, pattern='^(add|subtract|transfer)$'),
                CallbackQueryHandler(display_leaderboard, pattern='^leaderboard$'),
                CallbackQueryHandler(display_history, pattern='^history$'),
                # Allow direct commands for leaderboard/history even if already in MAIN_MENU_CHOICE state
                CommandHandler("leaderboard", display_leaderboard),
                CommandHandler("history", display_history),
            ],
            # --- ADD POINTS FLOW STATES ---
            SELECT_MEMBER_ADD: [
                CallbackQueryHandler(select_member_add, pattern='^select_member_[0-9]+$'),
                CallbackQueryHandler(start_command, pattern='^main_menu$') # Allow going back to main menu
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
            # --- SUBTRACT POINTS FLOW STATES ---
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
            # --- TRANSFER POINTS FLOW STATES ---
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
            # --- ADD MEMBER FLOW STATES ---
            ADD_MEMBER_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_new_member_name)
            ],
            ADD_MEMBER_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_new_member_id)
            ],
            CONFIRM_ADD_MEMBER: [
                CallbackQueryHandler(confirm_add_member, pattern='^(confirm|cancel_action)$')
            ],
        },
        fallbacks=[
            # Global fallbacks: these handlers are active in ALL states
            CommandHandler("cancel", cancel_action), # Direct /cancel command
            CallbackQueryHandler(cancel_action, pattern='^cancel_action$'), # From any "Cancel" button
            CallbackQueryHandler(start_command, pattern='^main_menu$'), # From any "Back to Main Menu" button
            # Catch any text that doesn't match an expected input in the current state
            # This should generally be placed after specific state handlers to ensure they get priority
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_not_in_conversation)
        ],
        per_user=True, # Each user gets their own independent conversation state
        #per_chat=True, # Use this if you want one conversation per group chat,
                      # but per_user is generally better for personal bot interactions
    )

    application.add_handler(conv_handler)

    # Handlers for messages/commands that are NOT part of any conversation.
    # These will only be triggered if `conv_handler` does not consume the update.
    application.add_handler(MessageHandler(filters.COMMAND, unknown))
    application.add_handler(MessageHandler(filters.TEXT, handle_text_not_in_conversation))

    # Schedule the history purge job to run periodically
    # The job will run every 24 hours, starting 5 minutes after the bot starts.
    application.job_queue.run_repeating(history_purge_job, interval=timedelta(hours=24), first=datetime.now() + timedelta(minutes=5))

    logger.info("Bot is polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()