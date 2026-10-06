from decimal import Decimal, ROUND_HALF_UP

from django.core.validators import MaxValueValidator
from django.db import models
from django.utils.text import slugify
from brands.models import Brand


class ProductQuerySet(models.QuerySet):
    """Scoping de visibilidad por estado de autenticación."""

    def visible_to(self, user):
        """Productos que este usuario puede ver.

        Los productos `members_only` solo son visibles para usuarios autenticados;
        para anónimos se ocultan por completo (no aparecen en listados ni detalle).
        """
        if user and getattr(user, "is_authenticated", False):
            return self
        return self.filter(members_only=False)


class Category(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    brand = models.ForeignKey(
        Brand,
        on_delete=models.CASCADE,
        related_name="categories",
        null=True,
        blank=True,
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        related_name="children",
        null=True,
        blank=True,
        help_text=(
            "Categoria padre, para armar jerarquias (ej: Cortantes > Halloween). "
            "Vacio = categoria de nivel superior."
        ),
    )

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        if self.parent_id:
            return f"{self.parent.name} > {self.name}"
        return self.name


class Product(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, blank=True)
    sku = models.CharField(
        max_length=64,
        unique=True,
        blank=True,
        help_text="Identificador único de catálogo (feeds de Meta/Google). Se autogenera desde el ID si se deja vacío.",
    )
    google_product_category = models.CharField(
        max_length=255,
        blank=True,
        help_text=(
            "Categoría de la taxonomía de Google/Meta (ej: '1239' o "
            "'Sporting Goods > Exercise & Fitness'). Usada en el feed de Meta Catalog."
        ),
    )
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.PositiveIntegerField(default=0)
    is_available = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    members_only = models.BooleanField(
        default=False,
        help_text="Si está activo, el producto solo es visible y comprable por usuarios con cuenta.",
    )
    member_discount_percent = models.PositiveSmallIntegerField(
        default=0,
        validators=[MaxValueValidator(100)],
        help_text="Descuento (%) que reciben los usuarios con cuenta sobre este producto. 0 = sin descuento.",
    )
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="products")
    brand = models.ForeignKey(
        Brand,
        on_delete=models.CASCADE,
        related_name="products",
        null=True,
        blank=True,
    )
    # Integración BamBuddy: ID del archivo en la Library de BamBuddy.
    # Si está seteado, al pagarse una orden con este producto se encola
    # automáticamente en la impresora. Se gestiona desde el admin de Django.
    bambuddy_file_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="ID del archivo en BamBuddy Library. Si está seteado, se envía a imprimir automáticamente al pagarse una orden.",
    )
    bundle_discounts = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            'Descuento por volumen (mismo producto). Lista de tramos, ej: '
            '[{"quantity": 2, "discount_percent": 10}, {"quantity": 3, "discount_percent": 15}]. '
            "Vacío = sin oferta por cantidad (no se muestra el selector en el frontend). "
            "El % se aplica sobre el precio ya resuelto (de lista o de socio) — se COMBINA con "
            "member_discount_percent (no se elige el mejor de los dos), vía unit_price_for()."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering = ["-is_featured", "name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.sku:
            self.sku = f"3DARG-{self.pk:06d}"
            super().save(update_fields=["sku"])

    def __str__(self):
        return self.name

    @property
    def has_member_discount(self) -> bool:
        return self.member_discount_percent > 0

    @property
    def member_price(self) -> Decimal:
        """Precio con el descuento de socio aplicado (sin importar quién consulta)."""
        if not self.has_member_discount:
            return self.price
        factor = (Decimal(100) - Decimal(self.member_discount_percent)) / Decimal(100)
        return (self.price * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def price_for(self, user) -> Decimal:
        """Precio efectivo que paga `user`.

        Fuente de verdad del cobro: usada por cart, checkout y serializers.
        Los usuarios autenticados pagan `member_price`; los anónimos, `price`.
        """
        if user and getattr(user, "is_authenticated", False):
            return self.member_price
        return self.price

    def bundle_discount_percent_for(self, quantity: int) -> int:
        """% de descuento por volumen aplicable a `quantity` unidades de este producto.

        Toma el tramo de mayor cantidad que `quantity` todavía cubre (ej. tramos en
        2 y 3 unidades, comprando 5 se aplica el de 3). Sin `bundle_discounts` → 0.
        """
        if not self.bundle_discounts:
            return 0
        applicable = [
            int(tier.get("discount_percent", 0))
            for tier in self.bundle_discounts
            if quantity >= int(tier.get("quantity", 0))
        ]
        return max(applicable) if applicable else 0

    def unit_price_for(self, user, quantity: int = 1) -> Decimal:
        """Precio unitario efectivo para `user` llevándose `quantity` unidades.

        Aplica primero `price_for(user)` (socio vs. anónimo) y, encima, el
        descuento por volumen de `bundle_discounts` si corresponde — ambos
        descuentos se combinan (no hay que elegir uno u otro). Fuente de verdad
        del cobro cuando hay cantidad involucrada: la usan cart y checkout.
        """
        base = self.price_for(user)
        bundle_pct = self.bundle_discount_percent_for(quantity)
        if bundle_pct <= 0:
            return base
        factor = (Decimal(100) - Decimal(bundle_pct)) / Decimal(100)
        return (base * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def is_visible_to(self, user) -> bool:
        return (not self.members_only) or bool(user and getattr(user, "is_authenticated", False))


class ProductImage(models.Model):
    product = models.ForeignKey(Product, related_name="images", on_delete=models.CASCADE)
    image = models.ImageField(upload_to="products/images/")
    order = models.PositiveIntegerField(default=0)
    alt = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.product.name} - imagen {self.order}"
