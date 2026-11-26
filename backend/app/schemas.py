"""Pydantic-Schemas für API und KI-Werkzeuge (validieren sämtliche Eingaben)."""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

TaskStatus = Literal["open", "in_progress", "waiting", "done", "archived"]
Priority = Literal["low", "normal", "high", "critical"]
ProjectStatus = Literal["planned", "active", "paused", "completed", "archived"]
MemoryCategory = Literal["project", "decision", "planning_rule", "recurring", "goal", "note", "preference"]

HEX_COLOR = r"^#[0-9A-Fa-f]{6}$"


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ----------------------------------------------------------------- Auth
class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(min_length=10, max_length=256)


class ProfileIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    timezone: str | None = Field(default=None, max_length=64)
    language: Literal["de", "en"] | None = None

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        if v is None:
            return v
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(v)
        except Exception as exc:  # noqa: BLE001
            raise ValueError("Unbekannte Zeitzone") from exc
        return v


class UserOut(ORM):
    id: int
    username: str
    display_name: str
    timezone: str
    language: str
    has_avatar: bool = False


# ----------------------------------------------------------------- Projekte
class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10000)
    goal: str = Field(default="", max_length=5000)
    status: ProjectStatus = "active"
    priority: Priority = "normal"
    start_date: date | None = None
    deadline: date | None = None
    color: str = Field(default="#5B7FD6", pattern=HEX_COLOR)
    categories: list[str] = Field(default_factory=list, max_length=20)
    notes: str = Field(default="", max_length=50000)


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    goal: str | None = Field(default=None, max_length=5000)
    status: ProjectStatus | None = None
    priority: Priority | None = None
    start_date: date | None = None
    deadline: date | None = None
    color: str | None = Field(default=None, pattern=HEX_COLOR)
    categories: list[str] | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=50000)


class ProjectOut(ORM):
    id: int
    name: str
    description: str
    goal: str
    status: str
    priority: str
    start_date: date | None
    deadline: date | None
    color: str
    categories: list[str]
    notes: str
    created_at: datetime
    updated_at: datetime
    ai_summary: str | None = None
    ai_summary_at: datetime | None = None
    progress: int = 0
    task_total: int = 0
    task_done: int = 0
    task_open: int = 0
    task_overdue: int = 0
    next_due: date | None = None


# ----------------------------------------------------------------- Aufgaben
class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=10000)
    status: TaskStatus = "open"
    priority: Priority = "normal"
    project_id: int | None = None
    parent_id: int | None = None
    due_date: date | None = None
    estimated_minutes: int | None = Field(default=None, ge=0, le=100000)
    actual_minutes: int | None = Field(default=None, ge=0, le=100000)
    depends_on: list[int] = Field(default_factory=list, max_length=50)


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=10000)
    status: TaskStatus | None = None
    priority: Priority | None = None
    project_id: int | None = None
    parent_id: int | None = None
    due_date: date | None = None
    estimated_minutes: int | None = Field(default=None, ge=0, le=100000)
    actual_minutes: int | None = Field(default=None, ge=0, le=100000)
    depends_on: list[int] | None = Field(default=None, max_length=50)
    sort_order: int | None = None


class TaskOut(ORM):
    id: int
    title: str
    description: str
    status: str
    priority: str
    project_id: int | None
    parent_id: int | None
    due_date: date | None
    estimated_minutes: int | None
    actual_minutes: int | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    sort_order: int
    depends_on: list[int]
    origin: str
    project_name: str | None = None
    project_color: str | None = None
    subtask_total: int = 0
    subtask_done: int = 0
    overdue: bool = False


# ----------------------------------------------------------------- Kalender
class EventIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    notes: str = Field(default="", max_length=10000)
    location: str = Field(default="", max_length=300)
    start: datetime | None = None
    end: datetime | None = None
    all_day: bool = False
    start_date: date | None = None
    end_date: date | None = None  # inklusiv (letzter Tag)
    rrule: str | None = Field(default=None, max_length=500)
    category_id: int | None = None
    reminders: list[int] = Field(default_factory=list, max_length=5)
    task_id: int | None = None
    project_id: int | None = None
    busy: bool | None = None
    target: Literal["internal", "google"] = "internal"
    google_calendar_id: str | None = None


class EventPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    notes: str | None = Field(default=None, max_length=10000)
    location: str | None = Field(default=None, max_length=300)
    start: datetime | None = None
    end: datetime | None = None
    all_day: bool | None = None
    start_date: date | None = None
    end_date: date | None = None
    rrule: str | None = Field(default=None, max_length=500)
    category_id: int | None = None
    reminders: list[int] | None = Field(default=None, max_length=5)
    task_id: int | None = None
    project_id: int | None = None
    busy: bool | None = None


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    color: str = Field(default="#5B7FD6", pattern=HEX_COLOR)


# ----------------------------------------------------------------- Gedächtnis
class MemoryIn(BaseModel):
    content: str = Field(min_length=1, max_length=5000)
    category: MemoryCategory = "note"
    project_id: int | None = None
    pinned: bool = False


class MemoryPatch(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=5000)
    category: MemoryCategory | None = None
    project_id: int | None = None
    pinned: bool | None = None


class MemoryOut(ORM):
    id: int
    content: str
    category: str
    source: str
    project_id: int | None
    pinned: bool
    created_at: datetime
    updated_at: datetime


# ----------------------------------------------------------------- Chat
class ChatIn(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    via_voice: bool = False
