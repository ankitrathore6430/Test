import logging
import threading
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackContext
from telegram.constants import ParseMode

# --- Flask App Setup ---
# This part runs a simple web server to keep the bot alive on hosting services like Render.
app = Flask(__name__)

@app.route('/')
def index():
    return "I'm alive!"

def run_flask():
    # The host must be '0.0.0.0' to be reachable by external services.
    # The port can be any available port, e.g., 8080.
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
        "Hi! I am a recurring message bot.\n\n"
        "To set a recurring message, reply to any message and use:\n"
        "/set <minutes>\n\n"
        "Use /status to see the current schedule.\n"
        "Use /stop to stop the recurring message.\n"
        "Use /help to see more details."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Here's how to use me:\n\n"
        "▶️ *To set a schedule:*\n"
        "1. Send any message (text, photo, video, etc.).\n"
        "2. Reply to that message with the command `/set <minutes>`.\n"
        "   (Time must be between 1 and 60 minutes).\n\n"
        "▶️ *To check the schedule:*\n"
        "   Use the command `/status`.\n\n"
        "▶️ *To stop the schedule:*\n"
        "   Use the command `/stop`.",
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def set_timer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_message.chat_id
    replied_message = update.message.reply_to_message

    if not replied_message:
        await update.message.reply_text("Error: You need to reply to a message to set it on a recurring schedule.")
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
            await update.message.reply_text("Sorry, I can only schedule text, photos, videos, documents, audio, or stickers.")
            return

        interval_seconds = minutes * 60
        job_removed = remove_job_if_exists(str(chat_id), context)
        
        context.job_queue.run_repeating(
            send_recurring_message,
            interval=interval_seconds,
            first=interval_seconds,
            chat_id=chat_id,
            name=str(chat_id),
            data=job_data
        )

        text = f"✅ Message set successfully! It will repeat every {minutes} minute(s)."
        if job_removed:
            text += "\n\n_The old schedule was replaced._"
        await update.effective_message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

    except (IndexError, ValueError):
        await update.effective_message.reply_text("Usage: Reply to a message with `/set <minutes>`")

async def stop_timer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id
    job_removed = remove_job_if_exists(str(chat_id), context)
    text = "Timer successfully stopped!" if job_removed else "You do not have an active timer."
    await update.message.reply_text(text)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    current_jobs = context.job_queue.get_jobs_by_name(str(chat_id))

    if not current_jobs:
        await update.message.reply_text("There is no recurring message scheduled for this chat.")
        return

    job = current_jobs[0]
    job_data = job.data
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
    
    next_run_utc = job.next_t.strftime('%Y-%m-%d %H:%M:%S UTC')

    status_message = (
        "ℹ️ **Current Schedule Status**\n\n"
        f"**Frequency:** Every {interval} minute(s)\n"
        f"**Content Type:** {media_type}\n"
        f"**Content Preview:** {content_desc}\n"
        f"**Next Send Time:** {next_run_utc}"
    )

    await update.message.reply_text(status_message, parse_mode=ParseMode.MARKDOWN)

async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    new_members = update.message.new_chat_members
    for member in new_members:
        welcome_message = f"Welcome to the group, {member.first_name}! We're glad to have you here."
        await update.message.reply_text(welcome_message)

def main() -> None:
    """Run the bot and the web server."""
    # Start Flask server in a new thread
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    print("Uptime server started...")

    # --- Telegram Bot Setup ---
    BOT_TOKEN = "1233674761:AAEBZHtON8aNiahNYslG4Hi9IqQFIaQUFUE"
    application = Application.builder().token(BOT_TOKEN).build()

    # Register command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("set", set_timer))
    application.add_handler(CommandHandler("stop", stop_timer))
    application.add_handler(CommandHandler("status", status_command))

    # Register handler for new members
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome))

    # Start the Bot
    print("Bot is running... Press Ctrl-C to stop.")
    application.run_polling()

if __name__ == "__main__":
    main()
        
