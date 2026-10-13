from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.application.repository_sync import RepositorySyncService
from app.db.session import get_db
from app.github.schemas import GitHubUser
from app.github.service import GitHubService
from app.repository.schemas import RepositoryImportSummary
from app.api.dependencies import require_admin_access

router = APIRouter(
    prefix="/github",
    tags=["GitHub"],
)

github_service = GitHubService()
repository_sync_service = RepositorySyncService()


@router.get(
    "/me",
    response_model=GitHubUser,
)
def get_me() -> GitHubUser:
    return github_service.get_authenticated_user()


@router.post(
    "/repositories/import",
    response_model=RepositoryImportSummary,
    dependencies=[Depends(require_admin_access)],
)
def import_repositories_endpoint(
    db: Session = Depends(get_db),
) -> RepositoryImportSummary:
    return repository_sync_service.import_repositories(db)