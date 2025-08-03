import logging
import json
import os
import shutil
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from uuid import uuid4
import asyncio

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
from telegram.error import BadRequest, NetworkError

# --- Configuration ---
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set.")

ADMIN_ID = int(os.getenv("TELEGRAM_ADMIN_ID", "123456789"))
if ADMIN_ID == 123456789:
    logging.warning("TELEGRAM_ADMIN_ID is placeholder. Admin features may not work.")

GROUP_CHAT_ID = os.getenv("TELEGRAM_GROUP_CHAT_ID")  # Optional for group notifications
DATA_FILE = "points_data.json"
BACKUP_DIR = "backups"
HISTORY_PURGE_INTERVAL_DAYS = 60  # 2 months
WEEKLY_SUMMARY_DAY = 6  # Sunday (0=Monday, 6=Sunday)

# --- Conversation States ---
MAIN_MENU, SELECT_MEMBER_ADD, ENTER_AMOUNT_ADD, ENTER_REASON_ADD, CONFIRM_ADD, \
SELECT_MEMBER_SUBTRACT, ENTER_AMOUNT_SUBTRACT, ENTER_REASON_SUBTRACT, CONFIRM_SUBTRACT, \
SELECT_FROM_TRANSFER, SELECT_TO_TRANSFER, ENTER_AMOUNT_TRANSFER, ENTER_REASON_TRANSFER, CONFIRM_TRANSFER, \
ADD_MEMBER_NAME, ADD_MEMBER_ID, CONFIRM_ADD_MEMBER = range(17)

# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# --- Data Classes ---
class FamilyGoal:
    def __init__(self, name: str, points: int = 0):
        self.name = name
        self.points = points

    def to_dict(self) -> Dict[str, any]:
        return {"name": self.name, "points": self.points}

    @classmethod
    def from_dict(cls, data: Dict[str, any]) -> "FamilyGoal":
        return cls(data["name"], data.get("points", 0))

class DataManager:
    def __init__(self, data_file: str, backup_dir: str):
        self.data_file = data_file
        self.backup_dir = backup_dir
        self.family_members: Dict[int, str] = {}
        self.points: Dict[str, int] = {}
        self.history: List[Dict] = []
        self.family_goal = FamilyGoal("Car")
        self.load_data()

    def load_data(self) -> None:
        """Loads data from JSON file or initializes defaults."""
        os.makedirs(self.backup_dir, exist_ok=True)
        initial_members = {
            15260416: "Papa",
            441113371: "Mama",
            1059153162: "Danya",
            5678069063: "Vlad",
            5863747570: "Tima",
        }
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, "r") as f:
                    data = json.load(f)
                    self.points = data.get("points", {})
                    self.history = data.get("history", [])
                    self.family_members = {int(k): v for k, v in data.get("family_members", initial_members).items()}
                    self.family_goal = FamilyGoal.from_dict(data.get("family_goal", {"name": "Car"}))
            else:
                self.family_members = initial_members
                self.points = {str(uid): 0 for uid in initial_members}
                self.history = []
                self.save_data()
        except Exception as e:
            logger.error(f"Error loading {self.data_file}: {e}. Using defaults.")
            self.family_members = initial_members
            self.points = {str(uid): 0 for uid in initial_members}
            self.history = []
            self.save_data()

    def save_data(self) -> None:
        """Saves data to JSON file and creates a backup."""
        try:
            data = {
                "points": self.points,
                "history": self.history,
                "family_members": {str(k): v for k, v in self.family_members.items()},
                "family_goal": self.family_goal.to_dict(),
            }
            with open(self.data_file, "w") as f:
                json.dump(data, f, indent=4)
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            backup_file = os.path.join(self.backup_dir, f"points_data_{timestamp}.json")
            shutil.copy(self.data_file, backup_file)
            logger.info(f"Data saved. Backup created: {backup_file}")
        except Exception as e:
            logger.error(f"Failed to save data: {e}")

    def add_member(self, user_id: int, name: str) -> Tuple[bool, str]:
        """Adds a new family member."""
        if user_id in self.family_members:
            return False, f"User {name} (ID: {user_id}) already exists."
        self.family_members[user_id] = name
        self.points[str(user_id)] = 0
        self.save_data()
        return True, "Member added successfully."

    def record_activity(
        self,
        performer_id: int,
        action: str,
        amount: int,
        target_id: Optional[int] = None,
        source_id: Optional[int] = None,
        reason: str = "",
    ) -> None:
        """Records an activity in history."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = {
            "id": str(uuid4()),
            "timestamp": timestamp,
            "performer_id": performer_id,
            "performer": self.family_members.get(performer_id, f"User {performer_id}"),
            "action": action,
            "amount": amount,
            "reason": reason,
        }
        if target_id:
            entry["target_id"] = target_id
            entry["target"] = self.family_members.get(target_id, "Car" if target_id == -1 else f"User {target_id}")
        if source_id:
            entry["source_id"] = source_id
            entry["source"] = self.family_members.get(source_id, f"User {source_id}")
        self.history.append(entry)
        self.save_data()

    def purge_old_history(self) -> None:
        """Purges history entries older than HISTORY_PURGE_INTERVAL_DAYS."""
        cutoff = datetime.now() - timedelta(days=HISTORY_PURGE_INTERVAL_DAYS)
        initial_len = len(self.history)
        self.history = [
            entry for entry in self.history
            if datetime.strptime(entry["timestamp"], "%Y-%m-%d %H:%M:%S") >= cutoff
        ]
        if len(self.history) < initial_len:
            logger.info(f"Purged {initial_len - len(self.history)} old history entries.")
            self.save_data()

    def get_weekly_summary(self) -> str:
        """Generates a weekly summary of points and history."""
        one_week_ago = datetime.now() - timedelta(days=7)
        weekly_history = [
            entry for entry in self.history
            if datetime.strptime(entry["timestamp"], "%Y-%m-%d %H:%M:%S") >= one_week_ago
        ]
        points_summary = "\n".join(
            f"• {self.family_members.get(int(uid), f'User {uid}')}: {points} points"
            for uid, points in sorted(self.points.items(), key=lambda x: int(x[0]))
            if int(uid) in self.family_members
        )
        history_summary = "\n\n".join(
            f"*{entry['timestamp']}* - {entry['performer']} {entry['action']} {entry['amount']} points "
            f"{'to ' + entry.get('target', '') if 'target' in entry else ''}"
            f"{'from ' + entry.get('source', '') + ' to ' + entry.get('target', '') if 'source' in entry else ''}"
            f" (Reason: _{entry['reason']}_)"
            for entry in reversed(weekly_history[-10:])
        )
        return (
            f"📊 **Weekly Family Points Summary** 📊\n\n"
            f"**Current Points**:\n{points_summary or 'No points yet.'}\n\n"
            f"**Family Goal (Car)**: {self.family_goal.points} points\n\n"
            f"**Recent Activity**:\n{history_summary or 'No activity this week.'}"
        )

# --- Bot UI Helper ---
class BotUI:
    @staticmethod
    def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
        """Returns a custom keyboard for the main menu."""
        keyboard = [
            ["➕ Add Points", "➖ Subtract Points"],
            ["↔️ Transfer Points", "📊 Leaderboard"],
            ["📜 History"],
        ]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

    @staticmethod
    def get_member_selection_keyboard(members: Dict[int, str], exclude_id: Optional[int] = None, include_car: bool = False) -> InlineKeyboardMarkup:
        """Returns an inline keyboard for selecting members."""
        keyboard = []
        for uid, name in sorted(members.items(), key=lambda x: x[1]):
            if uid != exclude_id:
                keyboard.append([InlineKeyboardButton(name, callback_data=f"select_member_{uid}")])
        if include_car:
            keyboard.append([InlineKeyboardButton("🚗 Car (Family Goal)", callback_data="select_member_-1")])
        keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="main_menu")])
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def get_confirmation_keyboard() -> InlineKeyboardMarkup:
        """Returns a confirmation keyboard."""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Confirm", callback_data="confirm")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")],
        ])

# --- Bot Logic ---
class FamilyPointsBot:
    def __init__(self, token: str, data_manager: DataManager):
        self.token = token
        self.data_manager = data_manager
        self.application = Application.builder().token(token).build()
        self.setup_handlers()

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles /start command and main menu."""
        await self._send_or_edit_message(
            update,
            "👋 Welcome to the Family Points Bot! Choose an action:",
            reply_markup=BotUI.get_main_menu_keyboard(),
        )
        context.user_data.clear()
        return MAIN_MENU

    async def handle_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles main menu selections."""
        query = update.callback_query
        text = update.message.text if update.message else query.data
        await (query.answer() if query else asyncio.sleep(0))

        context.user_data["action_type"] = text
        if text == "➕ Add Points":
            await self._send_or_edit_message(
                update,
                "Select a member to add points to:",
                reply_markup=BotUI.get_member_selection_keyboard(self.data_manager.family_members),
            )
            return SELECT_MEMBER_ADD
        elif text == "➖ Subtract Points":
            await self._send_or_edit_message(
                update,
                "Select a member to subtract points from:",
                reply_markup=BotUI.get_member_selection_keyboard(self.data_manager.family_members),
            )
            return SELECT_MEMBER_SUBTRACT
        elif text == "↔️ Transfer Points":
            await self._send_or_edit_message(
                update,
                "Select who to transfer points FROM:",
                reply_markup=BotUI.get_member_selection_keyboard(self.data_manager.family_members),
            )
            return SELECT_FROM_TRANSFER
        elif text == "📊 Leaderboard":
            return await self.display_leaderboard(update, context)
        elif text == "📜 History":
            return await self.display_history(update, context)
        else:
            await self._send_or_edit_message(
                update,
                "Please select a valid option:",
                reply_markup=BotUI.get_main_menu_keyboard(),
            )
            return MAIN_MENU

    async def select_member_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles member selection for adding points."""
        query = update.callback_query
        await query.answer()
        if query.data == "main_menu":
            return await self.start_command(update, context)
        target_id = int(query.data.split("_")[-1])
        target_name = self.data_manager.family_members.get(target_id, "Unknown")
        context.user_data.update({"target_id": target_id, "target_name": target_name})
        await query.edit_message_text(f"Enter points to add to {target_name}:")
        return ENTER_AMOUNT_ADD

    async def enter_amount_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles point amount input for adding."""
        try:
            amount = int(update.message.text)
            if amount <= 0:
                await update.message.reply_text("Please enter a positive number:")
                return ENTER_AMOUNT_ADD
            context.user_data["amount"] = amount
            await update.message.reply_text(
                f"Enter reason for adding {amount} points to {context.user_data['target_name']}:",
                reply_markup=ReplyKeyboardRemove(),
            )
            return ENTER_REASON_ADD
        except ValueError:
            await update.message.reply_text("Please enter a valid number:")
            return ENTER_AMOUNT_ADD

    async def enter_reason_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles reason input for adding points."""
        reason = update.message.text.strip()
        if not reason or reason.isdigit():
            await update.message.reply_text("Please provide a descriptive reason:")
            return ENTER_REASON_ADD
        context.user_data["reason"] = reason
        await update.message.reply_text(
            f"Confirm adding {context.user_data['amount']} points to {context.user_data['target_name']}?\nReason: {reason}",
            reply_markup=BotUI.get_confirmation_keyboard(),
        )
        return CONFIRM_ADD

    async def confirm_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Confirms adding points."""
        query = update.callback_query
        await query.answer()
        if query.data == "confirm":
            target_id, amount, reason = context.user_data["target_id"], context.user_data["amount"], context.user_data["reason"]
            self.data_manager.points[str(target_id)] = self.data_manager.points.get(str(target_id), 0) + amount
            self.data_manager.record_activity(update.effective_user.id, "add", amount, target_id=target_id, reason=reason)
            await query.edit_message_text(
                f"✅ Added {amount} points to {context.user_data['target_name']} (Reason: {reason}).\n"
                f"New total: {self.data_manager.points[str(target_id)]} points.",
                reply_markup=BotUI.get_main_menu_keyboard(),
            )
        else:
            await query.edit_message_text("❌ Action cancelled.", reply_markup=BotUI.get_main_menu_keyboard())
        context.user_data.clear()
        return MAIN_MENU

    async def select_member_subtract(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles member selection for subtracting points."""
        query = update.callback_query
        await query.answer()
        if query.data == "main_menu":
            return await self.start_command(update, context)
        target_id = int(query.data.split("_")[-1])
        target_name = self.data_manager.family_members.get(target_id, "Unknown")
        context.user_data.update({"target_id": target_id, "target_name": target_name})
        await query.edit_message_text(f"Enter points to subtract from {target_name}:")
        return ENTER_AMOUNT_SUBTRACT

    async def enter_amount_subtract(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles point amount input for subtracting."""
        try:
            amount = int(update.message.text)
            if amount <= 0:
                await update.message.reply_text("Please enter a positive number:")
                return ENTER_AMOUNT_SUBTRACT
            if self.data_manager.points.get(str(context.user_data["target_id"]), 0) < amount:
                await update.message.reply_text(
                    f"🛑 {context.user_data['target_name']} has only {self.data_manager.points.get(str(context.user_data['target_id']), 0)} points.",
                    reply_markup=BotUI.get_main_menu_keyboard(),
                )
                context.user_data.clear()
                return MAIN_MENU
            context.user_data["amount"] = amount
            await update.message.reply_text(
                f"Enter reason for subtracting {amount} points from {context.user_data['target_name']}:",
                reply_markup=ReplyKeyboardRemove(),
            )
            return ENTER_REASON_SUBTRACT
        except ValueError:
            await update.message.reply_text("Please enter a valid number:")
            return ENTER_AMOUNT_SUBTRACT

    async def enter_reason_subtract(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles reason input for subtracting points."""
        reason = update.message.text.strip()
        if not reason or reason.isdigit():
            await update.message.reply_text("Please provide a descriptive reason:")
            return ENTER_REASON_SUBTRACT
        context.user_data["reason"] = reason
        await update.message.reply_text(
            f"Confirm subtracting {context.user_data['amount']} points from {context.user_data['target_name']}?\nReason: {reason}",
            reply_markup=BotUI.get_confirmation_keyboard(),
        )
        return CONFIRM_SUBTRACT

    async def confirm_subtract(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Confirms subtracting points."""
        query = update.callback_query
        await query.answer()
        if query.data == "confirm":
            target_id, amount, reason = context.user_data["target_id"], context.user_data["amount"], context.user_data["reason"]
            self.data_manager.points[str(target_id)] -= amount
            self.data_manager.record_activity(update.effective_user.id, "subtract", amount, target_id=target_id, reason=reason)
            await query.edit_message_text(
                f"✅ Subtracted {amount} points from {context.user_data['target_name']} (Reason: {reason}).\n"
                f"New total: {self.data_manager.points[str(target_id)]} points.",
                reply_markup=BotUI.get_main_menu_keyboard(),
            )
        else:
            await query.edit_message_text("❌ Action cancelled.", reply_markup=BotUI.get_main_menu_keyboard())
        context.user_data.clear()
        return MAIN_MENU

    async def select_from_transfer(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles source member selection for transfer."""
        query = update.callback_query
        await query.answer()
        if query.data == "main_menu":
            return await self.start_command(update, context)
        from_id = int(query.data.split("_")[-1])
        from_name = self.data_manager.family_members.get(from_id, "Unknown")
        context.user_data.update({"from_id": from_id, "from_name": from_name})
        await query.edit_message_text(
            f"Select who to transfer points TO from {from_name}:",
            reply_markup=BotUI.get_member_selection_keyboard(self.data_manager.family_members, exclude_id=from_id, include_car=True),
        )
        return SELECT_TO_TRANSFER

    async def select_to_transfer(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles destination selection for transfer."""
        query = update.callback_query
        await query.answer()
        if query.data == "main_menu":
            return await self.start_command(update, context)
        to_id = int(query.data.split("_")[-1])
        to_name = "Car" if to_id == -1 else self.data_manager.family_members.get(to_id, "Unknown")
        if context.user_data["from_id"] == to_id:
            await query.edit_message_text(
                "You cannot transfer points to yourself. Select another recipient:",
                reply_markup=BotUI.get_member_selection_keyboard(self.data_manager.family_members, exclude_id=context.user_data["from_id"], include_car=True),
            )
            return SELECT_TO_TRANSFER
        context.user_data.update({"to_id": to_id, "to_name": to_name})
        await query.edit_message_text(f"Enter points to transfer from {context.user_data['from_name']} to {to_name}:")
        return ENTER_AMOUNT_TRANSFER

    async def enter_amount_transfer(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles point amount input for transfer."""
        try:
            amount = int(update.message.text)
            if amount <= 0:
                await update.message.reply_text("Please enter a positive number:")
                return ENTER_AMOUNT_TRANSFER
            if self.data_manager.points.get(str(context.user_data["from_id"]), 0) < amount:
                await update.message.reply_text(
                    f"🛑 {context.user_data['from_name']} has only {self.data_manager.points.get(str(context.user_data['from_id']), 0)} points.",
                    reply_markup=BotUI.get_main_menu_keyboard(),
                )
                context.user_data.clear()
                return MAIN_MENU
            context.user_data["amount"] = amount
            await update.message.reply_text(
                f"Enter reason for transferring {amount} points from {context.user_data['from_name']} to {context.user_data['to_name']}:",
                reply_markup=ReplyKeyboardRemove(),
            )
            return ENTER_REASON_TRANSFER
        except ValueError:
            await update.message.reply_text("Please enter a valid number:")
            return ENTER_AMOUNT_TRANSFER

    async def enter_reason_transfer(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles reason input for transfer."""
        reason = update.message.text.strip()
        if not reason or reason.isdigit():
            await update.message.reply_text("Please provide a descriptive reason:")
            return ENTER_REASON_TRANSFER
        context.user_data["reason"] = reason
        await update.message.reply_text(
            f"Confirm transferring {context.user_data['amount']} points from {context.user_data['from_name']} to {context.user_data['to_name']}?\nReason: {reason}",
            reply_markup=BotUI.get_confirmation_keyboard(),
        )
        return CONFIRM_TRANSFER

    async def confirm_transfer(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Confirms transferring points."""
        query = update.callback_query
        await query.answer()
        if query.data == "confirm":
            from_id, to_id, amount, reason = (
                context.user_data["from_id"],
                context.user_data["to_id"],
                context.user_data["amount"],
                context.user_data["reason"],
            )
            self.data_manager.points[str(from_id)] -= amount
            if to_id == -1:
                self.data_manager.family_goal.points += amount
            else:
                self.data_manager.points[str(to_id)] = self.data_manager.points.get(str(to_id), 0) + amount
            self.data_manager.record_activity(
                update.effective_user.id, "transfer", amount, source_id=from_id, target_id=to_id, reason=reason
            )
            msg = (
                f"✅ Transferred {amount} points from {context.user_data['from_name']} to {context.user_data['to_name']} (Reason: {reason}).\n"
                f"New totals:\n{context.user_data['from_name']}: {self.data_manager.points[str(from_id)]} points\n"
                f"{context.user_data['to_name']}: {self.data_manager.family_goal.points if to_id == -1 else self.data_manager.points[str(to_id)]} points"
            )
            await query.edit_message_text(msg, reply_markup=BotUI.get_main_menu_keyboard())
        else:
            await query.edit_message_text("❌ Action cancelled.", reply_markup=BotUI.get_main_menu_keyboard())
        context.user_data.clear()
        return MAIN_MENU

    async def add_member_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Starts adding a new family member."""
        await update.message.reply_text("Enter the new member's name:", reply_markup=ReplyKeyboardRemove())
        context.user_data["temp_performer_id"] = update.effective_user.id
        return ADD_MEMBER_NAME

    async def enter_new_member_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles new member name input."""
        name = update.message.text.strip()
        if not name or any(char.isdigit() for char in name):
            await update.message.reply_text("Please enter a valid name (text only):")
            return ADD_MEMBER_NAME
        context.user_data["new_member_name"] = name
        await update.message.reply_text(
            f"Enter {name}'s Telegram User ID (forward a message to @userinfobot to get it):",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ADD_MEMBER_ID

    async def enter_new_member_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handles new member ID input."""
        try:
            member_id = int(update.message.text)
            if member_id <= 0:
                await update.message.reply_text("Please enter a valid Telegram User ID:")
                return ADD_MEMBER_ID
            context.user_data["new_member_id"] = member_id
            await update.message.reply_text(
                f"Confirm adding:\nName: *{context.user_data['new_member_name']}*\nID: `{member_id}`",
                parse_mode="Markdown",
                reply_markup=BotUI.get_confirmation_keyboard(),
            )
            return CONFIRM_ADD_MEMBER
        except ValueError:
            await update.message.reply_text("Please enter a valid number for the Telegram ID:")
            return ADD_MEMBER_ID

    async def confirm_add_member(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Confirms adding a new member."""
        query = update.callback_query
        await query.answer()
        if query.data == "confirm":
            member_id, name = context.user_data["new_member_id"], context.user_data["new_member_name"]
            success, message = self.data_manager.add_member(member_id, name)
            msg = f"🎉 {name} (ID: `{member_id}`) added!" if success else f"⚠️ {message}"
            if success:
                self.data_manager.record_activity(
                    context.user_data.get("temp_performer_id", update.effective_user.id),
                    "add_member",
                    0,
                    target_id=member_id,
                    reason=f"Added {name}",
                )
            await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=BotUI.get_main_menu_keyboard())
        else:
            await query.edit_message_text("❌ Action cancelled.", reply_markup=BotUI.get_main_menu_keyboard())
        context.user_data.clear()
        return MAIN_MENU

    async def display_leaderboard(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Displays the leaderboard."""
        if not self.data_manager.points or all(points == 0 for uid, points in self.data_manager.points.items() if int(uid) in self.data_manager.family_members):
            msg = "🏆 **Leaderboard** 🏆\n\nNo points yet. Start adding some!"
        else:
            msg = "🏆 **Leaderboard** 🏆\n\n" + "\n".join(
                f"• {self.data_manager.family_members.get(int(uid), f'User {uid}')}: {points} points"
                for uid, points in sorted(self.data_manager.points.items(), key=lambda x: x[1], reverse=True)
                if int(uid) in self.data_manager.family_members and points != 0
            ) + f"\n\n🚗 **Car (Family Goal)**: {self.data_manager.family_goal.points} points"
        await self._send_or_edit_message(update, msg, parse_mode="Markdown", reply_markup=BotUI.get_main_menu_keyboard())
        return MAIN_MENU

    async def display_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Displays recent history."""
        if not self.data_manager.history:
            msg = "📜 **History** 📜\n\nNo activity yet."
        else:
            msg = "📜 **History** 📜\n\n" + "\n\n".join(
                f"*{entry['timestamp']}* - {entry['performer']} {entry['action']} {entry['amount']} points "
                f"{'to ' + entry.get('target', '') if 'target' in entry else ''}"
                f"{'from ' + entry.get('source', '') + ' to ' + entry.get('target', '') if 'source' in entry else ''}"
                f" (Reason: _{entry['reason']}_)"
                for entry in reversed(self.data_manager.history[-10:])
            )
        await self._send_or_edit_message(update, msg, parse_mode="Markdown", reply_markup=BotUI.get_main_menu_keyboard())
        return MAIN_MENU

    async def cancel_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancels the current action."""
        await self._send_or_edit_message(
            update, "❌ Action cancelled.", reply_markup=BotUI.get_main_menu_keyboard()
        )
        context.user_data.clear()
        return MAIN_MENU

    async def unknown_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handles unknown commands."""
        await update.message.reply_text(
            "❓ Unknown command. Use /start to begin.", reply_markup=BotUI.get_main_menu_keyboard()
        )

    async def handle_text_not_in_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handles unexpected text input."""
        await update.message.reply_text(
            "Please use the menu options or /start.", reply_markup=BotUI.get_main_menu_keyboard()
        )

    async def weekly_summary_job(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Sends weekly summary every Sunday."""
        if datetime.now().weekday() == WEEKLY_SUMMARY_DAY:
            summary = self.data_manager.get_weekly_summary()
            chat_id = GROUP_CHAT_ID or ADMIN_ID
            try:
                await context.bot.send_message(chat_id=chat_id, text=summary, parse_mode="Markdown")
                logger.info(f"Weekly summary sent to chat {chat_id}")
            except Exception as e:
                logger.error(f"Failed to send weekly summary: {e}")

    async def history_purge_job(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Purges old history periodically."""
        logger.info("Running history purge job...")
        self.data_manager.purge_old_history()

    async def _send_or_edit_message(
        self,
        update: Update,
        text: str,
        reply_markup=None,
        parse_mode: Optional[str] = None,
    ) -> None:
        """Sends or edits a message with retry logic."""
        for attempt in range(3):
            try:
                if update.callback_query:
                    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
                    return
                else:
                    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
                    return
            except BadRequest as e:
                logger.warning(f"Failed to edit/send message (attempt {attempt + 1}): {e}")
                await asyncio.sleep(1)
            except NetworkError as e:
                logger.warning(f"Network error (attempt {attempt + 1}): {e}")
                await asyncio.sleep(2)
        logger.error("Failed to send/edit message after retries. Sending new message.")
        await update.effective_chat.send_message(text, reply_markup=reply_markup, parse_mode=parse_mode)

    def setup_handlers(self) -> None:
        """Sets up all bot handlers."""
        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler("start", self.start_command),
                CommandHandler("points", self.start_command),
                CommandHandler("add_member", self.add_member_command, filters=filters.User(ADMIN_ID)),
            ],
            states={
                MAIN_MENU: [
                    MessageHandler(filters.Regex("^(➕ Add Points|➖ Subtract Points|↔️ Transfer Points|📊 Leaderboard|📜 History)$"), self.handle_main_menu),
                    CommandHandler("leaderboard", self.display_leaderboard),
                    CommandHandler("history", self.display_history),
                ],
                SELECT_MEMBER_ADD: [CallbackQueryHandler(self.select_member_add, pattern="^select_member_[0-9-]+$")],
                ENTER_AMOUNT_ADD: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.enter_amount_add)],
                ENTER_REASON_ADD: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.enter_reason_add)],
                CONFIRM_ADD: [CallbackQueryHandler(self.confirm_add, pattern="^(confirm|cancel_action)$")],
                SELECT_MEMBER_SUBTRACT: [CallbackQueryHandler(self.select_member_subtract, pattern="^select_member_[0-9]+$")],
                ENTER_AMOUNT_SUBTRACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.enter_amount_subtract)],
                ENTER_REASON_SUBTRACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.enter_reason_subtract)],
                CONFIRM_SUBTRACT: [CallbackQueryHandler(self.confirm_subtract, pattern="^(confirm|cancel_action)$")],
                SELECT_FROM_TRANSFER: [CallbackQueryHandler(self.select_from_transfer, pattern="^select_member_[0-9]+$")],
                SELECT_TO_TRANSFER: [CallbackQueryHandler(self.select_to_transfer, pattern="^select_member_[0-9-]+$")],
                ENTER_AMOUNT_TRANSFER: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.enter_amount_transfer)],
                ENTER_REASON_TRANSFER: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.enter_reason_transfer)],
                CONFIRM_TRANSFER: [CallbackQueryHandler(self.confirm_transfer, pattern="^(confirm|cancel_action)$")],
                ADD_MEMBER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.enter_new_member_name)],
                ADD_MEMBER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.enter_new_member_id)],
                CONFIRM_ADD_MEMBER: [CallbackQueryHandler(self.confirm_add_member, pattern="^(confirm|cancel_action)$")],
            },
            fallbacks=[
                CommandHandler("cancel", self.cancel_action),
                CallbackQueryHandler(self.cancel_action, pattern="^cancel_action$"),
                CallbackQueryHandler(self.start_command, pattern="^main_menu$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text_not_in_conversation),
            ],
            per_user=True,
        )
        self.application.add_handler(conv_handler)
        self.application.add_handler(MessageHandler(filters.COMMAND, self.unknown_command))
        self.application.job_queue.run_repeating(self.history_purge_job, interval=timedelta(hours=24), first=datetime.now() + timedelta(minutes=5))
        self.application.job_queue.run_repeating(self.weekly_summary_job, interval=timedelta(hours=24), first=datetime.now() + timedelta(minutes=5))

    def run(self) -> None:
        """Starts the bot."""
        logger.info("Starting Family Points Bot...")
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)

def main() -> None:
    data_manager = DataManager(DATA_FILE, BACKUP_DIR)
    bot = FamilyPointsBot(TOKEN, data_manager)
    bot.run()

if __name__ == "__main__":
    main()