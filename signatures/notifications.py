"""
Module-scoped notifications.

Helper for fanning out a notification to every user who has read access to a
given business module (plus all ADMIN users). Used across Purchase, Sales,
Finance, Transport and Returns so people only get alerts for the modules they
actually work in.

PI/PO *verification* notifications are intentionally NOT routed through here —
those stay targeted to the specific assigned verifiers (see services.py).
"""
import logging

from django.contrib.contenttypes.models import ContentType
from django.contrib.auth import get_user_model

from .models import Notification

logger = logging.getLogger(__name__)


def module_recipients(module, exclude_user=None):
    """
    Return a set of user ids that should receive notifications for `module`:
    everyone with can_read on that module, plus all ADMIN-role users.
    """
    from accounts.models import UserModulePermission

    User = get_user_model()
    ids = set(
        UserModulePermission.objects.filter(
            module=module, can_read=True
        ).values_list('user_id', flat=True)
    )
    ids |= set(User.objects.filter(role='ADMIN').values_list('id', flat=True))
    if exclude_user is not None:
        ids.discard(exclude_user.id)
    return ids


def notify_module(module, *, notification_type, title, message, obj,
                  actor=None, action_url='', exclude_actor=True):
    """
    Create a Notification for every user with read access to `module`.

    `obj` is the related record (must have a UUID primary key — all the relevant
    models do); it backs the notification's generic foreign key. Never raises:
    notification delivery must never break the underlying business action.
    """
    try:
        recipient_ids = module_recipients(
            module, exclude_user=actor if exclude_actor else None
        )
        if not recipient_ids:
            return 0

        content_type = ContentType.objects.get_for_model(obj.__class__)
        notifications = [
            Notification(
                user_id=uid,
                notification_type=notification_type,
                content_type=content_type,
                object_id=obj.pk,
                actor=actor,
                title=title,
                message=message,
                action_url=action_url or '',
            )
            for uid in recipient_ids
        ]
        Notification.objects.bulk_create(notifications)
        return len(notifications)
    except Exception:  # pragma: no cover - defensive: never break the caller
        logger.exception("notify_module failed for module=%s type=%s", module, notification_type)
        return 0
