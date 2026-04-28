from django.urls import path

from .views import ChatQueryView, ChatbotVoiceTranscriptionView, EmployeeCheckView


urlpatterns = [
    path("query/", ChatQueryView.as_view(), name="chatbot-query"),
    path("lex-chat/", ChatQueryView.as_view(), name="chatbot-legacy-query"),
    path("voice/", ChatbotVoiceTranscriptionView.as_view(), name="chatbot-voice-transcription"),
    path("check-employee/", EmployeeCheckView.as_view(), name="chatbot-check-employee"),
]
