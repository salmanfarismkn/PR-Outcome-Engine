from http import HTTPStatus

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Request,
)
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.webhook.dispatcher import WebhookDispatcher
from app.webhook.service import WebhookService
from app.webhook.exceptions import (
    WebhookDependencyPending,
)
from app import db

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

    data = webhook_service.parse_payload(
        payload
    )

    print(
        "[webhook-debug] endpoint: mark_processing started; "
        f"event={x_github_event!r}, delivery={x_github_delivery}",
        flush=True,
    )
    webhook_service.mark_processing(
        db=db,
        event=event,
    )
    print("[webhook-debug] endpoint: mark_processing returned", flush=True)

    try:
        print("[webhook-debug] endpoint: dispatch started", flush=True)
        webhook_dispatcher.dispatch(
            db=db,
            event_type=x_github_event,
            payload=data,
            delivery_id=x_github_delivery,
        )
        print("[webhook-debug] endpoint: dispatch returned", flush=True)

        print("[webhook-debug] endpoint: mark_processed started", flush=True)
        webhook_service.mark_processed(
            db=db,
            event=event,
        )
        print("[webhook-debug] endpoint: mark_processed returned", flush=True)

    except WebhookDependencyPending as exc:

        print("[webhook-debug] endpoint: mark_pending started", flush=True)
        webhook_service.mark_pending(
            db=db,
            event=event,
            reason=str(exc),
        )
        print("[webhook-debug] endpoint: mark_pending returned", flush=True)

        return {
            "status": "pending",
            "reason": str(exc),
        }

    except Exception as exc:

        print(
            "[webhook-debug] endpoint: mark_failed started; "
            f"error={type(exc).__name__}: {exc}",
            flush=True,
        )
        webhook_service.mark_failed(
            db=db,
            event=event,
            error_message=str(exc),
        )
        print("[webhook-debug] endpoint: mark_failed returned", flush=True)

        raise HTTPException(
            status_code=500,
            detail="Webhook processing failed.",
        ) from exc

    print("Event type:", request.headers.get("X-GitHub-Event"))

    return {
        "status": "processed",
        "event": x_github_event,
    }