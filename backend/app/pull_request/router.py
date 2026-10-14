from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.application.pull_request_sync import PullRequestSyncService
from app.db.session import get_db
from app.pull_request.schemas import PullRequestImportSummary, PullRequestResponse
from app.repository.models import Repository
from app.pull_request.models import PullRequest
from app.pull_request.schemas import PullRequestSchema
from app.api.dependencies import require_admin_access

router = APIRouter(
    prefix="/pull-requests",
    tags=["Pull Requests"],
)

pull_request_sync_service = PullRequestSyncService()


@router.get(
    "/{pull_request_id}",
    response_model=PullRequestSchema,
    status_code=HTTPStatus.OK,
)
def get_pull_request(pull_request_id: int, db: Session = Depends(get_db)) -> PullRequest:
    pr = db.get(PullRequest, pull_request_id)
    if pr is None:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Pull request not found.")
    return pr


@router.post(
    "/import/{repository_id}",
    response_model=PullRequestImportSummary,
    status_code=HTTPStatus.OK,
    dependencies=[Depends(require_admin_access)],
)

def import_pull_requests(repository_id: int, db: Session = Depends(get_db)) -> PullRequestImportSummary:
    repository = db.get(Repository, repository_id)
    if repository is None:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Repository not found.")

    summary = pull_request_sync_service.import_pull_requests(db=db, repository=repository)
    if summary is None:
        return PullRequestImportSummary(
            repository_id=repository_id,
            imported=0,
            skipped=0,
            total=0,
            details=[]
        )
    return summary

@router.post(
    "/{pull_request_id}/refresh",
    response_model=PullRequestResponse,
    dependencies=[Depends(require_admin_access)],
)
def refresh_pull_request(
    pull_request_id: int,
    db: Session = Depends(get_db),
):
    pull_request = db.get(
        PullRequest,
        pull_request_id,
    )

    if pull_request is None:
        raise HTTPException(
            status_code=404,
            detail="Pull request not found.",
        )

    return pull_request_sync_service.refresh_pull_request(
        db=db,
        pull_request=pull_request,
    )
