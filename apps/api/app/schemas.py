from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StrictBool,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.models import GenerationStage, StoryStatus
from app.services import storage


Locale = Literal["en", "fr"]
StoryLanguage = Literal["en", "fr"]
ChildName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
ChildAge = Annotated[int, Field(ge=1, le=12)]
ChildInterests = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=500)
]
StoryEventText = Annotated[
    str, StringConstraints(strip_whitespace=True,
                           min_length=1, max_length=2000)
]
StoryTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
StoryPageText = Annotated[
    str, StringConstraints(strip_whitespace=True,
                           min_length=1, max_length=2500)
]
StoryPages = Annotated[list[StoryPageText], Field(min_length=1, max_length=12)]


class ParentCreate(BaseModel):
    email: EmailStr
    locale: Locale = "en"


class ParentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    locale: Locale
    is_subscribed: bool = False
    free_stories_used: int = 0
    created_at: datetime

    @model_validator(mode="before")
    @classmethod
    def _coerce_billing_defaults(cls, data: Any) -> Any:
        if hasattr(data, "is_subscribed"):
            if data.is_subscribed is None:
                data.is_subscribed = False
            if data.free_stories_used is None:
                data.free_stories_used = 0
        return data


class ParentRegister(BaseModel):
    email: EmailStr
    password: Annotated[str, StringConstraints(min_length=8, max_length=128)]
    locale: Locale = "en"


class ParentLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ChildCreate(BaseModel):
    name: ChildName
    age: ChildAge
    interests: ChildInterests = ""
    language: StoryLanguage = "en"


class ChildUpdate(BaseModel):
    name: ChildName | None = None
    age: ChildAge | None = None
    interests: ChildInterests | None = None
    language: StoryLanguage | None = None

    @model_validator(mode="after")
    def reject_null_fields(self) -> Self:
        null_fields = [
            field_name
            for field_name in self.model_fields_set
            if getattr(self, field_name) is None
        ]
        if null_fields:
            raise ValueError(
                f"Fields cannot be null: {', '.join(null_fields)}")
        return self


class ChildOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    parent_id: UUID
    name: str
    age: int
    interests: str
    language: StoryLanguage
    created_at: datetime


class StoryCreate(BaseModel):
    child_id: UUID
    event_text: StoryEventText


class StoryApprove(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approve: StrictBool


class StoryPageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_number: Annotated[int, Field(strict=True, ge=1, le=12)]
    text: StoryPageText


StoryPageUpdates = Annotated[
    list[StoryPageUpdate], Field(min_length=1, max_length=12)
]


class StoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: StoryTitle | None = None
    pages: StoryPageUpdates | None = None

    @model_validator(mode="after")
    def validate_changes(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one story change is required.")

        null_fields = [
            field_name
            for field_name in self.model_fields_set
            if getattr(self, field_name) is None
        ]
        if null_fields:
            raise ValueError(
                f"Fields cannot be null: {', '.join(null_fields)}"
            )

        if self.pages is not None:
            page_numbers = [page.page_number for page in self.pages]
            if len(page_numbers) != len(set(page_numbers)):
                raise ValueError("Story page numbers must be unique.")

        return self


class StoryGenerationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: StoryTitle
    pages: StoryPages


class StoryPageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    page_number: int
    text: str
    image_url: str | None
    audio_url: str | None

    @field_validator("image_url", "audio_url")
    @classmethod
    def resolve_asset_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not storage.is_managed_reference(value):
            return value
        return storage.resolve_url(value)


class ReaderStoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    child_id: UUID
    title: str
    language: StoryLanguage
    created_at: datetime
    pages: list[StoryPageOut]


class StoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    child_id: UUID
    title: str
    language: StoryLanguage
    status: StoryStatus
    failure_reason: str | None
    cost_usd: Decimal
    created_at: datetime
    approved_at: datetime | None
    pages: list[StoryPageOut]
    generation_stage: GenerationStage


class StoryDetailOut(StoryOut):
    event_text: str
    safety_reason: str | None
