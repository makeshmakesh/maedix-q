import json
import logging
import redis
from celery import shared_task

logger = logging.getLogger('instagram')

QUEUE_MAX_SIZE = 500


@shared_task
def trim_queue():
    """Flush the Celery queue if it exceeds QUEUE_MAX_SIZE"""
    r = redis.Redis(host='localhost', port=6379, db=0)
    queue_size = r.llen('celery')
    if queue_size > QUEUE_MAX_SIZE:
        r.delete('celery')
        logger.warning(f"Queue trimmed: {queue_size} tasks were stale, queue flushed")


@shared_task(bind=True, max_retries=2, default_retry_delay=10)
def process_comment_task(self, comment_data, ig_business_account_id):
    """Process a comment webhook event in background"""
    try:
        from instagram.views import InstagramWebhookView
        view = InstagramWebhookView()
        view.handle_comment(comment_data, ig_business_account_id)
    except Exception as exc:
        logger.error(f"Celery comment task failed: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2, default_retry_delay=10)
def process_message_task(self, messaging_data, ig_business_account_id):
    """Process a message webhook event in background"""
    try:
        from instagram.views import InstagramWebhookView
        view = InstagramWebhookView()
        view.handle_message(messaging_data, ig_business_account_id)
    except Exception as exc:
        logger.error(f"Celery message task failed: {exc}")
        raise self.retry(exc=exc)
