# Используем официальный образ Python 3.11
FROM python:3.11-slim

# Безопасные настройки
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Рабочая директория
WORKDIR /app

# Создаём непривилегированного пользователя (лучшая практика)
RUN addgroup --system --gid 1000 appuser && \
    adduser --system --uid 1000 --gid 1000 --disabled-password --gecos "" appuser

# Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Копируем исходный код
COPY . .

# Даём права владельца пользователю appuser (включая lab.db, если он есть)
RUN chown -R appuser:appuser /app

# Переключаемся на непривилегированного пользователя
USER appuser

# Порт
EXPOSE 8000

# Запуск
CMD ["uvicorn", "app.app_main:app", "--host", "0.0.0.0", "--port", "8000"]