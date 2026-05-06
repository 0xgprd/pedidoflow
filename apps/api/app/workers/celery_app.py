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
        # Aquí se registrarán los módulos con tasks (Fase 1+).
        # "app.workers.extraction",
        # "app.workers.embeddings",
        # "app.workers.sage",
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
)
