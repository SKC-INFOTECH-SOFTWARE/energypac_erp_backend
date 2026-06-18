import json
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.serializers.json import DjangoJSONEncoder
from .models import Notification

try:
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer
    CHANNELS_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    CHANNELS_AVAILABLE = False

@receiver(post_save, sender=Notification)
def notification_created(sender, instance, created, **kwargs):
    """
    Signal handler: When a notification is created, broadcast it via WebSocket (if channels available)
    """
    if not created or not CHANNELS_AVAILABLE:
        return

    try:
        # Prepare notification data
        notification_data = {
            'id': str(instance.id),
            'title': instance.title,
            'message': instance.message,
            'notification_type': instance.notification_type,
            'action_url': instance.action_url,
            'is_read': instance.is_read,
            'created_at': instance.created_at.isoformat(),
            'actor': {
                'id': instance.actor.id if instance.actor else None,
                'username': instance.actor.username if instance.actor else None,
                'first_name': instance.actor.first_name if instance.actor else None,
                'last_name': instance.actor.last_name if instance.actor else None,
            }
        }

        # Get channel layer
        channel_layer = get_channel_layer()

        # Send to user's WebSocket group
        async_to_sync(channel_layer.group_send)(
            f'user_{instance.user.id}',
            {
                'type': 'send_notification',
                'notification': notification_data
            }
        )

        print(f'[Signal] Notification sent to user {instance.user.username}')

    except Exception as e:
        print(f'[Signal] Error broadcasting notification: {str(e)}')


def ready():
    """
    Called when app is ready
    """
    pass
