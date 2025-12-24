from fastapi import FastAPI, HTTPException, Query, Path, status
from typing import Any, Dict, Optional, List
from sqlalchemy import create_engine, select, asc, desc, func
from sqlalchemy.orm import declarative_base, mapped_column, Mapped, Session
from sqlalchemy.types import Integer, String, Float, Boolean
from datetime import datetime, timezone
from pydantic import BaseModel, Field, field_validator, ConfigDict
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import os

DATABASE_URL = "sqlite:///lab.db"
engine = create_engine(DATABASE_URL, echo=False, future=True)
Base = declarative_base()


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    details: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_done: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[int] = mapped_column(Integer, default=1)
    due_date: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)

Base.metadata.create_all(engine)
application = FastAPI(title="ToDo")

class TaskBase(BaseModel):
    title: str = Field(..., min_length=3, description="Заголовок задачи (минимум 3 символа)")
    details: Optional[str] = Field(None, description="Дополнительные сведения")
    is_done: bool = Field(False, description="Статус выполнения")
    priority: int = Field(1, ge=1, le=3, description="Приоритет: 1 (низкий), 2 (средний), 3 (высокий)")
    due_date: Optional[str] = Field(None, description="Дата/время дедлайна в формате ISO 8601")

    @field_validator("due_date", mode='before')
    @classmethod
    def validate_due_date(cls, v):
        if v is None:
            return v
        if not isinstance(v, str):
            raise ValueError("due_date must be a string")
        try:
            dt_str = v.replace('Z', '+00:00')
            datetime.fromisoformat(dt_str)
        except ValueError:
            raise ValueError("due_date must be a valid ISO 8601 datetime string")
        return v

    @field_validator("title")
    @classmethod
    def title_must_not_be_all_whitespace(cls, v):
        if not v.strip():
            raise ValueError("title must contain non-whitespace characters")
        return v

class TaskCreate(TaskBase):
    pass

class TaskUpdate(TaskBase):
    title: Optional[str] = Field(None, min_length=3)
    is_done: Optional[bool] = None
    priority: Optional[int] = Field(None, ge=1, le=3)
    due_date: Optional[str] = None
    details: Optional[str] = None

    @field_validator("title", mode='before')
    @classmethod
    def title_not_empty_if_provided(cls, v):
        if v is not None and not v.strip():
            raise ValueError("title must contain non-whitespace characters if provided")
        return v


class TaskResponse(TaskBase):
    id: int
    created_at: str
    updated_at: Optional[str]

    model_config = ConfigDict(from_attributes=True)

@application.get("/health", tags=["system"])
def health():
    return {"status": "ok"}


@application.get("/tasks", response_model=List[TaskResponse], tags=["tasks"])
def list_items(
    q: Optional[str] = Query(None, description="Поиск по подстроке в title и details (без учёта регистра)"),
    is_done: Optional[bool] = Query(None, description="Фильтр по статусу выполнения"),
    priority: Optional[int] = Query(None, ge=1, le=3, description="Фильтр по приоритету (1–3)"),
    due_before: Optional[str] = Query(None, description="Задачи с due_date <= указанной даты (ISO 8601)"),
    due_after: Optional[str] = Query(None, description="Задачи с due_date >= указанной даты (ISO 8601)"),
    sort: str = Query("created_at", description="Поле сортировки: created_at, due_date, priority"),
    order: str = Query("asc", description="Порядок: asc или desc"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100)
):
    valid_sort_fields = {"created_at", "due_date", "priority"}
    if sort not in valid_sort_fields:
        raise HTTPException(
            status_code=400,
            detail=f"Недопустимое значение sort: {sort}. Допустимые: {', '.join(valid_sort_fields)}"
        )

    if order not in {"asc", "desc"}:
        raise HTTPException(
            status_code=400,
            detail="Порядок сортировки должен быть 'asc' или 'desc'"
        )

    with Session(engine) as session:
        stmt = select(Task)

        if q:
            ql = f"%{q.lower()}%"
            stmt = stmt.where(
                (func.lower(Task.title).like(ql)) |
                ((Task.details.is_not(None)) & (func.lower(Task.details).like(ql)))
            )

        if is_done is not None:
            stmt = stmt.where(Task.is_done == is_done)
        if priority is not None:
            stmt = stmt.where(Task.priority == priority)
        if due_before is not None:
            stmt = stmt.where(Task.due_date <= due_before)
        if due_after is not None:
            stmt = stmt.where(Task.due_date >= due_after)

        sort_col = getattr(Task, sort)
        stmt = stmt.order_by(desc(sort_col) if order == "desc" else asc(sort_col))
        stmt = stmt.offset(offset).limit(limit)

        tasks = session.scalars(stmt).all()
        return tasks


@application.get("/tasks/{task_id}", response_model=TaskResponse, tags=["tasks"])
def get_task(task_id: int = Path(ge=1)):
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return task


@application.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED, tags=["tasks"])
def create_task(task: TaskCreate):
    now = datetime.now(timezone.utc).isoformat()
    obj = Task(
        title=task.title,
        details=task.details,
        is_done=task.is_done,
        priority=task.priority,
        due_date=task.due_date,
        created_at=now,
        updated_at=None
    )

    with Session(engine) as session:
        session.add(obj)
        session.commit()
        session.refresh(obj)
        return obj


@application.put("/tasks/{task_id}", response_model=TaskResponse, tags=["tasks"])
def update_task(task_id: int = Path(ge=1), task: TaskUpdate = ...):
    with Session(engine) as session:
        obj = session.get(Task, task_id)
        if not obj:
            raise HTTPException(status_code=404, detail="Task not found")

        update_data = task.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(obj, key, value)

        obj.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        session.refresh(obj)
        return obj


@application.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["tasks"])
def delete_task(task_id: int = Path(ge=1)):
    with Session(engine) as session:
        obj = session.get(Task, task_id)
        if not obj:
            raise HTTPException(status_code=404, detail="Task not found")
        session.delete(obj)
        session.commit()
        return


# Определяем путь к папке static относительно app_main.py
current_dir = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(current_dir, "static")

# Подключаем статику
application.mount("/static", StaticFiles(directory=static_dir), name="static")

# Главная страница — отдаём index.html
@application.get("/", response_class=HTMLResponse, include_in_schema=False)
def read_root():
    with open(os.path.join(static_dir, "index.html"), "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())