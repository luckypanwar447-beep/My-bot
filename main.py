import os
import sys
import asyncio
import subprocess
import logging
import re
from aiohttp import web
from PIL import Image
import pytesseract

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

IDENTITY_INPUT, OTP_INPUT = range(2)
MY_AADHAAR_URL = "https://myaadhaar.uidai.gov.in/genricDownloadAadhaar"

def ensure_dependencies():
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "playwright"])
    
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"])
    
    # Check Tesseract binary
    try:
        subprocess.run(["tesseract", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        logging.info("Installing Tesseract OCR on system...")
        subprocess.run(["apt-get", "update", "-y"], check=False)
        subprocess.run(["apt-get", "install", "-y", "tesseract-ocr"], check=False)

ensure_dependencies()

from playwright.async_api import async_playwright

# Render HTTP Port Dummy Server (Health Check Pass Karwane Ke Liye)
async def handle_dummy_request(request):
    return web.Response(text="Bot is Live and Running!")

async def start_dummy_server():
    app = web.Application()
    app.router.add_get('/', handle_dummy_request)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Dummy Web Server running on port {port}")

# OCR Function for Captcha Auto-Bypass
def solve_captcha_image(image_path: str) -> str:
    try:
        img = Image.open(image_path).convert('L') # Convert to Grayscale
        text = pytesseract.image_to_string(img, config='--psm 6')
        clean_text = re.sub(r'[^a-zA-Z0-9]', '', text)
        return clean_text
    except Exception as e:
        logging.error(f"OCR Error: {e}")
        return ""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Namaste! Kripya apna 12-digit UIDAI Reference ID ya Registered Phone Number enter karein:"
    )
    return IDENTITY_INPUT

async def process_identity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    input_text = update.message.text.strip()
    
    if not input_text.isdigit() or len(input_text) not in [10, 12]:
        await update.message.reply_text("Galat Input! Valid 10-digit Phone Number ya 12-digit Reference Number daalein.")
        return IDENTITY_INPUT

    context.user_data['identity'] = input_text
    await update.message.reply_text("Portal load ho raha hai... Anti-bot headers inject aur Captcha Auto-Solve ho raha hai...")

    try:
        pw = await async_playwright().start()
        
        # Real Browser User-Agent and Headers Bypass Setup
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-blink-features=AutomationControlled'
            ]
        )
        
        context_browser = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={'width': 1366, 'height': 768},
            extra_http_headers={
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Connection': 'keep-alive'
            }
        )

        page = await context_browser.new_page()
        
        # Automation Detection Remove Script
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        await page.goto(MY_AADHAAR_URL, wait_until="networkidle")
        await page.wait_for_selector("//img[@alt='Captcha']", timeout=20000)

        # Captcha Save & Auto OCR Solve
        captcha_path = f"captcha_{update.effective_user.id}.png"
        captcha_element = page.locator("//img[@alt='Captcha']")
        await captcha_element.screenshot(path=captcha_path)
        
        extracted_captcha = solve_captcha_image(captcha_path)
        logging.info(f"Auto Solved Captcha Text: {extracted_captcha}")

        # Input ID and Captcha
        await page.fill("input[name='uid']", input_text)
        if extracted_captcha:
            await page.fill("input[name='captcha']", extracted_captcha)
        
        # Click Send OTP Button
        await page.click("//button[contains(text(), 'Send OTP')]")
        
        context.user_data['pw'] = pw
        context.user_data['browser'] = browser
        context.user_data['page'] = page
        context.user_data['captcha_file'] = captcha_path
        
        await update.message.reply_text(
            f"Captcha Auto-Bypassed ({extracted_captcha})!\n\nOTP send request submit kar di gayi hai. Multi-Factor OTP yahan enter karein:"
        )
        return OTP_INPUT

    except Exception as e:
        await update.message.reply_text(f"Error: Session Load Failed. Details: {str(e)}")
        await cleanup_session(context)
        return ConversationHandler.END

async def process_otp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    otp_text = update.message.text.strip()
    page = context.user_data.get('page')

    try:
        await page.fill("input[name='otp']", otp_text)
        await page.click("//button[contains(text(), 'Verify & Download')]")
        await update.message.reply_text("Verification process Complete ho raha hai...")
    except Exception as e:
        await update.message.reply_text(f"OTP submit failure: {str(e)}")
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
    bot_token = os.getenv("BOT_TOKEN")
    
    if not bot_token:
        print("ERROR: BOT_TOKEN environment variable is missing!")
        return

    loop = asyncio.get_event_loop()
    loop.create_task(start_dummy_server())

    application = ApplicationBuilder().token(bot_token).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            IDENTITY_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_identity)],
            OTP_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_otp)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    application.add_handler(conv_handler)
    application.run_polling()

if __name__ == '__main__':
    main()
