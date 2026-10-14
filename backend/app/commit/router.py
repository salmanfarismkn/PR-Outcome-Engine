from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.application.commit_sync import CommitSyncService
from app.commit.schemas import CommitImportSummary
from app.db.session import get_db
from app.pull_request.models import PullRequest
from app.api.dependencies import require_admin_access

router = APIRouter(
    prefix="/commits",
    tags=["Commits"],
)

commit_sync_service = CommitSyncService()


@router.post(
    "/import/{pull_request_id}",
    response_model=CommitImportSummary,
    status_code=HTTPStatus.OK,
    dependencies=[Depends(require_admin_access)],
)
def import_commits(
    pull_request_id: int,
    db: Session = Depends(get_db),
) -> CommitImportSummary:

    pull_request = db.get(
        PullRequest,
        pull_request_id,
    )

    if pull_request is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="Pull request not found.",
        )

    return commit_sync_service.import_commits(
        db=db,
        pull_request=pull_request,
    )