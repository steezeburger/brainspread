from django.urls import path

from . import views

app_name = "web_archives"

urlpatterns = [
    path("capture/", views.capture_web_archive, name="capture"),
    path("by-block/<str:block_uuid>/", views.get_web_archive, name="by_block"),
]
