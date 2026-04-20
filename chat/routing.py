from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # Allow any characters in room name
    re_path(r'ws/chat/(?P<room_name>.+)/$', consumers.ChatConsumer.as_asgi()),
]