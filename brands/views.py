from django.db.models import Prefetch
from rest_framework.generics import ListAPIView
from .models import Brand
from .serializers import BrandSerializer


class BrandListAPIView(ListAPIView):
    serializer_class = BrandSerializer

    def get_queryset(self):
        # Sin esto, BrandSerializer.get_children() + "links" disparaban una
        # query extra por marca raíz (children) y por cada marca (sus links)
        # — N+1 real, visible en Sentry. Las hijas (y, por si alguna vez
        # tienen hijas propias, las nietas) se prefetchean con sus propios
        # "links" y se guardan en `active_children` para que el serializer
        # las use sin volver a pegarle a la DB (ver get_children). Hoy 3DARG
        # es el único root (jerarquía de un solo nivel real), pero se deja
        # un nivel extra de prefetch para no reintroducir el N+1 si alguna
        # vez se carga una sub-sub-marca.
        grandchildren_qs = Brand.objects.filter(is_active=True).prefetch_related("links")
        children_qs = Brand.objects.filter(is_active=True).prefetch_related(
            "links",
            Prefetch("children", queryset=grandchildren_qs, to_attr="active_children"),
        )
        return (
            Brand.objects.filter(
                parent__isnull=True,
                is_active=True,
                show_in_navbar=True,
            )
            .prefetch_related(
                "links",
                Prefetch("children", queryset=children_qs, to_attr="active_children"),
            )
            .order_by("navbar_order")
        )