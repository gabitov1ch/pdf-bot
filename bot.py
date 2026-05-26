import logging
from io import BytesIO
from PIL import Image, ImageOps
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, InputMediaPhoto
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

import os
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

user_photos = {}       # {user_id: [bytes, ...]}
user_file_ids = {}     # {user_id: [file_id, ...]}
user_lang = {}

WAITING_FILENAME = 1

TEXTS = {
    "kz": {
        "welcome": "Сәлем! 👋 Фотоларды PDF-ке айналдыратын бот.\n\n📸 Фото жібер, содан кнопканы бас!",
        "photo_added": "📸 Жаңа фото қосылды!",
        "photo_count": "Барлығы: <b>{}</b> фото жиналған.",
        "no_photos": "⚠️ Фото жоқ! Алдымен фото жібер.",
        "ask_filename": "📝 PDF файлының атын жаз:",
        "generating": "⏳ {} фотодан PDF жасалуда...",
        "done": "✅ Дайын! {} фото → {}.pdf",
        "cleared": "🗑 {} фото өшірілді.",
        "nothing_clear": "Өшіретін фото жоқ.",
        "count": "📊 Қазір <b>{}</b> фото жиналған.",
        "error": "❌ Қате шықты. Қайтадан көріп бақ.",
        "choose_lang": "🌐 Тілді таңда:",
        "lang_set": "✅ Қазақ тілі орнатылды!",
        "btn_convert": "✅ Конвертациялау",
        "btn_clear": "🗑 Суреттерді тазалау",
        "btn_count": "📊 Фото саны",
        "btn_back": "◀️ Артқа",
        "btn_lang": "🌐 Тіл өзгерту",
    },
    "ru": {
        "welcome": "Привет! 👋 Бот для конвертации фото в PDF.\n\n📸 Отправь фото, затем нажми кнопку!",
        "photo_added": "📸 Новое фото добавлено!",
        "photo_count": "Всего: <b>{}</b> фото собрано.",
        "no_photos": "⚠️ Нет фото! Сначала отправь фото.",
        "ask_filename": "📝 Напиши название PDF файла:",
        "generating": "⏳ Создаю PDF из {} фото...",
        "done": "✅ Готово! {} фото → {}.pdf",
        "cleared": "🗑 {} фото удалено.",
        "nothing_clear": "Нет фото для удаления.",
        "count": "📊 Сейчас <b>{}</b> фото собрано.",
        "error": "❌ Произошла ошибка. Попробуй снова.",
        "choose_lang": "🌐 Выбери язык:",
        "lang_set": "✅ Русский язык установлен!",
        "btn_convert": "✅ Конвертировать",
        "btn_clear": "🗑 Очистить изображения",
        "btn_count": "📊 Кол-во фото",
        "btn_back": "◀️ Назад",
        "btn_lang": "🌐 Сменить язык",
    },
}

def t(user_id, key):
    lang = user_lang.get(user_id, "ru")
    return TEXTS[lang][key]

def menu_keyboard(user_id):
    lang = user_lang.get(user_id, "ru")
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(TEXTS[lang]["btn_convert"]), KeyboardButton(TEXTS[lang]["btn_clear"])],
            [KeyboardButton(TEXTS[lang]["btn_count"]), KeyboardButton(TEXTS[lang]["btn_lang"])],
        ],
        resize_keyboard=True,
    )

def back_inline(user_id):
    lang = user_lang.get(user_id, "ru")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(TEXTS[lang]["btn_back"], callback_data="back")],
    ])

def lang_inline():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🇰🇿 Қазақша", callback_data="lang_kz"),
         InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")],
    ])

# ── /start ────────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(t(user_id, "welcome"), reply_markup=menu_keyboard(user_id))

# ── /change_language ──────────────────────────────────────────────────────────
async def change_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(t(user_id, "choose_lang"), reply_markup=lang_inline())

# ── Фото қабылдау ─────────────────────────────────────────────────────────────
async def receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    photo = update.message.photo[-1]

    # Байттарды сақтау
    photo_file = await photo.get_file()
    photo_bytes = await photo_file.download_as_bytearray()

    if user_id not in user_photos:
        user_photos[user_id] = []
    if user_id not in user_file_ids:
        user_file_ids[user_id] = []

    user_photos[user_id].append(bytes(photo_bytes))
    user_file_ids[user_id].append(photo.file_id)
    count = len(user_photos[user_id])

    await update.message.reply_text(
        t(user_id, 'photo_count').format(count),
        parse_mode="HTML",
        reply_markup=menu_keyboard(user_id),
    )

# ── Reply keyboard мәтін өңдеу ────────────────────────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    lang = user_lang.get(user_id, "ru")

    if text == TEXTS[lang]["btn_convert"]:
        photos = user_photos.get(user_id, [])
        if not photos:
            await update.message.reply_text(t(user_id, "no_photos"), reply_markup=menu_keyboard(user_id))
            return
        await update.message.reply_text(t(user_id, "ask_filename"), reply_markup=back_inline(user_id))
        return WAITING_FILENAME

    elif text == TEXTS[lang]["btn_clear"]:
        count = len(user_photos.pop(user_id, []))
        user_file_ids.pop(user_id, None)
        msg = t(user_id, "cleared").format(count) if count else t(user_id, "nothing_clear")
        await update.message.reply_text(msg, reply_markup=menu_keyboard(user_id))

    elif text == TEXTS[lang]["btn_count"]:
        count = len(user_photos.get(user_id, []))
        await update.message.reply_text(t(user_id, "count").format(count), parse_mode="HTML", reply_markup=menu_keyboard(user_id))

    elif text == TEXTS[lang]["btn_lang"]:
        await update.message.reply_text(t(user_id, "choose_lang"), reply_markup=lang_inline())

# ── Inline кнопка ─────────────────────────────────────────────────────────────
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "back":
        await query.message.reply_text(t(user_id, "welcome"), reply_markup=menu_keyboard(user_id))
        return ConversationHandler.END

    elif data == "lang_kz":
        user_lang[user_id] = "kz"
        await query.message.reply_text(TEXTS["kz"]["lang_set"], reply_markup=menu_keyboard(user_id))
        return ConversationHandler.END

    elif data == "lang_ru":
        user_lang[user_id] = "ru"
        await query.message.reply_text(TEXTS["ru"]["lang_set"], reply_markup=menu_keyboard(user_id))
        return ConversationHandler.END

# ── Файл атын қабылдау ────────────────────────────────────────────────────────
async def receive_filename(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    filename = update.message.text.strip()
    filename = "".join(c for c in filename if c.isalnum() or c in (" ", "_", "-")).strip()
    if not filename:
        filename = "photos"

    photos = user_photos.get(user_id, [])
    if not photos:
        await update.message.reply_text(t(user_id, "no_photos"), reply_markup=menu_keyboard(user_id))
        return ConversationHandler.END

    await update.message.reply_text(t(user_id, "generating").format(len(photos)))

    try:
        pdf_buffer = build_pdf(photos)
        await update.message.reply_document(
            document=pdf_buffer,
            filename=f"{filename}.pdf",
            caption=t(user_id, "done").format(len(photos), filename),
            reply_markup=menu_keyboard(user_id)
        )
        user_photos.pop(user_id, None)
        user_file_ids.pop(user_id, None)
    except Exception as e:
        logger.error("PDF қате: %s", e)
        await update.message.reply_text(t(user_id, "error"), reply_markup=menu_keyboard(user_id))

    return ConversationHandler.END

# ── PDF жасаушы ───────────────────────────────────────────────────────────────
def build_pdf(photo_bytes_list):
    buffer = BytesIO()
    images = []
    for photo_bytes in photo_bytes_list:
        img = Image.open(BytesIO(photo_bytes))
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        images.append(img)

    if not images:
        return buffer

    c = canvas.Canvas(buffer)
    for img in images:
        img_w, img_h = img.size
        page_w = img_w * 72 / 96
        page_h = img_h * 72 / 96
        c.setPageSize((page_w, page_h))
        img_buffer = BytesIO()
        img.save(img_buffer, format="JPEG", quality=95)
        img_buffer.seek(0)
        c.drawImage(ImageReader(img_buffer), 0, 0, width=page_w, height=page_h)
        c.showPage()

    c.save()
    buffer.seek(0)
    return buffer

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text),
        ],
        states={
            WAITING_FILENAME: [
                CallbackQueryHandler(button_handler, pattern="^back$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_filename),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("change_language", change_language))
    app.add_handler(MessageHandler(filters.PHOTO, receive_photo))
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^(lang_kz|lang_ru|back)$"))
    app.add_handler(conv_handler)

    print("✅ Бот іске қосылды!")
    app.run_polling()

if __name__ == "__main__":
    main()
