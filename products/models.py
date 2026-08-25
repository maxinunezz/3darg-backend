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

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Product(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, blank=True)
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

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering = ["-is_featured", "name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

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
