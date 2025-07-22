from django.urls import path
from . import views

urlpatterns = [
    path("", views.panel_view, name="panel"),
    path("api/command/", views.handle_driver_command),
    path("api/sdr/command/", views.handle_sdr_command),
]
