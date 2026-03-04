import os
import json
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
    """Slots every 30 minutes from 07:00 to 22:30"""
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

# ─── Smart date parsing via Claude API ───────────────────────────────────────

import urllib.request

async def parse_date_with_claude(user_input: str) -> datetime | None:
    """Send the user's free-text date to Claude and get back a parsed datetime."""
    today = now_israel().strftime("%d/%m/%Y")
    prompt = (
        f"היום הוא {today}. "
        f"המשתמש רוצה תזכורת בתאריך/שעה הבאים: \"{user_input}\". "
        "החזר JSON בלבד, בלי שום טקסט נוסף, בפורמט: "
        "{\"datetime\": \"YYYY-MM-DD HH:MM\"} "
        "אם לא ניתן להבין את התאריך, החזר: {\"datetime\": null}"
    )

    body = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 100,
        "messages": [{"role": "user", "content": prompt}]
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            text = data["content"][0]["text"].strip()
            parsed = json.loads(text)
            if parsed.get("datetime"):
                naive = datetime.strptime(parsed["datetime"], "%Y-%m-%d %H:%M")
                return ISRAEL_TZ.localize(naive)
    except Exception:
        pass
    return None

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
        reminder_time = await parse_date_with_claude(text)
        if reminder_time:
            await _save_new_task(update, context, reminder_time)
        else:
            await update.message.reply_text(
                "❌ לא הצלחתי להבין את התאריך 🤔\n\n"
                "נסה לכתוב בצורה אחרת, לדוגמה:\n"
                "• `4 במרץ 2026 09:30`\n"
                "• `4.3.2026 09:30`\n"
                "• `4/3/2026 9:30`\n"
                "• `מחרתיים ב-10 בבוקר`",
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

    # ── בחירה מהירה ──
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
                "• `מחרתיים ב-10 בבוקר`\n"
                "• `יום שני ב-14:30`",
                parse_mode="Markdown"
            )
        return

    # ── בחירת יום ──
    if data.startswith("day_"):
        selected_date = data[4:]  # YYYY-MM-DD
        await query.edit_message_text(
            f"⏰ *בחר שעה:*",
            reply_markup=hour_picker_keyboard(selected_date),
            parse_mode="Markdown"
        )
        return

    # ── בחירת שעה (slot) ──
    if data.startswith("slot_"):
        # slot_YYYY-MM-DD_HHMM
        parts = data.split("_")
        selected_date = parts[1]   # YYYY-MM-DD
        time_str = parts[2]        # HHMM
        hour = int(time_str[:2])
        minute = int(time_str[2:])
        naive_time = datetime.strptime(selected_date, "%Y-%m-%d").replace(hour=hour, minute=minute, second=0)
        reminder_time = ISRAEL_TZ.localize(naive_time)
        await _save_new_task(query, context, reminder_time)
        return

    # ── בוצע / מחק ──
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
        first=10,
        chat_id=int(chat_id)
    )

    print("🤖 הבוט עלה! מאזין להודעות...")
    app.run_polling()

if __name__ == "__main__":
    main()
