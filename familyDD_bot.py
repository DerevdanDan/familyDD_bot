import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
)
import json
import logging
import os

# --- Configuration and Constants ---
# Use environment variable for secure token handling on deployment platforms like Railway
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") 
# Fallback for local testing if the environment variable isn't set
if not BOT_TOKEN:
    # NOTE: In a production environment, you should remove this hardcoded token
    # or ensure the environment variable is always set.
    BOT_TOKEN = "7142262881:AAGXHFcMY_bSWKhEXJRBtU05rU-lo86YpxQ" 

DATA_FILE = "data.json"
PARTICIPANTS = ["Mama", "Papa", "Danya", "Vlad", "Tima", "Car"]
CAR_ACCOUNT_NAME = "Car"
CAR_STARTING_POINTS = 50

# Conversation States for the multi-step transaction process
SELECT_ACTION, SELECT_SOURCE, SELECT_TARGET, GET_REASON, GET_AMOUNT = range(5)

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Data Persistence Functions ---

def load_data():
    """Loads points and history data from the JSON file."""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
            return data["points"], data["history"]
    else:
        # Initial state: 0 points for people, 50 points for the Car
        initial_points = {name: 0 for name in PARTICIPANTS}
        initial_points[CAR_ACCOUNT_NAME] = CAR_STARTING_POINTS # Set Car's initial points
        initial_history = []
        return initial_points, initial_history

def save_data(points, history):
    """Saves points and history data to the JSON file."""
    data = {"points": points, "history": history}
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

POINTS, HISTORY = load_data()

# --- Utility Functions ---

def get_main_keyboard():
    """Creates the main menu keyboard."""
    keyboard = [
        [InlineKeyboardButton("➕ Add Points", callback_data="ACTION_add")],
        [InlineKeyboardButton("➖ Subtract Points", callback_data="ACTION_subtract")],
        [InlineKeyboardButton("🔁 Transfer Points", callback_data="ACTION_transfer")],
        [InlineKeyboardButton("📊 See Points Table", callback_data="ACTION_table")],
        [InlineKeyboardButton("📜 See History", callback_data="ACTION_history")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_participant_keyboard(prefix):
    """Creates a keyboard for selecting a participant (Source or Target)."""
    keyboard = [[InlineKeyboardButton(name, callback_data=f"{prefix}_{name}")] for name in PARTICIPANTS]
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    return InlineKeyboardMarkup(keyboard)

# --- Command and Handler Functions ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Sends a welcome message and the main menu."""
    await update.message.reply_text(
        "Welcome! I am your Family Points Counter Bot.\n"
        "Use the buttons below to manage your points.",
        reply_markup=get_main_keyboard()
    )
    return SELECT_ACTION

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Edits the message to show the main menu or sends a new one if not a callback."""
    query = update.callback_query
    
    if query:
        await query.answer()
        await query.edit_message_text(
            "Please select an action:",
            reply_markup=get_main_keyboard()
        )
    else:
        # Should only happen from the /start fallback, but good to be robust
        await update.message.reply_text(
            "Returning to main menu:",
            reply_markup=get_main_keyboard()
        )
    return SELECT_ACTION

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles button presses for actions and participant selection."""
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "cancel":
        await query.edit_message_text("Transaction cancelled. Returning to main menu.", reply_markup=get_main_keyboard())
        return SELECT_ACTION
    
    elif data == "back_to_menu":
        # Handled by show_main_menu below
        return await show_main_menu(update, context)
        
    elif data.startswith("ACTION_"):
        action = data.split("_")[1]
        context.user_data['action'] = action
        
        if action == "table":
            return await show_points_table(update, context)
        elif action == "history":
            return await show_history(update, context)
        elif action in ["add", "subtract"]:
            await query.edit_message_text(
                f"You chose to **{action} points**. Who is the target?",
                reply_markup=get_participant_keyboard("TARGET"),
                parse_mode="Markdown"
            )
            return SELECT_TARGET
        elif action == "transfer":
            await query.edit_message_text(
                "You chose to **transfer points**. Who is the source?",
                reply_markup=get_participant_keyboard("SOURCE"),
                parse_mode="Markdown"
            )
            return SELECT_SOURCE

    elif data.startswith("SOURCE_"):
        context.user_data['source'] = data.split("_")[1]
        await query.edit_message_text(
            f"Source is **{context.user_data['source']}**. Who is the target?",
            reply_markup=get_participant_keyboard("TARGET"),
            parse_mode="Markdown"
        )
        return SELECT_TARGET

    elif data.startswith("TARGET_"):
        context.user_data['target'] = data.split("_")[1]
        action = context.user_data['action']
        
        # Now we have all needed participants, ASK FOR REASON FIRST
        msg = f"**Selected Action:** {action.capitalize()} Points\n"
        
        if action in ["add", "subtract"]:
            msg += f"**Target:** {context.user_data['target']}\n\n"
        elif action == "transfer":
            source = context.user_data['source']
            target = context.user_data['target']
            msg += f"**Source:** {source}\n"
            msg += f"**Target:** {target}\n\n"
            
        msg += "Please reply with the **reason** for this transaction (e.g., 'Completed chores', 'Paid back a debt')."
            
        await query.edit_message_text(msg, parse_mode="Markdown")
        return GET_REASON # <--- NEW STATE TRANSITION

    # Fallback to main menu if data is not recognized
    return SELECT_ACTION

async def get_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Captures the reason and asks for the amount."""
    
    # Save the user's message as the reason
    reason = update.message.text
    context.user_data['reason'] = reason
    
    # Now ask for the amount
    # We use reply_text here because it's a message handler, not a callback handler
    await update.message.reply_text(
        f"You entered the reason: **{reason}**.\n\n"
        f"How many points would you like to put for this transaction? "
        f"Please reply with only the **amount in numbers** (e.g., `10`, `50`).",
        parse_mode="Markdown"
    )
    
    return GET_AMOUNT # <--- Transition to the final state

async def get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Processes the user's message containing only the amount and executes the transaction."""
    user_input = update.message.text.strip()
    reason = context.user_data['reason'] # Retrieve the saved reason
    
    # 1. Parse and Validate Input
    try:
        amount = int(user_input)
        
        if amount <= 0:
            raise ValueError("Amount must be a positive number.")
            
    except ValueError:
        await update.message.reply_text(
            f"❌ **Input Error:** Please reply with only a valid **positive number** for the amount.",
            parse_mode="Markdown"
        )
        # Stay in the same state to retry
        return GET_AMOUNT 

    # 2. Setup Transaction variables
    action = context.user_data['action']
    target = context.user_data.get('target')
    source = context.user_data.get('source')
    
    global POINTS, HISTORY 
    
    # --- Car Account Restrictions ---
    if target == CAR_ACCOUNT_NAME and action == "subtract":
        await update.message.reply_text(
            f"❌ **Transaction Failed:** You cannot subtract points from the **{CAR_ACCOUNT_NAME}** account.",
            reply_markup=get_main_keyboard(),
            parse_mode="Markdown"
        )
        return SELECT_ACTION

    if source == CAR_ACCOUNT_NAME and action == "transfer":
        await update.message.reply_text(
            f"❌ **Transaction Failed:** The **{CAR_ACCOUNT_NAME}** account cannot transfer points to others.",
            reply_markup=get_main_keyboard(),
            parse_mode="Markdown"
        )
        return SELECT_ACTION
    # --- End Restrictions ---
    
    transaction_successful = False
    log_entry = f"[{update.message.date.strftime('%Y-%m-%d %H:%M')}] {reason} ({amount} points): "
    
    # 3. Perform the Transaction
    if action == "add":
        POINTS[target] += amount
        log_entry += f"➕ {target} received {amount} points."
        transaction_successful = True
        
    elif action == "subtract":
        if POINTS[target] < amount:
            await update.message.reply_text(
                f"❌ **Transaction Failed:** {target} only has {POINTS[target]} points. Cannot subtract {amount}.",
                reply_markup=get_main_keyboard(),
                parse_mode="Markdown"
            )
            return SELECT_ACTION
            
        POINTS[target] -= amount
        log_entry += f"➖ {target} lost {amount} points."
        transaction_successful = True
        
    elif action == "transfer":
        if POINTS[source] < amount:
            await update.message.reply_text(
                f"❌ **Transaction Failed:** {source} only has {POINTS[source]} points. Cannot transfer {amount}.",
                reply_markup=get_main_keyboard(),
                parse_mode="Markdown"
            )
            return SELECT_ACTION
            
        POINTS[source] -= amount
        POINTS[target] += amount
        log_entry += f"🔁 {source} transferred {amount} points to {target}."
        transaction_successful = True
        
    # 4. Save Data and Conclude
    if transaction_successful:
        HISTORY.append(log_entry)
        save_data(POINTS, HISTORY)
        
        # Determine who to show the new point total for (usually the target)
        final_person = target 
        if action == "subtract":
             final_person = target # Show the new total for the person who lost points
        
        await update.message.reply_text(
            f"✅ **Transaction Complete!**\n{log_entry.replace('[', '').replace(']', '')}\n\n"
            f"**{final_person}** now has **{POINTS[final_person]}** points.",
            reply_markup=get_main_keyboard(),
            parse_mode="Markdown"
        )
    
    return SELECT_ACTION


async def show_points_table(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Generates and displays the current points table."""
    global POINTS
    
    sorted_points = sorted(POINTS.items(), key=lambda item: item[1], reverse=True)
    
    table_text = "✨ **Current Points Table** ✨\n\n"
    for name, points in sorted_points:
        table_text += f"**{name}:** {points}\n"
        
    await context.bot.edit_message_text(
        chat_id=update.callback_query.message.chat_id,
        message_id=update.callback_query.message.message_id,
        text=table_text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")]]),
        parse_mode="Markdown"
    )
    return SELECT_ACTION

async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Displays the points transaction history."""
    global HISTORY
    
    history_text = "📜 **Transaction History (Last 10)** 📜\n\n"
    
    if not HISTORY:
        history_text += "No transactions recorded yet."
    else:
        # Show the last 10 transactions
        for entry in HISTORY[-10:]:
            history_text += f"{entry}\n"
            
    await context.bot.edit_message_text(
        chat_id=update.callback_query.message.chat_id,
        message_id=update.callback_query.message.message_id,
        text=history_text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")]]),
        parse_mode="Markdown"
    )
    return SELECT_ACTION

# --- Main Bot Function ---

def main():
    """Starts the bot."""
    
    if not BOT_TOKEN:
        logger.error("FATAL: BOT_TOKEN is not set. Please set the TELEGRAM_BOT_TOKEN environment variable.")
        return

    # 1. Create the Application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # 2. Define the Conversation Handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            # State 0: Main menu and initial action selection
            SELECT_ACTION: [
                CallbackQueryHandler(handle_callback_query, pattern=r'^ACTION_'),
                CallbackQueryHandler(show_main_menu, pattern='^back_to_menu$')
            ],
            # State 1: Selecting the source (only for transfer)
            SELECT_SOURCE: [
                CallbackQueryHandler(handle_callback_query, pattern=r'^SOURCE_'),
                CallbackQueryHandler(show_main_menu, pattern='^cancel$')
            ],
            # State 2: Selecting the target (add, subtract, transfer)
            SELECT_TARGET: [
                CallbackQueryHandler(handle_callback_query, pattern=r'^TARGET_'),
                CallbackQueryHandler(show_main_menu, pattern='^cancel$')
            ],
            # State 3: Receiving the reason as a message
            GET_REASON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_reason)
            ],
            # State 4: Receiving the amount as a message
            GET_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_amount)
            ],
        },
        # Fallback to main menu on cancellation or timeout
        fallbacks=[CommandHandler("start", start), CallbackQueryHandler(show_main_menu, pattern='^cancel$')],
        allow_reentry=True
    )
    
    # 3. Add Handlers to the Application
    application.add_handler(conv_handler)
    
    # 4. Start the Bot
    logger.info("Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()