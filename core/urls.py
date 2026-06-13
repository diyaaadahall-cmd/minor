from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('chatbot/', views.site_chatbot, name='site_chatbot'),
    path('subject/<str:subject_name>/', views.subject_notes, name='subject_notes'),
    path('subject/<str:subject_name>/chat/', views.pdf_chat, name='pdf_chat'),
    path('subject/<str:subject_name>/progress/', views.update_note_progress, name='update_note_progress'),
]
