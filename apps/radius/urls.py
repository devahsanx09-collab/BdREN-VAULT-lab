from django.urls import path

from . import views

urlpatterns = [
    path("api/radius/users", views.users, name="api-radius-users"),
    path("api/radius/users/<str:username>", views.user_detail, name="api-radius-user-detail"),
    path("api/radius/nas", views.nas, name="api-radius-nas"),
    path("api/radius/nas/<int:pk>", views.nas_detail, name="api-radius-nas-detail"),
    path("api/radius/nas/<int:pk>/secret", views.nas_secret, name="api-radius-nas-secret"),
    path("api/radius/audit", views.audit, name="api-radius-audit"),
]
