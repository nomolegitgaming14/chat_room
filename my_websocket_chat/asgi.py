import os
import django
from django.core.asgi import get_asgi_application

# Set the settings module FIRST
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'my_websocket_chat.settings')

# Initialize Django BEFORE importing other things
django.setup()

# Now import channels and routing after Django is ready
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from chat import routing

application = ProtocolTypeRouter({
    'http': get_asgi_application(),
    'websocket': AuthMiddlewareStack(
        URLRouter(
            routing.websocket_urlpatterns
        )
    ),
})