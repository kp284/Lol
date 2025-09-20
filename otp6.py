# -*- coding: utf-8 -*-
"""
This is a complete, self-contained Telegram bot for an OTP service.
It runs on Termux using long polling and stores all data in a single file SQLite database.
This version is updated to be modular and fully functional.
"""
from telegram.constants import ChatAction
# --- Import necessary libraries ---
import os
import secrets
import string
import qrcode
import logging
import time
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.error import TelegramError
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
)

# Configure logging to show information and errors in the console
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.DEBUG)
logger = logging.getLogger(__name__)

# --- Basic Configuration ---
# You MUST replace these with your own Bot Token and Admin User ID.
TOKEN = "8331319111:AAE6SojQBC1DEYvY4OkVyRcozSaO0sck9f0"
ADMIN_ID = 7507183871  # Replace with your Telegram User ID (as an integer)
UPI_ID = "krishpatel284@fam"
SUPPORT_LINK = "https://t.me/patelkrish_99"
DB_FILE = '1bot2.db'

# --- Conversation States for multi-step processes ---
(
    ADD_NUMBER_CATEGORY,
    ADD_NUMBER_NUMBER,
    ADD_NUMBER_PRICE,
    ADD_NUMBER_COUNTRY,
    ADD_NUMBER_DETAILS,
    CREATE_COUPON_VALUE,
    CREATE_COUPON_LIMIT,
    CLAIM_COUPON,
    REPLY_OTP_TO_USER,
    SET_DEPOSIT_UTR,
    BAN_USER_ID,
    UNBAN_USER_ID,
    ADD_CHANNEL_ID,
    ADD_CHANNEL_INVITE,
    REMOVE_CHANNEL_ID,
    ADD_BALANCE_USER_ID,
    ADD_BALANCE_AMOUNT,
    REMOVE_BALANCE_USER_ID,
    REMOVE_BALANCE_AMOUNT,
    SET_BONUS_VALUE,
    REJECT_DEPOSIT_REASON,
    GET_DEPOSIT_AMOUNT,
    BROADCAST_MESSAGE,
    BROADCAST_MEDIA,
    ASK_FOR_BUTTON_TEXT,
    ASK_FOR_BUTTON_URL,
    EDIT_NUMBER_ID,
    EDIT_NUMBER_FIELD,
    EDIT_NUMBER_VALUE,
    REMOVE_NUMBER_ID,
    ADD_ADMIN_ID,
    REMOVE_ADMIN_ID
) = range(32)


# --- Database Setup and Helper Functions ---

def setup_database():
    """Connects to the database and creates tables if they don't exist."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, balance REAL DEFAULT 0.0, purchased_count INTEGER DEFAULT 0, is_banned BOOLEAN DEFAULT FALSE)""")
    c.execute("""CREATE TABLE IF NOT EXISTS numbers (number_id TEXT PRIMARY KEY, category TEXT, number TEXT, price REAL, country TEXT, details TEXT, status TEXT, buyer_id INTEGER, purchase_time REAL, otp_sent BOOLEAN DEFAULT FALSE)""")
    c.execute("""CREATE TABLE IF NOT EXISTS deposits (deposit_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, utr TEXT, photo_id TEXT, status TEXT, timestamp REAL, amount REAL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS coupons (code TEXT PRIMARY KEY, value REAL, usage_limit INTEGER, used_count INTEGER DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS channels (id INTEGER PRIMARY KEY, title TEXT, invite_link TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS admins (id INTEGER PRIMARY KEY)""")
    c.execute("""CREATE TABLE IF NOT EXISTS claimed_coupons (user_id INTEGER, coupon_code TEXT, PRIMARY KEY (user_id, coupon_code))""")
    conn.commit()

    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", ('maintenance_mode', 'False'))
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", ('bonus_value', '0.1'))
    c.execute("INSERT OR IGNORE INTO admins (id) VALUES (?)", (ADMIN_ID,))
    conn.commit()
    conn.close()

def get_user(user_id):
    """Retrieves or creates a user entry in the database."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user_data = c.fetchone()
    if not user_data:
        c.execute("INSERT INTO users (id) VALUES (?)", (user_id,))
        conn.commit()
        c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        user_data = c.fetchone()
    conn.close()
    return dict(user_data)

def save_user(user_data):
    """Saves a user entry to the database."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET balance = ?, purchased_count = ?, is_banned = ? WHERE id = ?",
              (user_data['balance'], user_data['purchased_count'], user_data['is_banned'], user_data['id']))
    conn.commit()
    conn.close()

def get_setting(key):
    """Retrieves a setting from the database."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = ?", (key,))
    value = c.fetchone()
    conn.close()
    if value is None:
        return None
    return value[0] == 'True' if key == 'maintenance_mode' else float(value[0])

def set_setting(key, value):
    """Updates a setting in the database."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE settings SET value = ? WHERE key = ?", (str(value), key))
    conn.commit()
    conn.close()

def is_admin(user_id):
    """Checks if a user is an admin."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT * FROM admins WHERE id = ?", (user_id,))
    is_admin = c.fetchone() is not None
    conn.close()
    return is_admin

def generate_qr(data, filename='qr_code.png'):
    """Generates a QR code image from a given string."""
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(filename)
    return filename

def generate_random_code(length=10):
    """Generates a random alphanumeric string for coupons."""
    chars = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))

def get_available_numbers():
    """Retrieves and sorts available numbers by price (highest first)."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM numbers WHERE status = 'available' ORDER BY price DESC")
    numbers = [dict(row) for row in c.fetchall()]
    conn.close()
    return numbers

def paginate_list(items, page, per_page=10):
    """Returns a slice of a list for pagination."""
    start = (page - 1) * per_page
    end = start + per_page
    return items[start:end]

async def check_force_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Checks if the user has joined all required channels."""
    user_id = update.effective_user.id
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM channels")
    channels = [dict(row) for row in c.fetchall()]
    conn.close()

    if not channels:
        return True

    unjoined_channels = []
    for channel in channels:
        try:
            member = await context.bot.get_chat_member(chat_id=channel['id'], user_id=user_id)
            if member.status not in ['member', 'creator', 'administrator']:
                unjoined_channels.append(channel)
        except TelegramError as e:
            logger.error(f"Error checking channel {channel['id']}: {e}")
            unjoined_channels.append(channel)

    if unjoined_channels:
        keyboard = [[InlineKeyboardButton(f"Join {channel['title']}", url=channel['invite_link'])] for channel in unjoined_channels]
        reply_markup = InlineKeyboardMarkup(keyboard)
        message_text = "Please join the following channels to use the bot:"
        
        try:
            if update.callback_query:
                await update.callback_query.edit_message_text(message_text, reply_markup=reply_markup)
            else:
                await update.message.reply_text(message_text, reply_markup=reply_markup)
        except TelegramError:
            await context.bot.send_message(user_id, message_text, reply_markup=reply_markup)
        
        return False
    return True

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the main bot menu."""
    keyboard = [
        [InlineKeyboardButton("💰 Deposit", callback_data='deposit'), InlineKeyboardButton("💳 Account", callback_data='account')],
        [InlineKeyboardButton("🛒 Buy Number", callback_data='buy_number:1')],
        [InlineKeyboardButton("🎁 Claim Bonus", callback_data='claim_bonus'), InlineKeyboardButton("📞 Support", url=SUPPORT_LINK)],
        [InlineKeyboardButton("Chat on WhatsApp", url="https://wa.me/6283163700186?text=Hello%20I%20need%20a%20help%20im%20from%20your%20bot")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = "Hello! Welcome to the OTP Bot \n 😁Hehe...\n\n Please select an option:"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)


# --- User-Facing Handlers ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /start command."""
    user_id = update.effective_user.id
    user_data = update.effective_user
    
    # Check if user already exists
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE id = ?", (user_id,))
    existing_user = c.fetchone()
    conn.close()

    if not existing_user:
        await context.bot.send_chat_action(chat_id=ADMIN_ID, action=ChatAction.TYPING)

        # It's a new user, send notification to admin
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"🎉 New User Alert! 🎉\n\n"
                f"👤 User : {user_data.full_name}\n"
                f"👋 Username : @{user_data.username}\n"
                f"🆔 User ID : {user_data.id}"
            ),
            parse_mode='HTML'
        )

    # Now, proceed with the original /start logic
    user = get_user(user_id)
    if user.get('is_banned'):
        await update.message.reply_text("Bot admin banned you....❌.")
        return

    if get_setting('maintenance_mode') and not is_admin(user_id):
        await update.message.reply_text("Bot is currently under maintenance. Please try again later.")
        return

    if not await check_force_join(update, context):
        return

    keyboard = [
        [InlineKeyboardButton("💰 Deposit", callback_data='deposit'), InlineKeyboardButton("💳 Account", callback_data='account')],
        [InlineKeyboardButton("🛒 Buy Number", callback_data='buy_number:1')],
        [InlineKeyboardButton("🎁 Claim Bonus", callback_data='claim_bonus'), InlineKeyboardButton("📞 Support", url=SUPPORT_LINK)],
        [InlineKeyboardButton("📞WhatsApp Support", url="https://wa.me/6283163700186?text=Hello%20I%20need%20a%20help%20im%20from%20your%20bot")]
    ]
    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data='admin:main')])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Hello! Welcome to the OTP Bot. Please select an option:", reply_markup=reply_markup)

async def handle_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Begins the deposit conversation by asking for the amount."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🤔How much would you like to deposit? Please enter a number.")
    return GET_DEPOSIT_AMOUNT

async def handle_account(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows user's balance, user ID, username, and purchased numbers."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user_username = query.from_user.username if query.from_user.username else 'N/A'
    user_full_name = query.from_user.full_name
    
    user = get_user(user_id)
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    total_deposits = c.execute("SELECT SUM(amount) FROM deposits WHERE user_id = ?", (user_id,)).fetchone()[0]
    conn.close()
    
    if total_deposits is None:
        total_deposits = 0.0

    text = (
        f"👤 User : <a href='tg://user=id?{user_id}'>{user_full_name}</a>\n"
        f"🆔 User ID : {user_id}\n\n"
        f"💸 Balance : ₹{user['balance']:.2f}\n\n"
        f"🧾 Your Total Orders : {user['purchased_count']} Points\n\n"
        f"💸 Total Deposits : {total_deposits:.2f}"
    )
    
    await query.edit_message_text(text, parse_mode='HTML')

async def get_deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives the deposit amount, then sends the QR code and instructions."""
    try:
        amount = float(update.message.text)
        if amount <= 0:
            raise ValueError
        context.user_data['deposit_amount'] = amount # Store the amount for later
        
        qr_filename = generate_qr(f"upi://pay?pa={UPI_ID}&am={amount}")
        
        keyboard = [[InlineKeyboardButton("✅ I Have Sent", callback_data='user:deposit:sent')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        caption = f"🙏Please send exactly ₹{amount:.2f} to UPI ID:\n{UPI_ID}\n\nOnce done, click 'I Have Sent' and upload your UTR and screenshot."
        
        await update.message.reply_photo(
            photo=open(qr_filename, 'rb'),
            caption=caption,
            parse_mode='HTML',
            reply_markup=reply_markup
        )
        os.remove(qr_filename)
        return SET_DEPOSIT_UTR
    except ValueError:
        await update.message.reply_text("❌Invalid amount. Please enter a valid number.")
        return GET_DEPOSIT_AMOUNT

async def handle_buy_number_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays a paginated list of available numbers."""
    query = update.callback_query
    await query.answer()
    page = int(query.data.split(':')[1])
    all_numbers = get_available_numbers()
    paginated_numbers = paginate_list(all_numbers, page)
    
    if not paginated_numbers:
        await query.edit_message_text("😑No numbers are currently available.")
        return

    text = "Available Numbers:\n\n"
    keyboard = []
    for number in paginated_numbers:
        text += f"Category: {number['category']}\nPrice: ₹{number['price']}\nCountry: {number['country']}\n\n"
        keyboard.append([InlineKeyboardButton(f"Buy {number['number']}", callback_data=f"buy:{number['number_id']}")])

    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"buy_number:{page - 1}"))
    if page * 10 < len(all_numbers):
        nav_buttons.append(InlineKeyboardButton("➡️ Next", callback_data=f"buy_number:{page + 1}"))
    if nav_buttons:
        keyboard.append(nav_buttons)

    keyboard.append([InlineKeyboardButton("🔙 Back to Main Menu", callback_data='main_menu')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def handle_buy_number_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the purchase confirmation of a number."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    number_id = query.data.split(':')[1]
    
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM numbers WHERE number_id = ? AND status = 'available'", (number_id,))
    number = c.fetchone()
    conn.close()

    if not number:
        await query.edit_message_text("This number is no longer available.")
        return
    
    user = get_user(user_id)
    if user['balance'] < number['price']:
        await query.edit_message_text("🤨Insufficient balance. Please deposit funds.")
        return
    
    context.user_data['confirm_purchase'] = number_id
    
    keyboard = [
        [InlineKeyboardButton("✅ Confirm Purchase", callback_data=f"confirm:{number_id}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="buy_number:1")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"🤔Are you sure you want to buy the number for {number['category']}?\n\nPrice: ₹{number['price']:.2f}"
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def start_claim_coupon(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Begins the coupon claim conversation."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Enter your coupon code:")
    return CLAIM_COUPON

async def claim_coupon(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the coupon claim logic."""
    coupon_code = update.message.text.strip().upper()
    user_id = update.effective_user.id
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Check if the user has already claimed this coupon
    c.execute("SELECT * FROM claimed_coupons WHERE user_id = ? AND coupon_code = ?", (user_id, coupon_code))
    if c.fetchone():
        await update.message.reply_text("🤨You have already claimed this coupon.")
        conn.close()
        return ConversationHandler.END

    c.execute("SELECT * FROM coupons WHERE code = ?", (coupon_code,))
    coupon = c.fetchone()
    
    if coupon and coupon['used_count'] < coupon['usage_limit']:
        user = get_user(user_id)
        user['balance'] += coupon['value']
        save_user(user)
        
        c.execute("UPDATE coupons SET used_count = used_count + 1 WHERE code = ?", (coupon_code,))
        
        # Add a record to the new claimed_coupons table
        c.execute("INSERT INTO claimed_coupons (user_id, coupon_code) VALUES (?, ?)", (user_id, coupon_code))
        
        conn.commit()
        await update.message.reply_text(f"⚡️Coupon redeemed! You have received ₹{coupon['value']:.2f} to your account.")
    else:
        await update.message.reply_text("👀Invalid or expired coupon code.")
    
    conn.close()
    await show_main_menu(update, context)
    return ConversationHandler.END

# --- Admin Panel Handlers ---

async def admin_panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin panel entry point."""
    query = update.callback_query
    if query:
        await query.answer()
        user_id = query.from_user.id
    else:
        user_id = update.effective_user.id

    if not is_admin(user_id):
        if query:
            await query.edit_message_text("You are not an admin.")
        else:
            await update.message.reply_text("You are not an admin.")
        return

    keyboard = [
        [InlineKeyboardButton("➕ Add Number", callback_data='admin:add_number'), InlineKeyboardButton("✏️ Edit/Remove", callback_data='admin:edit_remove_number_menu')],
        [InlineKeyboardButton("📊 Statistics", callback_data='admin:stats'), InlineKeyboardButton("📢 Broadcast", callback_data='admin:broadcast')],
        [InlineKeyboardButton("➕ Add/Remove Force Join", callback_data='admin:manage_channels')],
        [InlineKeyboardButton("🚫 Ban/Unban", callback_data='admin:ban_unban')],
        [InlineKeyboardButton("🎁 Create Coupon", callback_data='admin:create_coupon')],
        [InlineKeyboardButton("➕ Add/Remove Balance", callback_data='admin:manage_balance')],
        [InlineKeyboardButton("⚙️ Settings", callback_data='admin:settings'),InlineKeyboardButton("👑 Manage Admins", callback_data='admin:manage_admins')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Always send a new message instead of editing
    if query and query.message:
        await query.message.edit_text("Admin Panel:", reply_markup=reply_markup)
    else:
        await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

        await context.bot.send_message(user_id, "Admin Panel:", reply_markup=reply_markup)




async def handle_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Routes to different admin panel sections based on button clicks."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if not is_admin(user_id):
        return

    data = query.data.split(':')
    action = data[1]

    if action == 'main':
        await admin_panel_handler(update, context)
    elif action == 'stats':
        await show_stats(update, context)
    elif action == 'manage_admins':
        await manage_admins_menu(update, context)
    elif action == 'add_number':
        # This action starts a new conversation handler, so we don't need to return anything
        # It's handled by a separate ConversationHandler entry point in main()
        await start_add_number_conv(update, context)
    elif action == 'edit_remove_number_menu':
        await edit_remove_number_menu(update, context)
    elif action == 'remove_number_menu':
        await remove_number_menu(update, context)
    elif action == 'remove_number':
        await remove_number(update, context)
    elif action == 'broadcast':
        await start_broadcast_conv(update, context)
    elif action == 'manage_channels':
        await manage_channels_menu(update, context)
    elif action == 'add_channel':
        await start_add_channel(update, context)
    elif action == 'remove_channel_menu':
        await remove_channel_menu(update, context)
    elif action == 'remove_channel':
        await remove_channel(update, context)
    elif action == 'ban_unban':
        await ban_unban_menu(update, context)
    elif action == 'ban_user':
        await start_ban_user(update, context)
    elif action == 'unban_user':
        await start_unban_user(update, context)
    elif action == 'create_coupon':
        await start_create_coupon_conv(update, context)
    elif action == 'manage_balance':
        await manage_balance_menu(update, context)
    elif action == 'add_balance':
        await start_add_balance(update, context)
    elif action == 'remove_balance':
        await start_remove_balance(update, context)
    elif action == 'settings':
        await show_settings_menu(update, context)
    elif action == 'settings':
        await handle_settings(update, context)
    elif action == 'deposit':
        # Admin Deposit Approval
        deposit_id = int(data[3])
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # Query for a pending deposit
        c.execute("SELECT user_id, utr, amount FROM deposits WHERE deposit_id = ? AND status = 'pending'", (deposit_id,))
        deposit = c.fetchone()
        
        # Nested if/elif for deposit actions
        if data[2] == 'accept':
            if deposit:
                user_id = deposit['user_id']
                deposit_amount = deposit['amount']

                user = get_user(user_id)
                bonus = get_setting('bonus_value')

                # Add balance and bonus
                user['balance'] += deposit_amount + (deposit_amount * bonus)
                save_user(user)

                # Update deposit status to accepted
                c.execute("UPDATE deposits SET status = 'accepted' WHERE deposit_id = ?", (deposit_id,))
                conn.commit()

                await context.bot.send_message(user_id, f"✨Your deposit of ₹{deposit_amount:.2f} has been accepted!🎉 A bonus of {bonus*100}% was added. Your new balance is ₹{user['balance']:.2f}.")
                await context.bot.send_message(query.from_user.id, f"✅ The deposit for user `{user_id}` has been accepted. Amount: ₹{deposit_amount:.2f}")
                await query.edit_message_text(f"✅ Deposit Request Accepted.")

            else:
                await query.edit_message_text("Error: Deposit not found or already processed.")
            conn.close()

        elif data[2] == 'decline':
            context.user_data['state'] = REJECT_DEPOSIT_REASON
            context.user_data['deposit_id'] = deposit_id
            await context.bot.send_message(query.from_user.id, "❌ Deposit decline process initiated. Please reply to this message with the reason.")
            await query.edit_message_text("❌ Deposit Request Declined. Awaiting reason.")
            return REJECT_DEPOSIT_REASON




async def reject_deposit_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the reason for a rejected deposit."""
    deposit_id = context.user_data.get('deposit_id')
    reason = update.message.text
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Get user_id before closing the connection
    c.execute("SELECT user_id FROM deposits WHERE deposit_id = ?", (deposit_id,))
    user_id_result = c.fetchone()
    
    if user_id_result:
        user_id = user_id_result[0]
        c.execute("UPDATE deposits SET status = 'rejected' WHERE deposit_id = ?", (deposit_id,))
        conn.commit()
        conn.close()

        try:
            await context.bot.send_message(user_id, f"😔Your deposit has been rejected.\nReason: {reason}")
            await update.message.reply_text("Deposit rejected and user notified.")
        except TelegramError:
            await update.message.reply_text("Failed to notify user. Deposit rejected.")
    else:
        conn.close()
        await update.message.reply_text("Error: Deposit not found.")

    return ConversationHandler.END


async def manage_admins_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows the manage admins menu."""
    query = update.callback_query
    await query.answer()
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id FROM admins")
    admins = [row[0] for row in c.fetchall()]
    conn.close()

    admin_list_text = "Current Admins:\n" + "\n".join([f"`{admin_id}`" for admin_id in admins])

    keyboard = [
        [InlineKeyboardButton("➕ Add Admin", callback_data='admin:add_admin')],
        [InlineKeyboardButton("➖ Remove Admin", callback_data='admin:remove_admin')],
        [InlineKeyboardButton("🔙 Back to Admin", callback_data='admin:main')]
    ]
    await query.edit_message_text(f"👑 Manage Admins\n\n{admin_list_text}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def start_add_admin_conv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Begins the add admin conversation."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Please reply with the User ID of the new admin.")
    return ADD_ADMIN_ID

async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Adds a new admin by User ID."""
    try:
        user_id_to_add = int(update.message.text)
        
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO admins (id) VALUES (?)", (user_id_to_add,))
        conn.commit()
        conn.close()
        
        await update.message.reply_text(f"User {user_id_to_add} has been added as an admin.")
    except ValueError:
        await update.message.reply_text("Invalid User ID. Please enter a number.")
    return ConversationHandler.END

async def start_remove_admin_conv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Begins the remove admin conversation."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Please reply with the User ID of the admin to remove.")
    return REMOVE_ADMIN_ID

async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Removes an admin by User ID."""
    try:
        user_id_to_remove = int(update.message.text)
        
        # Check if the user is trying to remove the last admin
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM admins")
        admin_count = c.fetchone()[0]
        
        if admin_count <= 1:
            await update.message.reply_text("You cannot remove the last admin.")
            conn.close()
            return ConversationHandler.END
        
        c.execute("DELETE FROM admins WHERE id = ?", (user_id_to_remove,))
        conn.commit()
        conn.close()
        
        await update.message.reply_text(f"User {user_id_to_remove} has been removed as an admin.")
    except ValueError:
        await update.message.reply_text("Invalid User ID. Please enter a number.")
    return ConversationHandler.END


async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays bot statistics for the admin."""
    query = update.callback_query
    await query.answer()
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    total_users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_orders = c.execute("SELECT COUNT(*) FROM numbers WHERE status = 'sold'").fetchone()[0]
    total_deposits = c.execute("SELECT COUNT(*) FROM deposits").fetchone()[0]
    total_deposited_amount = c.execute("SELECT SUM(amount) FROM deposits").fetchone()[0]
    
    conn.close()
    text = f"📊 Statistics\n\nTotal Users: {total_users}\nTotal Orders: {total_orders}\nTotal Deposits: {total_deposits}\nTotal deposit amount: {total_deposited_amount}"
    await query.edit_message_text(text, parse_mode='HTML')

# --- Admin Panel Message Handlers ---
async def handle_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Sends a broadcast message to all users and ends the conversation."""
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END

    message_to_broadcast = update.message
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id FROM users")
    users = c.fetchall()
    conn.close()

    for user in users:
        try:
            if message_to_broadcast.text:
                await context.bot.send_message(chat_id=user[0], text=message_to_broadcast.text, parse_mode='HTML')
            elif message_to_broadcast.photo:
                await context.bot.send_photo(chat_id=user[0], photo=message_to_broadcast.photo[-1].file_id, caption=message_to_broadcast.caption, parse_mode='HTML')
            elif message_to_broadcast.video:
                await context.bot.send_video(chat_id=user[0], video=message_to_broadcast.video.file_id, caption=message_to_broadcast.caption, parse_mode='HTML')
            time.sleep(0.1)
        except TelegramError:
            continue
    
    await update.message.reply_text("Broadcast complete.")
    return ConversationHandler.END

async def handle_confirm_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the final number purchase after confirmation."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    number_id = query.data.split(':')[1]

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM numbers WHERE number_id = ? AND status = 'available'", (number_id,))
    number = c.fetchone()
    
    if not number:
        await query.edit_message_text("This number is no longer available.")
        conn.close()
        return

    user = get_user(user_id)
    if user['balance'] < number['price']:
        await query.edit_message_text("🤨Insufficient balance. Please deposit funds.")
        conn.close()
        return
    
    user['balance'] -= number['price']
    user['purchased_count'] += 1
    save_user(user)
    
    c.execute("UPDATE numbers SET status = 'sold', buyer_id = ?, purchase_time = ?, otp_sent = FALSE WHERE number_id = ?", (user_id, time.time(), number_id))
    conn.commit()
    conn.close()
    
    await query.edit_message_text(f"congrates🎉! You have successfully purchased the number {number['number']}.\n\nPlease wait for the OTP...")
    
    admin_keyboard = [[InlineKeyboardButton("Reply OTP", callback_data=f"admin:reply_otp:{user_id}:{number['number_id']}")]]
    await context.bot.send_message(ADMIN_ID, f"New purchase from user `{user_id}` (@{query.from_user.username}):\n\nNumber: {number['number']}\nPrice: ₹{number['price']}\n\nPlease reply with the OTP.", reply_markup=InlineKeyboardMarkup(admin_keyboard), parse_mode='HTML')


async def reply_otp_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Forwards the OTP to the correct user or issues a refund."""
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
        
    buyer_id = int(context.user_data.get('buyer_id'))
    number_id = context.user_data.get('number_id')
    otp = update.message.text.strip()
    
    if otp.lower() == "refund":
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT price FROM numbers WHERE number_id = ?", (number_id,))
        number_price = c.fetchone()
        conn.close()
        
        if number_price:
            user = get_user(buyer_id)
            user['balance'] += number_price[0]
            save_user(user)
            await context.bot.send_chat_action(chat_id=buyer_id, action=ChatAction.TYPING)
            await context.bot.send_message(chat_id=buyer_id, text=f"The number purchase was cancelled. Your balance has been refunded with **₹{number_price[0]:.2f}**.", parse_mode='HTML')
            await update.message.reply_text("Refund successful.")
        else:
            await update.message.reply_text("Failed to find number details for refund.")
            
    else:
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            # Correctly updates the otp_sent status to TRUE
            c.execute("UPDATE numbers SET otp_sent = TRUE WHERE number_id = ?", (number_id,))
            conn.commit()
            conn.close()
            await context.bot.send_chat_action(chat_id=buyer_id, action=ChatAction.TYPING)
            await context.bot.send_message(chat_id=buyer_id, text=f"Your OTP is: `{otp}`")
            await update.message.reply_text("OTP sent successfully to the user.")
        except TelegramError as e:
            await update.message.reply_text(f"Failed to send OTP to user. Error: {e.message}")
            
    return ConversationHandler.END


async def check_for_expired_orders(context: ContextTypes.DEFAULT_TYPE):
    """Checks for numbers purchased more than 10 minutes ago and refunds the user."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Correctly queries for numbers with status 'sold', purchase_time over 10 mins, AND otp_sent is FALSE
    expired_timestamp = time.time() - 600  # 10 minutes = 600 seconds
    c.execute("SELECT * FROM numbers WHERE status = 'sold' AND purchase_time < ? AND otp_sent = FALSE", (expired_timestamp,))
    expired_numbers = c.fetchall()
    
    for number in expired_numbers:
        user = get_user(number['buyer_id'])
        user['balance'] += number['price']
        save_user(user)
        
        # Update number status to available and clear buyer ID, and commit the changes
        c.execute("UPDATE numbers SET status = 'available', buyer_id = NULL, purchase_time = NULL WHERE number_id = ?", (number['number_id'],))
        conn.commit()  # <-- This is the missing commit
        
        try:
            await context.bot.send_message(number['buyer_id'], f"⚠️ **Order Expired**\n\nThe OTP for your number (`{number['number']}`) was not provided in time. Your balance of `₹{number['price']:.2f}` has been refunded to your account.", parse_mode='HTML')
            await context.bot.send_message(ADMIN_ID, f"⚠️ **Order Expired & Refunded**\n\nOrder for number `{number['number']}` has expired. User `{number['buyer_id']}` has been automatically refunded.", parse_mode='HTML')
        except TelegramError:
            # Handle cases where the bot cannot reach the user
            logger.error(f"Failed to send refund message to user {number['buyer_id']}.")
            
    conn.close()

# --- Admin: Ban/Unban Functions ---
async def ban_unban_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows the ban/unban menu."""
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("🚫 Ban User", callback_data='admin:ban_user'), InlineKeyboardButton("✅ Unban User", callback_data='admin:unban_user')],
        [InlineKeyboardButton("🔙 Back to Admin", callback_data='admin:main')]
    ]
    await query.edit_message_text("Ban/Unban Users:", reply_markup=InlineKeyboardMarkup(keyboard))

async def start_ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Begins the ban user conversation."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Please reply with the User ID to ban.")
    return BAN_USER_ID

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Bans a user by ID."""
    try:
        user_id_to_ban = int(update.message.text)
        
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        c.execute("SELECT id FROM users WHERE id = ?", (user_id_to_ban,))
        if c.fetchone() is None:
            c.execute("INSERT INTO users (id) VALUES (?)", (user_id_to_ban,))
        
        c.execute("UPDATE users SET is_banned = TRUE WHERE id = ?", (user_id_to_ban,))
        conn.commit()
        conn.close()
        
        await update.message.reply_text(f"User {user_id_to_ban} has been banned.")
    except ValueError:
        await update.message.reply_text("Invalid User ID. Please enter a number.")
    return ConversationHandler.END

async def start_unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Begins the unban user conversation."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Please reply with the User ID to unban.")
    return UNBAN_USER_ID

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Unbans a user by ID."""
    try:
        user_id_to_unban = int(update.message.text)
        
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        c.execute("SELECT id FROM users WHERE id = ?", (user_id_to_unban,))
        if c.fetchone() is None:
            await update.message.reply_text(f"User {user_id_to_unban} does not exist in the database.")
            conn.close()
            return ConversationHandler.END
            
        c.execute("UPDATE users SET is_banned = FALSE WHERE id = ?", (user_id_to_unban,))
        conn.commit()
        conn.close()
        
        await update.message.reply_text(f"User {user_id_to_unban} has been unbanned.")
    except ValueError:
        await update.message.reply_text("Invalid User ID. Please enter a number.")
    return ConversationHandler.END
# --- Admin: Manage Channels Functions ---
async def manage_channels_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows the manage channels menu with current channels listed."""
    query = update.callback_query
    await query.answer()
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM channels")
    channels = [dict(row) for row in c.fetchall()]
    conn.close()

    text = "Force Join Channels:\n\n"
    if channels:
        for channel in channels:
            text += f"Title: {channel['title']}\nID: `{channel['id']}`\nLink: {channel['invite_link']}\n\n"
    else:
        text += "No channels configured."

    keyboard = [
        [InlineKeyboardButton("➕ Add Channel", callback_data='admin:add_channel')],
        [InlineKeyboardButton("➖ Remove Channel", callback_data='admin:remove_channel_menu')],
        [InlineKeyboardButton("🔙 Back to Admin", callback_data='admin:main')]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def start_add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the add channel conversation."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Please reply with the Channel ID (e.g., -100123456789). The bot must be an admin in the channel to fetch the invite link automatically.")
    return ADD_CHANNEL_ID

async def get_channel_id_and_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gets the channel ID and saves the channel with the automatically fetched invite link."""
    try:
        channel_id = int(update.message.text)
        
        # Check if bot is an admin and fetch invite link
        chat = await context.bot.get_chat(channel_id)
        if chat.type not in ['channel', 'supergroup']:
            await update.message.reply_text("The provided ID does not belong to a channel or supergroup.")
            return ADD_CHANNEL_ID
        
        member = await context.bot.get_chat_member(chat_id=channel_id, user_id=context.bot.id)
        if not member.status in ['creator', 'administrator']:
            await update.message.reply_text("I must be an admin in the channel with permission to invite users to fetch the link. Please add me and try again.")
            return ADD_CHANNEL_ID
        
        # Get the primary invite link
        invite_link = chat.invite_link
        if not invite_link:
            await update.message.reply_text("Could not fetch a primary invite link. Please ensure I have the 'create invite link' permission.")
            return ADD_CHANNEL_ID
            
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO channels (id, title, invite_link) VALUES (?, ?, ?)", (channel_id, chat.title, invite_link))
        conn.commit()
        conn.close()
        
        await update.message.reply_text(f"✨Successfully added channel '{chat.title}'. Users will now be required to join it.")
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text("Invalid Channel ID. Please enter a number.")
        return ADD_CHANNEL_ID
    except TelegramError as e:
        await update.message.reply_text(f"Failed to add channel. Error: {e.message}. Please ensure the bot is an admin in the channel and the ID is correct.")
        return ADD_CHANNEL_ID

async def remove_channel_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays a list of channels with buttons to remove them."""
    query = update.callback_query
    await query.answer()
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM channels")
    channels = [dict(row) for row in c.fetchall()]
    conn.close()

    if not channels:
        await query.edit_message_text("No channels to remove.")
        return

    keyboard = [[InlineKeyboardButton(f"Remove {channel['title']}", callback_data=f"admin:remove_channel:{channel['id']}")] for channel in channels]
    keyboard.append([InlineKeyboardButton("🔙 Back to Edit/Remove Menu", callback_data='admin:edit_remove_number_menu')])
    
    await query.edit_message_text("Select a channel to remove:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def remove_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Removes a channel based on the button press."""
    query = update.callback_query
    await query.answer()
    channel_id = int(query.data.split(':')[2])
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
    conn.commit()
    conn.close()
    await query.edit_message_text("Channel removed successfully.")
    await manage_channels_menu(update, context)

# --- Admin: Manage Numbers Functions ---

async def edit_remove_number_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows a menu for editing and removing numbers."""
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("✏️ Edit Number", callback_data='admin:edit_number_menu')],
        [InlineKeyboardButton("➖ Remove Number", callback_data='admin:remove_number_menu')],
        [InlineKeyboardButton("🔙 Back to Admin", callback_data='admin:main')]
    ]
    await query.edit_message_text("Edit/Remove Numbers:", reply_markup=InlineKeyboardMarkup(keyboard))

async def start_edit_number_conv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Displays a list of numbers to edit and starts the conversation."""
    query = update.callback_query
    await query.answer()
    
    available_numbers = get_available_numbers()
    if not available_numbers:
        await query.edit_message_text("No numbers are available to edit.")
        return ConversationHandler.END

    text = "Select a number to edit:\n\n"
    keyboard = []
    for num in available_numbers:
        text += f"ID: `{num['number_id']}`\nNumber: {num['number']}\nPrice: ${num['price']}\n\n"
        keyboard.append([InlineKeyboardButton(f"Edit {num['number']}", callback_data=f"edit_number:{num['number_id']}")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    # The conversation will be started by the CallbackQueryHandler.
    return EDIT_NUMBER_ID

async def select_edit_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the number ID and asks for the field to edit."""
    query = update.callback_query
    await query.answer()
    number_id = query.data.split(':')[1]
    context.user_data['number_to_edit'] = number_id
    
    keyboard = [
        [InlineKeyboardButton("Category", callback_data="field:category"), InlineKeyboardButton("Number", callback_data="field:number")],
        [InlineKeyboardButton("Price", callback_data="field:price"), InlineKeyboardButton("Country", callback_data="field:country")],
        [InlineKeyboardButton("Details", callback_data="field:details")]
    ]
    
    await query.edit_message_text("Which field do you want to edit?", reply_markup=InlineKeyboardMarkup(keyboard))
    return EDIT_NUMBER_FIELD

async def select_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the field and asks for the new value."""
    query = update.callback_query
    await query.answer()
    field = query.data.split(':')[1]
    context.user_data['edit_field'] = field
    
    await query.edit_message_text(f"Please enter the new value for '{field}':")
    return EDIT_NUMBER_VALUE

async def save_edited_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Saves the new value to the database and ends the conversation."""
    new_value = update.message.text
    number_id = context.user_data['number_to_edit']
    field_to_edit = context.user_data['edit_field']
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(f"UPDATE numbers SET {field_to_edit} = ? WHERE number_id = ?", (new_value, number_id))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(f"Successfully updated '{field_to_edit}' for number `{number_id}`.")
    return ConversationHandler.END


async def remove_number_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays a list of numbers to remove."""
    query = update.callback_query
    await query.answer()
    all_numbers = get_available_numbers()

    if not all_numbers:
        await query.edit_message_text("No numbers to remove.")
        return

    keyboard = [[InlineKeyboardButton(f"Remove {num['number']}", callback_data=f"admin:remove_number:{num['number_id']}")] for num in all_numbers]
    keyboard.append([InlineKeyboardButton("🔙 Back to Edit/Remove Menu", callback_data='admin:edit_remove_number_menu')])
    
    await query.edit_message_text("Select a number to remove:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def remove_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Removes a number by ID."""
    query = update.callback_query
    await query.answer()
    number_id = query.data.split(':')[2]

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM numbers WHERE number_id = ?", (number_id,))
    conn.commit()
    conn.close()

    await query.edit_message_text(f"Number with ID `{number_id}` has been removed.", parse_mode='HTML')
    await edit_remove_number_menu(update, context)

async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the current conversation."""
    user_id = update.effective_user.id
    
    # Check if the user is in a conversation
    if context.user_data:
        # Clear all user data related to the conversation
        context.user_data.clear()
        
        # Send a confirmation message
        await update.message.reply_text("The current process has been cancelled.")
        
        # Check if the user is an admin to return them to the admin panel
        if is_admin(user_id):
            await admin_panel_handler(update, context)
            return ConversationHandler.END
        else:
            await show_main_menu(update, context)
            return ConversationHandler.END
    else:
        await update.message.reply_text("You are not in an active conversation.")
        return ConversationHandler.END
# --- Admin: Manage Balance Functions ---
async def manage_balance_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows the manage balance menu."""
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("➕ Add Balance", callback_data='admin:add_balance'), InlineKeyboardButton("➖ Remove Balance", callback_data='admin:remove_balance')],
        [InlineKeyboardButton("🔙 Back to Admin", callback_data='admin:main')]
    ]
    await query.edit_message_text("Manage User Balance:", reply_markup=InlineKeyboardMarkup(keyboard))

async def start_add_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Begins adding balance to a user."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Please reply with the User ID to add balance to.")
    return ADD_BALANCE_USER_ID

async def get_add_balance_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gets the user ID and asks for the amount."""
    try:
        user_id = int(update.message.text)
        user = get_user(user_id)
        context.user_data['target_user_id'] = user_id
        await update.message.reply_text(f"User found: {user_id}. Current balance: ₹{user['balance']:.2f}. Please enter the amount to add:")
        return ADD_BALANCE_AMOUNT
    except ValueError:
        await update.message.reply_text("Invalid User ID. Please enter a number.")
        return ADD_BALANCE_USER_ID

async def add_balance_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Adds the balance to the user."""
    try:
        amount = float(update.message.text)
        user_id = context.user_data.get('target_user_id')
        user = get_user(user_id)
        user['balance'] += amount
        save_user(user)
        await update.message.reply_text(f"Successfully added ₹{amount:.2f} to user {user_id}. New balance: ₹{user['balance']:.2f}.")
        return ConversationHandler.END
    except (ValueError, TypeError):
        await update.message.reply_text("Invalid amount. Please enter a number.")
        return ADD_BALANCE_AMOUNT

async def start_remove_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Begins removing balance from a user."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Please reply with the User ID to remove balance from.")
    return REMOVE_BALANCE_USER_ID

async def get_remove_balance_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gets the user ID and asks for the amount to remove."""
    try:
        user_id = int(update.message.text)
        user = get_user(user_id)
        context.user_data['target_user_id'] = user_id
        await update.message.reply_text(f"User found: {user_id}. Current balance: ${user['balance']:.2f}. Please enter the amount to remove:")
        return REMOVE_BALANCE_AMOUNT
    except ValueError:
        await update.message.reply_text("Invalid User ID. Please enter a number.")
        return REMOVE_BALANCE_USER_ID

async def remove_balance_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Removes the balance from the user."""
    try:
        amount = float(update.message.text)
        user_id = context.user_data.get('target_user_id')
        user = get_user(user_id)
        user['balance'] -= amount
        save_user(user)
        await update.message.reply_text(f"Successfully removed ₹{amount:.2f} from user {user_id}. New balance: ₹{user['balance']:.2f}.")
        return ConversationHandler.END
    except (ValueError, TypeError):
        await update.message.reply_text("Invalid amount. Please enter a number.")
        return REMOVE_BALANCE_AMOUNT

# --- Admin: Settings Functions ---
async def show_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows the bot settings menu."""
    query = update.callback_query
    await query.answer()
    maintenance_mode = get_setting('maintenance_mode')
    bonus_value = get_setting('bonus_value')
    keyboard = [
        [InlineKeyboardButton(f"Toggle Maintenance Mode ({'ON' if maintenance_mode else 'OFF'})", callback_data=f"admin:settings:toggle_maintenance")],
        [InlineKeyboardButton(f"Set Bonus ({bonus_value})", callback_data="admin:settings:set_bonus")],
        [InlineKeyboardButton("🔙 Back to Admin", callback_data='admin:main')]
    ]
    await query.edit_message_text("Bot Settings:", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles settings button clicks."""
    query = update.callback_query
    await query.answer()

    data = query.data.split(':')
    if len(data) < 3:
        # This is the main 'Settings' button, show the menu
        await show_settings_menu(update, context)
        return ConversationHandler.END

    action = data[2]

    if action == 'toggle_maintenance':
        current_mode = get_setting('maintenance_mode')
        set_setting('maintenance_mode', not current_mode)
        await query.edit_message_text(f"Maintenance mode is now {'ON' if not current_mode else 'OFF'}.")
        await show_settings_menu(update, context)
    return ConversationHandler.END

async def start_set_bonus_conv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the bonus setting conversation."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Please reply with the new bonus value (e.g., 0.25 for 25%).")
    return SET_BONUS_VALUE

async def set_bonus_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Sets the new bonus value."""
    try:
        bonus = float(update.message.text)
        if 0.1 <= bonus <= 0.32:
            set_setting('bonus_value', bonus)
            await update.message.reply_text(f"Bonus value has been set to {bonus}.")
        else:
            await update.message.reply_text("Invalid bonus value. Please enter a number between 0.1 and 0.32.")
    except ValueError:
        await update.message.reply_text("Invalid input. Please enter a number.")
    return ConversationHandler.END

# --- Message and Conversation Handlers ---

async def handle_deposit_utr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the UTR and screenshot submission."""
    user_id = update.effective_user.id
    if update.message.photo and update.message.caption:
        utr = update.message.caption
        photo_file_id = update.message.photo[-1].file_id
        
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        deposit_amount = context.user_data.get('deposit_amount', 0)
        c.execute("INSERT INTO deposits (user_id, utr, photo_id, status, timestamp, amount) VALUES (?, ?, ?, ?, ?, ?)",
                  (user_id, utr, photo_file_id, 'pending', time.time(), deposit_amount))
        deposit_id = c.lastrowid
        conn.commit()
        conn.close()

        admin_keyboard = [
            [InlineKeyboardButton("✅ Accept", callback_data=f"admin:deposit:accept:{deposit_id}"),
             InlineKeyboardButton("❌ Decline", callback_data=f"admin:deposit:decline:{deposit_id}")]
        ]
        
        await update.message.reply_text("Your deposit information has been sent for admin review. You will be notified shortly.")
        await context.bot.send_chat_action(chat_id=ADMIN_ID, action=ChatAction.TYPING)
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=photo_file_id,
            caption=f"New Deposit Pending\n\nAmount :{deposit_amount:.2f}\nUser ID: `{user_id}`\nUTR: `{utr}`",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(admin_keyboard)
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text("Please send a single message with both the UTR in the caption and a payment screenshot.")
        return SET_DEPOSIT_UTR

async def start_add_number_conv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the add number conversation."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Please enter the number category (e.g., WhatsApp, Telegram):")
    return ADD_NUMBER_CATEGORY

async def add_number_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the first step of adding a new number."""
    context.user_data['category'] = update.message.text
    await update.message.reply_text("Enter the number:")
    return ADD_NUMBER_NUMBER
    
async def add_number_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the number entry."""
    context.user_data['number'] = update.message.text
    await update.message.reply_text("Enter the price (e.g., 5.00):")
    return ADD_NUMBER_PRICE
        
async def add_number_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the price entry."""
    try:
        price = float(update.message.text)
        context.user_data['price'] = price
        await update.message.reply_text("Enter the country:")
        return ADD_NUMBER_COUNTRY
    except ValueError:
        await update.message.reply_text("Invalid price. Please enter a number.")
        return ADD_NUMBER_PRICE
        
async def add_number_country(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the country entry."""
    context.user_data['country'] = update.message.text
    await update.message.reply_text("Enter any additional details:")
    return ADD_NUMBER_DETAILS
    
async def add_number_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the details entry and saves the number."""
    details = update.message.text
    user_data = context.user_data
    number_id = generate_random_code(12)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO numbers (number_id, category, number, price, country, details, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (number_id, user_data['category'], user_data['number'], user_data['price'], user_data['country'], details, 'available'))
    conn.commit()
    conn.close()
    await update.message.reply_text("Number added successfully.")
    return ConversationHandler.END

async def start_create_coupon_conv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the create coupon conversation."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Please enter the value of the coupon (e.g., 5.00).")
    return CREATE_COUPON_VALUE

async def create_coupon_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the coupon count entry."""
    try:
        count = int(update.message.text)
        if count <= 0: raise ValueError
        context.user_data['coupon_count'] = count
        await update.message.reply_text("Enter the value for each coupon:")
        return CREATE_COUPON_VALUE
    except ValueError:
        await update.message.reply_text("Invalid number. Please enter a valid number of coupons.")
        return CREATE_COUPON_COUNT

async def start_deposit_utr_conv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the deposit UTR conversation."""
    query = update.callback_query
    await query.answer()
    await update.callback_query.message.reply_text("Please reply to this message with your UTR and a screenshot of the payment.")
    return SET_DEPOSIT_UTR

async def ask_for_button_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Saves the broadcast content and asks if a button should be added."""
    context.user_data['broadcast_content'] = update.message
    keyboard = [[InlineKeyboardButton("Yes", callback_data="add_button_yes")], [InlineKeyboardButton("No", callback_data="add_button_no")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Do you want to add a button to this broadcast?", reply_markup=reply_markup)
    return BROADCAST_MEDIA

async def handle_button_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the Yes/No response for adding a button."""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'add_button_yes':
        await query.edit_message_text("Please send the text for the button.")
        return ASK_FOR_BUTTON_TEXT
    else: # 'add_button_no'
        await query.edit_message_text("Okay, sending the broadcast without a button.")
        await send_broadcast_message(context)
        await context.bot.send_message(update.effective_user.id, "Broadcast to all users complete.")
        return ConversationHandler.END

async def get_button_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gets the button text and asks for the URL."""
    context.user_data['button_text'] = update.message.text
    await update.message.reply_text("Great. Now, please send the URL for the button.")
    return ASK_FOR_BUTTON_URL

async def get_button_url_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gets the button URL, constructs the button, and sends the broadcast."""
    button_url = update.message.text
    button_text = context.user_data['button_text']
    
    keyboard = [[InlineKeyboardButton(button_text, url=button_url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text("Excellent. Sending the broadcast with the button now.")
    await send_broadcast_message(context, reply_markup=reply_markup)
    await context.bot.send_message(update.effective_user.id, "Broadcast to all users complete.")
    return ConversationHandler.END

async def send_broadcast_message(context: ContextTypes.DEFAULT_TYPE, reply_markup: InlineKeyboardMarkup = None):
    """Sends the broadcast message to all users, with an optional button."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id FROM users")
    users = c.fetchall()
    conn.close()
    
    message = context.user_data['broadcast_content']
    
    for user in users:
        try:
            if message.text:
                await context.bot.send_message(user[0], message.text, reply_markup=reply_markup, parse_mode='HTML')
            elif message.photo:
                await context.bot.send_photo(user[0], message.photo[-1].file_id, caption=message.caption, reply_markup=reply_markup, parse_mode='HTML')
            elif message.video:
                await context.bot.send_video(user[0], message.video.file_id, caption=message.caption, reply_markup=reply_markup, parse_mode='HTML')
            time.sleep(0.1)
        except TelegramError:
            continue

async def start_broadcast_conv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the broadcast conversation."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("What type of message would you like to broadcast?\n\nSend a TEXT message, or send a PHOTO/VIDEO with your caption. (You can add a button later.)")
    return BROADCAST_MESSAGE


async def create_coupon_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the coupon value entry and asks for the usage limit."""
    try:
        value = float(update.message.text)
        if value <= 0:
            raise ValueError
        context.user_data['coupon_value'] = value
        await update.message.reply_text("Enter the total number of times this coupon can be claimed:")
        return CREATE_COUPON_LIMIT
    except ValueError:
        await update.message.reply_text("Invalid value. Please enter a valid number.")
        return CREATE_COUPON_VALUE

async def create_coupon_limit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the usage limit and creates the single coupon."""
    try:
        usage_limit = int(update.message.text)
        if usage_limit <= 0:
            raise ValueError

        coupon_value = context.user_data['coupon_value']
        code = generate_random_code(10)
        
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT INTO coupons (code, value, usage_limit) VALUES (?, ?, ?)", (code, coupon_value, usage_limit))
        conn.commit()
        conn.close()

        admin_message = f"✅ Coupon created!\n\nCode: <code>{code}</code>\nValue: ₹{coupon_value:.2f}\nUsage Limit: {usage_limit}"
        await update.message.reply_text(admin_message, parse_mode='HTML')
        
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("Invalid usage limit. Please enter a whole number greater than 0.")
        return CREATE_COUPON_LIMIT


async def start_reply_otp_conv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the OTP reply conversation."""
    query = update.callback_query
    await query.answer()
    buyer_id, number_id = query.data.split(':')[2], query.data.split(':')[3]
    context.user_data['buyer_id'] = buyer_id
    context.user_data['number_id'] = number_id
    await query.edit_message_text("Please reply to this message with the OTP to send to the user.")
    return REPLY_OTP_TO_USER

async def start_reject_deposit_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the conversation to get the reason for a rejected deposit."""
    query = update.callback_query
    await query.answer()
    
    # Store the deposit ID from the callback data
    deposit_id = int(query.data.split(':')[3])
    context.user_data['deposit_id'] = deposit_id
    
    # Send a NEW message instead of editing the old one
    await context.bot.send_message(query.message.chat_id, "❌ Deposit decline process initiated. Please reply to this message with the reason.")
    
    return REJECT_DEPOSIT_REASON
# --- Main Function to Run the Bot ---
def main():
    """Starts the bot using long polling."""
    setup_database()
    application = ApplicationBuilder().token(TOKEN).build()

    # --- Conversation Handlers (Multi-Step Processes) ---
    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_deposit, pattern=r'^deposit$')],
        states={
            GET_DEPOSIT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_deposit_amount)],
            SET_DEPOSIT_UTR: [
                CallbackQueryHandler(start_deposit_utr_conv, pattern=r'^user:deposit:sent$'),
                MessageHandler(filters.PHOTO & filters.CAPTION, handle_deposit_utr)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel_handler)],
    ))

    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(start_claim_coupon, pattern=r'^claim_bonus$')],
        states={CLAIM_COUPON: [MessageHandler(filters.TEXT & ~filters.COMMAND, claim_coupon)]},
        fallbacks=[CommandHandler('cancel', cancel_handler)],
    ))

    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(start_add_number_conv, pattern=r'^admin:add_number$')],
        states={
            ADD_NUMBER_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_number_category)],
            ADD_NUMBER_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_number_number)],
            ADD_NUMBER_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_number_price)],
            ADD_NUMBER_COUNTRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_number_country)],
            ADD_NUMBER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_number_details)],
        },
        fallbacks=[CommandHandler('cancel', cancel_handler)],
    ))

    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(start_reply_otp_conv, pattern=r'^admin:reply_otp')],
        states={REPLY_OTP_TO_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, reply_otp_to_user)]},
        fallbacks=[CommandHandler('cancel', cancel_handler)],
    ))

    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(start_broadcast_conv, pattern=r'^admin:broadcast$')],
        states={
            BROADCAST_MESSAGE: [MessageHandler(filters.ALL & ~filters.COMMAND, ask_for_button_confirmation)],
            BROADCAST_MEDIA: [CallbackQueryHandler(handle_button_confirmation, pattern=r'add_button_(yes|no)')],
            ASK_FOR_BUTTON_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_button_text)],
            ASK_FOR_BUTTON_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_button_url_and_send)],
        },
        fallbacks=[CommandHandler('cancel', cancel_handler)],
    ))

    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(start_add_channel, pattern=r'^admin:add_channel$')],
        states={
            ADD_CHANNEL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_channel_id_and_save)],
        },
        fallbacks=[CommandHandler('cancel', cancel_handler)],
    ))

    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(start_set_bonus_conv, pattern=r'^admin:settings:set_bonus$')],
        states={SET_BONUS_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_bonus_value)]},
        fallbacks=[CommandHandler('cancel', cancel_handler)],
    ))

    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(start_edit_number_conv, pattern=r'^admin:edit_number_menu$')],
        states={
            EDIT_NUMBER_ID: [CallbackQueryHandler(select_edit_number, pattern=r'^edit_number:')],
            EDIT_NUMBER_FIELD: [CallbackQueryHandler(select_edit_field, pattern=r'^field:')],
            EDIT_NUMBER_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_edited_value)],
        },
        fallbacks=[CommandHandler('cancel', cancel_handler)],
    ))

    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(start_add_balance, pattern=r'^admin:add_balance$')],
        states={
            ADD_BALANCE_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_add_balance_user_id)],
            ADD_BALANCE_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_balance_amount)]
        },
        fallbacks=[CommandHandler('cancel', cancel_handler)],
    ))

    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(start_remove_balance, pattern=r'^admin:remove_balance$')],
        states={
            REMOVE_BALANCE_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_remove_balance_user_id)],
            REMOVE_BALANCE_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, remove_balance_amount)]
        },
        fallbacks=[CommandHandler('cancel', cancel_handler)],
    ))

    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(start_ban_user, pattern=r'^admin:ban_user$')],
        states={BAN_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, ban_user)]},
        fallbacks=[CommandHandler('cancel', cancel_handler)],
    ))

    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(start_unban_user, pattern=r'^admin:unban_user$')],
        states={UNBAN_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, unban_user)]},
        fallbacks=[CommandHandler('cancel', cancel_handler)],
    ))

    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(start_add_admin_conv, pattern=r'^admin:add_admin$')],
        states={ADD_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_admin)]},
        fallbacks=[CommandHandler('cancel', cancel_handler)],
    ))

    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(start_remove_admin_conv, pattern=r'^admin:remove_admin$')],
        states={REMOVE_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, remove_admin)]},
        fallbacks=[CommandHandler('cancel', cancel_handler)],
    ))

    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(start_reject_deposit_reason, pattern=r'^admin:deposit:decline')],
        states={REJECT_DEPOSIT_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, reject_deposit_reason)]},
        fallbacks=[CommandHandler('cancel', cancel_handler)],
    ))

    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(start_create_coupon_conv, pattern=r'^admin:create_coupon$')],
        states={
            CREATE_COUPON_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_coupon_value)],
            CREATE_COUPON_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_coupon_limit)],
        },
        fallbacks=[CommandHandler('cancel', cancel_handler)],
    ))


    # --- General Handlers (Non-Conversational) ---
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("admin", admin_panel_handler))
    application.add_handler(CallbackQueryHandler(handle_account, pattern=r'^account$'))
    application.add_handler(CallbackQueryHandler(handle_buy_number_list, pattern=r'^buy_number:\d+$'))
    application.add_handler(CallbackQueryHandler(handle_buy_number_purchase, pattern=r'^buy:'))
    application.add_handler(CallbackQueryHandler(handle_confirm_purchase, pattern=r'^confirm:'))
    application.add_handler(CallbackQueryHandler(show_main_menu, pattern=r'^main_menu$'))
    application.add_handler(CallbackQueryHandler(handle_admin_panel, pattern=r'^admin:deposit:accept:'))
    application.add_handler(CallbackQueryHandler(remove_channel, pattern=r'^admin:remove_channel:'))
    application.add_handler(CallbackQueryHandler(remove_number, pattern=r'^admin:remove_number:'))
    application.add_handler(CallbackQueryHandler(handle_settings, pattern=r'^admin:settings:'))
    application.add_handler(CallbackQueryHandler(handle_admin_panel, pattern=r'^admin:'))
    application.add_handler(CommandHandler("cancel", cancel_handler))
    #jobs........
    application.job_queue.run_repeating(check_for_expired_orders, interval=10, first=10)


    logger.info("Starting bot...")
    application.run_polling()
    logger.info("Bot stopped.")

if __name__ == '__main__':
    main()
