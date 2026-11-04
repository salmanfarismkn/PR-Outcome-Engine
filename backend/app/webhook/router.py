from http import HTTPStatus
import logging
import json
from time import perf_counter

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Request,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.webhook.dispatcher import WebhookDispatcher
from app.webhook.exceptions import (
    DuplicateWebhookDelivery,
    WebhookDependencyPending,
)
from app.webhook.service import WebhookService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/webhooks",
    tags=["Webhooks"],
)

webhook_service = WebhookService()
webhook_dispatcher = WebhookDispatcher()


@router.post(
    "/github",
    status_code=HTTPStatus.OK,
)
async def github_webhook(
    request: Request,
    x_github_event: str = Header(
        ...,
        alias="X-GitHub-Event",
    ),
    x_github_delivery: str = Header(
        ...,
        alias="X-GitHub-Delivery",
    ),
    x_hub_signature_256: str | None = Header(
        default=None,
        alias="X-Hub-Signature-256",
    ),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    payload = await request.body()

    if not webhook_service.verify_signature(
        payload=payload,
        signature=x_hub_signature_256,
        secret=settings.github_webhook_secret,
    ):
        logger.warning(
            "Rejected GitHub webhook with invalid signature "
            "(event=%s, delivery=%s)",
            x_github_event,
            x_github_delivery,
        )
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail="Invalid webhook signature.",
        )

    event = webhook_service.get_event(
        db=db,
        delivery_id=x_github_delivery,
    )

    if event is not None:
        if event.status == "processed":
            logger.debug(
                "Ignoring already-processed GitHub delivery %s",
                x_github_delivery,
            )
            return {
                "status": "already_processed",
            }

        if event.status in {"received", "processing"}:
            return {
                "status": "in_progress",
            }

        if event.status == "pending":
            return {
                "status": "pending",
                "reason": event.error_message,
            }
        if event.status == "failed":
            logger.warning(
                "Ignoring failed GitHub webhook delivery "
                "(event=%s, delivery=%s, event_id=%s, attempts=%s)",
                x_github_event,
                x_github_delivery,
                getattr(event, "id", None),
                getattr(event, "attempt_count", 0),
            )
            return {
                "status": "failed",
                "reason": event.error_message,
            }
    else:
        try:
            event = webhook_service.create_event(
                db=db,
                delivery_id=x_github_delivery,
                event_type=x_github_event,
                payload=payload,
            )
        except DuplicateWebhookDelivery as exc:
            event = exc.event
            if event.status == "processed":
                return {
                    "status": "already_processed",
                }
            if event.status in {"received", "processing"}:
                return {
                    "status": "in_progress",
                }
            if event.status == "pending":
                return {
                    "status": "pending",
                    "reason": event.error_message,
                }
            if event.status == "failed":
                return {
                    "status": "failed",
                    "reason": event.error_message,
                }

    try:
        data = webhook_service.parse_payload(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning(
            "GitHub webhook payload is malformed "
            "(event=%s, delivery=%s, event_id=%s, failure_category=payload)",
            x_github_event,
            x_github_delivery,
            getattr(event, "id", None),
        )
        webhook_service.mark_failed(
            db=db,
            event=event,
            error_message=f"Malformed webhook payload: {exc}",
        )
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="Malformed webhook payload.",
        ) from exc

    logger.info(
        "Starting GitHub webhook processing "
        "(event=%s, delivery=%s, event_id=%s, previous_status=%s, "
        "new_status=processing, attempt_count=%s)",
        x_github_event,
        x_github_delivery,
        getattr(event, "id", None),
        event.status,
        getattr(event, "attempt_count", 0) + 1,
    )
    started_at = perf_counter()
    webhook_service.mark_processing(
        db=db,
        event=event,
    )

    try:
        webhook_dispatcher.dispatch(
            db=db,
            event_type=x_github_event,
            payload=data,
            delivery_id=x_github_delivery,
        )

        webhook_service.mark_processed(
            db=db,
            event=event,
        )

        logger.info(
            "GitHub webhook processed successfully "
            "(event=%s, delivery=%s, event_id=%s, new_status=processed, "
            "attempt_count=%s, duration_ms=%.1f)",
            x_github_event,
            x_github_delivery,
            getattr(event, "id", None),
            getattr(event, "attempt_count", 0),
            (perf_counter() - started_at) * 1000,
        )

    except WebhookDependencyPending as exc:
        webhook_service.mark_pending(
            db=db,
            event=event,
            reason=str(exc),
        )

        logger.warning(
            "GitHub webhook remains pending because a dependency "
            "is unavailable (event=%s, delivery=%s, event_id=%s, "
            "new_status=pending, duration_ms=%.1f, failure_category=dependency)",
            x_github_event,
            x_github_delivery,
            getattr(event, "id", None),
            (perf_counter() - started_at) * 1000,
        )

        return {
            "status": "pending",
            "reason": str(exc),
        }

    except Exception as exc:
        logger.exception(
            "GitHub webhook processing failed "
            "(event=%s, delivery=%s, event_id=%s, duration_ms=%.1f, "
            "failure_category=handler)",
            x_github_event,
            x_github_delivery,
            getattr(event, "id", None),
            (perf_counter() - started_at) * 1000,
        )

        try:
            webhook_service.mark_failed(
                db=db,
                event=event,
                error_message=str(exc),
            )
        except SQLAlchemyError:
            logger.exception(
                "Failed to persist failed GitHub webhook status "
                "(event=%s, delivery=%s)",
                x_github_event,
                x_github_delivery,
            )

        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Webhook processing failed.",
        ) from exc

    return {
        "status": "processed",
        "event": x_github_event,
    }
