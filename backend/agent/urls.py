from django.urls import path

from . import views

urlpatterns = [
    path("status/", views.AgentStatusView.as_view()),
    path("messages/", views.AgentMessagesView.as_view()),
    path("chat/", views.AgentChatView.as_view()),
    path("undo/", views.AgentUndoView.as_view()),
    path("reset/", views.AgentResetView.as_view()),
]
