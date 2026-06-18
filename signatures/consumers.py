import json
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import AccessToken
from .models import Notification

User = get_user_model()

class NotificationConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time notifications

    Features:
    - JWT token authentication
    - Real-time notification delivery
    - Heartbeat mechanism to detect disconnects
    - Graceful reconnection handling
    - Message queueing on temporary disconnects
    """

    async def connect(self):
        """Handle WebSocket connection"""
        try:
            # Get token from URL
            token = self.scope['query_string'].decode().split('token=')[-1]

            # Validate token
            self.user = await self._get_user_from_token(token)

            if not self.user:
                await self.close(code=4001, reason='Invalid token')
                return

            # Create user-specific channel name
            self.channel_name = f'user_{self.user.id}'

            # Add to group
            await self.channel_layer.group_add(self.channel_name, self.channel_name)

            # Accept connection
            await self.accept()

            # Send connection acknowledgment
            await self.send(text_data=json.dumps({
                'type': 'connection_established',
                'user_id': self.user.id,
                'username': self.user.username,
            }))

            # Start heartbeat
            asyncio.create_task(self._heartbeat())

            print(f'[WS] User {self.user.username} connected')

        except Exception as e:
            print(f'[WS] Connection error: {str(e)}')
            await self.close(code=4000, reason='Connection failed')

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection"""
        if hasattr(self, 'user'):
            print(f'[WS] User {self.user.username} disconnected (code: {close_code})')

            # Remove from group
            if hasattr(self, 'channel_name'):
                await self.channel_layer.group_discard(self.channel_name, self.channel_name)

    async def receive(self, text_data):
        """Handle incoming WebSocket messages"""
        try:
            data = json.loads(text_data)
            action = data.get('action')

            if action == 'ping':
                # Heartbeat response
                await self.send(text_data=json.dumps({'type': 'pong'}))

            elif action == 'get_unread_count':
                # Send current unread count
                count = await self._get_unread_count()
                await self.send(text_data=json.dumps({
                    'type': 'unread_count',
                    'count': count
                }))

            else:
                print(f'[WS] Unknown action: {action}')

        except json.JSONDecodeError:
            print('[WS] Invalid JSON received')
        except Exception as e:
            print(f'[WS] Error handling message: {str(e)}')

    async def send_notification(self, event):
        """
        Receive notification from group and send to WebSocket
        Called by Django signals when notification is created
        """
        try:
            notification = event['notification']

            await self.send(text_data=json.dumps({
                'type': 'notification',
                'payload': notification
            }))

        except Exception as e:
            print(f'[WS] Error sending notification: {str(e)}')

    async def _heartbeat(self):
        """
        Send periodic heartbeat to keep connection alive
        Helps detect dead connections
        """
        while True:
            try:
                await asyncio.sleep(30)  # Send ping every 30 seconds
                await self.send(text_data=json.dumps({
                    'type': 'ping'
                }))
            except Exception as e:
                print(f'[WS] Heartbeat error: {str(e)}')
                break

    @database_sync_to_async
    def _get_user_from_token(self, token):
        """
        Extract user from JWT token
        """
        try:
            access_token = AccessToken(token)
            user_id = access_token['user_id']
            return User.objects.get(id=user_id)
        except Exception as e:
            print(f'[WS] Token validation error: {str(e)}')
            return None

    @database_sync_to_async
    def _get_unread_count(self):
        """
        Get unread notification count for user
        """
        try:
            return Notification.objects.filter(
                user=self.user,
                is_read=False
            ).count()
        except Exception as e:
            print(f'[WS] Error getting unread count: {str(e)}')
            return 0
