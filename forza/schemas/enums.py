from __future__ import annotations

from enum import Enum

class ValueStrEnum(str, Enum):
    def __str__(self) -> str:
        return self.value

class WeatherType(ValueStrEnum):
    DRY = "dry"
    RAIN = "rain"
    UNKNOWN = "unknown"

class ExtractionStatus(ValueStrEnum):
    """Status of a single image extraction result."""

    OK = "ok"
    ERROR = "error"
    CANCELLED = "cancelled"

class AttemptStatus(ValueStrEnum):
    OK = "ok"
    ERROR = "error"
    CANCELLED = "cancelled"

class RunStatus(ValueStrEnum):
    """Lifecycle status of a complete extraction run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class RunMode(ValueStrEnum):
    NORMAL = "normal"
    DRY_RUN = "dry_run"

class ImageFileStatus(ValueStrEnum):
    AVAILABLE = "available"
    MISSING = "missing"

class BestLapStatus(ValueStrEnum):
    PENDING = "pending"
    CONTRIBUTING = "contributing"
    NON_CONTRIBUTING = "non_contributing"

class ImageProcessingStatus(ValueStrEnum):
    UNPROCESSED = "unprocessed"
    PROCESSING = "processing"
    PROCESSED_OK = "processed_ok"
    PROCESSED_ERROR = "processed_error"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"

class ImageFlagStatus(ValueStrEnum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    IGNORED = "ignored"

class ImageFlagType(ValueStrEnum):
    DUPLICATE = "duplicate"
    DIRTY_LAP = "dirty_lap"
    TRACK = "track"
    WEATHER = "weather"
    RACE_CLASS = "race_class"
    CAR = "car"
    DRIVER_NAME = "driver_name"

class ReviewCaseStatus(ValueStrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    IGNORED = "ignored"
    AUTO_RESOLVED = "auto_resolved"

class ReviewOutcome(ValueStrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    MODEL_ERROR = "model_error"
    IGNORED = "ignored"

class ReviewReason(ValueStrEnum):
    DIRTY_LAP = "dirty_lap"
    TRACK = "track"
    WEATHER = "weather"
    RACE_CLASS = "race_class"
    CAR = "car"
    DRIVER_NAME = "driver_name"

class ReviewTrigger(ValueStrEnum):
    MODEL_MARKED_DIRTY = "model_marked_dirty"
    WEATHER_UNKNOWN = "weather_unknown"
    RAIN_TIME_SUSPICIOUS = "rain_time_suspicious"
    TRACK_UNKNOWN = "track_unknown"
    TRACK_UNRESOLVED = "track_unresolved"
    TRACK_NOT_IN_REFERENCE = "track_not_in_reference"
    CLASS_UNKNOWN = "class_unknown"
    CLASS_INVALID = "class_invalid"
    CAR_EMPTY = "car_empty"
    CAR_NOT_IN_REFERENCE = "car_not_in_reference"
    DRIVER_NAME_EMPTY = "driver_name_empty"
    NUMERIC_PREFIX = "numeric_prefix"
    INVALID_SYMBOL = "invalid_symbol"

class ReviewDecisionField(ValueStrEnum):
    DIRTY = "dirty"
    TRACK = "track"
    WEATHER = "weather"
    RACE_CLASS = "race_class"
    CAR = "car"
    DRIVER = "driver"

class CorrectionCause(ValueStrEnum):
    REVIEW = "review"
    REBUILD = "rebuild"
    AUTO = "auto"
    UNKNOWN = "unknown"

class RuntimeSnapshotKind(ValueStrEnum):
    PREFLIGHT = "preflight"

class ExportFormat(ValueStrEnum):
    CSV = "csv"
    PDF = "pdf"

class RaceClass(ValueStrEnum):
    E = "E"
    D = "D"
    C = "C"
    B = "B"
    A = "A"
    TCR = "TCR"
    S = "S"
    R = "R"
    P = "P"
    X = "X"
    MIXED = "Mixed"
    UNKNOWN = "Unknown"
