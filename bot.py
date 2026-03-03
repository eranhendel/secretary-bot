import os
import json
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# ─── Storage (JSON file) ───────────────────────────────────────────────────────
TASKS_FILE = "tasks.json"

def load_tasks():
    if os.path.exists(TASKS_FILE):
        with open(TASKS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_tasks(tasks):
    with open(TASKS_FILE, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)

def get_next_id(tasks):
    return max((t["id"] for t in tasks), default=0) + 1

# ─── Commands ─────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *שלום! אני המזכירה האישית שלך*\n\n"
        "הנה מה שאני יכול לעשות:\n\n"
        "➕ /add – הוסף משימה חדשה\n"
        "📋 /list – הצג את כל המשימות\n"
        "✅ /done `<מספר>` – סמן משימה כבוצעה\n"
        "🗑 /delete `<מספר>` – מחק משימה\n"
        "❓ /help – עזרה\n\n"
        "אתה יכול גם פשוט לכתוב לי משימה ואני אוסיף אותה!"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def add_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the add-task flow"""
    await update.message.reply_text(
        "📝 *מה המשימה?*\nכתוב את תיאור המשימה:",
        parse_mode="Markdown"
    )
    context.user_data["state"] = "waiting_task_text"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    text = update.message.text.strip()

    # ── Flow: waiting for task text ──
    if state == "waiting_task_text":
        context.user_data["new_task_text"] = text
        context.user_data["state"] = "waiting_reminder_time"

        keyboard = [
            [InlineKeyboardButton("⏰ בעוד שעה", callback_data="remind_1h"),
             InlineKeyboardButton("🌅 מחר בבוקר (9:00)", callback_data="remind_tomorrow")],
            [InlineKeyboardButton("📅 בעוד שבוע", callback_data="remind_week"),
             InlineKeyboardButton("✍️ הזן שעה ידנית", callback_data="remind_custom")],
            [InlineKeyboardButton("🚫 בלי תזכורת", callback_data="remind_none")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"✅ שמרתי: *{text}*\n\nמתי להזכיר לך?",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return

    # ── Flow: waiting for custom reminder time ──
    if state == "waiting_custom_time":
        try:
            reminder_time = datetime.strptime(text, "%d/%m/%Y %H:%M")
            await _save_new_task(update, context, reminder_time)
        except ValueError:
            await update.message.reply_text(
                "❌ פורמט לא תקין. אנא הזן בפורמט: `DD/MM/YYYY HH:MM`\nלדוגמה: `25/12/2025 09:00`",
                parse_mode="Markdown"
            )
        return

    # ── No state: treat as new task directly ──
    context.user_data["new_task_text"] = text
    context.user_data["state"] = "waiting_reminder_time"

    keyboard = [
        [InlineKeyboardButton("⏰ בעוד שעה", callback_data="remind_1h"),
         InlineKeyboardButton("🌅 מחר בבוקר (9:00)", callback_data="remind_tomorrow")],
        [InlineKeyboardButton("📅 בעוד שבוע", callback_data="remind_week"),
         InlineKeyboardButton("✍️ הזן שעה ידנית", callback_data="remind_custom")],
        [InlineKeyboardButton("🚫 בלי תזכורת", callback_data="remind_none")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"📌 הוספתי משימה: *{text}*\n\nמתי להזכיר לך?",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # ── Reminder time selection ──
    if data.startswith("remind_"):
        now = datetime.now()
        reminder_time = None

        if data == "remind_1h":
            reminder_time = now + timedelta(hours=1)
        elif data == "remind_tomorrow":
            reminder_time = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0)
        elif data == "remind_week":
            reminder_time = now + timedelta(weeks=1)
        elif data == "remind_none":
            reminder_time = None
        elif data == "remind_custom":
            context.user_data["state"] = "waiting_custom_time"
            await query.edit_message_text(
                "📅 הזן תאריך ושעה בפורמט:\n`DD/MM/YYYY HH:MM`\nלדוגמה: `25/12/2025 09:00`",
                parse_mode="Markdown"
            )
            return

        await _save_new_task(query, context, reminder_time)
        return

    # ── Done / Delete from list ──
    if data.startswith("done_"):
        task_id = int(data.split("_")[1])
        tasks = load_tasks()
        for t in tasks:
            if t["id"] == task_id:
                t["done"] = True
                break
        save_tasks(tasks)
        await query.edit_message_text(f"✅ משימה #{task_id} סומנה כבוצעה!")
        return

    if data.startswith("delete_"):
        task_id = int(data.split("_")[1])
        tasks = load_tasks()
        tasks = [t for t in tasks if t["id"] != task_id]
        save_tasks(tasks)
        await query.edit_message_text(f"🗑 משימה #{task_id} נמחקה.")
        return

async def _save_new_task(source, context, reminder_time):
    """Save task to JSON and schedule reminder"""
    tasks = load_tasks()
    task_text = context.user_data.get("new_task_text", "משימה ללא כותרת")
    task = {
        "id": get_next_id(tasks),
        "text": task_text,
        "done": False,
        "created": datetime.now().isoformat(),
        "reminder": reminder_time.isoformat() if reminder_time else None,
        "reminded": False
    }
    tasks.append(task)
    save_tasks(tasks)
    context.user_data["state"] = None

    msg = f"🎉 *משימה נוספה בהצלחה!*\n\n📌 {task_text}\n"
    if reminder_time:
        msg += f"⏰ תזכורת: {reminder_time.strftime('%d/%m/%Y %H:%M')}"
    else:
        msg += "🚫 ללא תזכורת"

    if hasattr(source, "edit_message_text"):
        await source.edit_message_text(msg, parse_mode="Markdown")
    else:
        await source.message.reply_text(msg, parse_mode="Markdown")

async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = load_tasks()
    pending = [t for t in tasks if not t["done"]]

    if not pending:
        await update.message.reply_text("🎉 אין משימות פתוחות! הכל בוצע.")
        return

    for t in pending:
        reminder_str = ""
        if t.get("reminder"):
            dt = datetime.fromisoformat(t["reminder"])
            reminder_str = f"\n⏰ תזכורת: {dt.strftime('%d/%m/%Y %H:%M')}"

        keyboard = [[
            InlineKeyboardButton("✅ בוצע", callback_data=f"done_{t['id']}"),
            InlineKeyboardButton("🗑 מחק", callback_data=f"delete_{t['id']}")
        ]]
        await update.message.reply_text(
            f"#{t['id']} – {t['text']}{reminder_str}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def done_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("שימוש: /done <מספר משימה>")
        return
    task_id = int(args[0])
    tasks = load_tasks()
    found = False
    for t in tasks:
        if t["id"] == task_id:
            t["done"] = True
            found = True
            break
    if found:
        save_tasks(tasks)
        await update.message.reply_text(f"✅ משימה #{task_id} סומנה כבוצעה!")
    else:
        await update.message.reply_text(f"❌ לא נמצאה משימה #{task_id}")

async def delete_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("שימוש: /delete <מספר משימה>")
        return
    task_id = int(args[0])
    tasks = load_tasks()
    new_tasks = [t for t in tasks if t["id"] != task_id]
    if len(new_tasks) < len(tasks):
        save_tasks(new_tasks)
        await update.message.reply_text(f"🗑 משימה #{task_id} נמחקה.")
    else:
        await update.message.reply_text(f"❌ לא נמצאה משימה #{task_id}")

# ─── Reminder checker (runs every minute) ────────────────────────────────────

async def check_reminders(context: ContextTypes.DEFAULT_TYPE):
    tasks = load_tasks()
    now = datetime.now()
    changed = False

    for t in tasks:
        if t.get("done") or t.get("reminded") or not t.get("reminder"):
            continue
        reminder_time = datetime.fromisoformat(t["reminder"])
        if now >= reminder_time:
            chat_id = context.job.chat_id
            keyboard = [[
                InlineKeyboardButton("✅ בוצע", callback_data=f"done_{t['id']}"),
                InlineKeyboardButton("⏰ תזכיר שוב בשעה", callback_data=f"remind_1h")
            ]]
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🔔 *תזכורת!*\n\n📌 {t['text']}",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            t["reminded"] = True
            changed = True

    if changed:
        save_tasks(tasks)

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token:
        raise ValueError("❌ חסר TELEGRAM_BOT_TOKEN בסביבה!")
    if not chat_id:
        raise ValueError("❌ חסר TELEGRAM_CHAT_ID בסביבה!")

    app = Application.builder().token(token).build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("add", add_task))
    app.add_handler(CommandHandler("list", list_tasks))
    app.add_handler(CommandHandler("done", done_cmd))
    app.add_handler(CommandHandler("delete", delete_cmd))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Reminder job — every 60 seconds
    app.job_queue.run_repeating(
        check_reminders,
        interval=60,
        first=10,
        chat_id=int(chat_id)
    )

    print("🤖 הבוט עלה! מאזין להודעות...")
    app.run_polling()

if __name__ == "__main__":
    main()
