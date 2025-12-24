# FastAPI ToDo Lab

Простое приложение для управления задачами (ToDo) на FastAPI с SQLite

## Запуск в Docker

1. Сборка образа

```bash
docker build -t fastapi-todo .
```

3. Запуск контейнера (с сохранением данных)

```bash
docker run --rm -p 8000:8000 -v "${PWD}/lab.db:/app/lab.db" fastapi-todo
```

## Запуск тестов

1. Установка зависимостей

```bash
pip install -r requirements.txt
```

2. Запуск(локально)

```bash
pytest
```