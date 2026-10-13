from fastapi import APIRouter, Depends, HTTPException
from http import HTTPStatus
from sqlalchemy.orm import Session

from app.core.exceptions import RepositoryAlreadyExistsError
from app.db.session import get_db
from app.repository.schemas import (
    RepositoryCreate,
    RepositoryResponse,
)
from app.repository.service import RepositoryService
from app.api.dependencies import require_admin_access

router = APIRouter(
    prefix="/repositories",
    tags=["Repositories"],
)

# Instantiate the service once
repository_service = RepositoryService()


@router.post(
    "",
    response_model=RepositoryResponse,
    status_code=HTTPStatus.CREATED,
    dependencies=[Depends(require_admin_access)],
)
def create(
    payload: RepositoryCreate,
    db: Session = Depends(get_db),
):
    try:
        return repository_service.create_repository(db, payload)
    except RepositoryAlreadyExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        )


@router.get(
    "",
    response_model=list[RepositoryResponse],
)
def list_repositories(db: Session = Depends(get_db)):
    return repository_service.list(db)
