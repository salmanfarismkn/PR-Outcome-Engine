from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db

from app.application.changed_file_sync import ChangedFileSyncService
from app.changed_file.schemas import ChangedFileImportSummary
from app.api.dependencies import require_admin_access

router = APIRouter(prefix="/changed-files", tags=["changed-files"])


@router.post(
    "/import/{commit_id}",
    response_model=ChangedFileImportSummary,
    dependencies=[Depends(require_admin_access)],
)
def import_changed_files(
    commit_id: int,
    owner: str,
    repository: str,
    pull_number: int,
    db: Session = Depends(get_db),
) -> ChangedFileImportSummary:
    """
    Import changed files for a given commit in a pull request.
    """
    service = ChangedFileSyncService()
    return service.import_changed_files(
        db=db,
        owner=owner,
        repository=repository,
        pull_number=pull_number,
        commit_id=commit_id,
    )
