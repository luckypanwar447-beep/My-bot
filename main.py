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
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

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

ensure_dependencies()

# Render Health Check Server
async def handle_dummy_request(request):
    return web.Response(text="Bot is Live")

async def start_dummy_server():
    app = web.Application()
    app.router.add_get('/', handle_dummy_request)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# Captcha Solver Logic
def solve_captcha_image(image_path: str) -> str:
    try:
        img = Image.open(image_path).convert('L')
        text = pytesseract.image_to_string(img, config='--psm 6')
        return re.sub(r'[^a-zA-Z0-9]', '', text)
    except Exception as e:
        logging.error(f"OCR Error: {e}")
        return ""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Namaste! Kripya apna 12-digit Aadhaar Number ya Reference ID enter karein:"
    )
    return IDENTITY_INPUT

async def process_identity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    input_text = update.message.text.strip()
    
    if not input_text.isdigit() or len(input_text) not in [10, 12]:
        await update.message.reply_text("Galat Input! Valid 12-digit Aadhaar ya 10-digit Phone Number daalein.")
        return IDENTITY_INPUT

    context.user_data['identity'] = input_text
    await update.message.reply_text("Bypassing Anti-Bot Protection... Portal load ho raha hai...")

    try:
        pw = await async_playwright().start()
        
        # High Stealth Browser Options
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-infobars',
                '--window-size=1920,1080',
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
            ]
        )
        
        context_browser = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080},
            locale="en-US,en",
            timezone_id="Asia/Kolkata",
            extra_http_headers={
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9,hi;q=0.8',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache',
                'Sec-Ch-Ua': '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"Windows"',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Upgrade-Insecure-Requests': '1'
            }
        )

        page = await context_browser.new_page()
        
        # Apply Playwright Stealth Evasion
        await stealth_async(page)
        
        # Increased Timeout to 60 Seconds
        page.set_default_timeout(60000)
        
        await page.goto(MY_AADHAAR_URL, wait_until="domcontentloaded")
        await page.wait_for_selector("//img[@alt='Captcha']", timeout=60000)

        # Captcha Save & Solve
        captcha_path = f"captcha_{update.effective_user.id}.png"
        captcha_element = page.locator("//img[@alt='Captcha']")
        await captcha_element.screenshot(path=captcha_path)
        
        extracted_captcha = solve_captcha_image(captcha_path)
        logging.info(f"Auto Solved Captcha Text: {extracted_captcha}")

        # Input ID and Captcha
        await page.fill("input[name='uid']", input_text)
        if extracted_captcha:
            await page.fill("input[name='captcha']", extracted_captcha)
        
        # Trigger Send OTP
        await page.click("//button[contains(text(), 'Send OTP')]")
        
        context.user_data['pw'] = pw
        context.user_data['browser'] = browser
        context.user_data['page'] = page
        context.user_data['captcha_file'] = captcha_path
        
        await update.message.reply_text(
            f"Captcha Solved: [{extracted_captcha}]\n\nOTP Request Submit kar di gayi hai. Registered mobile par aaya OTP enter karein:"
        )
        return OTP_INPUT

    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")
        await cleanup_session(context)
        return ConversationHandler.END

async def process_otp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    otp_text = update.message.text.strip()
    page = context.user_data.get('page')

    try:
        await page.fill("input[name='otp']", otp_text)
        await page.click("//button[contains(text(), 'Verify & Download')]")
        await update.message.reply_text("OTP submit kar diya gaya hai. File process ho rahi hai...")
    except Exception as e:
        await update.message.reply_text(f"Failed: {str(e)}")
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
        print("ERROR: BOT_TOKEN environment variable missing!")
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
