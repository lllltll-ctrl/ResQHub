"""
SQLAlchemy ORM-моделі домену ResQHub.

Моделі: Object, Telemetry, Score, Scenario, Assignment, Event.
Всі сутності використовують UUID PK та таймстампи у UTC.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ObjectType(str, enum.Enum):
    SHELTER = "SHELTER"
    SCHOOL = "SCHOOL"
    RESILIENCE_POINT = "RESILIENCE_POINT"
    HOSPITAL = "HOSPITAL"
    FIRE_STATION = "FIRE_STATION"


class ObjectCriticality(int, enum.Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4
    EMERGENCY = 5


class ScoreStatus(str, enum.Enum):
    STABLE = "STABLE"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    RESCUE_IN_TRANSIT = "RESCUE_IN_TRANSIT"


class ScenarioType(str, enum.Enum):
    NORMAL = "NORMAL"
    BLACKOUT = "BLACKOUT"
    PARTIAL_OUTAGE = "PARTIAL_OUTAGE"
    SIGNAL_DOWN = "SIGNAL_DOWN"
    RESET = "RESET"


class ScenarioScope(str, enum.Enum):
    CITY = "CITY"
    DISTRICT = "DISTRICT"
    OBJECT = "OBJECT"


class ResourceType(str, enum.Enum):
    GENERATOR = "GENERATOR"
    BATTERY_BANK = "BATTERY_BANK"
    STARLINK = "STARLINK"
    TECH_TEAM = "TECH_TEAM"
    FUEL = "FUEL"


class AssignmentStatus(str, enum.Enum):
    REQUESTED = "REQUESTED"
    DISPATCHED = "DISPATCHED"
    ARRIVED = "ARRIVED"
    CANCELLED = "CANCELLED"


class EventType(str, enum.Enum):
    STATUS_CHANGE = "STATUS_CHANGE"
    ALERT = "ALERT"
    ASSIGNMENT = "ASSIGNMENT"
    SCENARIO_START = "SCENARIO_START"
    SCENARIO_END = "SCENARIO_END"
    MANUAL = "MANUAL"


class EventSeverity(str, enum.Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class Object(Base):
    __tablename__ = "objects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[ObjectType] = mapped_column(
        Enum(ObjectType), nullable=False, index=True
    )
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    district: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    address: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    criticality: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    battery_capacity_wh: Mapped[float] = mapped_column(
        Float, nullable=False, default=5000.0
    )
    has_generator: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_starlink: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    telemetry: Mapped[list[Telemetry]] = relationship(
        back_populates="object", cascade="all, delete-orphan"
    )
    scores: Mapped[list[Score]] = relationship(
        back_populates="object", cascade="all, delete-orphan"
    )
    assignments: Mapped[list[Assignment]] = relationship(
        back_populates="object", cascade="all, delete-orphan"
    )


class Telemetry(Base):
    __tablename__ = "telemetry"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    object_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("objects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    power_on: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    battery_pct: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    battery_est_hours: Mapped[float] = mapped_column(
        Float, nullable=False, default=24.0
    )
    temp_c: Mapped[float] = mapped_column(Float, nullable=False, default=21.0)
    humidity_pct: Mapped[float] = mapped_column(Float, nullable=False, default=45.0)
    co2_ppm: Mapped[float] = mapped_column(Float, nullable=False, default=600.0)
    signal: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    internet_on: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    occupancy: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    generator_on: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    scenario_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scenarios.id", ondelete="SET NULL"),
        nullable=True,
    )

    object: Mapped[Object] = relationship(back_populates="telemetry")

    __table_args__ = (
        CheckConstraint(
            "battery_pct >= 0 AND battery_pct <= 100", name="ck_telemetry_battery_range"
        ),
        CheckConstraint(
            "signal >= 0 AND signal <= 4", name="ck_telemetry_signal_range"
        ),
        CheckConstraint("occupancy >= 0", name="ck_telemetry_occupancy_nonneg"),
    )


class Score(Base):
    __tablename__ = "scores"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    object_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("objects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    score: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    status: Mapped[ScoreStatus] = mapped_column(
        Enum(ScoreStatus), nullable=False, default=ScoreStatus.STABLE
    )
    time_to_critical_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    components: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    object: Mapped[Object] = relationship(back_populates="scores")

    __table_args__ = (
        CheckConstraint("score >= 0 AND score <= 100", name="ck_score_range"),
    )


class Scenario(Base):
    __tablename__ = "scenarios"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    type: Mapped[ScenarioType] = mapped_column(Enum(ScenarioType), nullable=False)
    scope: Mapped[ScenarioScope] = mapped_column(
        Enum(ScenarioScope), nullable=False, default=ScenarioScope.CITY
    )
    target: Mapped[str | None] = mapped_column(String(200), nullable=True)
    intensity: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True
    )


class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    object_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("objects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resource_type: Mapped[ResourceType] = mapped_column(
        Enum(ResourceType), nullable=False
    )
    status: Mapped[AssignmentStatus] = mapped_column(
        Enum(AssignmentStatus), nullable=False, default=AssignmentStatus.REQUESTED
    )
    eta_min: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    priority_score: Mapped[float] = mapped_column(Float, nullable=False, default=50.0)
    justification: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    object: Mapped[Object] = relationship(back_populates="assignments")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    object_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("objects.id", ondelete="SET NULL"), nullable=True
    )
    scenario_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scenarios.id", ondelete="SET NULL"),
        nullable=True,
    )
    type: Mapped[EventType] = mapped_column(Enum(EventType), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[EventSeverity] = mapped_column(
        Enum(EventSeverity), nullable=False, default=EventSeverity.INFO
    )
