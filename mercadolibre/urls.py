from django.urls import path

from . import views

urlpatterns = [
    path("authorize/", views.authorize, name="ml-authorize"),
    path("callback/", views.callback, name="ml-callback"),
    path("webhook/", views.webhook, name="ml-webhook"),
]
