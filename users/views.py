import logging
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from django.shortcuts import get_object_or_404
from .models import Favorite
from .serializers import (
    RegisterSerializer,
    UserSerializer,
    FavoriteSerializer,
    GoogleAuthSerializer,
    ChangePasswordSerializer,
    PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer,
)

logger = logging.getLogger(__name__)


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]


class GoogleAuthView(APIView):
    """
    POST /api/users/google/ {id_token, brand_slug?}
    Verifica el id_token de Google, hace get_or_create del User por email
    y devuelve el mismo par access/refresh que /api/auth/token/.
    """

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = GoogleAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        refresh = RefreshToken.for_user(user)
        return Response(
            {"access": str(refresh.access_token), "refresh": str(refresh)},
            status=status.HTTP_200_OK,
        )


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class ChangePasswordView(APIView):
    """
    POST /api/users/change-password/ {current_password?, new_password}
    current_password es opcional solo si la cuenta todavía no tiene password
    usable (alta por Google) — ver ChangePasswordSerializer.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PasswordResetThrottle(AnonRateThrottle):
    rate = "5/hour"


class PasswordResetRequestView(APIView):
    """
    POST /api/users/password-reset/ {email}
    Caso "olvidé la contraseña": siempre responde 200 con mensaje genérico
    (no confirma si el email existe, evita enumeración de cuentas). Si existe,
    manda un mail con un link a FRONTEND_BASE_URL/reset-password?uid=&token=.
    """

    permission_classes = [permissions.AllowAny]
    throttle_classes = [PasswordResetThrottle]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = get_user_model().objects.filter(email__iexact=serializer.validated_data["email"]).first()
        if user:
            self._send_reset_email(user)

        return Response(
            {"detail": "Si el email existe, te enviamos un link para recuperar tu contraseña."},
            status=status.HTTP_200_OK,
        )

    def _send_reset_email(self, user):
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        frontend_base = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000").rstrip("/")
        reset_url = f"{frontend_base}/reset-password?uid={uid}&token={token}"
        try:
            send_mail(
                subject="Recuperá tu contraseña",
                message=(
                    "Hola,\n\n"
                    "Recibimos un pedido para restablecer tu contraseña.\n"
                    f"Entrá a este link para elegir una nueva (válido por 3 días):\n{reset_url}\n\n"
                    "Si no lo pediste vos, podés ignorar este mensaje."
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=True,
            )
        except Exception:
            logger.exception("Error enviando email de recuperación de contraseña a %s", user.email)


class PasswordResetConfirmView(APIView):
    """
    POST /api/users/password-reset/confirm/ {uid, token, new_password}
    Caso "estoy logueado pero no recuerdo la actual" usa el mismo mecanismo:
    pide un link nuevo desde "Mis datos" en vez de tipear la contraseña vieja.
    """

    permission_classes = [permissions.AllowAny]
    throttle_classes = [PasswordResetThrottle]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


class FavoriteListView(generics.ListCreateAPIView):
    serializer_class = FavoriteSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return (
            Favorite.objects.filter(user=self.request.user)
            .select_related("product__category", "product__brand")
            .prefetch_related("product__images")
        )


class FavoriteDestroyView(generics.DestroyAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return get_object_or_404(
            Favorite,
            user=self.request.user,
            product_id=self.kwargs["product_id"],
        )
