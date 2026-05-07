"""Celery app — cola para tasks IA pesadas (extracción PDF, embeddings).

Run worker:
    celery -A app.workers.celery_app worker --loglevel=info
"""

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "pedidoflow",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.workers.tasks",
        # "app.workers.embeddings",  # Fase 2
        # "app.workers.sage",        # Fase 5
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Europe/Madrid",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=600,        # 10 min hard limit
    task_soft_time_limit=540,   # 9 min soft limit
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=50,
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=settings.celery_task_always_eager,
    # Beat schedule (cron): poll todas las integraciones Outlook cada 5 min
    beat_schedule={
        "poll-outlook-every-5min": {
            "task": "app.workers.tasks.poll_all_outlook_integrations",
            "schedule": 300.0,  # segundos
        },
    },
)
