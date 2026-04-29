from django.urls import path

from . import views

app_name = "assets"

urlpatterns = [
    path("", views.upload_asset, name="upload"),
    path("<str:asset_uuid>/", views.serve_asset, name="serve"),
]
