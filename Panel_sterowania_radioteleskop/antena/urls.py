from django.urls import path
from . import views

urlpatterns = [
    path("", views.panel_view, name="panel"),
    path("api/command/", views.handle_command),
]
