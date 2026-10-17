import re
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.text import slugify
from brands.models import Brand


def _max_tier_discount(tiers, quantity: int) -> int:
    """% de descuento del tramo de mayor cantidad que `quantity` todavía
    cubre, dada una lista de tramos `[{"quantity": N, "discount_percent": P}, ...]`.

    Helper compartido por `Product.bundle_discount_percent_for()` (mismo
    producto) y `Category.bundle_discount_percent_for()` (combo entre
    productos de la misma subcategoría) — misma semántica de tramos en los
    dos casos, solo cambia qué cantidad se les pasa.
    """
    if not tiers:
        return 0
    applicable = [
        int(tier.get("discount_percent", 0))
        for tier in tiers
        if quantity >= int(tier.get("quantity", 0))
    ]
    return max(applicable) if applicable else 0


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
    bundle_discounts = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Descuento por combo entre PRODUCTOS DISTINTOS de esta misma "
            "subcategoría exacta (no suma con subcategorías hermanas ni con "
            "la categoría padre). Lista de tramos, ej: "
            '[{"quantity": 2, "discount_percent": 10}, {"quantity": 3, "discount_percent": 15}]. '
            "La cantidad del tramo es la SUMA de unidades entre todos los "
            "productos de esta categoría en el carrito (mezclados o "
            "repetidos — comprar 5 unidades del mismo producto también "
            "cuenta). Vacío = sin combo para esta subcategoría. Disponible "
            "para cualquier marca, no es exclusivo de ninguna. Si el "
            "producto además tiene su propio `bundle_discounts` (mismo "
            "producto, ver Product), se aplica el MAYOR de los dos "
            "porcentajes, no la suma."
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

    def bundle_discount_percent_for(self, quantity: int) -> int:
        """% de descuento por combo aplicable a `quantity` unidades combinadas
        de productos de esta subcategoría exacta (ver help_text de
        `bundle_discounts`)."""
        return _max_tier_discount(self.bundle_discounts, quantity)


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
    shape = models.CharField(
        "Forma",
        max_length=50,
        blank=True,
        help_text=(
            "Forma del producto (ej: Animal, Estrella, Número, Calabaza...) "
            "— se manda como atributo COOKIE_CUTTER_SHAPE de la publicación "
            "de Mercado Libre, solo si la categoría cargada lo admite (hoy "
            "MLA375405 'Cortantes' sí lo tiene — aparece en Mercado Libre "
            "como 'Características secundarias', suma a la calidad de la "
            "publicación). Texto libre: no hace falta que coincida con las "
            "opciones sugeridas de ML. Vacío = no se informa."
        ),
    )
    is_dishwasher_safe = models.BooleanField(
        "Apto para lavavajillas",
        null=True,
        blank=True,
        default=None,
        help_text=(
            "Si el producto es apto para lavavajillas. Se manda como "
            "atributo IS_DISHWASHER_SAFE de la publicación de Mercado Libre "
            "(Sí/No), solo si la categoría cargada lo admite. Dejalo en "
            "blanco ('Desconocido', valor vacío) si no corresponde "
            "informarlo — a diferencia de un booleano normal, acá 'vacío' "
            "no equivale a 'No': simplemente no se manda el atributo."
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
    ml_price = models.DecimalField(
        "Precio Mercado Libre",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=(
            "Precio a publicar en Mercado Libre, si querés que sea distinto "
            "del precio de la web ('price', arriba). Vacío = se usa el "
            "mismo precio en los dos canales (comportamiento de siempre). "
            "Pensado para compensar que Mercado Libre cobra más comisión/"
            "impuestos que una venta directa desde la web: cargá acá el "
            "precio que querés cobrar puntualmente en ML y el resumen de "
            "más abajo te muestra la ganancia neta resultante. `price` "
            "sigue siendo la base: es el que manda presupuestos3d en cada "
            "sync y el que se usa siempre en la web. Si volvés a dejar "
            "este campo vacío, ML vuelve a usar 'price' automáticamente."
        ),
    )
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

    ml_last_synced_at = models.DateTimeField(
        "Última sincronización con Mercado Libre",
        null=True,
        blank=True,
        editable=False,
        help_text=(
            "Última vez que `sync_product()` publicó/actualizó (o pausó/reactivó) "
            "este ítem contra la API real de Mercado Libre. Puramente informativo "
            "— lo pisa el propio sync, no se edita a mano."
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
        return _max_tier_discount(self.bundle_discounts, quantity)

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

    def sale_price_for(self, channel: str) -> Decimal:
        """Precio de venta efectivo para `channel` ('ml' o 'web').

        Hoy solo Mercado Libre puede diferenciarse: si `ml_price` está
        cargado, se usa ese; si no, se cae al `price` general (mismo
        comportamiento que antes de que existiera `ml_price`). La web
        siempre usa `price` — no hay (todavía) un `web_price` propio,
        porque `price` YA ES el precio de la web.
        """
        if channel == "ml" and self.ml_price is not None:
            return self.ml_price
        return self.price

    def channel_total_expenses(self, channel: str) -> Decimal:
        """Suma de todos los gastos de vender este producto por `channel`
        ('ml' o 'web'): comisión + IVA + Ingresos Brutos + otro costo
        variable (los cuatro en % sobre el precio efectivo del canal, ver
        `sale_price_for()`) más el cargo fijo y el costo de envío (ambos en
        $). Fuente de verdad de "Total de gastos del canal" en la pantalla
        de Precio/Stock/Canales del admin.
        """
        precio = self.sale_price_for(channel)
        percent_total = (
            getattr(self, f"{channel}_commission_percent")
            + getattr(self, f"{channel}_vat_percent")
            + getattr(self, f"{channel}_gross_income_tax_percent")
            + getattr(self, f"{channel}_other_variable_percent")
        )
        variable = precio * percent_total / Decimal(100)
        fixed = getattr(self, f"{channel}_fixed_fee") + getattr(self, f"{channel}_shipping_cost")
        return (variable + fixed).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def channel_expense_breakdown(self, channel: str) -> list[dict]:
        """Desglose línea por línea de los gastos que suma
        `channel_total_expenses()` — cada uno con su monto en $ y qué %
        representa sobre el precio efectivo del canal (ver
        `sale_price_for()`). Puramente informativo para el admin (ver
        `ProductAdmin._channel_resumen()`): no se usa en ningún cálculo de
        ganancia, `channel_total_expenses()` sigue siendo la única fuente de
        verdad del total.
        """
        precio = self.sale_price_for(channel)
        lineas = []
        percent_fields = (
            ("commission_percent", "Comisión"),
            ("vat_percent", "IVA"),
            ("gross_income_tax_percent", "Ingresos Brutos"),
            ("other_variable_percent", "Otro costo variable (ej: cuotas)"),
        )
        for field, label in percent_fields:
            pct = getattr(self, f"{channel}_{field}")
            monto = (precio * pct / Decimal(100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            lineas.append({"label": label, "percent": pct, "amount": monto})

        fixed_fields = (
            ("fixed_fee", "Cargo fijo"),
            ("shipping_cost", "Costo de envío"),
        )
        for field, label in fixed_fields:
            monto = getattr(self, f"{channel}_{field}")
            pct = (
                (monto / precio * Decimal(100)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
                if precio
                else None
            )
            lineas.append({"label": label, "percent": pct, "amount": monto})

        return lineas

    def channel_net_profit(self, channel: str, cost: Decimal | None) -> Decimal | None:
        """Ganancia neta ($) vendiendo por `channel`: precio efectivo del
        canal (ver `sale_price_for()`) - cost - gastos del canal. `cost`
        viene de presupuestos3d (ver
        `products/services/presupuestos3d.py::get_cost()`) — si no está
        disponible, no se puede calcular la ganancia real y se devuelve
        `None` (el admin muestra "costo no disponible" en ese caso).
        """
        if cost is None:
            return None
        precio = self.sale_price_for(channel)
        gastos = self.channel_total_expenses(channel)
        return (precio - cost - gastos).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def channel_net_profit_percent(self, channel: str, cost: Decimal | None) -> Decimal | None:
        """Ganancia neta como % del precio efectivo del canal (ver
        `sale_price_for()`). `None` si falta el costo o si ese precio es 0
        (no se puede expresar un % sobre precio cero)."""
        precio = self.sale_price_for(channel)
        if cost is None or not precio:
            return None
        ganancia = self.channel_net_profit(channel, cost)
        return (ganancia / precio * Decimal(100)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


class ProductoEnMercadoLibre(Product):
    """Proxy de `Product` (misma tabla, sin migración de datos) para tener una
    vista de admin separada con solo los productos ya publicados en Mercado
    Libre (`ml_item_id` cargado) — pensada para el día a día de "entrar a ver/
    tocar lo que ya está en ML", sin tener que buscarlo entre los ~400
    productos del catálogo completo. Ver `ProductoEnMercadoLibreAdmin`
    (`products/admin.py`), que filtra el queryset y reusa TODO lo demás
    (fieldsets, inlines, acciones) de `ProductAdmin` por herencia.
    """

    class Meta:
        proxy = True
        verbose_name = "Producto publicado en Mercado Libre"
        verbose_name_plural = "Productos publicados en Mercado Libre"


class CostTemplate(models.Model):
    """"Plantilla de costo" compartida por muchas variantes de catálogo.

    Es el equivalente, del lado de 3darg-backend, a un `Producto` de costeo
    marcado `es_producto_ecommerce=True` en presupuestos3d (ej: "Cortante
    4cm", "Shaker grande"): un perfil de costo/precio que aplica a MUCHOS
    `ProductVariant` sin importar diseño, marca o categoría — se carga el
    presupuesto una sola vez ahí y se propaga a cada variante que lo
    referencie (`ProductVariant.cost_template`).

    No reemplaza `Product.cutter_size` (sigue existiendo sin tocar, es el
    mecanismo viejo de costeo "por tag" que usa `CosteoSyncAPIView`) — lo
    sucede: la migración `0034_crear_productvariant_y_costtemplate` crea un
    `CostTemplate` por cada valor de `cutter_size` en uso (`legacy_cutter_size`)
    para no perder la agrupación histórica, dejando `sale_price` vacío (no
    se fuerza un precio único retroactivo sobre variantes que hoy pueden
    tener precios distintos a pesar de compartir tamaño de costeo).
    """

    nombre = models.CharField(
        max_length=100,
        unique=True,
        help_text=(
            "Nombre del presupuesto/perfil de costo, tal como se carga en "
            "presupuestos3d (ej: \"Cortante 4cm\", \"Shaker grande\"). Libre, "
            "sin límite de cantidad — a diferencia del viejo cutter_size, no "
            "está atado a un enum fijo de 5 valores."
        ),
    )
    external_ref = models.CharField(
        max_length=64,
        unique=True,
        null=True,
        blank=True,
        help_text=(
            "Referencia estable del Producto de costeo en presupuestos3d que "
            "originó este template (la que viaja en el payload del sync). Se "
            "usa para hacer upsert por ID en vez de por nombre, así renombrar "
            "el presupuesto en presupuestos3d no rompe el link. Vacío en los "
            "templates migrados desde cutter_size (todavía no vienen de un "
            "sync real)."
        ),
    )
    sale_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=(
            "Precio de venta a aplicar a todos los ProductVariant que "
            "referencien este template. Vacío = todavía no se sincronizó "
            "ningún precio desde presupuestos3d para este template (las "
            "variantes conservan su propio precio actual, sin tocarlo)."
        ),
    )
    weight_kg = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    length_cm = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    width_cm = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    height_cm = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    size_label = models.CharField(
        "Tamaño (informativo)",
        max_length=50,
        blank=True,
        help_text=(
            "Tamaño informativo (ej: 'Mediano', 'Chico') que se propaga solo "
            "al 'Tamaño' (`size`) de TODAS las variantes/productos vinculados "
            "a este template — mismo criterio automático que precio y medidas "
            "(ver `ProductVariant.save()`): se pisa en cada guardado de la "
            "variante mientras este campo tenga algo cargado; vacío = no toca "
            "el 'Tamaño' que ya tenga cargado el producto."
        ),
    )
    legacy_cutter_size = models.CharField(
        max_length=20,
        blank=True,
        help_text=(
            "Valor de Product.cutter_size que originó este template en la "
            "migración inicial (0034) — solo trazabilidad histórica, no se "
            "usa en ningún cálculo nuevo."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nombre"]
        verbose_name = "Plantilla de costo"
        verbose_name_plural = "Plantillas de costo"

    def __str__(self):
        return self.nombre


# Campos de medidas que se heredan del CostTemplate a la variante/producto en
# ProductVariant.save() — mismo set que usa CosteoSyncAPIView (`_MEASUREMENT_FIELDS`
# en products/views.py) para no duplicar criterio de qué es "medida del template".
_COST_TEMPLATE_MEASUREMENT_FIELDS = ("weight_kg", "length_cm", "width_cm", "height_cm")


class ProductVariant(models.Model):
    """Unidad vendible real de un `Product` (el diseño/modelo).

    `Product` sigue siendo "la ficha" del diseño — nombre, categoría, marca,
    fotos, publicación en Mercado Libre/feed. `ProductVariant` es el
    tamaño/color puntual que se vende, con su propio precio/stock/SKU.

    Fase 1 (migración `0034_crear_productvariant_y_costtemplate.py`): cada
    `Product` tenía EXACTAMENTE una variante y nada del resto del sistema la
    leía — era solo el anclaje para que el sync de costeo de presupuestos3d
    tuviera dónde vincularse.

    Fase 2 (actual): `cart`/`orders`/`payments` SÍ leen `ProductVariant`
    cuando un producto tiene más de una — un mismo `Product` (el diseño,
    ej. "Molde de torta Unicornio") puede tener varias `ProductVariant` de
    `size` (ej. Chico/Mediano/Grande), cada una con su propio precio y
    stock. Si un producto sigue teniendo una sola variante, todo sigue
    funcionando igual que en Fase 1 (no es obligatorio migrar todo el
    catálogo de una). El selector de "Talle" del frontend solo se muestra
    si `product.variants` tiene más de una entrada.
    """

    product = models.ForeignKey(
        Product,
        related_name="variants",
        on_delete=models.CASCADE,
    )
    color = models.CharField(max_length=50, blank=True)
    size = models.CharField("Tamaño", max_length=50, blank=True)
    order = models.PositiveIntegerField(
        "Orden",
        default=0,
        help_text=(
            "Orden de aparición entre las variantes de este producto (ej: "
            "Chico=1, Mediano=2, Grande=3) — el alfabético no sirve para "
            "una progresión de tamaños. No afecta nada más."
        ),
    )
    sku = models.CharField(max_length=64, unique=True, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.PositiveIntegerField(default=0)
    cost_template = models.ForeignKey(
        CostTemplate,
        related_name="variants",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text=(
            "Presupuesto de presupuestos3d del que toma precio/medidas esta "
            "variante. Vacío = variante con precio propio, no ligada a "
            "ningún presupuesto compartido (ej: producto a medida)."
        ),
    )
    weight_kg = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    length_cm = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    width_cm = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    height_cm = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    gtin = models.CharField("GTIN / código de barras", max_length=32, blank=True)
    is_available = models.BooleanField(default=True)
    ml_variation_id = models.CharField(
        max_length=32,
        blank=True,
        help_text=(
            "ID de la variación en Mercado Libre, para cuando el ítem tenga "
            "variaciones reales publicadas (no usado todavía, Fase 1 publica "
            "igual que siempre a nivel Product)."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["product", "order", "color", "size"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "color", "size"],
                name="unique_variant_per_product_color_size",
            ),
        ]
        verbose_name = "Variante de producto"
        verbose_name_plural = "Variantes de producto"

    def __str__(self):
        return f"{self.product.name} ({self.label})"

    @property
    def label(self) -> str:
        """Etiqueta corta de esta variante (ej. "Mediano / Rojo"), para
        mostrar en el selector de Talle, el carrito, el checkout y el
        historial de pedidos — un solo lugar para no repetir el `" / "
        .join(...)` en cada consumidor."""
        return " / ".join(filter(None, [self.size, self.color])) or "única"

    @property
    def has_member_discount(self) -> bool:
        """Usa el % de descuento de socio del `Product` (no hay uno propio
        por variante) — el incentivo de socios es por producto, el talle
        solo cambia precio/stock base."""
        return self.product.member_discount_percent > 0

    @property
    def member_price(self) -> Decimal:
        """Precio con el descuento de socio del `Product` aplicado sobre el
        precio PROPIO de esta variante (mismo cálculo que
        `Product.member_price`, pero sobre `self.price`)."""
        if not self.has_member_discount:
            return self.price
        factor = (Decimal(100) - Decimal(self.product.member_discount_percent)) / Decimal(100)
        return (self.price * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def price_for(self, user) -> Decimal:
        """Precio efectivo que paga `user` por ESTA variante — mismo
        criterio que `Product.price_for()` (socio = `member_price`, anónimo
        = `price`), pero resuelto sobre el precio propio de la variante."""
        if user and getattr(user, "is_authenticated", False):
            return self.member_price
        return self.price

    def save(self, *args, **kwargs):
        """Si la variante está vinculada a un `CostTemplate`, hereda de ahí
        precio y medidas (peso/largo/ancho/alto) — y las refleja también en
        el `Product` subyacente, mientras dure la Fase 1 — sin importar si
        el guardado viene del form de edición normal, del shell, de
        `list_editable` o de una API. Esto evita que un vínculo hecho fuera
        de la acción "Asignar template de costo..." (la única que antes
        copiaba estos datos a mano) deje la variante/producto desactualizados
        en silencio — exactamente lo que pasó con "Adorno Bola": se vinculó
        el template editando la variante directo y el precio nunca se
        propagó.

        Igual que `CosteoSyncAPIView`, cada campo del template se copia solo
        si está cargado (`is not None`) — un template con una medida vacía no
        borra la medida que ya tenía la variante. `size_label` sigue el mismo
        criterio pero con "vacío" de string (`if template.size_label:`), para
        armar el "Tamaño" (`size`) de la variante/producto sin tener que
        cargarlo a mano en cada diseño — ej: todo lo vinculado al template
        "Mediano" queda con `size="Mediano"` solo.

        `CosteoSyncAPIView` y la acción de admin siguen actualizando estos
        campos con `.update()` a propósito (son operaciones en bloque sobre
        muchas variantes a la vez, no pasan por este `save()` uno por uno) —
        esta lógica cubre el resto de los casos, que antes no tenían ninguna
        garantía.

        OJO Fase 2: este espejo a `Product` solo tiene sentido mientras el
        producto tenga EXACTAMENTE una variante (el caso Fase 1, donde
        `Product.price`/medidas siguen siendo la fuente de verdad para
        cart/checkout de un producto sin talles). Si el producto ya tiene
        más de una `ProductVariant` (ej: Chico/Mediano/Grande), cada talle
        tiene su propio precio real — pisar `Product` con el de "la última
        variante que se guardó" sería arbitrario y rompería el precio que
        ven las otras variantes, así que el espejo se omite en ese caso.
        """
        update_kwargs = {}
        if self.cost_template_id:
            template = self.cost_template
            if template.sale_price is not None:
                self.price = template.sale_price
                update_kwargs["price"] = template.sale_price
            for field in _COST_TEMPLATE_MEASUREMENT_FIELDS:
                value = getattr(template, field)
                if value is not None:
                    setattr(self, field, value)
                    update_kwargs[field] = value
            if template.size_label:
                self.size = template.size_label
                update_kwargs["size"] = template.size_label
        super().save(*args, **kwargs)
        if update_kwargs and ProductVariant.objects.filter(product_id=self.product_id).count() <= 1:
            Product.objects.filter(pk=self.product_id).update(**update_kwargs)


class ProductImage(models.Model):
    class Channel(models.TextChoices):
        WEB = "web", "Página web"
        ML = "ml", "Mercado Libre"

    product = models.ForeignKey(Product, related_name="images", on_delete=models.CASCADE)
    image = models.ImageField(upload_to="products/images/")
    order = models.PositiveIntegerField(
        default=0,
        help_text="Orden de la foto dentro de su canal (web o Mercado Libre).",
    )
    alt = models.CharField(max_length=200, blank=True)
    channel = models.CharField(
        max_length=10,
        choices=Channel.choices,
        default=Channel.WEB,
        help_text=(
            "A dónde se muestra esta foto. Cada foto pertenece a un solo canal — "
            "si la necesitás en los dos, cargala dos veces (una en cada apartado "
            "de Imágenes del admin)."
        ),
    )

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.product.name} - imagen {self.order}"
