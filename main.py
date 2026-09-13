import os
import logging
from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# Logging configuration
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

IDENTITY_INPUT, CAPTCHA_INPUT, OTP_INPUT = range(3)
MY_AADHAAR_URL = "https://myaadhaar.uidai.gov.in/genricDownloadAadhaar"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Namaste! Kripya apna 12-digit Aadhaar Number ya Registered Phone Number enter karein:"
    )
    return IDENTITY_INPUT

async def process_identity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    input_text = update.message.text.strip()
    
    if not input_text.isdigit() or len(input_text) not in [10, 12]:
        await update.message.reply_text("Galat Input! Valid 10-digit Phone Number ya 12-digit Aadhaar Number daalein.")
        return IDENTITY_INPUT

    context.user_data['identity'] = input_text
    await update.message.reply_text("Portal fetch ho raha hai... Captcha image screenshot generate ho raha hai...")

    try:
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        
        await page.goto(MY_AADHAAR_URL)
        await page.wait_for_selector("//img[@alt='Captcha']", timeout=15000)

        # Captcha Screenshot save karein
        captcha_path = f"captcha_{update.effective_user.id}.png"
        captcha_element = page.locator("//img[@alt='Captcha']")
        await captcha_element.screenshot(path=captcha_path)
        
        context.user_data['pw'] = pw
        context.user_data['browser'] = browser
        context.user_data['page'] = page
        context.user_data['captcha_file'] = captcha_path
        
        await update.message.reply_photo(
            photo=open(captcha_path, "rb"),
            caption="Kripya ye Captcha text exact enter karein:"
        )
        return CAPTCHA_INPUT
    except Exception as e:
        await update.message.reply_text(f"Error: Portal load nahi ho sakha. Details: {str(e)}")
        return ConversationHandler.END

async def process_captcha(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    captcha_text = update.message.text.strip()
    page = context.user_data.get('page')
    identity = context.user_data.get('identity')

    try:
        await page.fill("input[name='uid']", identity)
        await page.fill("input[name='captcha']", captcha_text)
        await page.click("//button[contains(text(), 'Send OTP')]")

        await update.message.reply_text("OTP request submit kar di gayi hai. Multi-Factor OTP enter karein:")
        return OTP_INPUT
    except Exception as e:
        await update.message.reply_text("Captcha submit fail ho gaya. `/start` firse karein.")
        await cleanup_session(context)
        return ConversationHandler.END

async def process_otp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    otp_text = update.message.text.strip()
    page = context.user_data.get('page')

    try:
        await page.fill("input[name='otp']", otp_text)
        await page.click("//button[contains(text(), 'Verify & Download')]")
        await update.message.reply_text("Verification process Complete ho raha hai...")
    finally:
        await cleanup_session(context)

    return ConversationHandler.END

async def cleanup_session(context: ContextTypes.DEFAULT_TYPE):
    browser = context.user_data.get('browser')
    pw = context.user_data.get('pw')
    captcha_file = context.user_data.get('captcha_file')

    if browser:
        await browser.close()
    if pw:
        await pw.stop()
    if captcha_file and os.path.exists(captcha_file):
        os.remove(captcha_file)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await cleanup_session(context)
    await update.message.reply_text("Process cancel kar diya gaya hai.")
    return ConversationHandler.END

def main():
    # Environment Variable se Bot Token fetch hoga
    bot_token = os.getenv("BOT_TOKEN")
    
    if not bot_token:
        print("ERROR: BOT_TOKEN environment variable is missing!")
        return

    application = ApplicationBuilder().token(bot_token).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            IDENTITY_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_identity)],
            CAPTCHA_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_captcha)],
            OTP_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_otp)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    application.add_handler(conv_handler)
    application.run_polling()

if __name__ == '__main__':
    main()
