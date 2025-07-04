import logging
import json
from datetime import datetime
import os # <-- Add this import

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- Configuration ---
# Get token from environment variable
# IMPORTANT: When deploying on Railway, you MUST set an environment variable
# named 'TELEGRAM_BOT_TOKEN' with your actual bot token.
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set. Please set it for deployment.")

# Map Telegram User IDs to family member names
# This is crucial for the bot to identify who is who, regardless of username changes.
# Make sure these IDs are correct!
FAMILY_MEMBERS = {
    15260416: "Papa",
    441113371: "Mama",
    1059153162: "Danya",
    5678069063: "Vlad",
    5863747570: "Tima",
}

# Invert the dictionary for easy lookup of ID by name
NAME_TO_ID = {name.lower(): uid for uid, name in FAMILY_MEMBERS.items()}

DATA_FILE = 'points_data.json' # File to store points and history

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
    return {}, [] # Return empty if file doesn't exist

def save_data(points, history):
    """Saves points and history to the JSON file."""
    with open(DATA_FILE, 'w') as f:
        json.dump({'points': points, 'history': history}, f, indent=4)

# Initialize points and history when the bot starts
current_points, activity_history = load_data()

# Ensure all family members are initialized in points data
for uid, name in FAMILY_MEMBERS.items():
    if str(uid) not in current_points:
        current_points[str(uid)] = 0
save_data(current_points, activity_history) # Save initial state if new members added

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
    # Keep history to a reasonable size (e.g., last 100 entries)
    if len(activity_history) > 100:
        activity_history.pop(0) # Remove oldest entry
    save_data(current_points, activity_history)

# --- Command Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message and explanation of commands."""
    await update.message.reply_text(
        "Hello! I'm your Family Points Tracker bot. "
        "I help manage points for Mama, Papa, Danya, Vlad, and Tima.\n\n"
        "Here are the commands you can use:\n"
        "/add <amount> <user_name> <reason> - Add points\n"
        "/subtract <amount> <user_name> <reason> - Subtract points\n"
        "/transfer <amount> <from_user_name> <to_user_name> <reason> - Transfer points\n"
        "/leaderboard - Show current points\n"
        "/history - Show recent activity\n\n"
        "Remember: All point actions require a reason!"
    )

async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Adds points to a specific user."""
    args = context.args
    performer_id = update.message.from_user.id

    if len(args) < 3:
        await update.message.reply_text(
            "Usage: `/add <amount> <user_name> <reason>`\n"
            "Example: `/add 10 Danya for helping clean`"
        )
        return

    try:
        amount = int(args[0])
        if amount <= 0:
            await update.message.reply_text("Amount must be a positive number.")
            return
    except ValueError:
        await update.message.reply_text("Amount must be a number.")
        return

    target_name = args[1].lower()
    target_id = get_user_id_by_name(target_name)

    if target_id is None:
        await update.message.reply_text(
            f"User '{args[1]}' not recognized. Please use one of: " +
            ", ".join([name for uid, name in FAMILY_MEMBERS.items()])
        )
        return

    reason = " ".join(args[2:])
    if not reason:
        await update.message.reply_text("Please provide a reason for adding points.")
        return

    # Ensure target user exists in points tracking, initialize if new (should be covered by startup)
    if str(target_id) not in current_points:
        current_points[str(target_id)] = 0

    current_points[str(target_id)] += amount
    record_activity(performer_id, "add", amount, target_id=target_id, reason=reason)
    save_data(current_points, activity_history)

    await update.message.reply_text(
        f"{get_user_name(performer_id)} added {amount} points to {get_user_name(target_id)} "
        f"(Reason: {reason}).\n"
        f"New total for {get_user_name(target_id)}: {current_points[str(target_id)]} points."
    )

async def subtract_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Subtracts points from a specific user."""
    args = context.args
    performer_id = update.message.from_user.id

    if len(args) < 3:
        await update.message.reply_text(
            "Usage: `/subtract <amount> <user_name> <reason>`\n"
            "Example: `/subtract 5 Vlad for not doing chores`"
        )
        return

    try:
        amount = int(args[0])
        if amount <= 0:
            await update.message.reply_text("Amount must be a positive number.")
            return
    except ValueError:
        await update.message.reply_text("Amount must be a number.")
        return

    target_name = args[1].lower()
    target_id = get_user_id_by_name(target_name)

    if target_id is None:
        await update.message.reply_text(
            f"User '{args[1]}' not recognized. Please use one of: " +
            ", ".join([name for uid, name in FAMILY_MEMBERS.items()])
        )
        return

    reason = " ".join(args[2:])
    if not reason:
        await update.message.reply_text("Please provide a reason for subtracting points.")
        return

    if str(target_id) not in current_points or current_points[str(target_id)] < amount:
        await update.message.reply_text(
            f"{get_user_name(target_id)} doesn't have enough points. "
            f"Current: {current_points.get(str(target_id), 0)} points."
        )
        return

    current_points[str(target_id)] -= amount
    record_activity(performer_id, "subtract", amount, target_id=target_id, reason=reason)
    save_data(current_points, activity_history)

    await update.message.reply_text(
        f"{get_user_name(performer_id)} subtracted {amount} points from {get_user_name(target_id)} "
        f"(Reason: {reason}).\n"
        f"New total for {get_user_name(target_id)}: {current_points[str(target_id)]} points."
    )

async def transfer_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Transfers points between two users."""
    args = context.args
    performer_id = update.message.from_user.id

    if len(args) < 4:
        await update.message.reply_text(
            "Usage: `/transfer <amount> <from_user_name> <to_user_name> <reason>`\n"
            "Example: `/transfer 20 Papa Mama for helping with dinner`"
        )
        return

    try:
        amount = int(args[0])
        if amount <= 0:
            await update.message.reply_text("Amount must be a positive number.")
            return
    except ValueError:
        await update.message.reply_text("Amount must be a number.")
        return

    from_name = args[1].lower()
    from_id = get_user_id_by_name(from_name)
    to_name = args[2].lower()
    to_id = get_user_id_by_name(to_name)

    if from_id is None or to_id is None:
        await update.message.reply_text(
            f"One or both users not recognized. Please use names from: " +
            ", ".join([name for uid, name in FAMILY_MEMBERS.items()])
        )
        return

    if from_id == to_id:
        await update.message.reply_text("Cannot transfer points to yourself!")
        return

    reason = " ".join(args[3:])
    if not reason:
        await update.message.reply_text("Please provide a reason for the transfer.")
        return

    # Ensure users exist in points tracking
    if str(from_id) not in current_points:
        current_points[str(from_id)] = 0
    if str(to_id) not in current_points:
        current_points[str(to_id)] = 0

    if current_points[str(from_id)] < amount:
        await update.message.reply_text(
            f"{get_user_name(from_id)} doesn't have enough points to transfer. "
            f"Current: {current_points[str(from_id)]} points."
        )
        return

    current_points[str(from_id)] -= amount
    current_points[str(to_id)] += amount
    record_activity(performer_id, "transfer", amount, source_id=from_id, target_id=to_id, reason=reason)
    save_data(current_points, activity_history)

    await update.message.reply_text(
        f"{get_user_name(performer_id)} transferred {amount} points from {get_user_name(from_id)} to {get_user_name(to_id)} "
        f"(Reason: {reason}).\n"
        f"New totals:\n"
        f"{get_user_name(from_id)}: {current_points[str(from_id)]} points\n"
        f"{get_user_name(to_id)}: {current_points[str(to_id)]} points."
    )

async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays the current point totals for all members."""
    if not current_points:
        await update.message.reply_text("No points tracked yet. Start adding some!")
        return

    # Sort members by points in descending order
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


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays recent activity history."""
    if not activity_history:
        await update.message.reply_text("No activity recorded yet.")
        return

    history_msg = "📜 **Recent Point Activity** 📜\n\n"
    # Show last 10 activities for brevity
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

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles unknown commands."""
    await update.message.reply_text("Sorry, I don't understand that command.")


def main() -> None:
    """Starts the bot."""
    application = Application.builder().token(TOKEN).build()

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", start)) # Help alias for start
    application.add_handler(CommandHandler("add", add_command))
    application.add_handler(CommandHandler("subtract", subtract_command))
    application.add_handler(CommandHandler("transfer", transfer_command))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(CommandHandler("history", history_command))

    # Add handler for unknown commands
    application.add_handler(MessageHandler(filters.COMMAND, unknown))

    logger.info("Bot is polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()