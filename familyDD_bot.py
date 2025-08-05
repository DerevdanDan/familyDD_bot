import logging
import json
import os
from datetime import datetime
from typing import Dict, List, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
    ConversationHandler,
)

# Configuration
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set.")

ADMIN_ID = int(os.getenv("TELEGRAM_ADMIN_ID", "123456789"))

# Conversation states
MAIN_MENU, SELECT_MEMBER, ENTER_AMOUNT, ENTER_REASON, CONFIRM_ACTION = range(5)

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

class FamilyPointsBot:
    def __init__(self):
        self.data_file = "points_data.json"
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
        """Load data from JSON file or initialize defaults"""
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.points = data.get('points', {})
                    self.history = data.get('history', [])
                    self.car_points = data.get('car_points', 0)
            else:
                # Initialize with zero points for all members
                self.points = {str(uid): 0 for uid in self.family_members}
                self.history = []
                self.car_points = 0
                self.save_data()
                
            # Ensure all family members have point entries
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
            
    def is_family_member(self, user_id: int) -> bool:
        """Check if user is a family member"""
        return user_id in self.family_members or user_id == ADMIN_ID
        
    def record_action(self, user_id: int, action: str, amount: int, target: str, reason: str):
        """Record an action in history"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
        """Handle /start command"""
        if not self.is_family_member(update.effective_user.id):
            await update.message.reply_text("❌ You are not authorized to use this bot.")
            return ConversationHandler.END
            
        await update.message.reply_text(
            "👋 Welcome to Family Points Bot!\nChoose an action:",
            reply_markup=self.get_main_menu_keyboard()
        )
        context.user_data.clear()
        return MAIN_MENU
        
    async def handle_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle main menu selections"""
        if not self.is_family_member(update.effective_user.id):
            return ConversationHandler.END
            
        text = update.message.text
        
        if text == "➕ Add Points":
            context.user_data['action'] = 'add'
            await update.message.reply_text(
                "Select member to add points to:",
                reply_markup=self.get_member_keyboard(include_car=False)  # No car for add
            )
            return SELECT_MEMBER
            
        elif text == "➖ Subtract Points":
            context.user_data['action'] = 'subtract'
            await update.message.reply_text(
                "Select member to subtract points from:",
                reply_markup=self.get_member_keyboard(include_car=False)  # No car for subtract
            )
            return SELECT_MEMBER
            
        elif text == "↔️ Transfer Points":
            context.user_data['action'] = 'transfer'
            await update.message.reply_text(
                "Select member to transfer points FROM:",
                reply_markup=self.get_member_keyboard(include_car=False)  # No car as source
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
        await query.answer()
        
        if query.data == "cancel":
            await query.edit_message_text("❌ Cancelled.")
            return await self.start(update, context)
            
        action = context.user_data.get('action')
        
        if action == 'transfer':
            # Check if this is the first selection (source) or second selection (destination)
            if 'from_member' not in context.user_data:
                # First selection - source member
                if query.data == "member_car":
                    await query.edit_message_text("❌ Cannot transfer FROM car.")
                    return await self.start(update, context)
                    
                member_id = query.data.split('_')[1]
                member_name = self.family_members.get(int(member_id), "Unknown")
                context.user_data['from_member'] = member_id
                context.user_data['from_name'] = member_name
                
                await query.edit_message_text(
                    f"Select member to transfer points TO from {member_name}:",
                    reply_markup=self.get_member_keyboard(include_car=True)  # Include car as destination
                )
                return SELECT_MEMBER
            else:
                # Second selection - destination member
                if query.data == "member_car":
                    target_name = "Car"
                    target_id = "car"
                else:
                    member_id = query.data.split('_')[1]
                    target_name = self.family_members.get(int(member_id), "Unknown")
                    target_id = member_id
                
                # Check if trying to transfer to self
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
                    reply_markup=ReplyKeyboardRemove()
                )
                return ENTER_AMOUNT
            
        else:
            # For add/subtract, store the target member
            member_id = query.data.split('_')[1]
            member_name = self.family_members.get(int(member_id), "Unknown")
                
            context.user_data['target_member'] = member_id
            context.user_data['target_name'] = member_name
            
            await query.edit_message_text(
                f"Enter amount of points to {action} for {member_name}:",
                reply_markup=ReplyKeyboardRemove()
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
                # For transfer, we need to check if source has enough points
                from_member = context.user_data.get('from_member')
                current_points = self.points.get(from_member, 0)
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
                f"Confirm {action_word} {amount} points to {target_name}?\nReason: {reason}",
                reply_markup=self.get_confirmation_keyboard()
            )
            
        return CONFIRM_ACTION
        
    async def confirm_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle action confirmation"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "cancel":
            await query.edit_message_text("❌ Cancelled.")
            return await self.start(update, context)
            
        action = context.user_data.get('action')
        amount = context.user_data.get('amount')
        reason = context.user_data.get('reason')
        
        try:
            if action == 'add':
                target = context.user_data.get('target_member')
                self.points[target] = self.points.get(target, 0) + amount
                target_name = self.family_members.get(int(target), "Unknown")
                    
                self.record_action(update.effective_user.id, "add", amount, target_name, reason)
                
                await query.edit_message_text(
                    f"✅ Added {amount} points to {target_name}!\nReason: {reason}",
                    reply_markup=self.get_main_menu_keyboard()
                )
                
            elif action == 'subtract':
                target = context.user_data.get('target_member')
                current_points = self.points.get(target, 0)
                if current_points < amount:
                    await query.edit_message_text(
                        f"❌ {context.user_data['target_name']} only has {current_points} points.",
                        reply_markup=self.get_main_menu_keyboard()
                    )
                    context.user_data.clear()
                    return MAIN_MENU
                    
                self.points[target] = current_points - amount
                target_name = self.family_members.get(int(target), "Unknown")
                
                self.record_action(update.effective_user.id, "subtract", amount, target_name, reason)
                
                await query.edit_message_text(
                    f"✅ Subtracted {amount} points from {target_name}!\nReason: {reason}",
                    reply_markup=self.get_main_menu_keyboard()
                )
                
            elif action == 'transfer':
                from_member = context.user_data.get('from_member')
                target = context.user_data.get('target_member')
                
                # Validate transfer is not to self
                if from_member == target:
                    await query.edit_message_text(
                        "❌ Cannot transfer to yourself.",
                        reply_markup=self.get_main_menu_keyboard()
                    )
                    context.user_data.clear()
                    return MAIN_MENU
                
                # Subtract from source
                current_points = self.points.get(from_member, 0)
                if current_points < amount:
                    await query.edit_message_text(
                        f"❌ {context.user_data['from_name']} only has {current_points} points.",
                        reply_markup=self.get_main_menu_keyboard()
                    )
                    context.user_data.clear()
                    return MAIN_MENU
                    
                self.points[from_member] = current_points - amount
                from_name = self.family_members.get(int(from_member), "Unknown")
                
                # Add to target
                if target == "car":
                    self.car_points += amount
                    target_name = "Car"
                else:
                    self.points[target] = self.points.get(target, 0) + amount
                    target_name = self.family_members.get(int(target), "Unknown")
                
                self.record_action(update.effective_user.id, "transfer", amount, f"{from_name} → {target_name}", reason)
                
                await query.edit_message_text(
                    f"✅ Transferred {amount} points from {from_name} to {target_name}!\nReason: {reason}",
                    reply_markup=self.get_main_menu_keyboard()
                )
                
        except Exception as e:
            logger.error(f"Error in confirm_action: {e}")
            await query.edit_message_text(
                f"❌ Error occurred: {str(e)}",
                reply_markup=self.get_main_menu_keyboard()
            )
            
        context.user_data.clear()
        return MAIN_MENU
        
    async def show_leaderboard(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show leaderboard"""
        # Sort members by points
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
            parse_mode='Markdown',
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
            
        # Show last 10 entries
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
            parse_mode='Markdown',
            reply_markup=self.get_main_menu_keyboard()
        )
        
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel current action"""
        await update.message.reply_text(
            "❌ Cancelled. Use /start to begin again.",
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
                    MessageHandler(filters.Regex("^(➕ Add Points|➖ Subtract Points|↔️ Transfer Points|📊 Leaderboard|📜 History)$"), self.handle_main_menu)
                ],
                SELECT_MEMBER: [
                    CallbackQueryHandler(self.select_member, pattern="^member_")
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
        """Run the bot"""
        application = Application.builder().token(TOKEN).build()
        self.setup_handlers(application)
        
        logger.info("Starting Family Points Bot...")
        application.run_polling()

def main():
    """Main function"""
    bot = FamilyPointsBot()
    bot.run()

if __name__ == "__main__":
    main()