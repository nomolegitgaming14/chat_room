import json
import re
import base64
from urllib.parse import unquote
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

class ChatConsumer(AsyncWebsocketConsumer):
    # Class variable to track connected users per room
    room_users = {}

    async def connect(self):
        print("=" * 50)
        print("🔌 CONNECT method called!")
        
        raw_room_name = unquote(self.scope['url_route']['kwargs']['room_name'])
        print(f"Raw room name: {raw_room_name}")
        
        self.room_name = raw_room_name
        safe_group_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', raw_room_name)
        self.room_group_name = f'chat_{safe_group_name}'
        
        print(f"Safe group name: {self.room_group_name}")
        
        # Get username from scope
        self.username = self.scope['user'].username if self.scope['user'].is_authenticated else "Anonymous"
        print(f"Username: {self.username}")
        
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        print(f"✅ WebSocket ACCEPTED for room: {self.room_name}")
        
        # Add user to room tracking
        await self.add_user_to_room(self.room_name, self.username)
        
        # Send welcome message to the new user only
        await self.send(text_data=json.dumps({
            'type': 'system',
            'message': f'Welcome to {self.room_name}! You can now send pictures 📸',
            'username': 'System',
            'timestamp': self.get_timestamp()
        }))
        
        # Send join notification to everyone in the room (as system message)
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'system_message',
                'message': f'{self.username} joined the chat',
                'username': 'System',
                'timestamp': self.get_timestamp()
            }
        )
        
        print("=" * 50)
    
    async def disconnect(self, close_code):
        print(f"❌ WebSocket DISCONNECTED: {close_code}")
        
        # Remove user from room tracking
        await self.remove_user_from_room(self.room_name, self.username)
        
        # Send leave notification to everyone in the room (as system message)
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'system_message',
                'message': f'{self.username} left the chat',
                'username': 'System',
                'timestamp': self.get_timestamp()
            }
        )
        
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
    
    async def system_message(self, event):
        # Send system message to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'system',
            'message': event['message'],
            'username': event['username'],
            'timestamp': event.get('timestamp', self.get_timestamp())
        }))
    
    async def room_picture_changed(self, event):
        # Send room picture change notification to all users as system message
        await self.send(text_data=json.dumps({
            'type': 'system',
            'message': event['message'],
            'username': 'System',
            'timestamp': self.get_timestamp()
        }))
    
    # 👇 ADD THESE TWO NEW METHODS
    async def username_changed(self, event):
        # Send username change notification to all users in the room
        await self.send(text_data=json.dumps({
            'type': 'system',
            'message': event['message'],
            'username': 'System',
            'timestamp': self.get_timestamp()
        }))
    
    async def profile_picture_changed(self, event):
        # Send profile picture change notification to all users in the room
        await self.send(text_data=json.dumps({
            'type': 'system',
            'message': event['message'],
            'username': 'System',
            'timestamp': self.get_timestamp()
        }))
    
    async def receive(self, text_data):
        print(f"📨 Received: {text_data[:100]}...")
        
        try:
            data = json.loads(text_data)
            message_type = data.get('type', 'text')
            
            if message_type == 'image':
                # Handle image
                image_data = data.get('image', '')
                username = data.get('username', '')
                
                if image_data:
                    image_url = await self.save_image(username, image_data)
                    
                    if image_url:
                        # Get user's profile picture
                        profile_picture = await self.get_profile_picture(username)
                        
                        # Send image to all users in room
                        await self.channel_layer.group_send(
                            self.room_group_name,
                            {
                                'type': 'send_image',
                                'image_url': image_url,
                                'username': username,
                                'profile_picture': profile_picture,
                                'timestamp': self.get_timestamp()
                            }
                        )
            else:
                # Handle text message
                message = data.get('message', '')
                username = data.get('username', '')
                
                if message:
                    await self.save_message(username, message)
                    
                    # Get user's profile picture
                    profile_picture = await self.get_profile_picture(username)
                    
                    await self.channel_layer.group_send(
                        self.room_group_name,
                        {
                            'type': 'send_message',
                            'message': message,
                            'username': username,
                            'profile_picture': profile_picture,
                            'timestamp': self.get_timestamp()
                        }
                    )
                    
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
    
    async def send_message(self, event):
        # Send text message to WebSocket with profile picture
        await self.send(text_data=json.dumps({
            'type': 'text',
            'message': event['message'],
            'username': event['username'],
            'profile_picture': event.get('profile_picture', None),
            'timestamp': event.get('timestamp', 'Just now')
        }))
    
    async def send_image(self, event):
        # Send image to WebSocket with profile picture
        await self.send(text_data=json.dumps({
            'type': 'image',
            'image_url': event['image_url'],
            'username': event['username'],
            'profile_picture': event.get('profile_picture', None),
            'timestamp': event.get('timestamp', 'Just now')
        }))
    
    async def room_renamed(self, event):
        # Send room rename notification to all users as system message
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'system_message',
                'message': f'Room renamed from "{event["old_name"]}" to "{event["new_name"]}"',
                'username': 'System',
                'timestamp': self.get_timestamp()
            }
        )
    
    def get_timestamp(self):
        from datetime import datetime
        return datetime.now().strftime('%H:%M')
    
    @database_sync_to_async
    def add_user_to_room(self, room_name, username):
        if room_name not in self.__class__.room_users:
            self.__class__.room_users[room_name] = set()
        self.__class__.room_users[room_name].add(username)
        print(f"✅ {username} joined {room_name}")
        print(f"Users in {room_name}: {self.__class__.room_users[room_name]}")
    
    @database_sync_to_async
    def remove_user_from_room(self, room_name, username):
        if room_name in self.__class__.room_users:
            self.__class__.room_users[room_name].discard(username)
            print(f"❌ {username} left {room_name}")
            if not self.__class__.room_users[room_name]:
                del self.__class__.room_users[room_name]
                print(f"Room {room_name} is now empty")
            else:
                print(f"Users remaining in {room_name}: {self.__class__.room_users[room_name]}")
    
    @database_sync_to_async
    def get_room_users(self, room_name):
        users = self.__class__.room_users.get(room_name, set())
        return list(users)
    
    @database_sync_to_async
    def get_profile_picture(self, username):
        from .models import UserProfile
        from django.contrib.auth.models import User
        
        try:
            user = User.objects.get(username=username)
            if hasattr(user, 'profile') and user.profile.profile_picture:
                return user.profile.profile_picture.url
            return None
        except Exception as e:
            print(f"Error getting profile picture: {e}")
            return None
    
    @database_sync_to_async
    def save_message(self, username, message):
        from .models import ChatRoom, Message
        from django.contrib.auth.models import User
        
        try:
            user = User.objects.get(username=username)
            room, created = ChatRoom.objects.get_or_create(name=self.room_name)
            Message.objects.create(room=room, user=user, content=message)
            print(f"💾 Message saved from {username}")
        except Exception as e:
            print(f"Error saving message: {e}")
    
    @database_sync_to_async
    def save_image(self, username, image_data):
        from .models import ChatRoom, Message
        from django.contrib.auth.models import User
        from django.core.files.base import ContentFile
        import uuid
        
        try:
            print(f"Saving image for: {username}")
            
            # Parse base64 image
            format, imgstr = image_data.split(';base64,')
            ext = format.split('/')[-1]
            
            # Generate unique filename
            filename = f"{uuid.uuid4().hex}.{ext}"
            
            # Decode and save
            image_content = ContentFile(base64.b64decode(imgstr), name=filename)
            
            user = User.objects.get(username=username)
            room, created = ChatRoom.objects.get_or_create(name=self.room_name)
            
            message = Message.objects.create(
                room=room,
                user=user,
                content=None,
                image=image_content
            )
            
            print(f"💾 Image saved: {filename}")
            return message.image.url
            
        except Exception as e:
            print(f"Error saving image: {e}")
            import traceback
            traceback.print_exc()
            return None