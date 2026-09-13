# Playwright Linux container pre-installed dependencies ke sath
FROM mcr.microsoft.com/playwright/python:v1.41.0-jammy

# App directory setup
WORKDIR /app

# Requirements copy & install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Baaki files copy karein
COPY . .

# Run bot
CMD ["python", "main.py"]
