from django.urls import path

from . import views

urlpatterns = [
    path("api/ping", views.ping_all, name="api-ping"),
    path("api/dashboard", views.dashboard, name="api-dashboard"),
]
