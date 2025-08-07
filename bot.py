import logging
import threading
import sqlite3
import pickle
import os
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackContext
from telegram.constants import ParseMode

# --- Database Setup ---
DB_FILE = "jobs.db"

def init_db():
    """Initialize the SQLite database."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            chat_id INTEGER PRIMARY KEY,
            job_data BLOB
        )
    ''')
    conn.commit()
    conn.close()
    logger.info("Database initialized.")

def save_job_to_db(chat_id, job_data):
    """Save a job's data to the database."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Serialize the job_data dictionary using pickle
    serialized_data = pickle.dumps(job_data)
    # Use INSERT OR REPLACE to handle both new and existing jobs
    cursor.execute("INSERT OR REPLACE INTO jobs (chat_id, job_data) VALUES (?, ?)", (chat_id, serialized_data))
    conn.commit()
    conn.close()
    logger.info(f"Job for chat_id {chat_id} saved to database.")

def load_job_from_db(chat_id):
    """Load a single job's data from the database."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT job_data FROM jobs WHERE chat_id = ?", (chat_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        # Deserialize the data using pickle
        return pickle.loads(row[0])
    return None

def load_all_jobs_from_db():
    """Load all jobs from the database."""
    if not os.path.exists(DB_FILE):
        return []
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id, job_data FROM jobs")
    rows = cursor.fetchall()
    conn.close()
    # Deserialize each job's data
    return [(row[0], pickle.loads(row[1])) for row in rows]

def delete_job_from_db(chat_id):
    """Delete a job from the database."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM jobs WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()
    logger.info(f"Job for chat_id {chat_id} deleted from database.")

# --- Flask App Setup ---
app = Flask(__name__)
@app.route('/')
def index():
    return "I'm alive!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# --- Telegram Bot Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

def remove_job_if_exists(name: str, context: CallbackContext) -> bool:
    current_jobs = context.job_queue.get_jobs_by_name(name)
    if not current_jobs:
        return False
    for job in current_jobs:
        job.schedule_removal()
    return True

async def send_recurring_message(context: CallbackContext) -> None:
    job = context.job
    job_data = job.data
    media_type = job_data.get('media_type')
    
    try:
        if media_type == 'text':
            await context.bot.send_message(job.chat_id, text=job_data['text'])
        # ... (add other media types as before)
        elif media_type == 'photo':
            await context.bot.send_photo(job.chat_id, photo=job_data['file_id'], caption=job_data.get('caption'))
        elif media_type == 'video':
            await context.bot.send_video(job.chat_id, video=job_data['file_id'], caption=job_data.get('caption'))
        elif media_type == 'document':
            await context.bot.send_document(job.chat_id, document=job_data['file_id'], caption=job_data.get('caption'))
        elif media_type == 'audio':
            await context.bot.send_audio(job.chat_id, audio=job_data['file_id'], caption=job_data.get('caption'))
        elif media_type == 'sticker':
             await context.bot.send_sticker(job.chat_id, sticker=job_data['file_id'])
    except Exception as e:
        logger.error(f"Error sending scheduled message to chat {job.chat_id}: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hi! I am a persistent recurring message bot.\n\n"
        "My schedules are now saved and will survive restarts.\n\n"
        "Use /set, /stop, and /status as before."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Here's how to use me:\n\n"
        "▶️ *To set a schedule:*\n"
        "1. Send any message (text, photo, etc.).\n"
        "2. Reply to it with `/set <minutes>`.\n\n"
        "▶️ *To check the schedule:*\n"
        "   Use `/status`.\n\n"
        "▶️ *To stop the schedule:*\n"
        "   Use `/stop`.",
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def set_timer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_message.chat_id
    replied_message = update.message.reply_to_message

    if not replied_message:
        await update.message.reply_text("Error: You must reply to a message to schedule it.")
        return

    try:
        minutes = int(context.args[0])
        if not 1 <= minutes <= 60:
            await update.effective_message.reply_text("Error: Please provide a time between 1 and 60 minutes.")
            return

        job_data = {
            'media_type': None, 'interval_minutes': minutes, 'text': None, 
            'caption': None, 'file_id': None
        }
        # ... (logic to populate job_data based on replied_message)
        if replied_message.text:
            job_data.update({'media_type': 'text', 'text': replied_message.text})
        elif replied_message.photo:
            job_data.update({'media_type': 'photo', 'file_id': replied_message.photo[-1].file_id, 'caption': replied_message.caption})
        elif replied_message.video:
            job_data.update({'media_type': 'video', 'file_id': replied_message.video.file_id, 'caption': replied_message.caption})
        elif replied_message.document:
            job_data.update({'media_type': 'document', 'file_id': replied_message.document.file_id, 'caption': replied_message.caption})
        elif replied_message.audio:
            job_data.update({'media_type': 'audio', 'file_id': replied_message.audio.file_id, 'caption': replied_message.caption})
        elif replied_message.sticker:
            job_data.update({'media_type': 'sticker', 'file_id': replied_message.sticker.file_id})
        else:
            await update.message.reply_text("Sorry, that media type is not supported.")
            return

        # Save to DB first
        save_job_to_db(chat_id, job_data)

        # Then schedule in memory
        interval_seconds = minutes * 60
        remove_job_if_exists(str(chat_id), context)
        context.job_queue.run_repeating(
            send_recurring_message,
            interval=interval_seconds,
            first=interval_seconds,
            chat_id=chat_id,
            name=str(chat_id),
            data=job_data
        )

        await update.effective_message.reply_text(f"✅ Message set successfully! It will repeat every {minutes} minute(s).")

    except (IndexError, ValueError):
        await update.effective_message.reply_text("Usage: Reply to a message with `/set <minutes>`")

async def stop_timer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id
    
    # Remove from memory and DB
    remove_job_if_exists(str(chat_id), context)
    delete_job_from_db(chat_id)
    
    await update.message.reply_text("Timer successfully stopped! The schedule has been cleared.")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    
    # Check the database directly for the most reliable status
    job_data = load_job_from_db(chat_id)

    if not job_data:
        await update.message.reply_text("There is no recurring message scheduled for this chat.")
        return

    # Check in-memory jobs to get the next run time
    current_jobs = context.job_queue.get_jobs_by_name(str(chat_id))
    next_run_display = "Pending restart..."
    if current_jobs and current_jobs[0].next_t:
        next_run_display = current_jobs[0].next_t.strftime('%Y-%m-%d %H:%M:%S UTC')

    interval = job_data.get('interval_minutes', 'N/A')
    media_type = job_data.get('media_type', 'Unknown').capitalize()
    
    content_desc = "Not available"
    if media_type.lower() == 'text':
        text = job_data.get('text', '')
        content_desc = f"\"{text[:70]}...\"" if len(text) > 70 else f"\"{text}\""
    else:
        content_desc = f"A {media_type.lower()} message"
        caption = job_data.get('caption')
        if caption:
            content_desc += f" with caption: \"{caption}\""
    
    status_message = (
        f"ℹ️ **Current Schedule Status**\n\n"
        f"**Frequency:** Every {interval} minute(s)\n"
        f"**Content Type:** {media_type}\n"
        f"**Content Preview:** {content_desc}\n"
        f"**Next Send Time:** {next_run_display}"
    )

    await update.message.reply_text(status_message, parse_mode=ParseMode.MARKDOWN)

async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    new_members = update.message.new_chat_members
    for member in new_members:
        await update.message.reply_text(f"Welcome, {member.first_name}!")

def main() -> None:
    """Run the bot, the web server, and load jobs from the database."""
    # Initialize the database
    init_db()

    # Start Flask server
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    logger.info("Uptime server started.")

    # --- Telegram Bot Setup ---
    BOT_TOKEN = "1233674761:AAEBZHtON8aNiahNYslG4Hi9IqQFIaQUFUE"
    application = Application.builder().token(BOT_TOKEN).build()

    # Load and reschedule jobs from the database on startup
    jobs_to_load = load_all_jobs_from_db()
    for chat_id, job_data in jobs_to_load:
        interval_seconds = job_data.get('interval_minutes', 1) * 60
        application.job_queue.run_repeating(
            send_recurring_message,
            interval=interval_seconds,
            first=10,  # Send 10s after restart to avoid spam
            chat_id=chat_id,
            name=str(chat_id),
            data=job_data
        )
    logger.info(f"Loaded and rescheduled {len(jobs_to_load)} jobs from the database.")

    # Register command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("set", set_timer))
    application.add_handler(CommandHandler("stop", stop_timer))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome))

    # Start the Bot
    logger.info("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
        
