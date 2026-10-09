from decimal import Decimal

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet, ModelChoiceIterator
from django.utils.html import format_html
from .models import Product, Category, ProductImage
from .services.presupuestos3d import get_cost
from mercadolibre.services import sync_product, MLSyncError, MIN_ML_PICTURES


class _GroupedCategoryIterator(ModelChoiceIterator):
    """Agrupa el <select> de categoría del form de Product por categoría
    raíz (ej: CORTANTES, RODILLOS TEXTURIZADORES), vía <optgroup> nativo de
    Django (`Select.optgroups()` ya sabe renderizar choices anidados, no
    hace falta tocar el widget) — mismo criterio visual que el sidebar de
    categorías de la tienda (`[brand]/shop/page.tsx` en el frontend), que
    también agrupa por categoría padre.

    Dentro de cada grupo, "Todos" y "Sets" van primero (son las
    subcategorías "genéricas", no atadas a un tema puntual) y el resto
    queda alfabético. Una categoría raíz SIN subcategorías (ej: "shaker"
    de Print&Gym) se lista suelta, sin agrupar.

    La categoría raíz (ej: "CORTANTES") es solo el título visual del
    grupo — un <optgroup> no es una <option>, así que no queda
    seleccionable: los productos siempre cuelgan de una subcategoría
    (temática, "Todos" o "Sets"), nunca de la raíz directamente.
    """

    PRIORIDAD = {"todos": 0, "sets": 1}

    def __iter__(self):
        if self.field.empty_label is not None:
            yield ("", self.field.empty_label)

        categorias = list(self.queryset)
        hijas_por_padre = {}
        for cat in categorias:
            if cat.parent_id:
                hijas_por_padre.setdefault(cat.parent_id, []).append(cat)

        def orden(cat):
            return (self.PRIORIDAD.get(cat.name.strip().lower(), 2), cat.name)

        for cat in categorias:
            if cat.parent_id:
                continue  # se listan debajo de su padre, no sueltas
            hijas = hijas_por_padre.get(cat.id)
            if hijas:
                yield (
                    cat.name.upper(),
                    [
                        (self.field.prepare_value(h), self.field.label_from_instance(h))
                        for h in sorted(hijas, key=orden)
                    ],
                )
            else:
                yield (self.field.prepare_value(cat), self.field.label_from_instance(cat))


class ProductImageInlineFormSet(BaseInlineFormSet):
    """Exige el piso de fotos de Mercado Libre (MIN_ML_PICTURES, hoy 3) al guardar
    el producto desde el admin si tiene prendido el canal ML (`is_available_ml`) —
    mismo criterio que `mercadolibre/services.py::_build_payload()` ya exige recién
    al publicar, pero acá lo frenamos antes, al guardar, para no dejar cargar un
    producto "ML-habilitado" que después va a fallar al intentar sincronizarlo.

    Esta validación cruzada no puede ir en `Product.clean()` porque las fotos son
    un inline: al validarse el form principal del producto, las imágenes todavía
    no están guardadas (ni el producto tiene pk todavía, si es nuevo). Acá, en
    cambio, Django ya dejó `is_available_ml` cargado en `self.instance` (lo asigna
    `_post_clean()` del form principal antes de guardar) y tenemos todas las filas
    de fotos del formset a mano, incluidas las marcadas para borrar.
    """

    def clean(self):
        super().clean()
        if any(self.errors):
            return  # ya hay errores de fila individuales, no sumar ruido encima
        if not getattr(self.instance, "is_available_ml", False):
            return

        count = 0
        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue
            cleaned = form.cleaned_data
            if not cleaned or cleaned.get("DELETE"):
                continue
            if cleaned.get("image") and cleaned.get("channel") != ProductImage.Channel.WEB:
                count += 1

        if count < MIN_ML_PICTURES:
            raise ValidationError(
                "Este producto tiene activado el canal Mercado Libre "
                f"(is_available_ml) — necesita al menos {MIN_ML_PICTURES} fotos "
                "marcadas para Mercado Libre (canal 'Ambos' o 'Solo Mercado Libre') "
                f"para poder guardarse. Hoy tiene {count}. Si todavía no tenés las "
                "fotos listas, desactivá 'is_available_ml' hasta cargarlas."
            )


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    formset = ProductImageInlineFormSet
    extra = 1
    fields = ["image", "channel", "order", "ml_order", "alt"]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "slug", "brand", "parent", "sku_prefix"]
    list_filter = ["brand", "parent"]
    search_fields = ["name", "slug", "sku_prefix"]
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ["parent"]


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    class Media:
        js = ["products/admin/category_cascade.js"]

    # Los productos tocados más recientemente (alta o edición) quedan arriba de
    # todo — es el orden más útil para el flujo de trabajo diario (ver qué se
    # cargó/editó último), en vez del alfabético/por id de siempre.
    ordering = ["-updated_at"]

    list_display = [
        "name", "brand", "sku", "price", "member_discount_percent", "members_only",
        "stock", "is_available", "is_available_web", "is_available_ml", "is_featured",
    ]
    list_filter = [
        "brand", "category", "members_only", "is_featured",
        "is_available", "is_available_web", "is_available_ml",
    ]
    list_editable = [
        "member_discount_percent", "members_only", "is_available", "is_available_web",
        "is_available_ml", "is_featured",
    ]
    search_fields = ["name", "description", "sku", "color", "size"]
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ["ml_item_id", "ml_resumen", "web_resumen"]
    inlines = [ProductImageInline]
    actions = ["publicar_en_mercadolibre", "regenerar_sku"]

    def _channel_resumen(self, obj, channel: str, label: str):
        """Costo (presupuestos3d, por SKU) + gastos totales + ganancia neta
        ($ y %) de vender `obj` por `channel`. Se recalcula en cada render
        de la ficha (al abrirla o guardarla) — no hace falta en vivo mientras
        se tipea, ver `products/services/presupuestos3d.py`.
        """
        if obj is None or not obj.pk:
            return "Guardá el producto primero para ver este resumen."

        cost = None
        costeo_sku = obj.cost_sku()
        if costeo_sku:
            cost_data = get_cost(costeo_sku)
            if cost_data:
                cost = Decimal(cost_data["unit_cost_avg"])
        costo_str = f"${cost:.2f}" if cost is not None else "costo no disponible"

        gastos = obj.channel_total_expenses(channel)
        ganancia = obj.channel_net_profit(channel, cost)
        if ganancia is not None:
            ganancia_pct = obj.channel_net_profit_percent(channel, cost)
            ganancia_str = f"${ganancia:.2f} ({ganancia_pct}%)"
        else:
            ganancia_str = "no se puede calcular (falta el costo de presupuestos3d)"

        return format_html(
            "<strong>Costo (presupuestos3d):</strong> {} &nbsp;|&nbsp; "
            "<strong>Gastos de {}:</strong> ${} &nbsp;|&nbsp; "
            "<strong>Ganancia neta:</strong> {}",
            costo_str, label, f"{gastos:.2f}", ganancia_str,
        )

    @admin.display(description="Resumen Mercado Libre")
    def ml_resumen(self, obj):
        return self._channel_resumen(obj, "ml", "Mercado Libre")

    @admin.display(description="Resumen Página web")
    def web_resumen(self, obj):
        return self._channel_resumen(obj, "web", "Página web")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        field = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if db_field.name == "category":
            # Dropdown agrupado por categoría raíz (CORTANTES, RODILLOS
            # TEXTURIZADORES, ...) — ver _GroupedCategoryIterator arriba.
            # Nombre solo (sin "Padre > Hijo", eso ya lo dice el <optgroup>).
            field.queryset = field.queryset.select_related("parent")
            field.label_from_instance = lambda obj: obj.name
            field.iterator = _GroupedCategoryIterator
        return field

    fieldsets = (
        (None, {
            "fields": ("name", "slug", "sku", "description", "category", "brand"),
            "description": (
                "El SKU se precarga solo al crear el producto (Product.generate_sku()), "
                "pero el campo queda editable por si hace falta corregirlo a mano "
                "(ej: typo, migración de un código viejo, etc.) — ver el help text "
                "del campo para el formato esperado. Guardalo dejándolo vacío para que "
                "se regenere automáticamente al crear el producto."
            ),
        }),
        ("Color y tamaño", {
            "fields": ("color", "size"),
            "description": (
                "Solo informativo (no son variantes con stock propio). Si los "
                "cargás, usá la acción \"Regenerar SKU\" de la lista para que "
                "queden reflejados en el SKU — no se recalcula solo al guardar."
            ),
        }),
        ("Precio y stock", {
            "fields": ("price", "stock", "cutter_size", "is_available", "is_featured"),
            "description": (
                "'Tamaño de cortante' es el tamaño de COSTEO (la pieza, no "
                "el diseño) — determina qué costo se trae de presupuestos3d "
                "para calcular la ganancia neta de cada canal más abajo. No "
                "tiene efecto en productos que no sean cortantes (dejalo "
                "vacío en ese caso)."
            ),
        }),
        ("Mercado Libre — canal y ganancia", {
            "fields": (
                "is_available_ml",
                "ml_commission_percent", "ml_fixed_fee", "ml_vat_percent",
                "ml_gross_income_tax_percent", "ml_other_variable_percent", "ml_shipping_cost",
                "ml_resumen",
            ),
            "description": (
                "Prender/apagar este producto en Mercado Libre y cargar los "
                "gastos de esa venta para ver cuánto queda de ganancia neta. "
                "Comisión ML varía ~11,8%–17,14% según categoría/tipo de "
                "publicación; el cargo fijo es escalonado por precio, cargalo "
                "a mano según la tabla vigente de ML. El costo de fabricación "
                "se trae solo de presupuestos3d por SKU — \"costo no disponible\" "
                "si ese sistema está apagado o el SKU no matchea. 'is_available' "
                "(arriba) sigue siendo el apagado general: si está apagado, no "
                "se vende en ningún lado sin importar este canal. Después de "
                "cambiar is_available_ml corré la acción \"Publicar/Actualizar "
                "en Mercado Libre\" para que el pausado/reactivado se refleje "
                "ahí — no es automático. También se apaga solo cuando Mercado "
                "Libre nos avisa (webhook) que el ítem ya no está activo."
            ),
        }),
        ("Página web — canal y ganancia", {
            "fields": (
                "is_available_web",
                "web_commission_percent", "web_fixed_fee", "web_vat_percent",
                "web_gross_income_tax_percent", "web_other_variable_percent", "web_shipping_cost",
                "web_resumen",
            ),
            "description": (
                "Prender/apagar este producto en la web y cargar los gastos de "
                "esa venta (ej: comisión del medio de pago, envío a cargo "
                "propio) para ver la ganancia neta. 'is_available' (arriba) "
                "sigue siendo el apagado general, independiente de este canal."
            ),
        }),
        ("Descuento por volumen", {
            "fields": ("bundle_discounts",),
            "description": (
                'Tramos de descuento por cantidad (mismo producto), ej: '
                '[{"quantity": 2, "discount_percent": 10}, {"quantity": 3, "discount_percent": 15}]. '
                "Vacío = no se muestra el selector de cantidad con descuento en el detalle del producto."
            ),
        }),
        ("Socios", {
            "fields": ("members_only", "member_discount_percent"),
            "description": (
                "members_only: el producto solo lo ven y compran usuarios con cuenta. "
                "member_discount_percent: descuento (%) que reciben los socios."
            ),
        }),
        ("Meta / Google Catalog", {
            "fields": ("google_product_category",),
            "description": (
                "Categoría de la taxonomía de Google/Meta para el feed de Meta Catalog "
                "(ej: 'Sporting Goods > Exercise & Fitness Equipment')."
            ),
        }),
        ("Mercado Libre", {
            "fields": (
                "ml_item_id", "ml_category_id", "weight_kg", "length_cm", "width_cm", "height_cm",
                "gtin", "warranty_months", "free_shipping_seller_paid",
            ),
            "description": (
                "ml_category_id y las dimensiones/peso son necesarios para publicar. "
                "ml_item_id se completa solo al publicar por primera vez. gtin, "
                "warranty_months y free_shipping_seller_paid son opcionales — mejoran "
                "la calidad/competitividad de la publicación pero no son obligatorios "
                "para poder publicar (ver help text de cada campo)."
            ),
        }),
    )

    @admin.action(description="Regenerar SKU")
    def regenerar_sku(self, request, queryset):
        """Recalcula el SKU con Product.generate_sku() usando el estado
        actual del producto (marca, categoría, color, tamaño).

        El SKU no se recalcula solo en cada guardado a propósito (ver
        help_text del campo) — esta acción es la forma explícita de
        actualizarlo, por ejemplo después de cargar color/tamaño por primera
        vez. Ojo: si el producto ya está publicado en Mercado Libre o en el
        feed, cambiar el SKU ahí puede romper el matching/historial.
        """
        actualizados = 0
        for product in queryset:
            nuevo_sku = product.generate_sku()
            if nuevo_sku != product.sku:
                product.sku = nuevo_sku
                product.save(update_fields=["sku"])
                actualizados += 1
        if actualizados:
            self.message_user(request, f"{actualizados} SKU regenerado(s).")
        else:
            self.message_user(request, "Ningún SKU cambió (ya estaban al día).")

    @admin.action(description="Publicar/Actualizar en Mercado Libre")
    def publicar_en_mercadolibre(self, request, queryset):
        ok, fail = 0, 0
        for product in queryset:
            try:
                sync_product(product)
                ok += 1
            except MLSyncError as exc:
                fail += 1
                self.message_user(request, f"{product.name}: {exc}", level="error")
            except Exception as exc:  # error inesperado (red, etc.) — no debe frenar el resto del lote
                fail += 1
                self.message_user(request, f"{product.name}: error inesperado ({exc})", level="error")
        if ok:
            self.message_user(request, f"{ok} producto(s) publicado(s)/actualizado(s) en Mercado Libre.")
        if fail:
            self.message_user(request, f"{fail} producto(s) con error, revisá los mensajes de arriba.", level="warning")
