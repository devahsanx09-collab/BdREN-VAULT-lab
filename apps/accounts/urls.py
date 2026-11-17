from django.urls import path

from . import views

urlpatterns = [
    path("setup", views.setup, name="setup"),
    path("login", views.login_view, name="login"),
    path("logout", views.logout_view, name="logout"),
    path("api/me", views.me, name="api-me"),
    path("api/me/password", views.change_my_password, name="api-me-password"),
    path("api/users", views.users, name="api-users"),
    path("api/users/signins", views.signins, name="api-users-signins"),
    path("api/users/<int:pk>", views.user_detail, name="api-user-detail"),
]
