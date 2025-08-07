import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackContext

# Enable logging to see errors and bot activity
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

def remove_job_if_exists(name: str, context: CallbackContext) -> bool:
    """Remove job with given name. Returns whether job was removed."""
    current_jobs = context.job_queue.get_jobs_by_name(name)
    if not current_jobs:
        return False
    for job in current_jobs:
        job.schedule_removal()
    return True

async def send_recurring_message(context: CallbackContext) -> None:
    """Callback function to send the message."""
    job = context.job
    try:
        await context.bot.send_message(job.chat_id, text=job.data['message'])
    except Exception as e:
        logger.error(f"Error sending message to chat {job.chat_id}: {e}")
        # Optionally, you could remove the job if sending fails repeatedly
        # job.schedule_removal()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for the /start command."""
    await update.message.reply_text(
        "Hi! I am a recurring message bot.\n\n"
        "Use /set <minutes> <message> to set a recurring message (1-60 minutes).\n"
        "Use /unset to stop the recurring message.\n"
        "Use /help to see the full list of commands."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for the /help command."""
    await update.message.reply_text(
        "Here are the available commands:\n\n"
        "/start - Start the bot\n"
        "/set <minutes> <message> - Set a recurring message. The time must be between 1 and 60 minutes.\n"
        "  Example: /set 5 This is a message every 5 minutes.\n"
        "/unset - Stop the recurring message.\n"
        "/help - Show this help message."
    )

async def set_timer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for the /set command. Adds a job to the queue."""
    chat_id = update.effective_message.chat_id
    try:
        # args[0] should contain the time for the timer in minutes
        minutes = int(context.args[0])
        if not 1 <= minutes <= 60:
            await update.effective_message.reply_text("Error: Please provide a time between 1 and 60 minutes.")
            return

        # Convert minutes to seconds for the job queue
        interval_seconds = minutes * 60

        # The message is everything after the time argument
        message = " ".join(context.args[1:])
        if not message:
            await update.effective_message.reply_text("Error: You need to provide a message to send!")
            return

        # Remove any existing job for this chat
        job_removed = remove_job_if_exists(str(chat_id), context)

        # Add the new job to the queue
        context.job_queue.run_repeating(
            send_recurring_message,
            interval=interval_seconds,
            first=0,
            chat_id=chat_id,
            name=str(chat_id),
            data={'message': message}
        )

        text = f"Success! Timer is set to repeat every {minutes} minute(s)."
        if job_removed:
            text += " The old timer was replaced."
        await update.effective_message.reply_text(text)

    except (IndexError, ValueError):
        await update.effective_message.reply_text("Usage: /set <minutes> <message>")


async def unset_timer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for the /unset command. Removes the job."""
    chat_id = update.message.chat_id
    job_removed = remove_job_if_exists(str(chat_id), context)
    text = "Timer successfully cancelled!" if job_removed else "You do not have an active timer."
    await update.message.reply_text(text)


def main() -> None:
    """Run the bot."""
    # --- IMPORTANT ---
    # This is your bot's unique token.
    BOT_TOKEN = "1233674761:AAEBZHtON8aNiahNYslG4Hi9IqQFIaQUFUE"

    # Create the Application and pass it your bot's token.
    application = Application.builder().token(BOT_TOKEN).build()

    # Register command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("set", set_timer))
    application.add_handler(CommandHandler("unset", unset_timer))

    # Start the Bot
    print("Bot is running... Press Ctrl-C to stop.")
    application.run_polling()

if __name__ == "__main__":
    main()
