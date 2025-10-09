import logging
import json
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Get token from environment
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN not set!")

# Conversation states
AMOUNT, REASON, CONFIRM = range(3)

# Family members
MEMBERS = {
    "15260416": "Papa",
    "441113371": "Mama",
    "1059153162": "Danya",
    "5678069063": "Vlad",
    "5863747570": "Tima",
}

# Data storage
DATA_FILE = "points_data.json"

def load_data():
    """Load points data from JSON file"""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                data = json.load(f)
                # Ensure all members exist
                for uid in MEMBERS.keys():
                    data['points'].setdefault(uid, 0)
                return data
        except Exception as e:
            logger.error(f"Error loading data: {e}")
    
    # Default data
    return {
        'points': {uid: 0 for uid in MEMBERS.keys()},
        'history': [],
        'car_points': 0
    }

def save_data(data):
    """Save points data to JSON file"""
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving data: {e}")

def add_history(data, user_id, action, amount, target, reason):
    """Add entry to history"""
    entry = {
        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'performer': MEMBERS.get(str(user_id), f"User {user_id}"),
        'action': action,
        'amount': amount,
        'target': target,
        'reason': reason
    }
    data['history'].append(entry)
    save_data(data)

# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    keyboard = [
        [InlineKeyboardButton("➕ Add Points", callback_data="action_add")],
        [InlineKeyboardButton("➖ Subtract Points", callback_data="action_subtract")],
        [InlineKeyboardButton("↔️ Transfer Points", callback_data="action_transfer")],
        [InlineKeyboardButton("📊 Leaderboard", callback_data="leaderboard")],
        [InlineKeyboardButton("📜 History", callback_data="history")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "👋 Welcome to Family Points Bot!\nChoose an action:"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)
    
    return ConversationHandler.END

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    
    data_str = query.data
    
    # Main menu actions
    if data_str.startswith("action_"):
        action = data_str.split("_")[1]
        context.user_data['action'] = action
        
        # Create member keyboard
        keyboard = []
        for uid, name in MEMBERS.items():
            keyboard.append([InlineKeyboardButton(name, callback_data=f"member_{uid}")])
        
        if action == "add":
            text = "Select member to ADD points to:"
        elif action == "subtract":
            text = "Select member to SUBTRACT points from:"
        else:  # transfer
            text = "Select member to transfer FROM:"
        
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return AMOUNT
    
    # Member selection
    elif data_str.startswith("member_"):
        uid = data_str.split("_")[1]
        action = context.user_data.get('action')
        
        if action == "transfer" and 'from_member' not in context.user_data:
            # First selection for transfer (FROM)
            context.user_data['from_member'] = uid
            context.user_data['from_name'] = MEMBERS[uid]
            
            keyboard = []
            for member_uid, name in MEMBERS.items():
                if member_uid != uid:  # Can't transfer to self
                    keyboard.append([InlineKeyboardButton(name, callback_data=f"member_{member_uid}")])
            keyboard.append([InlineKeyboardButton("🚗 Car", callback_data="member_car")])
            keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
            
            await query.edit_message_text(
                f"Select member to transfer TO from {MEMBERS[uid]}:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return AMOUNT
        else:
            # Store target member
            context.user_data['target'] = uid
            context.user_data['target_name'] = MEMBERS[uid]
            await query.edit_message_text("Enter amount of points:")
            return AMOUNT
    
    # Car selection (only for transfer TO)
    elif data_str == "member_car":
        context.user_data['target'] = "car"
        context.user_data['target_name'] = "Car"
        await query.edit_message_text("Enter amount of points:")
        return AMOUNT
    
    # Leaderboard
    elif data_str == "leaderboard":
        data = load_data()
        sorted_members = sorted(
            [(uid, name, data['points'][uid]) for uid, name in MEMBERS.items()],
            key=lambda x: x[2],
            reverse=True
        )
        
        text = "🏆 *Family Leaderboard* 🏆\n\n"
        for i, (uid, name, points) in enumerate(sorted_members, 1):
            emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "•"
            text += f"{emoji} {name}: {points} points\n"
        text += f"\n🚗 *Car Goal*: {data['car_points']} points"
        
        keyboard = [[InlineKeyboardButton("« Back to Menu", callback_data="back")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return ConversationHandler.END
    
    # History
    elif data_str == "history":
        data = load_data()
        if not data['history']:
            text = "📜 No activity history yet."
        else:
            text = "📜 *Recent Activity*\n\n"
            for entry in reversed(data['history'][-10:]):
                text += f"• {entry['timestamp']}\n"
                text += f"  {entry['performer']} {entry['action']} {entry['amount']}pts\n"
                text += f"  {entry['target']}: _{entry['reason']}_\n\n"
        
        keyboard = [[InlineKeyboardButton("« Back to Menu", callback_data="back")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return ConversationHandler.END
    
    # Back to menu
    elif data_str == "back":
        return await start(update, context)
    
    # Cancel
    elif data_str == "cancel":
        await query.edit_message_text("❌ Cancelled")
        context.user_data.clear()
        await start(update, context)
        return ConversationHandler.END
    
    # Confirm action
    elif data_str == "confirm":
        return await execute_action(update, context)

async def amount_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle amount input"""
    try:
        amount = int(update.message.text)
        if amount <= 0:
            await update.message.reply_text("Please enter a positive number:")
            return AMOUNT
        
        context.user_data['amount'] = amount
        await update.message.reply_text("Enter reason for this action:")
        return REASON
        
    except ValueError:
        await update.message.reply_text("Please enter a valid number:")
        return AMOUNT

async def reason_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle reason input"""
    reason = update.message.text.strip()
    if not reason:
        await update.message.reply_text("Please enter a reason:")
        return REASON
    
    context.user_data['reason'] = reason
    
    # Show confirmation
    action = context.user_data['action']
    amount = context.user_data['amount']
    
    if action == "transfer":
        from_name = context.user_data['from_name']
        target_name = context.user_data['target_name']
        text = f"Confirm: Transfer {amount} points from {from_name} to {target_name}?\nReason: {reason}"
    else:
        target_name = context.user_data['target_name']
        action_word = "Add" if action == "add" else "Subtract"
        text = f"Confirm: {action_word} {amount} points {'to' if action == 'add' else 'from'} {target_name}?\nReason: {reason}"
    
    keyboard = [
        [InlineKeyboardButton("✅ Confirm", callback_data="confirm")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return CONFIRM

async def execute_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Execute the confirmed action"""
    query = update.callback_query
    await query.answer()
    
    data = load_data()
    action = context.user_data['action']
    amount = context.user_data['amount']
    reason = context.user_data['reason']
    user_id = update.effective_user.id
    
    try:
        if action == "add":
            target = context.user_data['target']
            target_name = context.user_data['target_name']
            data['points'][target] += amount
            add_history(data, user_id, "add", amount, target_name, reason)
            await query.edit_message_text(f"✅ Added {amount} points to {target_name}!\nReason: {reason}")
        
        elif action == "subtract":
            target = context.user_data['target']
            target_name = context.user_data['target_name']
            
            if data['points'][target] < amount:
                await query.edit_message_text(f"❌ {target_name} only has {data['points'][target]} points")
                context.user_data.clear()
                await start(update, context)
                return ConversationHandler.END
            
            data['points'][target] -= amount
            add_history(data, user_id, "subtract", amount, target_name, reason)
            await query.edit_message_text(f"✅ Subtracted {amount} points from {target_name}!\nReason: {reason}")
        
        elif action == "transfer":
            from_member = context.user_data['from_member']
            from_name = context.user_data['from_name']
            target = context.user_data['target']
            target_name = context.user_data['target_name']
            
            if data['points'][from_member] < amount:
                await query.edit_message_text(f"❌ {from_name} only has {data['points'][from_member]} points")
                context.user_data.clear()
                await start(update, context)
                return ConversationHandler.END
            
            data['points'][from_member] -= amount
            
            if target == "car":
                data['car_points'] += amount
            else:
                data['points'][target] += amount
            
            add_history(data, user_id, "transfer", amount, f"{from_name} → {target_name}", reason)
            await query.edit_message_text(f"✅ Transferred {amount} points from {from_name} to {target_name}!\nReason: {reason}")
        
        save_data(data)
        
    except Exception as e:
        logger.error(f"Error executing action: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}")
    
    context.user_data.clear()
    await start(update, context)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel conversation"""
    context.user_data.clear()
    await update.message.reply_text("❌ Cancelled")
    await start(update, context)
    return ConversationHandler.END

def main():
    """Start the bot"""
    # Initialize data file if needed
    if not os.path.exists(DATA_FILE):
        save_data(load_data())
    
    # Create application
    application = Application.builder().token(TOKEN).build()
    
    # Setup conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            AMOUNT: [
                CallbackQueryHandler(button_handler),
                MessageHandler(filters.TEXT & ~filters.COMMAND, amount_input),
            ],
            REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, reason_input)],
            CONFIRM: [CallbackQueryHandler(button_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(CommandHandler("start", start))
    
    # Check if running on Railway (webhook mode)
    webhook_url = os.getenv("WEBHOOK_URL")
    port = int(os.getenv("PORT", "8080"))
    
    if webhook_url:
        logger.info(f"Starting webhook on port {port}")
        application.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=TOKEN,
            webhook_url=f"{webhook_url}/{TOKEN}"
        )
    else:
        logger.info("Starting polling mode")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()