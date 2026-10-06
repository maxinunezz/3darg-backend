from django.urls import path
from .views import RegisterView, MeView, FavoriteListView, FavoriteDestroyView, GoogleAuthView

urlpatterns = [
    path("register/", RegisterView.as_view(), name="user-register"),
    path("google/", GoogleAuthView.as_view(), name="user-google-auth"),
    path("me/", MeView.as_view(), name="user-me"),
    path("favorites/", FavoriteListView.as_view(), name="favorite-list"),
    path("favorites/<int:product_id>/", FavoriteDestroyView.as_view(), name="favorite-destroy"),
]
