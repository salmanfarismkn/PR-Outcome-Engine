from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ReviewResponse(BaseModel):
    id: int
    github_id: int
    pull_request_id: int
    reviewer_login: str
    state: str
    body: str | None
    submitted_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
    )


class ReviewImportSummary(BaseModel):
    imported: int
    updated: int = 0
    skipped: int
    total: int