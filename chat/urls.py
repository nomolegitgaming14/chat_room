from django.urls import path, re_path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('signup/', views.signup_view, name='signup'),
    path('', views.chat_rooms, name='chat_rooms'),
    re_path(r'room/(?P<room_name>.+)/$', views.chat_room, name='chat_room'),
    path('logout/', views.logout_view, name='logout'),
    path('upload_room_image/', views.upload_room_image, name='upload_room_image'),
    path('update_room_name/', views.update_room_name, name='update_room_name'),
    path('upload_profile_picture/', views.upload_profile_picture, name='upload_profile_picture'),
    path('delete_room/<int:room_id>/', views.delete_room, name='delete_room'),
    path('update_bio/', views.update_bio, name='update_bio'),
    path('update_username/', views.update_username, name='update_username'),
    path('create_room/', views.create_room, name='create_room'),
    path('personal-ai/', views.personal_ai, name='personal_ai'),
    path('ai-chat-api/', views.ai_chat_api, name='ai_chat_api'),
]