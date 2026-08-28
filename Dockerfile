FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# با تاخیر ۳۰ ثانیه شروع کن
CMD ["sh", "-c", "sleep 30 && python main.py"]
