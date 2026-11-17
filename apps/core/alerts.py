"""Optional failure notifications. Disabled unless explicitly configured in environment."""
import logging
import os
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.mail import send_mail

log = logging.getLogger(__name__)


def notify_backup_failure(device, message):
    """Send configured alerts with short timeouts; never fail a backup because alerting failed."""
    title = f"VAULT FAILED: {getattr(device, 'name', '') or device.ip} ({device.ip})"
    body = f"{title}\nTime: {__import__('django.utils.timezone', fromlist=['now']).now()}\nDetails: {message[:1500]}"
    token = os.environ.get('DBMS_TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = os.environ.get('DBMS_TELEGRAM_CHAT_ID', '').strip()
    if token and chat_id:
        try:
            data = urllib.parse.urlencode({'chat_id': chat_id, 'text': body}).encode()
            req = urllib.request.Request(f'https://api.telegram.org/bot{token}/sendMessage', data=data)
            with urllib.request.urlopen(req, timeout=3) as response:
                response.read(256)
        except Exception:
            log.warning('Telegram failure alert could not be delivered', exc_info=True)
    recipients = [x.strip() for x in os.environ.get('DBMS_ALERT_EMAILS', '').split(',') if x.strip()]
    if recipients:
        try:
            send_mail(title, body, getattr(settings, 'DEFAULT_FROM_EMAIL', None), recipients,
                      fail_silently=False)
        except Exception:
            log.warning('Email failure alert could not be delivered', exc_info=True)
