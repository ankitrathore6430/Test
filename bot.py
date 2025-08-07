import logging
import threading
import sqlite3
import pickle
import os
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackContext
from telegram.constants import ParseMode

# --- Persistent Disk Setup ---
DISK_PATH = "/var/data"
DB_FILE = os.path.join(DISK_PATH, "jobs.db")

def init_db():
    """Initialize the SQLite database in the persistent disk path."""
    try:
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
        logger.info(f"Database initialized successfully at {DB_FILE}")
    except sqlite3.OperationalError as e:
        logger.critical(f"FAILED TO INITIALIZE DATABASE at {DB_FILE}: {e}")
        logger.critical("This is likely a file permissions issue on your hosting service.")

def save_job_to_db(chat_id, job_data):
    """Save a job's data to the database."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        serialized_data = pickle.dumps(job_data)
        cursor.execute("INSERT OR REPLACE INTO jobs (chat_id, job_data) VALUES (?, ?)", (chat_id, serialized_data))
        conn.commit()
        conn.close()
        logger.info(f"Job for chat_id {chat_id} saved to database.")
    except Exception as e:
        logger.error(f"Failed to save job for chat {chat_id}: {e}")

def load_job_from_db(chat_id):
    """Load a single job's data from the database."""
    if not os.path.exists(DB_FILE): return None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT job_data FROM jobs WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return pickle.loads(row[0])
    except Exception as e:
        logger.error(f"Failed to load job for chat {chat_id}: {e}")
    return None

def load_all_jobs_from_db():
    """Load all jobs from the database."""
    if not os.path.exists(DB_FILE):
        return []
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT chat_id, job_data FROM jobs")
        rows = cursor.fetchall()
        conn.close()
        return [(row[0], pickle.loads(row[1])) for row in rows]
    except Exception as e:
        logger.error(f"Failed to load all jobs from DB: {e}")
        return []

def delete_job_from_db(chat_id):
    """Delete a job from the database."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM jobs WHERE chat_id = ?", (chat_id,))
        conn.commit()
        conn.close()
        logger.info(f"Job for chat_id {chat_id} deleted from database.")
    except Exception as e:
        logger.error(f"Failed to delete job for chat {chat_id}: {e}")

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
    await context.bot.send_message(job.chat_id, text=job_data['text'])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hi! I am a persistent recurring message bot.\n\n"
        "To set a recurring message (every 1 minute), use the command:\n"
        "`/set Your message here`\n\n"
        "Use `/status` to see the current schedule.\n"
        "Use `/stop` to clear the schedule.",
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Here's how to use me:\n\n"
        "▶️ *To set a schedule (every 1 minute):*\n"
        "   Use the command `/set Your message here`\n\n"
        "▶️ *To check the schedule:*\n"
        "   Use `/status`\n\n"
        "▶️ *To stop the schedule:*\n"
        "   Use `/stop`",
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def set_timer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_message.chat_id
    try:
        message_to_set = " ".join(context.args)
        if not message_to_set:
            await update.message.reply_text("Error: You need to provide a message after the /set command.\n\nExample: `/set Hello world`")
            return

        minutes = 1
        interval_seconds = 60

        job_data = {
            'text': message_to_set,
            'interval_minutes': minutes
        }

        save_job_to_db(chat_id, job_data)

        remove_job_if_exists(str(chat_id), context)
        context.job_queue.run_repeating(
            send_recurring_message,
            interval=interval_seconds,
            first=interval_seconds,
            chat_id=chat_id,
            name=str(chat_id),
            data=job_data
        )

        await update.effective_message.reply_text(f"✅ Message set successfully! It will now repeat every minute.")

    except Exception as e:
        logger.error(f"Error in set_timer for chat {chat_id}: {e}")
        await update.effective_message.reply_text("An error occurred while setting the timer.")

async def stop_timer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for the /stop command. Removes the job from memory and the database."""
    chat_id = update.message.chat_id
    
    # Remove from live memory
    job_removed = remove_job_if_exists(str(chat_id), context)
    
    # **CRITICAL FIX:** Also remove from the persistent database
    delete_job_from_db(chat_id)
    
    # Check if a job existed in either memory or DB to give a clear confirmation
    if job_removed or load_job_from_db(chat_id) is None:
         await update.message.reply_text("Timer successfully stopped! The schedule has been cleared.")
    else:
         await update.message.reply_text("You do not have an active timer.")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    
    job_data = load_job_from_db(chat_id)

    if not job_data:
        await update.message.reply_text("There is no recurring message scheduled for this chat.")
        return

    current_jobs = context.job_queue.get_jobs_by_name(str(chat_id))
    next_run_display = "Active (will send after next restart/interval)"
    if current_jobs and current_jobs[0].next_t:
        next_run_display = current_jobs[0].next_t.strftime('%Y-%m-%d %H:%M:%S UTC')

    text = job_data.get('text', '')
    content_desc = f"\"{text[:70]}...\"" if len(text) > 70 else f"\"{text}\""
    
    status_message = (
        f"ℹ️ **Current Schedule Status**\n\n"
        f"**Frequency:** Every 1 minute\n"
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
    # --- Diagnostic check for disk permissions ---
    if os.path.isdir(DISK_PATH):
        if not os.access(DISK_PATH, os.W_OK):
            logger.critical(f"❌ CRITICAL ERROR: Disk path {DISK_PATH} is NOT WRITABLE.")
    else:
        try:
            os.makedirs(DISK_PATH)
            logger.info(f"✅ Success: Created writable disk path at {DISK_PATH}.")
        except Exception as e:
            logger.critical(f"❌ CRITICAL ERROR: Could not create disk path {DISK_PATH}. Error: {e}")
    
    init_db()

    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    logger.info("Uptime server started.")

    BOT_TOKEN = "1233674761:AAEBZHtON8aNiahNYslG4Hi9IqQFIaQUFUE"
    application = Application.builder().token(BOT_TOKEN).build()

    jobs_to_load = load_all_jobs_from_db()
    for chat_id, job_data in jobs_to_load:
        interval_seconds = 60
        application.job_queue.run_repeating(
            send_recurring_message,
            interval=interval_seconds,
            first=10,
            chat_id=chat_id,
            name=str(chat_id),
            data=job_data
        )
    logger.info(f"Loaded and rescheduled {len(jobs_to_load)} jobs from the database.")

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("set", set_timer))
    application.add_handler(CommandHandler("stop", stop_timer))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome))

    logger.info("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
        
