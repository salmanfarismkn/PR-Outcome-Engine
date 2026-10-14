from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.schemas import PullRequestMetrics
from app.changed_file.models import ChangedFile
from app.analysis.classifier import FileClassifier
from app.check.models import CheckRun

from app.review.models import Review

class AnalysisService:
    """Calculates deterministic metrics from persisted PR data."""

    def calculate_metrics(
        self,
        db: Session,
        pull_request_id: int,
    ) -> PullRequestMetrics:

        files = list(
            db.scalars(
                select(ChangedFile)
                .where(
                    ChangedFile.pull_request_id == pull_request_id
                )
            )
        )

        total_files = len(files)

        source_files = 0
        test_files = 0
        documentation_files = 0
        config_files = 0
        binary_files = 0

        renamed_files = 0
        deleted_files = 0

        added_lines = 0
        deleted_lines = 0
        security_sensitive_files = 0
        dependency_files = 0
        database_files = 0
        ci_files = 0
        largest_file_changes = 0

        for file in files:
            filename = file.filename.lower()

            if self._is_source_file(filename):
                source_files += 1

            if self._is_test_file(filename):
                test_files += 1

            if self._is_documentation(filename):
                documentation_files += 1

            if self._is_config_file(filename):
                config_files += 1

            if file.patch is None:
                binary_files += 1

            if file.status == "renamed":
                renamed_files += 1

            if file.status == "removed":
                deleted_files += 1

            added_lines += file.additions
            deleted_lines += file.deletions
            file_changes = file.additions + file.deletions

            largest_file_changes = max(
                largest_file_changes,
                file_changes,
            )

            if FileClassifier.is_security_sensitive(file.filename):
                security_sensitive_files += 1

            if FileClassifier.is_dependency_file(file.filename):
                dependency_files += 1

            if FileClassifier.is_database_related(file.filename):
                database_files += 1

            if FileClassifier.is_ci_related(file.filename):
                ci_files += 1

        check_runs = list(
            db.scalars(
                select(CheckRun).where(CheckRun.pull_request_id == pull_request_id)
            )
        )

        check_count = len(check_runs)

        successful_check_count = sum(
            1
            for check in check_runs
            if check.conclusion == "success"
        )

        failed_check_count = sum(
            1
            for check in check_runs
            if check.conclusion in {
                "failure",
                "timed_out",
                "action_required",
                "cancelled",
            }
        )

        pending_check_count = sum(
            1
            for check in check_runs
            if check.status != "completed"
        )

        reviews = list(
            db.scalars(
                select(Review)
                .where(
                    Review.pull_request_id == pull_request_id
                )
            )
        )
        review_count = len(reviews)

        approved_review_count = sum(
            1
            for review in reviews
            if review.state.upper() == "APPROVED"
        )

        changes_requested_count = sum(
            1
            for review in reviews
            if review.state.upper() == "CHANGES_REQUESTED"
        )

        unique_reviewer_count = len(
            {
                review.reviewer_login
                for review in reviews
                if review.reviewer_login
            }
        )
        return PullRequestMetrics(
            total_files=total_files,
            source_files=source_files,
            test_files=test_files,
            documentation_files=documentation_files,
            config_files=config_files,
            binary_files=binary_files,
            renamed_files=renamed_files,
            deleted_files=deleted_files,
            added_lines=added_lines,
            deleted_lines=deleted_lines,
            total_changes=added_lines + deleted_lines,
            security_sensitive_files=security_sensitive_files,
            dependency_files=dependency_files,
            database_files=database_files,
            ci_files=ci_files,
            largest_file_changes=largest_file_changes,
            review_count=review_count,
            approved_review_count=approved_review_count,
            changes_requested_count=changes_requested_count,
            unique_reviewer_count=unique_reviewer_count,

            check_count=check_count,
            successful_check_count=successful_check_count,
            failed_check_count=failed_check_count,
            pending_check_count=pending_check_count,
        )

    @staticmethod
    def _is_test_file(filename: str) -> bool:
        path = PurePosixPath(filename)

        test_directories = {
            "test",
            "tests",
            "__tests__",
        }

        if any(
            directory in test_directories
            for directory in path.parts
        ):
            return True

        return (
            ".test." in filename
            or ".spec." in filename
            or filename.startswith("test_")
        )

    @staticmethod
    def _is_documentation(filename: str) -> bool:
        path = PurePosixPath(filename)

        documentation_extensions = {
            ".md",
            ".mdx",
            ".rst",
            ".txt",
        }

        documentation_directories = {
            "docs",
            "documentation",
        }

        if path.suffix in documentation_extensions:
            return True

        return any(
            directory in documentation_directories
            for directory in path.parts
        )

    @staticmethod
    def _is_config_file(filename: str) -> bool:
        path = PurePosixPath(filename)

        config_names = {
            ".env",
            ".env.example",
            "dockerfile",
            "docker-compose.yml",
            "docker-compose.yaml",
            "package.json",
            "tsconfig.json",
            "pyproject.toml",
            "alembic.ini",
        }

        if path.name in config_names:
            return True

        config_extensions = {
            ".yml",
            ".yaml",
            ".toml",
            ".ini",
            ".conf",
            ".config",
        }

        return path.suffix in config_extensions

    @staticmethod
    def _is_source_file(filename: str) -> bool:
        path = PurePosixPath(filename)

        source_extensions = {
            ".py",
            ".js",
            ".jsx",
            ".ts",
            ".tsx",
            ".java",
            ".go",
            ".rs",
            ".cpp",
            ".c",
            ".h",
            ".hpp",
            ".cs",
            ".php",
            ".rb",
            ".swift",
            ".kt",
            ".kts",
        }

        return path.suffix in source_extensions