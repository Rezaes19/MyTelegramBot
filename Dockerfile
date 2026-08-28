FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# مهم: اسم فایل اصلی رو اینجا بذار
# اگه فایلت main.py هست:
CMD ["python", "main.py"]

# اگه فایلت bot.py هست:
# CMD ["python", "bot.py"]

# اگه فایلت combined_bot.py هست:
# CMD ["python", "combined_bot.py"]
