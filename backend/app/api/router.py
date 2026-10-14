from fastapi import APIRouter, Depends

from app.api.dependencies import require_read_access
from app.repository.router import router as repository_router
from app.github.router import router as github_router
from app.pull_request.router import router as pull_request_router
from app.commit.router import router as commit_router
from app.analysis.router import router as analysis_router
from app.changed_file.router import router as changed_file_router
from app.risk.router import router as risk_router
from app.review.router import router as review_router
from app.check.router import router as check_router
from app.feature.router import router as feature_router
from app.outcome.router import router as outcome_router
from app.dataset.router import router as dataset_router

router = APIRouter(dependencies=[Depends(require_read_access)])

router.include_router(repository_router)
router.include_router(github_router)
router.include_router(pull_request_router)
router.include_router(commit_router)
router.include_router(analysis_router)
router.include_router(changed_file_router)
router.include_router(risk_router)
router.include_router(review_router)
router.include_router(check_router)
router.include_router(feature_router)
router.include_router(outcome_router)
router.include_router(dataset_router)