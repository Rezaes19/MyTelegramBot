FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir telethon==1.34.0
CMD ["python", "main.py"]
