from django.urls import path

from . import views

app_name = "oauth_server"

urlpatterns = [
    path("authorize/", views.authorize, name="authorize"),
    path("login/", views.login, name="login"),
    path("token/", views.token, name="token"),
    path("register/", views.register_client, name="register"),
]
