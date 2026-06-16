"""Common response schemas."""

from typing import Generic, List, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageResponse(BaseModel, Generic[T]):
    items: List[T]
    total: int
    page: int
    size: int


class HealthResponse(BaseModel):
    status: str = "ok"
    app: str


class MessageResponse(BaseModel):
    message: str


class JobStatusResponse(BaseModel):
    id: int
    job_type: str
    status: str
    progress: int = Field(ge=0, le=100)
    message: str | None = None
    error: str | None = None
