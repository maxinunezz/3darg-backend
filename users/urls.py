from django.urls import path
from .views import (
    RegisterView,
    MeView,
    ChangePasswordView,
    PasswordResetRequestView,
    PasswordResetConfirmView,
    FavoriteListView,
    FavoriteDestroyView,
    GoogleAuthView,
)

urlpatterns = [
    path("register/", RegisterView.as_view(), name="user-register"),
    path("google/", GoogleAuthView.as_view(), name="user-google-auth"),
    path("me/", MeView.as_view(), name="user-me"),
    path("change-password/", ChangePasswordView.as_view(), name="user-change-password"),
    path("password-reset/", PasswordResetRequestView.as_view(), name="password-reset-request"),
    path("password-reset/confirm/", PasswordResetConfirmView.as_view(), name="password-reset-confirm"),
    path("favorites/", FavoriteListView.as_view(), name="favorite-list"),
    path("favorites/<int:product_id>/", FavoriteDestroyView.as_view(), name="favorite-destroy"),
]
