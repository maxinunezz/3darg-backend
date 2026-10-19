"""Reagrupa el sidebar del admin por área de negocio en vez del agrupado
default de Django (una caja por app, orden alfabético) — con 13 apps
registradas, varias de una sola bandeja de leads (wholesale,
whatsapp_community, vending), el sidebar quedaba con demasiadas cajas
sueltas al mismo nivel que Orders/Products, difícil de escanear.

Solo cambia el agrupamiento visual de /admin/ (parchea
`AdminSite.get_app_list`) — no toca permisos, ni las URLs de app_index
(`/admin/<app_label>/`), ni el registro real de modelos. Importado desde
`config/urls.py` para que se aplique al arrancar (este módulo no es una app
instalada, así que Django no lo autodiscovery-ea solo).
"""

from django.contrib import admin

CATEGORIES = [
    ("Ventas", ["orders", "payments", "cart"]),
    ("Catálogo", ["products", "brands"]),
    ("Leads / Marketing", ["wholesale", "whatsapp_community", "vending"]),
    ("Contenido", ["cms"]),
    ("Integraciones", ["mercadolibre", "authtoken"]),
    ("Usuarios", ["users", "auth"]),
]

_APP_LABEL_TO_CATEGORY = {
    label: category for category, labels in CATEGORIES for label in labels
}
_CATEGORY_ORDER = [category for category, _labels in CATEGORIES]
_OTROS = "Otros"  # red de seguridad: una app nueva sin categoría asignada
# aparece acá en vez de desaparecer en silencio del sidebar.


def get_app_list(self, request, app_label=None):
    app_dict = self._build_app_dict(request, app_label)

    if app_label:
        # Página de detalle de una sola app (ej. /admin/orders/): se deja
        # el comportamiento default de Django, sin agrupar por categoría.
        app_list = sorted(app_dict.values(), key=lambda app: app["name"].lower())
        for app in app_list:
            app["models"].sort(key=lambda m: m["name"])
        return app_list

    grouped = {}
    for label, app in app_dict.items():
        category = _APP_LABEL_TO_CATEGORY.get(label, _OTROS)
        group = grouped.setdefault(category, {
            "name": category,
            "app_label": f"_grupo_{category}",
            "app_url": None,
            "has_module_perms": True,
            "models": [],
        })
        group["models"].extend(app["models"])

    order = _CATEGORY_ORDER + ([_OTROS] if _OTROS in grouped else [])
    result = []
    for category in order:
        group = grouped.get(category)
        if not group:
            continue
        group["models"].sort(key=lambda m: m["name"])
        result.append(group)
    return result


admin.site.get_app_list = get_app_list.__get__(admin.site, admin.site.__class__)
