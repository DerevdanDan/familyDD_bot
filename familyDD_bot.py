import logging
import json
import os
import sys 
from datetime import datetime
from typing import Dict, List, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
    ConversationHandler,
)
from telegram.constants import ParseMode # Ensure this is imported for Markdown

# --- Configuration for Webhooks on Railway ---
# Assuming these environment variables are already set up on Railway
PORT = int(os.environ.get('PORT', '8080'))
WEBHOOK_URL = os.environ.get('WEBHOOK_URL') 
HOST = '0.0.0.0'

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    logging.error("TELEGRAM_BOT_TOKEN environment variable not set. Exiting.")
    sys.exit(1)

# Conversation states
MAIN_MENU, SELECT_MEMBER, ENTER_AMOUNT, ENTER_REASON, CONFIRM_ACTION = range(5)

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ----------------------------------------------
# ➡️ MINIMAL CHANGES APPLIED HERE:
# 1. Removed is_family_member function.
# 2. Removed authorization check from start().
# 3. Removed authorization check from handle_main_menu().
# ----------------------------------------------

class FamilyPointsBot:
    def __init__(self):
        self.data_file = "points_data.json"
        # The UIDs remain only to map IDs to names for points tracking and display.
        self.family_members = {
            15260416: "Papa",
            441113371: "Mama", 
            1059153162: "Danya",
            5678069063: "Vlad",
            5863747570: "Tima",
        }
        self.points = {}
        self.history = []
        self.car_points = 0
        self.load_data()
        
    def load_data(self):
        """Load data from JSON file or initialize defaults."""
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.points = data.get('points', {})
                    self.history = data.get('history', [])
                    self.car_points = data.get('car_points', 0)
            else:
                self.points = {str(uid): 0 for uid in self.family_members}
                self.history = []
                self.car_points = 0
                self.save_data()
                
            for uid in self.family_members:
                if str(uid) not in self.points:
                    self.points[str(uid)] = 0
                    
        except Exception as e:
            logger.error(f"Error loading data: {e}")
            self.points = {str(uid): 0 for uid in self.family_members}
            self.history = []
            self.car_points = 0
            
    def save_data(self):
        """Save data to JSON file"""
        try:
            data = {
                'points': self.points,
                'history': self.history,
                'car_points': self.car_points
            }
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving data: {e}")
            
    # ❌ REMOVED: The is_family_member function is no longer needed for access control.
        
    def record_action(self, user_id: int, action: str, amount: int, target: str, reason: str):
        """Record an action in history"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Use the name of the user who performed the action, or their ID if not in family_members
        performer = self.family_members.get(user_id, f"User {user_id}")
        
        entry = {
            'timestamp': timestamp,
            'performer': performer,
            'action': action,
            'amount': amount,
            'target': target,
            'reason': reason
        }
        self.history.append(entry)
        self.save_data()
        
    def get_main_menu_keyboard(self):
        """Get main menu keyboard"""
        keyboard = [
            ["➕ Add Points", "➖ Subtract Points"],
            ["↔️ Transfer Points", "📊 Leaderboard"],
            ["📜 History"]
        ]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
    def get_member_keyboard(self, include_car=False):
        """Get member selection keyboard"""
        keyboard = []
        for uid, name in self.family_members.items():
            keyboard.append([InlineKeyboardButton(name, callback_data=f"member_{uid}")])
        if include_car:
            keyboard.append([InlineKeyboardButton("🚗 Car", callback_data="member_car")])
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
        return InlineKeyboardMarkup(keyboard)
        
    def get_confirmation_keyboard(self):
        """Get confirmation keyboard"""
        keyboard = [
            [InlineKeyboardButton("✅ Confirm", callback_data="confirm")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
        ]
        return InlineKeyboardMarkup(keyboard)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle /start command - Now open to all users."""
        
        # ❌ REMOVED: Authorization check previously here.
        
        await update.message.reply_text(
            "👋 Welcome to Family Points Bot!\nChoose an action:",
            reply_markup=self.get_main_menu_keyboard()
        )
        context.user_data.clear()
        return MAIN_MENU
        
    async def handle_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle main menu selections - Open to all users."""
        
        # ❌ REMOVED: Authorization check previously here.
        
        text = update.message.text
        
        if text == "➕ Add Points":
            context.user_data['action'] = 'add'
            await update.message.reply_text(
                "Select member to add points to:",
                reply_markup=self.get_member_keyboard(include_car=False)
            )
            return SELECT_MEMBER
            
        elif text == "➖ Subtract Points":
            context.user_data['action'] = 'subtract'
            await update.message.reply_text(
                "Select member to subtract points from:",
                reply_markup=self.get_member_keyboard(include_car=False)
            )
            return SELECT_MEMBER
            
        elif text == "↔️ Transfer Points":
            context.user_data['action'] = 'transfer'
            await update.message.reply_text(
                "Select member to transfer points FROM:",
                reply_markup=self.get_member_keyboard(include_car=False)
            )
            return SELECT_MEMBER
            
        elif text == "📊 Leaderboard":
            await self.show_leaderboard(update, context)
            return MAIN_MENU
            
        elif text == "📜 History":
            await self.show_history(update, context)
            return MAIN_MENU
            
        else:
            await update.message.reply_text(
                "Please use the menu buttons:",
                reply_markup=self.get_main_menu_keyboard()
            )
            return MAIN_MENU
            
    async def select_member(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle member selection"""
        query = update.callback_query
        if query is None:
            return ConversationHandler.END
            
        await query.answer()
        
        if query.data == "cancel":
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Cancelled.",
                reply_markup=self.get_main_menu_keyboard()
            )
            return MAIN_MENU
            
        action = context.user_data.get('action')
        
        if action == 'transfer':
            if 'from_member' not in context.user_data:
                if query.data == "member_car":
                    await query.edit_message_text("❌ Cannot transfer FROM car.")
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text="Choose another action:",
                        reply_markup=self.get_main_menu_keyboard()
                    )
                    return MAIN_MENU
                    
                member_id = query.data.split('_')[1]
                member_name = self.family_members.get(int(member_id), "Unknown")
                context.user_data['from_member'] = member_id
                context.user_data['from_name'] = member_name
                
                await query.edit_message_text(
                    f"Select member to transfer points TO from {member_name}:",
                    reply_markup=self.get_member_keyboard(include_car=True)
                )
                return SELECT_MEMBER
            else:
                if query.data == "member_car":
                    target_name = "Car"
                    target_id = "car"
                else:
                    member_id = query.data.split('_')[1]
                    target_name = self.family_members.get(int(member_id), "Unknown")
                    target_id = member_id
                
                if context.user_data['from_member'] == target_id:
                    await query.edit_message_text(
                        "❌ Cannot transfer to yourself. Select another member:",
                        reply_markup=self.get_member_keyboard(include_car=True)
                    )
                    return SELECT_MEMBER
                
                context.user_data['target_member'] = target_id
                context.user_data['target_name'] = target_name
                
                await query.edit_message_text(
                    f"Enter amount of points to transfer from {context.user_data['from_name']} to {target_name}:",
                )
                return ENTER_AMOUNT
            
        else:
            member_id = query.data.split('_')[1]
            member_name = self.family_members.get(int(member_id), "Unknown")
                
            context.user_data['target_member'] = member_id
            context.user_data['target_name'] = member_name
            
            await query.edit_message_text(
                f"Enter amount of points to {action} for {member_name}:",
            )
            return ENTER_AMOUNT
            
    async def enter_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle amount input"""
        try:
            amount = int(update.message.text)
            if amount <= 0:
                await update.message.reply_text("Please enter a positive number:")
                return ENTER_AMOUNT
                
            context.user_data['amount'] = amount
            action = context.user_data.get('action')
            
            if action == 'transfer':
                from_member = context.user_data.get('from_member')
                current_points = self.points.get(str(from_member), 0)
                
                if current_points < amount:
                    await update.message.reply_text(
                        f"❌ {context.user_data['from_name']} only has {current_points} points.",
                        reply_markup=self.get_main_menu_keyboard()
                    )
                    context.user_data.clear()
                    return MAIN_MENU
                        
                await update.message.reply_text(
                    f"Enter reason for transferring {amount} points from {context.user_data['from_name']} to {context.user_data['target_name']}:"
                )
            else:
                await update.message.reply_text(
                    f"Enter reason for {action}ing {amount} points:"
                )
                
            return ENTER_REASON
            
        except ValueError:
            await update.message.reply_text("Please enter a valid number:")
            return ENTER_AMOUNT
            
    async def enter_reason(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle reason input"""
        reason = update.message.text.strip()
        if not reason:
            await update.message.reply_text("Please enter a reason:")
            return ENTER_REASON
            
        context.user_data['reason'] = reason
        action = context.user_data.get('action')
        amount = context.user_data.get('amount')
        
        if action == 'transfer':
            from_name = context.user_data.get('from_name')
            target_name = context.user_data.get('target_name')
            await update.message.reply_text(
                f"Confirm transferring {amount} points from {from_name} to {target_name}?\nReason: {reason}",
                reply_markup=self.get_confirmation_keyboard()
            )
        else:
            target_name = context.user_data.get('target_name')
            action_word = "adding" if action == 'add' else "subtracting"
            await update.message.reply_text(
                f"Confirm {action_word} {amount} points {'to' if action == 'add' else 'from'} {target_name}?\nReason: {reason}",
                reply_markup=self.get_confirmation_keyboard()
            )
            
        return CONFIRM_ACTION
        
    async def confirm_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle action confirmation"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "cancel":
            await query.edit_message_text("❌ Cancelled.")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Choose another action:",
                reply_markup=self.get_main_menu_keyboard()
            )
            return MAIN_MENU
            
        action = context.user_data.get('action')
        amount = context.user_data.get('amount')
        reason = context.user_data.get('reason')
        
        try:
            target = context.user_data.get('target_member')
            target_name = context.user_data.get('target_name')
            user_id = update.effective_user.id
            
            if action == 'add':
                self.points[target] = self.points.get(target, 0) + amount
                self.record_action(user_id, "add", amount, target_name, reason)
                await query.edit_message_text(
                    f"✅ Added {amount} points to {target_name}!\nReason: {reason}"
                )
                
            elif action == 'subtract':
                current_points = self.points.get(target, 0)
                if current_points < amount:
                    await query.edit_message_text(f"❌ {target_name} only has {current_points} points.")
                    context.user_data.clear()
                    return MAIN_MENU
                    
                self.points[target] = current_points - amount
                self.record_action(user_id, "subtract", amount, target_name, reason)
                await query.edit_message_text(
                    f"✅ Subtracted {amount} points from {target_name}!\nReason: {reason}"
                )
                
            elif action == 'transfer':
                from_member = context.user_data.get('from_member')
                from_name = context.user_data.get('from_name')
                
                if from_member == target:
                    await query.edit_message_text("❌ Cannot transfer to yourself.")
                    context.user_data.clear()
                    return MAIN_MENU
                
                current_points = self.points.get(from_member, 0)
                if current_points < amount:
                    await query.edit_message_text(f"❌ {from_name} only has {current_points} points.")
                    context.user_data.clear()
                    return MAIN_MENU
                    
                self.points[from_member] = current_points - amount
                
                if target == "car":
                    self.car_points += amount
                else:
                    self.points[target] = self.points.get(target, 0) + amount
                
                self.record_action(user_id, "transfer", amount, f"{from_name} → {target_name}", reason)
                await query.edit_message_text(
                    f"✅ Transferred {amount} points from {from_name} to {target_name}!\nReason: {reason}"
                )
                
        except Exception as e:
            logger.error(f"Error in confirm_action: {e}")
            await query.edit_message_text(f"❌ Error occurred: {str(e)}")
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Choose another action:",
            reply_markup=self.get_main_menu_keyboard()
        )
        context.user_data.clear()
        return MAIN_MENU
        
    async def show_leaderboard(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show leaderboard"""
        sorted_members = sorted(
            [(uid, name, self.points.get(str(uid), 0)) for uid, name in self.family_members.items()],
            key=lambda x: x[2],
            reverse=True
        )
        
        leaderboard_text = "🏆 **Family Leaderboard** 🏆\n\n"
        
        for i, (uid, name, points) in enumerate(sorted_members, 1):
            emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "•"
            leaderboard_text += f"{emoji} {name}: {points} points\n"
            
        leaderboard_text += f"\n🚗 **Car (Family Goal)**: {self.car_points} points"
        
        await update.message.reply_text(
            leaderboard_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=self.get_main_menu_keyboard()
        )
        
    async def show_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show recent history"""
        if not self.history:
            await update.message.reply_text(
                "📜 No activity history yet.",
                reply_markup=self.get_main_menu_keyboard()
            )
            return
            
        recent_history = self.history[-10:]
        history_text = "📜 **Recent Activity** 📜\n\n"
        
        for entry in reversed(recent_history):
            timestamp = entry['timestamp']
            performer = entry['performer']
            action = entry['action']
            amount = entry['amount']
            target = entry['target']
            reason = entry['reason']
            
            if action == 'transfer':
                history_text += f"🔄 {timestamp}\n{performer} transferred {amount} points: {target}\nReason: {reason}\n\n"
            elif action == 'add':
                history_text += f"➕ {timestamp}\n{performer} added {amount} points to {target}\nReason: {reason}\n\n"
            elif action == 'subtract':
                history_text += f"➖ {timestamp}\n{performer} subtracted {amount} points from {target}\nReason: {reason}\n\n"
                
        await update.message.reply_text(
            history_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=self.get_main_menu_keyboard()
        )
        
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel current action"""
        await update.message.reply_text(
            "❌ Cancelled. Choose another action.",
            reply_markup=self.get_main_menu_keyboard()
        )
        context.user_data.clear()
        return MAIN_MENU
        
    def setup_handlers(self, application: Application):
        """Setup bot handlers"""
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", self.start)],
            states={
                MAIN_MENU: [
                    MessageHandler(filters.Regex("^(➕ Add Points|➖ Subtract Points|↔️ Transfer Points|📊 Leaderboard|📜 History)$"), self.handle_main_menu),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_main_menu)
                ],
                SELECT_MEMBER: [
                    CallbackQueryHandler(self.select_member, pattern="^member_|^cancel$")
                ],
                ENTER_AMOUNT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.enter_amount)
                ],
                ENTER_REASON: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.enter_reason)
                ],
                CONFIRM_ACTION: [
                    CallbackQueryHandler(self.confirm_action, pattern="^(confirm|cancel)$")
                ]
            },
            fallbacks=[CommandHandler("cancel", self.cancel)]
        )
        
        application.add_handler(conv_handler)
        
    def run(self):
        """Run the bot using Webhooks for Railway deployment."""
        if not WEBHOOK_URL:
             logger.error("WEBHOOK_URL environment variable is not set. Cannot run webhooks.")
             return

        application = Application.builder().token(TOKEN).build()
        self.setup_handlers(application)
        
        # This Webhook configuration is maintained for your existing Railway deployment
        application.run_webhook(
            listen=HOST,
            port=PORT,
            url_path=TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{TOKEN}"
        )
        
        logger.info(f"Starting Family Points Bot via Webhooks on {HOST}:{PORT}")

def main():
    """Main function"""
    bot = FamilyPointsBot()
    bot.run()

if __name__ == "__main__":
    main()