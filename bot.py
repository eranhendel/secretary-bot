import os
import json
import re
from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# ─── Timezone ─────────────────────────────────────────────────────────────────
ISRAEL_TZ = pytz.timezone("Asia/Jerusalem")

def now_israel():
    return datetime.now(ISRAEL_TZ)

# ─── Smart date parser ────────────────────────────────────────────────────────

MONTHS_HE = {
    "ינואר": 1, "פברואר": 2, "מרץ": 3, "מרס": 3, "אפריל": 4,
    "מאי": 5, "יוני": 6, "יולי": 7, "אוגוסט": 8,
    "ספטמבר": 9, "אוקטובר": 10, "נובמבר": 11, "דצמבר": 12,
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

def parse_time_from_text(text: str):
    """Extract HH:MM from text, return (hour, minute) or None"""
    # Match patterns like 9:30, 09:30, 9:00, ב-9, ב9
    m = re.search(r'(\d{1,2}):(\d{2})', text)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r'ב[-–]?(\d{1,2})(?!\d|:)', text)
    if m:
        return int(m.group(1)), 0
    m = re.search(r'\b(\d{1,2})\s*(בבוקר|בצהריים|בערב|בלילה)\b', text)
    if m:
        h = int(m.group(1))
        period = m.group(2)
        if period == "בצהריים" and h < 12:
            h += 12
        elif period in ("בערב", "בלילה") and h < 12:
            h += 12
        return h, 0
    return None

def parse_free_date(text: str):
    """Parse a free-form Hebrew/English date string into a localized datetime."""
    now = now_israel()
    text_lower = text.strip().lower()

    # Extract time
    time_parts = parse_time_from_text(text)
    hour = time_parts[0] if time_parts else 9
    minute = time_parts[1] if time_parts else 0

    # Relative days
    if any(w in text_lower for w in ["היום", "today"]):
        d = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return d
    if any(w in text_lower for w in ["מחר", "tomorrow"]):
        d = (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        return d
    if any(w in text_lower for w in ["מחרתיים"]):
        d = (now + timedelta(days=2)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        return d

    # Weekday names
    days_he = {
        "ראשון": 6, "שני": 0, "שלישי": 1, "רביעי": 2,
        "חמישי": 3, "שישי": 4, "שבת": 5
    }
    for name, wd in days_he.items():
        if name in text_lower:
            days_ahead = (wd - now.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            d = (now + timedelta(days=days_ahead)).replace(hour=hour, minute=minute, second=0, microsecond=0)
            return d

    # Formats: DD.MM.YYYY, DD/MM/YYYY, DD-MM-YYYY
    m = re.search(r'(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})', text)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year < 100:
            year += 2000
        try:
            naive = datetime(year, month, day, hour, minute)
            return ISRAEL_TZ.localize(naive)
        except ValueError:
            pass

    # Format: DD/MM (without year)
    m = re.search(r'(\d{1,2})[./-](\d{1,2})(?![./-]\d)', text)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = now.year
        try:
            naive = datetime(year, month, day, hour, minute)
            if ISRAEL_TZ.localize(naive) < now:
                naive = datetime(year + 1, month, day, hour, minute)
            return ISRAEL_TZ.localize(naive)
        except ValueError:
            pass

    # Hebrew: "4 במרץ 2026" or "4 מרץ 2026"
    for month_name, month_num in MONTHS_HE.items():
        pattern = rf'(\d{{1,2}})\s+(?:ב)?{month_name}\s*(\d{{4}})?'
        m = re.search(pattern, text_lower)
        if m:
            day = int(m.group(1))
            year = int(m.group(2)) if m.group(2) else now.year
            try:
                naive = datetime(year, month_num, day, hour, minute)
                return ISRAEL_TZ.localize(naive)
            except ValueError:
                pass

    return None

# ─── Storage ──────────────────────────────────────────────────────────────────
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

# ─── Keyboards ────────────────────────────────────────────────────────────────

def quick_reminder_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏰ בעוד שעה", callback_data="remind_1h"),
         InlineKeyboardButton("🌅 מחר בבוקר (9:00)", callback_data="remind_tomorrow")],
        [InlineKeyboardButton("📅 בעוד שבוע", callback_data="remind_week"),
         InlineKeyboardButton("🗓 בחר תאריך ושעה", callback_data="remind_pick")],
        [InlineKeyboardButton("✍️ הזנה ידנית", callback_data="remind_custom"),
         InlineKeyboardButton("🚫 בלי תזכורת", callback_data="remind_none")],
    ])

def day_picker_keyboard():
    now = now_israel()
    days_he = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
    buttons = []
    row = []
    for i in range(7):
        day = now + timedelta(days=i)
        if i == 0:
            label = "היום"
        elif i == 1:
            label = "מחר"
        else:
            label = f"יום {days_he[day.weekday()]}"
        date_str = day.strftime("%d/%m")
        row.append(InlineKeyboardButton(
            f"{label} {date_str}",
            callback_data=f"day_{day.strftime('%Y-%m-%d')}"
        ))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)

def hour_picker_keyboard(selected_date: str):
    buttons = []
    row = []
    hour = 7
    minute = 0
    while hour < 23:
        label = f"{hour:02d}:{minute:02d}"
        row.append(InlineKeyboardButton(
            label,
            callback_data=f"slot_{selected_date}_{hour:02d}{minute:02d}"
        ))
        if len(row) == 4:
            buttons.append(row)
            row = []
        minute += 30
        if minute == 60:
            minute = 0
            hour += 1
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("🔙 חזור לבחירת יום", callback_data="remind_pick")])
    return InlineKeyboardMarkup(buttons)

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
    await update.message.reply_text(
        "📝 *מה המשימה?*\nכתוב את תיאור המשימה:",
        parse_mode="Markdown"
    )
    context.user_data["state"] = "waiting_task_text"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    text = update.message.text.strip()

    if state == "waiting_task_text":
        context.user_data["new_task_text"] = text
        context.user_data["state"] = "waiting_reminder_time"
        await update.message.reply_text(
            f"✅ שמרתי: *{text}*\n\nמתי להזכיר לך?",
            reply_markup=quick_reminder_keyboard(),
            parse_mode="Markdown"
        )
        return

    if state == "waiting_custom_time":
        reminder_time = parse_free_date(text)
        if reminder_time:
            await _save_new_task(update, context, reminder_time)
        else:
            await update.message.reply_text(
                "❌ לא הצלחתי להבין את התאריך 🤔\n\n"
                "נסה לכתוב כך:\n"
                "• `4 במרץ 2026 09:30`\n"
                "• `4.3.2026 09:30`\n"
                "• `4/3/2026 9:30`\n"
                "• `מחרתיים ב-10`\n"
                "• `יום שני ב-14:30`",
                parse_mode="Markdown"
            )
        return

    # הודעה רגילה = משימה חדשה
    context.user_data["new_task_text"] = text
    context.user_data["state"] = "waiting_reminder_time"
    await update.message.reply_text(
        f"📌 הוספתי משימה: *{text}*\n\nמתי להזכיר לך?",
        reply_markup=quick_reminder_keyboard(),
        parse_mode="Markdown"
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("remind_"):
        now = now_israel()

        if data == "remind_1h":
            await _save_new_task(query, context, now + timedelta(hours=1))
        elif data == "remind_tomorrow":
            t = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
            await _save_new_task(query, context, t)
        elif data == "remind_week":
            await _save_new_task(query, context, now + timedelta(weeks=1))
        elif data == "remind_none":
            await _save_new_task(query, context, None)
        elif data == "remind_pick":
            await query.edit_message_text(
                "🗓 *בחר יום:*",
                reply_markup=day_picker_keyboard(),
                parse_mode="Markdown"
            )
        elif data == "remind_custom":
            context.user_data["state"] = "waiting_custom_time"
            await query.edit_message_text(
                "✍️ *כתוב תאריך ושעה בכל פורמט שנוח לך:*\n\n"
                "• `4 במרץ 2026 09:30`\n"
                "• `4.3.2026 09:30`\n"
                "• `4/3/2026 9:30`\n"
                "• `מחרתיים ב-10`\n"
                "• `יום שני ב-14:30`",
                parse_mode="Markdown"
            )
        return

    if data.startswith("day_"):
        selected_date = data[4:]
        await query.edit_message_text(
            "⏰ *בחר שעה:*",
            reply_markup=hour_picker_keyboard(selected_date),
            parse_mode="Markdown"
        )
        return

    if data.startswith("slot_"):
        parts = data.split("_")
        selected_date = parts[1]
        time_str = parts[2]
        hour = int(time_str[:2])
        minute = int(time_str[2:])
        naive_time = datetime.strptime(selected_date, "%Y-%m-%d").replace(hour=hour, minute=minute, second=0)
        reminder_time = ISRAEL_TZ.localize(naive_time)
        await _save_new_task(query, context, reminder_time)
        return

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
        tasks = [t for t in load_tasks() if t["id"] != task_id]
        save_tasks(tasks)
        await query.edit_message_text(f"🗑 משימה #{task_id} נמחקה.")
        return

async def _save_new_task(source, context, reminder_time):
    tasks = load_tasks()
    task_text = context.user_data.get("new_task_text", "משימה ללא כותרת")
    task = {
        "id": get_next_id(tasks),
        "text": task_text,
        "done": False,
        "created": now_israel().isoformat(),
        "reminder": reminder_time.isoformat() if reminder_time else None,
        "reminded": False
    }
    tasks.append(task)
    save_tasks(tasks)
    context.user_data["state"] = None

    msg = f"🎉 *משימה נוספה בהצלחה!*\n\n📌 {task_text}\n"
    if reminder_time:
        msg += f"⏰ תזכורת: {reminder_time.strftime('%d/%m/%Y %H:%M')} (שעון ישראל)"
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

# ─── Reminder checker ────────────────────────────────────────────────────────

async def check_reminders(context: ContextTypes.DEFAULT_TYPE):
    tasks = load_tasks()
    now = now_israel()
    changed = False

    for t in tasks:
        if t.get("done") or t.get("reminded") or not t.get("reminder"):
            continue
        reminder_time = datetime.fromisoformat(t["reminder"])
        if reminder_time.tzinfo is None:
            reminder_time = ISRAEL_TZ.localize(reminder_time)
        if now >= reminder_time:
            keyboard = [[
                InlineKeyboardButton("✅ בוצע", callback_data=f"done_{t['id']}"),
                InlineKeyboardButton("⏰ תזכיר שוב בשעה", callback_data="remind_1h")
            ]]
            await context.bot.send_message(
                chat_id=context.job.chat_id,
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

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("add", add_task))
    app.add_handler(CommandHandler("list", list_tasks))
    app.add_handler(CommandHandler("done", done_cmd))
    app.add_handler(CommandHandler("delete", delete_cmd))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.job_queue.run_repeating(
        check_reminders,
        interval=10,
        first=5,
        chat_id=int(chat_id)
    )

    print("🤖 הבוט עלה! מאזין להודעות...")
    app.run_polling()

if __name__ == "__main__":
    main()
