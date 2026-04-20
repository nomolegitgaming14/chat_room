from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from .forms import SignUpForm, RoomEditForm, ProfilePictureForm, ProfileBioForm
from .models import ChatRoom, Message, UserProfile
import os
import google.generativeai as genai
from django.conf import settings
import json
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import re
from datetime import datetime

def login_view(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            return redirect('chat_rooms')
        else:
            return render(request, 'chat/login.html', {'error': 'Invalid credentials'})
    return render(request, 'chat/login.html')

def signup_view(request):
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('chat_rooms')
        else:
            return render(request, 'chat/signup.html', {'form': form, 'errors': form.errors})
    else:
        form = SignUpForm()
    return render(request, 'chat/signup.html', {'form': form})

def logout_view(request):
    logout(request)
    return redirect('login')

@login_required
def chat_rooms(request):
    # Ensure current user has a profile
    if not hasattr(request.user, 'profile'):
        UserProfile.objects.create(user=request.user)
    
    rooms = ChatRoom.objects.all().order_by('-created_at')
    
    current_profile = None
    current_bio = None
    if hasattr(request.user, 'profile'):
        if request.user.profile.profile_picture:
            current_profile = request.user.profile.profile_picture.url
        current_bio = request.user.profile.bio
    
    return render(request, 'chat/rooms.html', {
        'rooms': rooms,
        'current_user_profile': current_profile,
        'current_user_bio': current_bio,
    })

@login_required
def chat_room(request, room_name):
    # Get or create the room
    room, created = ChatRoom.objects.get_or_create(name=room_name)
    
    # If room was just created, set the creator as admin
    if created:
        room.admin = request.user
        room.save()
    
    # Ensure the current user has a profile
    if not hasattr(request.user, 'profile'):
        UserProfile.objects.create(user=request.user)
    
    # Check if current user is admin
    is_admin = (room.admin == request.user)
    
    # Get recent messages with user profiles
    messages = Message.objects.filter(room=room).select_related('user', 'user__profile')[:50]
    
    # Get user profiles for all users in the room
    users_in_room = set()
    for message in messages:
        users_in_room.add(message.user)
        if not hasattr(message.user, 'profile'):
            UserProfile.objects.create(user=message.user)
    
    user_profiles = {}
    for user in users_in_room:
        if hasattr(user, 'profile') and user.profile.profile_picture:
            user_profiles[user.username] = user.profile.profile_picture.url
        else:
            user_profiles[user.username] = None
    
    current_profile = None
    if hasattr(request.user, 'profile') and request.user.profile.profile_picture:
        current_profile = request.user.profile.profile_picture.url
    
    return render(request, 'chat/room.html', {
        'room_name': room_name,
        'messages': messages,
        'username': request.user.username,
        'room': room,
        'user_profiles': user_profiles,
        'current_user_profile': current_profile,
        'is_admin': is_admin,  # 👈 Add this
    })

@require_http_methods(["POST"])
def upload_room_image(request):
    try:
        room_name = request.POST.get('room_name')
        room_image = request.FILES.get('room_image')
        
        if room_name and room_image:
            room = ChatRoom.objects.get(name=room_name)
            
            # 👈 CHECK IF USER IS ADMIN
            if room.admin != request.user:
                return JsonResponse({'success': False, 'error': 'Only the room admin can change the room picture!'})
            
            # Delete old image if exists
            if room.room_image:
                old_image_path = room.room_image.path
                if os.path.isfile(old_image_path):
                    os.remove(old_image_path)
            
            room.room_image = room_image
            room.save()
            
            # Broadcast the room picture change to all users in the room
            try:
                channel_layer = get_channel_layer()
                safe_group_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', room_name)
                group_name = f'chat_{safe_group_name}'
                
                async_to_sync(channel_layer.group_send)(
                    group_name,
                    {
                        'type': 'system_message',
                        'message': f'{request.user.username} changed the room picture',
                        'username': 'System',
                        'timestamp': datetime.now().strftime('%H:%M')
                    }
                )
                print(f"✅ Broadcasted room picture change to group: {group_name}")
            except Exception as e:
                print(f"Error broadcasting picture change: {e}")
            
            return JsonResponse({
                'success': True,
                'image_url': room.room_image.url
            })
    except Exception as e:
        print(f"Error uploading room image: {e}")
    
    return JsonResponse({'success': False})

@require_http_methods(["POST"])
def update_room_name(request):
    print("=" * 50)
    print("update_room_name view called!")
    print(f"POST data: {request.POST}")
    
    try:
        old_name = request.POST.get('old_name')
        new_name = request.POST.get('new_name')
        
        print(f"Old name: '{old_name}'")
        print(f"New name: '{new_name}'")
        
        if not old_name or not new_name:
            return JsonResponse({'success': False, 'error': 'Missing room names'})
        
        if old_name == new_name:
            return JsonResponse({'success': False, 'error': 'New name is the same as old name'})
        
        # Check if new name already exists
        if ChatRoom.objects.filter(name=new_name).exists():
            return JsonResponse({'success': False, 'error': 'A room with this name already exists!'})
        
        # Get the room and update its name
        room = ChatRoom.objects.get(name=old_name)
        
        # 👈 CHECK IF USER IS ADMIN
        if room.admin != request.user:
            return JsonResponse({'success': False, 'error': 'Only the room admin can rename the room!'})
        
        print(f"Found room: {room.name} (ID: {room.id})")
        
        room.name = new_name
        room.save()
        
        print(f"Successfully renamed room to: {new_name}")
        
        return JsonResponse({
            'success': True,
            'new_name': new_name,
            'new_url': f'/chat/room/{new_name}/'
        })
        
    except ChatRoom.DoesNotExist:
        print(f"Room not found: {old_name}")
        return JsonResponse({'success': False, 'error': 'Room not found'})
    except Exception as e:
        print(f"Error updating room name: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def update_username(request):
    if request.method == 'POST':
        try:
            new_username = request.POST.get('username', '').strip()
            current_username = request.user.username
            
            if not new_username:
                return JsonResponse({'success': False, 'error': 'Username cannot be empty'})
            
            if new_username == current_username:
                return JsonResponse({'success': False, 'error': 'New username is the same as current'})
            
            # Check if username already exists
            if User.objects.filter(username=new_username).exists():
                return JsonResponse({'success': False, 'error': 'Username already taken'})
            
            # Update username
            request.user.username = new_username
            request.user.save()
            
            # 👇 ADD THIS BROADCAST
            # Broadcast username change to all rooms the user is in
            try:
                channel_layer = get_channel_layer()
                rooms = ChatRoom.objects.filter(messages__user=request.user).distinct()
                
                for room in rooms:
                    safe_group_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', room.name)
                    group_name = f'chat_{safe_group_name}'
                    
                    async_to_sync(channel_layer.group_send)(
                        group_name,
                        {
                            'type': 'username_changed',
                            'message': f'{current_username} changed their username to {new_username}'
                        }
                    )
                print(f"✅ Broadcasted username change from '{current_username}' to '{new_username}'")
            except Exception as e:
                print(f"Error broadcasting username change: {e}")
            
            return JsonResponse({'success': True, 'new_username': new_username})
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})

@login_required
def upload_profile_picture(request):
    # Ensure user has a profile
    if not hasattr(request.user, 'profile'):
        UserProfile.objects.create(user=request.user)
    
    if request.method == 'POST':
        form = ProfilePictureForm(request.POST, request.FILES, instance=request.user.profile)
        if form.is_valid():
            # Delete old profile picture if exists
            if request.user.profile.profile_picture:
                old_path = request.user.profile.profile_picture.path
                if os.path.isfile(old_path):
                    os.remove(old_path)
            
            form.save()
            
            # 👇 ADD THIS BROADCAST
            # Broadcast profile picture change to all rooms the user is in
            try:
                channel_layer = get_channel_layer()
                rooms = ChatRoom.objects.filter(messages__user=request.user).distinct()
                
                for room in rooms:
                    safe_group_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', room.name)
                    group_name = f'chat_{safe_group_name}'
                    
                    async_to_sync(channel_layer.group_send)(
                        group_name,
                        {
                            'type': 'profile_picture_changed',
                            'message': f'{request.user.username} updated their profile picture'
                        }
                    )
                print(f"✅ Broadcasted profile picture change for {request.user.username}")
            except Exception as e:
                print(f"Error broadcasting profile picture change: {e}")
            
            return JsonResponse({
                'success': True,
                'image_url': request.user.profile.profile_picture.url if request.user.profile.profile_picture else None
            })
    return JsonResponse({'success': False})

@require_http_methods(["POST"])
def delete_room(request, room_id):
    try:
        room = ChatRoom.objects.get(id=room_id)
        
        # 👈 CHECK IF USER IS ADMIN
        if room.admin != request.user:
            return JsonResponse({'success': False, 'error': 'Only the room admin can delete the room!'})
        
        room_name = room.name
        
        # Delete room image if exists
        if room.room_image:
            old_image_path = room.room_image.path
            if os.path.isfile(old_image_path):
                os.remove(old_image_path)
        
        # Delete all messages and their images in the room
        for message in room.messages.all():
            if message.image:
                image_path = message.image.path
                if os.path.isfile(image_path):
                    os.remove(image_path)
        
        # Delete the room (cascades to messages)
        room.delete()
        
        print(f"Deleted room: {room_name}")
        
        return JsonResponse({'success': True})
        
    except ChatRoom.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Room not found'})
    except Exception as e:
        print(f"Error deleting room: {e}")
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def update_bio(request):
    if request.method == 'POST':
        try:
            bio_text = request.POST.get('bio', '')
            
            # Limit to 500 characters
            if len(bio_text) > 500:
                return JsonResponse({'success': False, 'error': 'Bio too long (max 500 characters)'})
            
            # Ensure user has a profile
            if not hasattr(request.user, 'profile'):
                UserProfile.objects.create(user=request.user)
            
            # Update the bio
            request.user.profile.bio = bio_text
            request.user.profile.save()
            
            return JsonResponse({'success': True, 'bio': bio_text})
            
        except Exception as e:
            print(f"Error saving bio: {e}")
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

@require_http_methods(["POST"])
def create_room(request):
    try:
        room_name = request.POST.get('room_name', '').strip()
        max_members = request.POST.get('max_members', 50)
        
        if not room_name:
            return JsonResponse({'success': False, 'error': 'Room name cannot be empty'})
        
        if ChatRoom.objects.filter(name=room_name).exists():
            return JsonResponse({'success': False, 'error': 'A room with this name already exists!'})
        
        # Create room with current user as admin
        room = ChatRoom.objects.create(
            name=room_name,
            max_members=max_members,
            admin=request.user  # 👈 Set the creator as admin
        )
        
        return JsonResponse({
            'success': True,
            'room_id': room.id,
            'room_name': room.name
        })
        
    except Exception as e:
        print(f"Error creating room: {e}")
        return JsonResponse({'success': False, 'error': str(e)})
    

# Configure Gemini
genai.configure(api_key="YOUR_GEMINI_API_KEY")  # Better to use environment variable

@csrf_exempt
def ai_chat(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            user_message = data.get('message', '')
            
            # Get AI response
            model = genai.GenerativeModel('gemini-1.5-flash')
            response = model.generate_content(user_message)
            
            return JsonResponse({
                'success': True,
                'response': response.text
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
        
@login_required
def personal_ai(request):
    """Personal AI assistant view (only for the logged-in user)"""
    return render(request, 'chat/personal_ai.html', {
        'username': request.user.username,
        'current_user_profile': request.user.profile.profile_picture.url if hasattr(request.user, 'profile') and request.user.profile.profile_picture else None
    })

@csrf_exempt
@login_required
def ai_chat_api(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            user_message = data.get('message', '')
            
            print(f"📨 Received message from {request.user.username}: {user_message}")
            
            # Create a simple prompt
            prompt = f"""You are JARVIS, a helpful AI assistant. 
User: {user_message}
Assistant:"""
            
            # Use the correct model
            model = genai.GenerativeModel('gemini-1.5-flash')
            
            # Generate response
            response = model.generate_content(prompt)
            
            print(f"🤖 AI Response: {response.text[:100]}...")
            
            return JsonResponse({
                'success': True,
                'response': response.text
            })
            
        except Exception as e:
            print(f"❌ AI Error: {e}")
            import traceback
            traceback.print_exc()
            return JsonResponse({
                'success': False, 
                'error': str(e)
            })
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})