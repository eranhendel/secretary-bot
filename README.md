# 🤖 מזכירה אישית – Telegram Bot

בוט Telegram שמנהל משימות ושולח תזכורות אוטומטיות.

---

## 🚀 הוראות התקנה מלאות

### שלב 1 – צור בוט ב-Telegram

1. פתח Telegram וחפש **@BotFather**
2. שלח: `/newbot`
3. תן שם לבוט (לדוגמה: `המזכירה שלי`)
4. תן username לבוט (חייב להסתיים ב-`bot`, לדוגמה: `my_secretary_bot`)
5. BotFather ישלח לך **TOKEN** – שמור אותו! נראה כך:
   ```
   123456789:ABCdefGHIjklMNOpqrSTUVwxyz
   ```

---

### שלב 2 – קבל את ה-Chat ID שלך

1. חפש את הבוט שיצרת ב-Telegram ושלח לו `/start`
2. פתח בדפדפן:
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
   (החלף `<TOKEN>` בטוקן שקיבלת)
3. חפש בתוצאה את: `"chat":{"id":XXXXXXXXX}`
4. הספרות הן ה-**CHAT_ID** שלך

---

### שלב 3 – העלה ל-GitHub

1. צור חשבון ב-[github.com](https://github.com) אם אין לך
2. צור repository חדש בשם `secretary-bot`
3. העלה את כל הקבצים:
   ```bash
   git init
   git add .
   git commit -m "first commit"
   git remote add origin https://github.com/<username>/secretary-bot.git
   git push -u origin main
   ```

---

### שלב 4 – פרוס ב-Railway

1. כנס ל-[railway.app](https://railway.app) וצור חשבון חינמי
2. לחץ **"New Project"** → **"Deploy from GitHub repo"**
3. בחר את ה-repository `secretary-bot`
4. לאחר ה-deploy, כנס ל-**Variables** והוסף:

   | שם משתנה | ערך |
   |-----------|-----|
   | `TELEGRAM_BOT_TOKEN` | הטוקן מ-BotFather |
   | `TELEGRAM_CHAT_ID` | ה-Chat ID שלך |

5. Railway יפעיל מחדש את הבוט אוטומטית ✅

---

## 💬 איך להשתמש בבוט

| פקודה | תיאור |
|--------|--------|
| `/start` | הצג תפריט ראשי |
| `/add` | הוסף משימה חדשה |
| `/list` | הצג כל המשימות הפתוחות |
| `/done 3` | סמן משימה #3 כבוצעה |
| `/delete 3` | מחק משימה #3 |

**טיפ:** אתה יכול גם פשוט לכתוב את המשימה ישירות בצ'אט!

---

## ⏰ אפשרויות תזכורת

בעת הוספת משימה תקבל תפריט:
- **בעוד שעה**
- **מחר בבוקר (9:00)**
- **בעוד שבוע**
- **הזן שעה ידנית** (פורמט: `DD/MM/YYYY HH:MM`)
- **בלי תזכורת**

---

## 📁 מבנה הקבצים

```
secretary-bot/
├── bot.py           # הבוט הראשי
├── requirements.txt # תלויות Python
├── railway.toml     # הגדרות Railway
└── README.md        # המדריך הזה
```

---

## 🛠 הרצה מקומית (לבדיקה)

```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="your_token_here"
export TELEGRAM_CHAT_ID="your_chat_id_here"
python bot.py
```
