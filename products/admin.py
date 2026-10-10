from decimal import Decimal

from django import forms
from django.contrib import admin
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet, ModelChoiceIterator
from django.shortcuts import render
from django.urls import reverse
from django.utils.html import format_html
from .models import Product, Category, ProductImage, CostTemplate, ProductVariant
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


class _ChannelImageFormSet(BaseInlineFormSet):
    """Fija `channel` solo en cada fila nueva, según el apartado donde se
    cargó — ya no hace falta mostrar ese selector en el form: cada apartado
    (Web / Mercado Libre) filtra y fija su propio canal. Si una foto tiene
    que verse en los dos canales, se carga una vez en cada apartado (dos
    filas, mismo archivo).
    """

    channel_value = None  # lo fija cada subclase

    def save_new(self, form, commit=True):
        obj = super().save_new(form, commit=False)
        obj.channel = self.channel_value
        if commit:
            obj.save()
        return obj


class ProductImageWebFormSet(_ChannelImageFormSet):
    channel_value = ProductImage.Channel.WEB


class ProductImageMLFormSet(_ChannelImageFormSet):
    """Además de fijar el canal (ver `_ChannelImageFormSet`), exige el piso
    de fotos de Mercado Libre (MIN_ML_PICTURES, hoy 3) al guardar el
    producto desde el admin si tiene prendido el canal ML
    (`is_available_ml`) — mismo criterio que
    `mercadolibre/services.py::_build_payload()` ya exige recién al
    publicar, pero acá lo frenamos antes, al guardar, para no dejar cargar
    un producto "ML-habilitado" que después va a fallar al intentar
    sincronizarlo.

    Esta validación cruzada no puede ir en `Product.clean()` porque las
    fotos son un inline: al validarse el form principal del producto, las
    imágenes todavía no están guardadas (ni el producto tiene pk todavía,
    si es nuevo). Acá, en cambio, Django ya dejó `is_available_ml` cargado
    en `self.instance` (lo asigna `_post_clean()` del form principal antes
    de guardar) y tenemos todas las filas de este formset a mano (que ya
    son, todas, del canal Mercado Libre — este apartado no maneja fotos de
    la web), incluidas las marcadas para borrar.
    """

    channel_value = ProductImage.Channel.ML

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
            if cleaned.get("image"):
                count += 1

        if count < MIN_ML_PICTURES:
            raise ValidationError(
                "Este producto tiene activado el canal Mercado Libre "
                f"(is_available_ml) — necesita al menos {MIN_ML_PICTURES} fotos "
                f"en el apartado \"Imágenes — Mercado Libre\" para poder guardarse. "
                f"Hoy tiene {count}. Si todavía no tenés las fotos listas, desactivá "
                "'is_available_ml' hasta cargarlas."
            )


class _ChannelImageInline(admin.TabularInline):
    """Base para los dos apartados de imágenes (Web / Mercado Libre). Cada
    uno solo lista/edita las filas de `ProductImage` de su propio canal
    (`get_queryset`); el canal de las filas nuevas lo fija el formset (ver
    `_ChannelImageFormSet.save_new`), por eso no está en `fields`.
    """

    model = ProductImage
    extra = 1
    fields = ["image", "order", "alt"]
    channel = None  # lo fija cada subclase, debe matchear formset.channel_value

    def get_queryset(self, request):
        return super().get_queryset(request).filter(channel=self.channel)


class ProductImageWebInline(_ChannelImageInline):
    channel = ProductImage.Channel.WEB
    formset = ProductImageWebFormSet
    verbose_name = "Imagen — Página web"
    verbose_name_plural = "Imágenes — Página web"


class ProductImageMLInline(_ChannelImageInline):
    channel = ProductImage.Channel.ML
    formset = ProductImageMLFormSet
    verbose_name = "Imagen — Mercado Libre"
    verbose_name_plural = "Imágenes — Mercado Libre"


@admin.register(CostTemplate)
class CostTemplateAdmin(admin.ModelAdmin):
    """Plantillas de costo (`CostTemplate`): el "presupuesto de ecommerce"
    de presupuestos3d, del lado de 3darg-backend. Se crean solas vía el sync
    automático (`CosteoSyncAPIView`, upsert por `external_ref`) o a mano acá
    para variantes con precio propio que igual querés agrupar — lo que
    vincula de verdad un template a muchos productos es asignarlo desde
    `ProductVariantAdmin` (ver la acción "Asignar template de costo").
    """

    list_display = ["nombre", "sale_price", "external_ref", "legacy_cutter_size", "variantes_count", "updated_at"]
    search_fields = ["nombre", "external_ref"]
    list_filter = ["legacy_cutter_size"]
    readonly_fields = ["legacy_cutter_size", "created_at", "updated_at", "variantes_vinculadas"]
    fieldsets = (
        (None, {
            "fields": ("nombre", "external_ref", "sale_price"),
            "description": (
                "`external_ref` lo completa solo el sync de presupuestos3d (no lo "
                "edites a mano si este template viene de ahí: es la clave que usa "
                "para hacer upsert sin duplicar — renombrar `nombre` en presupuestos3d "
                "no rompe el link). Dejalo vacío para un template armado acá nomás, "
                "sin sync automático."
            ),
        }),
        ("Medidas", {"fields": ("weight_kg", "length_cm", "width_cm", "height_cm")}),
        ("Variantes vinculadas", {"fields": ("variantes_vinculadas",)}),
        ("Trazabilidad", {
            "fields": ("legacy_cutter_size", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="Variantes")
    def variantes_count(self, obj):
        return obj.variants.count()

    @admin.display(description="Variantes que usan este template")
    def variantes_vinculadas(self, obj):
        if not obj or not obj.pk:
            return "Guardá el template primero."
        variantes = list(obj.variants.select_related("product")[:50])
        if not variantes:
            return (
                "Ninguna variante usa este template todavía — asignalo desde "
                "\"Variantes de producto\" (acción \"Asignar template de costo "
                "a las variantes seleccionadas\")."
            )
        total = obj.variants.count()
        items = "".join(
            format_html(
                '<li><a href="{}">{}</a> — ${}</li>',
                reverse("admin:products_productvariant_change", args=[v.pk]),
                str(v),
                v.price,
            )
            for v in variantes
        )
        extra = f"<li>… y {total - 50} más.</li>" if total > 50 else ""
        return format_html("<ul>{}{}</ul>", items, extra)


class AsignarCostTemplateForm(forms.Form):
    cost_template = forms.ModelChoiceField(
        queryset=CostTemplate.objects.all(),
        label="Template de costo a asignar",
        help_text=(
            "Se asigna a TODAS las variantes seleccionadas de una sola vez — así "
            "un presupuesto cargado una vez en presupuestos3d aplica a muchos "
            "productos del catálogo. Si el template ya tiene 'Precio de venta' "
            "cargado, también se actualiza el precio de cada variante y del "
            "Product subyacente (mismo criterio que usa el sync automático de "
            "presupuestos3d, ver CosteoSyncAPIView)."
        ),
    )


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    """Variantes de catálogo. Fase 1: hay exactamente una por `Product`
    (migración `0035_migrar_productos_a_variantes_y_costtemplate`) y nada del
    checkout/Mercado Libre/el feed la lee todavía — pero ya se puede usar este
    admin para ir vinculando variantes a un `CostTemplate` compartido, que es
    justamente lo que necesita el sync de presupuestos3d para encontrar a
    quién aplicarle el precio.
    """

    list_display = [
        "__str__", "product", "sku", "price", "stock", "cost_template", "is_available",
    ]
    list_filter = ["cost_template", "is_available", "product__brand"]
    search_fields = ["sku", "product__name", "product__sku", "color", "size"]
    list_editable = ["price", "stock", "is_available"]
    autocomplete_fields = ["product", "cost_template"]
    actions = ["asignar_cost_template"]

    @admin.action(description="Asignar template de costo a las variantes seleccionadas")
    def asignar_cost_template(self, request, queryset):
        if "apply" in request.POST:
            form = AsignarCostTemplateForm(request.POST)
            if form.is_valid():
                template = form.cleaned_data["cost_template"]
                update_kwargs = {"cost_template": template}
                if template.sale_price is not None:
                    update_kwargs["price"] = template.sale_price
                queryset.update(**update_kwargs)

                if template.sale_price is not None:
                    # Fase 1: el Product subyacente sigue siendo lo que lee
                    # el carrito/ML/feed — se actualiza en el mismo golpe
                    # para que el precio nuevo tenga efecto real hoy mismo
                    # (ver CosteoSyncAPIView, mismo criterio).
                    product_ids = list(queryset.values_list("product_id", flat=True).distinct())
                    Product.objects.filter(pk__in=product_ids).update(price=template.sale_price)

                mensaje = (
                    f'{queryset.count()} variante(s) asignada(s) al template "{template.nombre}"'
                )
                if template.sale_price is not None:
                    mensaje += f", precio actualizado a ${template.sale_price}."
                else:
                    mensaje += " (el template no tiene precio cargado, no se tocó el precio de las variantes)."
                self.message_user(request, mensaje)
                return None
        else:
            form = AsignarCostTemplateForm()

        return render(
            request,
            "admin/products/productvariant/asignar_cost_template.html",
            {
                "variantes": queryset,
                "form": form,
                "title": "Asignar template de costo",
                "action_checkbox_name": ACTION_CHECKBOX_NAME,
                "opts": self.model._meta,
            },
        )


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
    readonly_fields = ["ml_item_id", "ml_resumen", "web_resumen", "variante_resumen"]
    inlines = [ProductImageWebInline, ProductImageMLInline]
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

    @admin.display(description="Variante / template de costo")
    def variante_resumen(self, obj):
        """Fase 1: cada Product tiene exactamente una ProductVariant (ver
        migración 0035). Este resumen es solo un atajo de navegación hacia
        el admin de ProductVariant — el precio/stock que de verdad se usa
        hoy en el carrito/ML/el feed sigue siendo el de este Product de
        acá arriba, no el de la variante (eso cambia en una fase siguiente).
        """
        if not obj or not obj.pk:
            return "Guardá el producto primero para ver su variante."
        variant = obj.variants.first()
        if not variant:
            return "Sin variante todavía (debería tener una, ver migración 0035)."
        url = reverse("admin:products_productvariant_change", args=[variant.pk])
        if variant.cost_template:
            template_url = reverse("admin:products_costtemplate_change", args=[variant.cost_template.pk])
            detalle = format_html(
                'template <a href="{}">{}</a>',
                template_url, variant.cost_template.nombre,
            )
        else:
            detalle = "sin template — precio propio"
        return format_html('<a href="{}">{}</a> — {}', url, str(variant), detalle)

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
        ("Precio y stock", {
            "fields": ("price", "stock", "cutter_size", "is_available", "is_featured", "variante_resumen"),
            "description": (
                "'Tamaño de cortante' es el tamaño de COSTEO (la pieza, no "
                "el diseño) — determina qué costo se trae de presupuestos3d "
                "para calcular la ganancia neta de cada canal más abajo. No "
                "tiene efecto en productos que no sean cortantes (dejalo "
                "vacío en ese caso). 'Variante / template de costo' es un "
                "atajo a la ProductVariant de este producto — ahí (o en bloque, "
                "desde \"Variantes de producto\" en el menú del admin) se "
                "asigna un CostTemplate compartido por muchos productos, que "
                "es lo que usa el sync de precios de presupuestos3d para saber "
                "a quién aplicarle un presupuesto. Por ahora el precio/stock "
                "que de verdad se vende sigue siendo el de arriba, no el de "
                "la variante (eso cambia en una fase siguiente)."
            ),
        }),
        ("Página web — todo lo que necesita este canal", {
            "fields": (
                "is_available_web",
                "google_product_category",
                "web_commission_percent", "web_fixed_fee", "web_vat_percent",
                "web_gross_income_tax_percent", "web_other_variable_percent", "web_shipping_cost",
                "web_resumen",
            ),
            "description": (
                "Todo lo que hace falta para vender este producto en la página web, "
                "junto en un solo lugar: prender/apagar el canal, la categoría de "
                "Google/Meta Catalog para el feed (se nutre del mismo catálogo web), "
                "y los gastos de esta venta (ej: comisión del medio de pago, envío a "
                "cargo propio) para ver la ganancia neta. 'is_available' (arriba) "
                "sigue siendo el apagado general, independiente de este canal."
            ),
        }),
        ("Mercado Libre — todo lo que necesita este canal", {
            "fields": (
                "is_available_ml",
                "ml_item_id", "ml_category_id",
                "color", "size", "shape", "is_dishwasher_safe",
                "weight_kg", "length_cm", "width_cm", "height_cm",
                "gtin", "warranty_months", "free_shipping_seller_paid",
                "ml_commission_percent", "ml_fixed_fee", "ml_vat_percent",
                "ml_gross_income_tax_percent", "ml_other_variable_percent", "ml_shipping_cost",
                "ml_resumen",
            ),
            "description": (
                "Todo lo que hace falta para publicar/actualizar este producto en "
                "Mercado Libre, junto en un solo lugar: prender/apagar el canal, "
                "categoría de ML, color/tamaño/forma/apto lavavajillas (se mandan como "
                "atributos reales de la publicación — COLOR/SIZE/COOKIE_CUTTER_SHAPE/"
                "IS_DISHWASHER_SAFE — SOLO si la categoría cargada los admite; si no, "
                "quedan solo informativos (color y tamaño además arman el SKU), sin "
                "romper nada; usá la acción \"Regenerar SKU\" de la lista si cargás/"
                "cambiás color o tamaño después de crear el producto, no se recalcula "
                "solo al guardar), dimensiones/peso (necesarios para el envío — sin "
                "esto ML marca el ítem con specs técnicas incompletas), GTIN/garantía/"
                "envío gratis (opcionales, mejoran la calidad/competitividad de la "
                "publicación) y los gastos de esta venta para ver la ganancia neta. "
                "ml_item_id se completa solo al "
                "publicar por primera vez. 'is_available' (arriba) sigue siendo el "
                "apagado general: si está apagado, no se vende en ningún lado sin "
                "importar este canal. Después de cambiar cualquier campo de acá corré "
                "la acción \"Publicar/Actualizar en Mercado Libre\" para que se "
                "refleje en la publicación real — no es automático. También se apaga "
                "solo cuando Mercado Libre nos avisa (webhook) que el ítem ya no está "
                "activo. Si 'is_available_ml' está prendido, necesitás al menos 3 "
                "fotos cargadas en el apartado \"Imágenes — Mercado Libre\" "
                "más abajo para poder guardar el producto."
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
                _, warnings = sync_product(product)
                ok += 1
                if warnings:
                    # ML aceptó el request (sin esto no se levanta MLSyncError) pero
                    # avisa que ignoró en silencio parte del payload — ej: no pudo
                    # activar envío gratis porque el precio no alcanza a cubrir el
                    # costo de envío. Sin este mensaje, el admin queda mostrando el
                    # campo "prendido" aunque no tenga efecto real en la publicación.
                    self.message_user(
                        request,
                        f"{product.name}: publicado/actualizado, pero Mercado Libre "
                        "avisó: " + "; ".join(warnings),
                        level="warning",
                    )
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
