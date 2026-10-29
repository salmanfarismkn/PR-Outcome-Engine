from unittest.mock import Mock

from app.application.changed_file_sync import ChangedFileSyncService


def test_changed_file_sync_fetches_and_imports_files_once(
    monkeypatch,
) -> None:
    importer = Mock()
    importer.import_changed_files.return_value = [object(), object()]
    monkeypatch.setattr(
        "app.application.changed_file_sync.ChangedFileService",
        lambda: importer,
    )
    service = ChangedFileSyncService()
    db = Mock()

    summary = service.import_changed_files(
        db=db,
        owner="owner",
        repository="repo",
        pull_number=42,
        commit_id=123,
    )

    importer.import_changed_files.assert_called_once_with(
        db=db,
        owner="owner",
        repository="repo",
        pull_number=42,
        commit_id=123,
    )
    assert summary.commit_id == 123
    assert summary.imported == 2
