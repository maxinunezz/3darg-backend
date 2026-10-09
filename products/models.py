import re
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
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
    sku_prefix = models.CharField(
        max_length=10,
        blank=True,
        help_text=(
            "Código corto para el SKU de productos de esta categoría (ej: COR "
            "para Cortantes, LLA para Llaveros). Solo hace falta cargarlo en "
            "categorías de nivel superior (sin categoría padre) — las "
            "subcategorías heredan el código de su raíz para no atar el SKU a "
            "una subcategoría que puede reordenarse. Igual que "
            "Brand.sku_prefix: evitar cambiarlo una vez que hay productos "
            "usándolo. Vacío = se usan las primeras letras del slug como "
            "fallback."
        ),
    )

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        if self.parent_id:
            return f"{self.parent.name} > {self.name}"
        return self.name

    def root_sku_prefix(self) -> str:
        """Código de SKU de la categoría raíz de este árbol.

        Sube por `parent` hasta la categoría de nivel superior y devuelve su
        `sku_prefix` (o un fallback armado del slug si no está cargado), para
        que el SKU no dependa de en qué subcategoría puntual quedó el
        producto hoy.
        """
        node = self
        seen = {node.pk}
        while node.parent_id and node.parent_id not in seen:
            node = node.parent
            seen.add(node.pk)
        if node.sku_prefix:
            return node.sku_prefix
        return slugify(node.slug).replace("-", "").upper()[:3] or "CAT"


class Product(models.Model):
    class CutterSize(models.TextChoices):
        """Tamaño de COSTEO del cortante (tamaño de la pieza, no el diseño).

        Ver `cost_sku()`/`COST_SKU_BY_CUTTER_SIZE` más abajo: todos los
        diseños de un mismo tamaño comparten el mismo costo de fabricación
        en presupuestos3d, así que el costo de un producto se busca por
        este campo, no por su `sku` propio.
        """
        MINI = "mini", "Mini"
        CHICO = "chico", "Chico"
        MEDIANO = "mediano", "Mediano"
        GRANDE = "grande", "Grande"
        A_MEDIDA = "a_medida", "A medida"

    # SKU sintético de costeo en presupuestos3d por tamaño de cortante (no
    # por diseño) — productos "ficticios" del otro lado (ej. "Cortante
    # Mediano x100") pensados para que muchos diseños de un mismo tamaño de
    # pieza compartan el mismo costeo, en vez de depender del SKU propio de
    # cada diseño (que dejaría el costo en "no disponible" cada vez que se
    # suma un diseño nuevo sin cargar un SKU nuevo del otro lado). Solo
    # MEDIANO tiene SKU sintético confirmado hoy — sumar una línea acá
    # cuando se cargue el costeo de los demás tamaños en presupuestos3d;
    # hasta entonces esos tamaños quedan en "costo no disponible" sin
    # romper nada (ver `cost_sku()` y `products/admin.py::_channel_resumen`).
    COST_SKU_BY_CUTTER_SIZE = {
        CutterSize.MEDIANO: "LUMY-COR-TALLA-MEDIANO",
    }

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, blank=True)
    sku = models.CharField(
        max_length=64,
        unique=True,
        blank=True,
        help_text=(
            "Identificador único de catálogo, compartido entre la web, el feed "
            "de Google/Meta, Mercado Libre y presupuestos3d. Se autogenera con "
            "el formato MARCA-CATEGORIA[-ID_SUBCATEGORIA]-NNNNNN[-VARIANTE] (ej: "
            "LUMY-COR-000037, LUMY-COR-04-000001 si la subcategoría tiene código "
            "propio cargado, o MSL-ARO-000401-VERDE) a partir de la marca, la "
            "categoría raíz del producto, el código propio de la subcategoría si "
            "está cargado y color/tamaño si están cargados — ver "
            "Product.generate_sku(). Con subcategoría, NNNNNN es un contador "
            "local a esa subcategoría (1, 2, 3...); sin subcategoría, es el pk "
            "global del producto. Una vez generado queda fijo: no se recalcula "
            "solo si después cambiás la categoría o el color, porque ya pudo "
            "haberse publicado en Mercado Libre o en el feed."
        ),
    )
    color = models.CharField(
        max_length=50,
        blank=True,
        help_text=(
            "Color del producto (no es una variante con stock propio — para "
            "eso falta un modelo de variantes que hoy no existe). Se usa "
            "para armar el SKU si está cargado, y además se manda como "
            "atributo COLOR de la publicación de Mercado Libre, pero SOLO si "
            "la categoría cargada en `ml_category_id` admite ese atributo "
            "(se verifica en vivo contra la API de ML al publicar) — si no "
            "lo admite, el campo queda solo para el SKU, sin romper nada."
        ),
    )
    size = models.CharField(
        "Tamaño",
        max_length=50,
        blank=True,
        help_text=(
            "Tamaño del producto (mismo criterio que color): se usa para "
            "armar el SKU si está cargado, y se manda como atributo SIZE de "
            "la publicación de Mercado Libre solo si la categoría cargada lo "
            "admite (hoy MLA375405 'Cortantes' no tiene un atributo de "
            "tamaño/talle propio, así que acá queda solo informativo — se "
            "activa solo si en el futuro se publica en una categoría que sí "
            "lo tenga, ej. indumentaria)."
        ),
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
    cutter_size = models.CharField(
        "Tamaño de cortante",
        max_length=20,
        choices=CutterSize.choices,
        blank=True,
        default=CutterSize.MEDIANO,
        help_text=(
            "Tamaño de costeo del cortante (la pieza, no el diseño) — se usa "
            "SOLO para traer el costo de fabricación desde presupuestos3d en "
            "la pantalla de Precio/Stock/Canales (ver cost_sku()), no afecta "
            "el SKU propio del producto. Vacío = no se busca costo por "
            "tamaño (producto no es un cortante). Si el tamaño elegido "
            "todavía no tiene SKU sintético cargado en COST_SKU_BY_CUTTER_SIZE, "
            "el costo queda en \"no disponible\" sin romper nada."
        ),
    )
    is_available = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    is_available_web = models.BooleanField(
        default=True,
        help_text=(
            "Habilita/deshabilita este producto puntualmente en la web (y el "
            "feed de Google/Meta), sin tocar su publicación en Mercado "
            "Libre. Además de esto tiene que estar activo 'is_available' "
            "(el apagado general)."
        ),
    )
    is_available_ml = models.BooleanField(
        default=True,
        help_text=(
            "Habilita/deshabilita este producto puntualmente en Mercado "
            "Libre, sin tocar la web. Desactivarlo pausa la publicación la "
            "próxima vez que corras la acción 'Publicar/Actualizar en "
            "Mercado Libre'; reactivarlo la vuelve a poner activa. También "
            "se apaga solo cuando Mercado Libre avisa (webhook) que el ítem "
            "ya no está activo (pausado, cerrado, eliminado) — ver "
            "mercadolibre/services.py::handle_item_notification()."
        ),
    )
    # --- Gastos por canal de venta (Mercado Libre / Página web) ---
    # Sin defaults de IVA/Ingresos Brutos a propósito: el dueño los carga a
    # mano según su situación impositiva real, no queremos asumir un valor
    # que puede ser incorrecto para su provincia/condición frente al IVA.
    ml_commission_percent = models.DecimalField(
        "Comisión Mercado Libre (%)",
        max_digits=5, decimal_places=2, default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Comisión que cobra Mercado Libre sobre el precio de venta (varía ~11,8%–17,14% según categoría/tipo de publicación).",
    )
    ml_fixed_fee = models.DecimalField(
        "Cargo fijo Mercado Libre",
        max_digits=10, decimal_places=2, default=0,
        validators=[MinValueValidator(0)],
        help_text="Cargo fijo por unidad vendida que cobra Mercado Libre (depende del precio, escalonado — cargalo a mano según la tabla vigente de ML).",
    )
    ml_vat_percent = models.DecimalField(
        "IVA Mercado Libre (%)",
        max_digits=5, decimal_places=2, default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="IVA aplicable a esta venta, si corresponde.",
    )
    ml_gross_income_tax_percent = models.DecimalField(
        "Ingresos Brutos Mercado Libre (%)",
        max_digits=5, decimal_places=2, default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Ingresos Brutos (IIBB) aplicable según la provincia del dueño.",
    )
    ml_other_variable_percent = models.DecimalField(
        "Otro costo variable Mercado Libre (%)",
        max_digits=5, decimal_places=2, default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Cualquier otro costo variable sobre el precio (ej: cuotas sin interés). Vacío/0 = no aplica.",
    )
    ml_shipping_cost = models.DecimalField(
        "Costo de envío Mercado Libre",
        max_digits=10, decimal_places=2, default=0,
        validators=[MinValueValidator(0)],
        help_text="Costo de envío que absorbe el vendedor en esta venta, si corresponde (Mercado Envíos full/flex, etc.).",
    )
    web_commission_percent = models.DecimalField(
        "Comisión Página web (%)",
        max_digits=5, decimal_places=2, default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Comisión sobre el precio de venta en este canal (ej: la de MercadoPago u otro medio de pago), si corresponde.",
    )
    web_fixed_fee = models.DecimalField(
        "Cargo fijo Página web",
        max_digits=10, decimal_places=2, default=0,
        validators=[MinValueValidator(0)],
        help_text="Cargo fijo por unidad vendida en este canal, si corresponde.",
    )
    web_vat_percent = models.DecimalField(
        "IVA Página web (%)",
        max_digits=5, decimal_places=2, default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="IVA aplicable a esta venta, si corresponde.",
    )
    web_gross_income_tax_percent = models.DecimalField(
        "Ingresos Brutos Página web (%)",
        max_digits=5, decimal_places=2, default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Ingresos Brutos (IIBB) aplicable según la provincia del dueño.",
    )
    web_other_variable_percent = models.DecimalField(
        "Otro costo variable Página web (%)",
        max_digits=5, decimal_places=2, default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Cualquier otro costo variable sobre el precio (ej: cuotas sin interés). Vacío/0 = no aplica.",
    )
    web_shipping_cost = models.DecimalField(
        "Costo de envío Página web",
        max_digits=10, decimal_places=2, default=0,
        validators=[MinValueValidator(0)],
        help_text="Costo de envío que absorbe el vendedor en esta venta, si corresponde.",
    )

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

    # --- Integración Mercado Libre (publicación manual vía admin, ver app `mercadolibre`) ---
    # ml_item_id queda vacío hasta la primera publicación exitosa; a partir de ahí
    # las siguientes sincronizaciones actualizan ese mismo ítem en vez de crear uno nuevo.
    ml_item_id = models.CharField(
        max_length=32,
        blank=True,
        help_text="ID del ítem en Mercado Libre (ej: MLA123456789). Se completa solo al publicar.",
    )
    ml_category_id = models.CharField(
        max_length=32,
        blank=True,
        default="MLA375405",
        help_text=(
            "Categoría de Mercado Libre, distinta de la Category interna. "
            "Default MLA375405 = 'Cortantes' (sirve para todo el catálogo de Lumy); "
            "cambiar si el producto es de otro rubro."
        ),
    )
    weight_kg = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="Peso en kg. Requerido por Mercado Libre para calcular el costo de envío (Mercado Envíos).",
    )
    length_cm = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    width_cm = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    height_cm = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    gtin = models.CharField(
        "GTIN / código de barras",
        max_length=32,
        blank=True,
        help_text=(
            "Código de barras real del producto (EAN/UPC/ISBN, 8 a 14 dígitos), solo si "
            "lo tiene. Para piezas artesanales sin código de barras, dejar vacío — "
            "Mercado Libre valida el checksum y rechaza la publicación si se manda uno "
            "inventado. Se envía como atributo GTIN del ítem (mejora la calidad de la "
            "publicación si está disponible, pero no es obligatorio en esta categoría)."
        ),
    )
    warranty_months = models.PositiveSmallIntegerField(
        "Garantía (meses)",
        null=True,
        blank=True,
        help_text=(
            "Meses de garantía del vendedor que se informan en la publicación de "
            "Mercado Libre (sale_terms: WARRANTY_TYPE='Garantía del vendedor' + "
            "WARRANTY_TIME). Vacío = no se informa garantía en la publicación."
        ),
    )
    free_shipping_seller_paid = models.BooleanField(
        "Envío gratis (lo paga el vendedor)",
        default=False,
        help_text=(
            "Si está activo, la publicación de Mercado Libre se marca con envío "
            "gratis y el costo del flete lo absorbe el vendedor — afecta la "
            "rentabilidad real, es una decisión de pricing, no solo técnica. "
            "OJO: si el precio del producto no alcanza a cubrir el costo de envío, "
            "Mercado Libre ignora este flag en silencio (no rechaza la publicación, "
            "pero tampoco activa el envío gratis) — confirmado en vivo, el warning "
            "que devuelve ML en ese caso (shipping.free_shipping.cost_exceeded) se "
            "muestra en el admin después de correr la acción \"Publicar/Actualizar "
            "en Mercado Libre\", prestale atención a ese mensaje. A diferencia de "
            "las dimensiones, este campo SÍ se puede actualizar en publicaciones ya "
            "existentes (no hace falta volver a crear el ítem)."
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
            self.sku = self.generate_sku()
            super().save(update_fields=["sku"])

    def clean(self):
        """Validaciones cruzadas entre `is_available` (apagado general),
        `is_featured` y los canales (`is_available_web`/`is_available_ml`).

        Regla de negocio: `is_available` manda sobre todos los canales —
        si está apagado, no se vende en ningún lado sin importar los
        otros flags. Pero la relación NO es al revés: apagar un canal
        puntual (web o ML) nunca debe tocar `is_available` ni el otro
        canal, cada uno es independiente. Se corre tanto al guardar desde
        el form de edición completo como al editar inline desde la lista
        del admin (`list_editable`), vía `ModelForm.full_clean()`.
        """
        super().clean()
        if self.is_featured and not self.is_available:
            raise ValidationError({
                "is_featured": (
                    "No se puede destacar un producto marcado como no "
                    "disponible (is_available). Activá 'is_available' primero."
                ),
            })

    def __str__(self):
        return self.name

    def generate_sku(self) -> str:
        """Arma el SKU MARCA-CATEGORIA[-ID_SUBCATEGORIA]-NNNNNN[-VARIANTE] a
        partir del estado actual del producto (marca, categoría raíz,
        subcategoría, color/tamaño).

        NNNNNN: si la categoría es una subcategoría con `sku_prefix` propio
        (ej: "04" en Cortantes > Animales de la Selva), es un CONTADOR LOCAL
        a esa subcategoría (1, 2, 3...), no el pk global del producto — así
        una subcategoría chica (ej: Navidad) no termina con números de 3
        cifras que no dicen nada sobre esa colección puntual. Si la
        categoría no tiene subcategoría con código propio, se sigue usando
        el pk global (comportamiento histórico, sin tocar — ver nota abajo).

        Ojo: este cambio de numeración rige desde que se agregó (no se
        regeneran retroactivamente los SKU ya asignados antes, para no
        romper publicaciones ya hechas en Mercado Libre/el feed — ver
        help_text de `sku`).

        Se usa al crear el producto (ver `save()`) y también desde la acción
        de admin "Regenerar SKU"/el management command `regenerar_skus` para
        recalcular a pedido. No se llama solo en cada `save()` — el SKU, una
        vez asignado, queda fijo aunque después cambien marca/categoría/color.
        """
        if self.brand_id and self.brand.sku_prefix:
            brand_code = self.brand.sku_prefix
        elif self.brand_id:
            brand_code = slugify(self.brand.slug).replace("-", "").upper()[:4] or "GEN"
        else:
            brand_code = "GEN"

        category_code = self.category.root_sku_prefix() if self.category_id else "GEN"

        base = f"{brand_code}-{category_code}"

        # Si el producto está en una subcategoría (no la raíz) y esa
        # subcategoría tiene su propio código cargado (ej: "04" en Cortantes
        # > Animales de la Selva), se suma como segmento extra del SKU y el
        # número pasa a ser un contador local a esa subcategoría.
        tiene_subcategoria = bool(
            self.category_id and self.category.parent_id and self.category.sku_prefix
        )
        if tiene_subcategoria:
            base += f"-{self.category.sku_prefix}"
            numero = self._next_subcategory_sku_number(base)
        else:
            numero = self.pk

        base += f"-{numero:06d}"

        variant_parts = []
        for value in (self.color, self.size):
            if value:
                code = slugify(value).replace("-", "").upper()
                if code:
                    variant_parts.append(code)
        if variant_parts:
            base += "-" + "-".join(variant_parts)
        return base

    def _next_subcategory_sku_number(self, prefix: str) -> int:
        """Próximo número libre dentro de `prefix` (ej: "LUMY-COR-45") entre
        los SKU ya asignados en la MISMA categoría de este producto.

        Toma el máximo ya usado (no solo cuenta productos) para no repetir
        un número si se borró alguno en el medio."""
        pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)")
        maximo = 0
        skus = (
            Product.objects.filter(category_id=self.category_id)
            .exclude(pk=self.pk)
            .values_list("sku", flat=True)
        )
        for sku in skus:
            match = pattern.match(sku)
            if match:
                maximo = max(maximo, int(match.group(1)))
        return maximo + 1

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

    def cost_sku(self) -> str | None:
        """SKU a consultar en presupuestos3d para el costo de fabricación
        de este producto.

        NO es `self.sku` (el SKU propio de cada diseño) — es el SKU
        sintético de costeo por `cutter_size` (`COST_SKU_BY_CUTTER_SIZE`),
        porque muchos diseños de cortante comparten el mismo tamaño de
        pieza y por lo tanto el mismo costo real. `None` si no tiene
        `cutter_size` cargado o ese tamaño todavía no tiene SKU sintético
        confirmado del otro lado — en ambos casos el admin muestra "costo
        no disponible" sin romper la ficha.
        """
        if not self.cutter_size:
            return None
        return self.COST_SKU_BY_CUTTER_SIZE.get(self.cutter_size)

    def channel_total_expenses(self, channel: str) -> Decimal:
        """Suma de todos los gastos de vender este producto por `channel`
        ('ml' o 'web'): comisión + IVA + Ingresos Brutos + otro costo
        variable (los cuatro en % sobre `price`) más el cargo fijo y el
        costo de envío (ambos en $). Fuente de verdad de "Total de gastos
        del canal" en la pantalla de Precio/Stock/Canales del admin.
        """
        percent_total = (
            getattr(self, f"{channel}_commission_percent")
            + getattr(self, f"{channel}_vat_percent")
            + getattr(self, f"{channel}_gross_income_tax_percent")
            + getattr(self, f"{channel}_other_variable_percent")
        )
        variable = self.price * percent_total / Decimal(100)
        fixed = getattr(self, f"{channel}_fixed_fee") + getattr(self, f"{channel}_shipping_cost")
        return (variable + fixed).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def channel_net_profit(self, channel: str, cost: Decimal | None) -> Decimal | None:
        """Ganancia neta ($) vendiendo por `channel`: price - cost - gastos
        del canal. `cost` viene de presupuestos3d (ver
        `products/services/presupuestos3d.py::get_cost()`) — si no está
        disponible, no se puede calcular la ganancia real y se devuelve
        `None` (el admin muestra "costo no disponible" en ese caso).
        """
        if cost is None:
            return None
        gastos = self.channel_total_expenses(channel)
        return (self.price - cost - gastos).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def channel_net_profit_percent(self, channel: str, cost: Decimal | None) -> Decimal | None:
        """Ganancia neta como % de `price`. `None` si falta el costo o si
        `price` es 0 (no se puede expresar un % sobre precio cero)."""
        if cost is None or not self.price:
            return None
        ganancia = self.channel_net_profit(channel, cost)
        return (ganancia / self.price * Decimal(100)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


class ProductImage(models.Model):
    class Channel(models.TextChoices):
        BOTH = "both", "Ambos (web y Mercado Libre)"
        WEB = "web", "Solo página web"
        ML = "ml", "Solo Mercado Libre"

    product = models.ForeignKey(Product, related_name="images", on_delete=models.CASCADE)
    image = models.ImageField(upload_to="products/images/")
    order = models.PositiveIntegerField(default=0, help_text="Orden de la foto en la página web.")
    ml_order = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Orden en la publicación de Mercado Libre, si querés que sea distinto al de la web. Vacío = usa el mismo orden que la web.",
    )
    alt = models.CharField(max_length=200, blank=True)
    channel = models.CharField(
        max_length=10,
        choices=Channel.choices,
        default=Channel.BOTH,
        help_text="A dónde se muestra esta foto. 'Ambos' es el comportamiento de siempre.",
    )

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.product.name} - imagen {self.order}"
