from datetime import datetime

from pydantic import BaseModel


class PRFeatureSnapshot(BaseModel):
    pull_request_id: int

    # PR size
    additions: int
    deletions: int
    changed_files: int

    # Commit activity
    commit_count: int
    unique_authors: int

    # Review activity
    review_count: int
    unique_reviewers: int
    approvals: int
    change_requests: int

    # CI
    check_count: int
    successful_checks: int
    failed_checks: int
    pending_checks: int

    # Repository / PR context
    is_draft: bool
  

    # Temporal information
    created_at: datetime
    age_hours: float