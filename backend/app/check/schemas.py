from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CheckRunResponse(BaseModel):
    id: int
    github_id: int
    pull_request_id: int

    name: str
    status: str
    conclusion: str | None

    details_url: str | None

    started_at: datetime | None
    completed_at: datetime | None

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
    )


class CheckRunImportSummary(BaseModel):
    imported: int
    skipped: int
    total: int
    updated: int = 0