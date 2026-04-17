"""Celery task entrypoint for local WSL2 worker execution."""

from celery import Celery


celery_app = Celery(
    "teamslack",
    broker="redis://localhost:6379/1",
    backend="redis://localhost:6379/2",
    include=["services.orchestrator.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)


@celery_app.task(name="teamslack.ping")
def ping() -> str:
    """Simple health task for worker verification."""
    return "pong"
