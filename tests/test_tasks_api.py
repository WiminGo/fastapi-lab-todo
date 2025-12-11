import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone
import tempfile
import os

# Импортируем приложение и модели из основного модуля
from app.app_main import application, Task, Base, TaskCreate, TaskUpdate

# Фикстура: временная БД и клиент
@pytest.fixture(scope="function")
def client():
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)

    test_db_url = f"sqlite:///{db_path}"
    test_engine = create_engine(test_db_url, echo=False, future=True)
    Base.metadata.create_all(bind=test_engine)

    # Подменяем engine в app_main
    import app.app_main
    original_engine = app.app_main.engine
    app.app_main.engine = test_engine

    with TestClient(application) as c:
        yield c

    # Восстанавливаем engine
    app.app_main.engine = original_engine
    test_engine.dispose()
    os.unlink(db_path)


# Фикстура: сессия для ORM-операций
@pytest.fixture(scope="function")
def db_session(client):
    from app.app_main import engine
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


# Вспомогательная функция: создать задачу напрямую через ORM
def create_task_in_db(session, **kwargs):
    now = datetime.now(timezone.utc).isoformat()
    task = Task(
        title=kwargs.get("title", "Test Task"),
        details=kwargs.get("details"),
        is_done=kwargs.get("is_done", False),
        priority=kwargs.get("priority", 1),
        due_date=kwargs.get("due_date"),
        created_at=kwargs.get("created_at", now),
        updated_at=kwargs.get("updated_at"),
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


# Тесты /health
def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# Тесты POST /tasks
def test_create_task_success(client):
    task_data = {
        "title": "Buy groceries",
        "details": "Milk, eggs, bread",
        "is_done": False,
        "priority": 2,
        "due_date": "2025-12-31T23:59:59Z"
    }
    response = client.post("/tasks", json=task_data)
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert data["title"] == "Buy groceries"
    assert data["priority"] == 2
    assert data["is_done"] is False
    assert data["due_date"] == "2025-12-31T23:59:59Z"
    assert "created_at" in data
    assert data["updated_at"] is None


def test_create_task_minimal_fields(client):
    response = client.post("/tasks", json={"title": "Minimal task"})
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Minimal task"
    assert data["priority"] == 1
    assert data["is_done"] is False
    assert data["details"] is None
    assert data["due_date"] is None


def test_create_task_validation_errors(client):
    # Слишком короткий title
    response = client.post("/tasks", json={"title": "ab"})
    assert response.status_code == 422

    # Пробелы вместо title
    response = client.post("/tasks", json={"title": "   "})
    assert response.status_code == 422

    # Неверный priority
    response = client.post("/tasks", json={"title": "Test", "priority": 5})
    assert response.status_code == 422

    # Неверный due_date
    response = client.post("/tasks", json={"title": "Test", "due_date": "invalid-date"})
    assert response.status_code == 422


# Тесты GET /tasks
def test_list_tasks_filters_and_sorting(client, db_session):
    # Очистка таблицы перед тестом
    db_session.execute(text("DELETE FROM tasks"))
    db_session.commit()

    # Подготовка данных
    create_task_in_db(db_session, title="Urgent task", priority=3, is_done=False, due_date="2025-12-20T10:00:00Z")
    create_task_in_db(db_session, title="Routine task", priority=1, is_done=True, due_date="2025-12-25T10:00:00Z")
    create_task_in_db(db_session, title="Medium task", details="Contains keyword", priority=2, is_done=False, due_date="2025-12-22T10:00:00Z")

    # Фильтр q
    response = client.get("/tasks?q=urgent")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert "Urgent task" in data[0]["title"]

    # Фильтр is_done
    response = client.get("/tasks?is_done=true")
    assert len(response.json()) == 1
    assert response.json()[0]["is_done"] is True

    # Фильтр priority
    response = client.get("/tasks?priority=2")
    assert len(response.json()) == 1
    assert response.json()[0]["priority"] == 2

    # Фильтры due_before / due_after
    response = client.get("/tasks?due_before=2025-12-21T00:00:00Z")
    assert len(response.json()) == 1  # Только Urgent task

    response = client.get("/tasks?due_after=2025-12-24T00:00:00Z")
    assert len(response.json()) == 1  # Только Routine

    # Сортировка по priority desc
    response = client.get("/tasks?sort=priority&order=desc")
    tasks = response.json()
    assert tasks[0]["priority"] == 3
    assert tasks[1]["priority"] == 2
    assert tasks[2]["priority"] == 1

    # Некорректный sort
    response = client.get("/tasks?sort=invalid_field")
    assert response.status_code == 400

    # Некорректный order
    response = client.get("/tasks?order=upside_down")
    assert response.status_code == 400


# Тесты GET /tasks/{id}
def test_get_task_by_id(client):
    response = client.post("/tasks", json={"title": "Find me"})
    task_id = response.json()["id"]

    response = client.get(f"/tasks/{task_id}")
    assert response.status_code == 200
    assert response.json()["title"] == "Find me"


def test_get_nonexistent_task(client):
    response = client.get("/tasks/999999")
    assert response.status_code == 404


def test_get_task_invalid_id(client):
    response = client.get("/tasks/abc")
    assert response.status_code == 422


# Тесты PUT /tasks/{id}
def test_update_task_partial(client):
    response = client.post("/tasks", json={"title": "Original", "priority": 1})
    task_id = response.json()["id"]
    original_updated_at = response.json()["updated_at"]

    # Обновляем только is_done и priority
    response = client.put(f"/tasks/{task_id}", json={"is_done": True, "priority": 3})
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Original"  # не изменилось
    assert data["is_done"] is True
    assert data["priority"] == 3
    assert data["updated_at"] != original_updated_at


def test_update_task_validation_error(client):
    response = client.post("/tasks", json={"title": "Valid task"})
    task_id = response.json()["id"]

    response = client.put(f"/tasks/{task_id}", json={"title": "ab"})  # слишком коротко
    assert response.status_code == 422


def test_update_nonexistent_task(client):
    response = client.put("/tasks/999999", json={"title": "New title"})
    assert response.status_code == 404


# Тесты DELETE /tasks/{id}
def test_delete_task_success(client):
    response = client.post("/tasks", json={"title": "To delete"})
    task_id = response.json()["id"]

    response = client.delete(f"/tasks/{task_id}")
    assert response.status_code == 204

    response = client.get(f"/tasks/{task_id}")
    assert response.status_code == 404


def test_delete_nonexistent_task(client):
    response = client.delete("/tasks/999999")
    assert response.status_code == 404
