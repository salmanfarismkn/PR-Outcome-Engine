from http import HTTPStatus
import logging

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
from app.webhook.exceptions import WebhookDependencyPending
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

        # Failed events are allowed to retry.
        # Received/processing events are also retriable.
    else:
        event = webhook_service.create_event(
            db=db,
            delivery_id=x_github_delivery,
            event_type=x_github_event,
            payload=payload,
        )

    data = webhook_service.parse_payload(payload)

    logger.info(
        "Starting GitHub webhook processing "
        "(event=%s, delivery=%s)",
        x_github_event,
        x_github_delivery,
    )
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
            "(event=%s, delivery=%s)",
            x_github_event,
            x_github_delivery,
        )

    except WebhookDependencyPending as exc:
        webhook_service.mark_pending(
            db=db,
            event=event,
            reason=str(exc),
        )

        logger.warning(
            "GitHub webhook remains pending because a dependency "
            "is unavailable (event=%s, delivery=%s)",
            x_github_event,
            x_github_delivery,
        )

        return {
            "status": "pending",
            "reason": str(exc),
        }

    except Exception as exc:
        logger.exception(
            "GitHub webhook processing failed "
            "(event=%s, delivery=%s)",
            x_github_event,
            x_github_delivery,
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
