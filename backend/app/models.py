"""Datenbankmodell von MOSI PLAN.

Alle fachlichen Daten (Projekte, Aufgaben, Termine, Gedächtnis, Wochenpläne)
liegen ausschließlich in dieser Datenbank. Hermes ist nur die Agentenebene.
"""
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    literal_column,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Berlin", nullable=False)
    language: Mapped[str] = mapped_column(String(8), default="de", nullable=False)
    avatar_path: Mapped[str | None] = mapped_column(String(255))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(Base):
    __tablename__ = "user_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # SHA-256 des Tokens
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    user_agent: Mapped[str] = mapped_column(String(255), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict | list | str | None] = mapped_column(JSONType)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    goal: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    priority: Mapped[str] = mapped_column(String(20), default="normal", nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    deadline: Mapped[date | None] = mapped_column(Date)
    color: Mapped[str] = mapped_column(String(16), default="#5B7FD6", nullable=False)
    categories: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    ai_summary_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tasks: Mapped[list["Task"]] = relationship(back_populates="project")


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    priority: Mapped[str] = mapped_column(String(20), default="normal", nullable=False)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    due_date: Mapped[date | None] = mapped_column(Date)
    estimated_minutes: Mapped[int | None] = mapped_column(Integer)
    actual_minutes: Mapped[int | None] = mapped_column(Integer)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    depends_on: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    origin: Mapped[str] = mapped_column(String(20), default="user", nullable=False)

    project: Mapped[Project | None] = relationship(back_populates="tasks")

    __table_args__ = (Index("ix_tasks_status_due", "status", "due_date"), Index("ix_tasks_project", "project_id"))


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    color: Mapped[str] = mapped_column(String(16), default="#5B7FD6", nullable=False)


class GoogleCalendar(Base):
    __tablename__ = "google_calendars"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    google_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    summary: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    color: Mapped[str] = mapped_column(String(16), default="#4C8DF6", nullable=False)
    access_role: Mapped[str] = mapped_column(String(32), default="reader", nullable=False)
    primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class CalendarEvent(TimestampMixin, Base):
    """Termin. source='internal' (MOSI-Kalender) oder 'google' (gespiegelt)."""

    __tablename__ = "calendar_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(16), default="internal", nullable=False)
    google_calendar_id: Mapped[str | None] = mapped_column(String(255))
    external_id: Mapped[str | None] = mapped_column(String(1024))
    etag: Mapped[str | None] = mapped_column(String(255))
    recurring_event_id: Mapped[str | None] = mapped_column(String(1024))
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    location: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    all_day: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Berlin", nullable=False)
    busy: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    rrule: Mapped[str | None] = mapped_column(String(500))
    exdates: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    reminders: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    origin: Mapped[str] = mapped_column(String(20), default="user", nullable=False)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sync_state: Mapped[str] = mapped_column(String(16), default="local", nullable=False)

    __table_args__ = (
        UniqueConstraint("source", "google_calendar_id", "external_id", name="uq_event_external"),
        Index("ix_events_range", "start_at", "end_at"),
    )


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default="Neues Gespräch", nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    summarized_until: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    meta: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_messages_conv", "conversation_id", "id"),)


class PendingAction(Base):
    """Vom Assistenten vorbereitete Aktion, die eine explizite Bestätigung braucht."""

    __tablename__ = "pending_actions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tool: Mapped[str] = mapped_column(String(64), nullable=False)
    args: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    preview: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    result: Mapped[dict | None] = mapped_column(JSONType)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MemoryEntry(TimestampMixin, Base):
    __tablename__ = "memory_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(32), default="note", nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="user", nullable=False)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (Index("ix_memory_fts", func.to_tsvector(literal_column("'german'"), content), postgresql_using="gin"),)


class WeeklyPlan(Base):
    __tablename__ = "weekly_plans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    week_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), default="draft", nullable=False)
    generated_by: Mapped[str] = mapped_column(String(16), default="user", nullable=False)
    data: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list["WeeklyPlanItem"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="WeeklyPlanItem.start_at"
    )


class WeeklyPlanItem(Base):
    __tablename__ = "weekly_plan_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("weekly_plans.id", ondelete="CASCADE"), nullable=False)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    priority: Mapped[str] = mapped_column(String(20), default="normal", nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="planned", nullable=False)  # planned/moved/removed
    original_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    event_id: Mapped[int | None] = mapped_column(ForeignKey("calendar_events.id", ondelete="SET NULL"))
    note: Mapped[str] = mapped_column(String(300), default="", nullable=False)

    plan: Mapped[WeeklyPlan] = relationship(back_populates="items")


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    link: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    dedupe_key: Mapped[str | None] = mapped_column(String(255), unique=True)
    channels: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False)
    p256dh: Mapped[str] = mapped_column(String(255), nullable=False)
    auth: Mapped[str] = mapped_column(String(255), nullable=False)
    user_agent: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(16), default="user", nullable=False)  # user/assistant/system
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    entity_id: Mapped[int | None] = mapped_column(Integer)
    project_id: Mapped[int | None] = mapped_column(Integer, index=True)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    data: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    ip: Mapped[str] = mapped_column(String(64), default="", nullable=False)
