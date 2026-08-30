FROM python:3.11-slim

RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

# نصب با ریسالو نکن
RUN pip install --no-cache-dir -r requirements.txt --no-deps || true

# نصب جداگانه
RUN pip install --no-cache-dir telethon psutil aiohttp asyncio aiocron aiofiles pytz googletrans==4.0.0-rc1 gtts google_play_scraper numpy matplotlib

# نصب pytgcalls با نسخه مشخص
RUN pip install --no-cache-dir tgcalls==2.0.0 pytgcalls==2.1.0

COPY . .

CMD ["python", "self.py"]
