"""Email log wire schemas (camelCase; status uppercased for the frontend)."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.email_outbox import EmailOutbox
from app.schemas.base import ApiModel


class EmailLogItem(ApiModel):
    id: str
    to_email: str = Field(serialization_alias="toEmail")
    subject: str
    template_key: str = Field(serialization_alias="templateKey")
    status: str
    attempts: int
    used_fallback: bool = Field(serialization_alias="usedFallback")
    created_at: datetime = Field(serialization_alias="createdAt")
    sent_at: Optional[datetime] = Field(default=None, serialization_alias="sentAt")
    next_attempt_at: Optional[datetime] = Field(default=None, serialization_alias="nextAttemptAt")

    @classmethod
    def from_row(cls, row: EmailOutbox) -> "EmailLogItem":
        return cls(
            id=row.id,
            to_email=row.to_email,
            subject=row.subject,
            template_key=row.template_key,
            status=row.status.upper(),
            attempts=row.attempts,
            used_fallback=row.used_fallback,
            created_at=row.created_at,
            sent_at=row.sent_at,
            next_attempt_at=row.next_attempt_at,
        )


class EmailLogDetail(EmailLogItem):
    html_body: str = Field(serialization_alias="htmlBody")
    text_body: str = Field(serialization_alias="textBody")
    last_error: Optional[str] = Field(default=None, serialization_alias="lastError")
    connection_id: Optional[str] = Field(default=None, serialization_alias="connectionId")

    @classmethod
    def from_row(cls, row: EmailOutbox) -> "EmailLogDetail":
        item = EmailLogItem.from_row(row)
        return cls(
            **item.model_dump(by_alias=False),
            html_body=row.html_body,
            text_body=row.text_body,
            last_error=row.last_error,
            connection_id=row.connection_id,
        )


class EmailLogListResponse(BaseModel):
    data: List[EmailLogItem]
    total: int
    page: int


class EmailLogNeighborResponse(BaseModel):
    email: Optional[EmailLogItem]
    total: int
