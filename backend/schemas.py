from typing import Literal
import keyword

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


FallbackReason = Literal[
    "unavailable", "timeout", "http_error", "invalid_output", "translation_unavailable"
]
VisualType = Literal[
    "title_card",
    "concept",
    "flow",
    "code",
    "concept_diagram",
    "process_flow",
    "code_execution",
    "fraction_model",
    "cause_effect",
]


class LessonRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    topic: str = Field(min_length=3, max_length=180)
    level: Literal["beginner", "intermediate"] = "beginner"
    language: Literal["en", "hi", "kn"] = "en"
    duration_seconds: Literal[30, 45, 60, 90] = 60


class CodeExecutionData(BaseModel):
    """Bounded data for a built-in for-loop visualization; this is never executed."""

    model_config = ConfigDict(extra="forbid")

    variable_name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,19}$")
    iterable_name: str = Field(min_length=1, max_length=32)
    values: list[str] = Field(min_length=2, max_length=6)

    @field_validator("variable_name")
    @classmethod
    def reject_keyword_variable(cls, value: str) -> str:
        if keyword.iskeyword(value):
            raise ValueError("variable_name must be a non-keyword identifier")
        return value

    @field_validator("iterable_name")
    @classmethod
    def strip_iterable_name(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError("iterable_name must be printable text")
        return value

    @field_validator("values")
    @classmethod
    def bound_iteration_values(cls, values: list[str]) -> list[str]:
        clean = [value.strip() if isinstance(value, str) else value for value in values]
        if any(not value or len(value) > 32 or any(ord(char) < 32 for char in value) for value in clean):
            raise ValueError("loop values must be printable strings of at most 32 characters")
        return clean


class FractionModelData(BaseModel):
    """A bounded equal-part area model; it contains numbers, never drawing code."""

    model_config = ConfigDict(extra="forbid")

    numerator: int = Field(ge=1, le=8)
    denominator: int = Field(ge=2, le=8)

    @model_validator(mode="after")
    def numerator_fits_whole(self) -> "FractionModelData":
        if self.numerator > self.denominator:
            raise ValueError("numerator cannot exceed the whole")
        return self


class CauseEffectData(BaseModel):
    """Small, display-only labels for a built-in cause/effect demonstration."""

    model_config = ConfigDict(extra="forbid")

    inputs: list[str] = Field(min_length=2, max_length=3)
    mechanism: str = Field(min_length=1, max_length=48)
    outputs: list[str] = Field(min_length=1, max_length=2)

    @field_validator("inputs", "outputs")
    @classmethod
    def bound_labels(cls, labels: list[str]) -> list[str]:
        clean = [label.strip() if isinstance(label, str) else label for label in labels]
        if any(
            not isinstance(label, str)
            or not label
            or len(label) > 48
            or any(ord(char) < 32 for char in label)
            for label in clean
        ):
            raise ValueError("cause/effect labels must be printable and at most 48 characters")
        return clean

    @field_validator("mechanism")
    @classmethod
    def bound_mechanism_label(cls, label: str) -> str:
        label = label.strip()
        if not label or any(ord(char) < 32 for char in label):
            raise ValueError("mechanism must be printable text")
        return label


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=100)
    narration: str = Field(min_length=5, max_length=1200)
    caption: str = Field(min_length=3, max_length=300)
    visual_type: VisualType = "concept"
    visual_data: dict[str, str] = Field(default_factory=dict)
    execution_data: CodeExecutionData | None = None
    fraction_data: FractionModelData | None = None
    cause_effect_data: CauseEffectData | None = None
    pause_seconds: float = Field(default=0.35, ge=0, le=1.5)

    @field_validator("title", "narration", "caption", mode="before")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value

    @field_validator("visual_data")
    @classmethod
    def bound_visual_data(cls, values: dict[str, str]) -> dict[str, str]:
        if len(values) > 16:
            raise ValueError("visual_data may contain at most 16 entries")
        total_characters = 0
        for key, value in values.items():
            if not key.strip() or len(key) > 40:
                raise ValueError("visual_data keys must be non-empty and at most 40 characters")
            if not value.strip() or len(value) > 320:
                raise ValueError("visual_data values must be non-empty and at most 320 characters")
            total_characters += len(key) + len(value)
        if total_characters > 1800:
            raise ValueError("visual_data is too large")
        return values

    @model_validator(mode="after")
    def validate_execution_visual(self) -> "Scene":
        if self.visual_type == "code_execution" and self.execution_data is None:
            raise ValueError("code_execution scenes require bounded execution_data")
        if self.visual_type != "code_execution" and self.execution_data is not None:
            raise ValueError("execution_data is only valid for code_execution scenes")
        if self.visual_type == "fraction_model" and self.fraction_data is None:
            raise ValueError("fraction_model scenes require bounded fraction_data")
        if self.visual_type != "fraction_model" and self.fraction_data is not None:
            raise ValueError("fraction_data is only valid for fraction_model scenes")
        if self.visual_type == "cause_effect" and self.cause_effect_data is None:
            raise ValueError("cause_effect scenes require bounded cause_effect_data")
        if self.visual_type != "cause_effect" and self.cause_effect_data is not None:
            raise ValueError("cause_effect_data is only valid for cause_effect scenes")
        return self


class LessonPlan(BaseModel):
    """Model-owned part of a plan; request metadata and planner status stay server-owned."""

    model_config = ConfigDict(extra="forbid")

    scenes: list[Scene] = Field(min_length=3, max_length=6)


class Lesson(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    topic: str
    level: Literal["beginner", "intermediate"]
    language: Literal["en", "hi", "kn"]
    target_duration_seconds: Literal[30, 45, 60, 90]
    scenes: list[Scene] = Field(min_length=3, max_length=6)
    source: Literal["sample", "ollama"] = "sample"
    fallback: bool = False
    fallback_reason: FallbackReason | None = None

    @field_validator("scenes")
    @classmethod
    def check_scenes(cls, scenes: list[Scene]) -> list[Scene]:
        if len(scenes) < 3:
            raise ValueError("A lesson requires at least three scenes.")
        return scenes

    @model_validator(mode="after")
    def check_planner_status(self) -> "Lesson":
        if self.source == "ollama" and (self.fallback or self.fallback_reason is not None):
            raise ValueError("An Ollama lesson cannot be marked as a sample fallback.")
        if self.fallback and (self.source != "sample" or self.fallback_reason is None):
            raise ValueError("A fallback lesson must identify its sample source and reason.")
        if not self.fallback and self.fallback_reason is not None:
            raise ValueError("fallback_reason is only valid for a fallback lesson.")
        return self


class RenderJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    lesson_id: str
    status: Literal["queued", "rendering", "completed", "failed"]
    output_filename: str
    duration_seconds: float | None = None
    target_duration_seconds: int | None = None
    duration_within_tolerance: bool | None = None

    video_url: str | None = None
    download_url: str | None = None
    captions_url: str | None = None
    manifest_url: str | None = None
    error: str | None = None
