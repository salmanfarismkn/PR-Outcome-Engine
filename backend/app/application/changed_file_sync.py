from sqlalchemy.orm import Session

from app.changed_file.service import ChangedFileService
from app.changed_file.schemas import ChangedFileImportSummary


class ChangedFileSyncService:
    def __init__(self) -> None:
        self._changed_file_service = ChangedFileService()

    def import_changed_files(
        self,
        db: Session,
        owner: str,
        repository: str,
        pull_number: int,
        commit_id: int,
    ) -> ChangedFileImportSummary:
        """
        Synchronize changed files for a given commit in a pull request.
        """

        imported_files = self._changed_file_service.import_changed_files(
            db=db,
            owner=owner,
            repository=repository,
            pull_number=pull_number,
            commit_id=commit_id,
        )
        return ChangedFileImportSummary(
            commit_id=commit_id,
            imported=len(imported_files),
        )
