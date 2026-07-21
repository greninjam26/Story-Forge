from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StrictBool,
    StringConstraints,
    model_validator,
)

from app.models import StoryStatus


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
    created_at: datetime


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
