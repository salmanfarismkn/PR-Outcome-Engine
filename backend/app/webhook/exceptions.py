class WebhookDependencyPending(Exception):
    """Raised when a webhook depends on data not synchronized yet."""

    def __init__(self, message: str):
        super().__init__(message)


class DuplicateWebhookDelivery(Exception):
    """Raised when another request persisted the same webhook delivery."""

    def __init__(self, event):
        self.event = event
        super().__init__(
            f"Webhook delivery {event.delivery_id!r} already exists."
        )
