from django.urls import path

from .views import create_route_plan, health

urlpatterns = [
    path("health", health, name="health"),
    path("route-plans", create_route_plan, name="route-plans"),
]
