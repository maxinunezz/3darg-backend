import re
import unicodedata
from collections import Counter
from decimal import Decimal

import requests
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from brands.models import Brand
from products.models import Category, Product, ProductImage

STOPWORDS = {"de", "la", "el", "los", "las", "en", "con", "y", "del", "al"}

# Overrides explícitos: código de carpeta -> pk de Product, para los casos
# ambiguos ya confirmados con el dueño (baby shower, luna, minnie) y para los
# "Brainrots" (personajes virales, se reusan los placeholders genéricos
# existentes en vez de usar nombres de personajes con posible marca registrada).
FOLDER_PK_OVERRIDES = {
    "05-03": 44,   # Baby Shower -> Cortante Sello Baby Shower (confirmado)
    "14-01": 88,   # Minnie -> Cortante Minnie Cara (por descarte)
    "17-02": 105,  # Luna -> Cortante Luna con Cara (confirmado)
    "08-01": 54,   # Brainrots (personajes virales) -> placeholders genéricos existentes
    "08-02": 55,
    "08-03": 56,
    "08-04": 57,
    "08-05": 58,
    "08-06": 59,
}

# Productos nuevos a crear antes de matchear (nombres/precios genéricos,
# confirmado con el dueño: "crealos con nombres y precios genericos").
NEW_PRODUCTS = [
    ("04-06", "cortantes-04-animales-de-la-selva", "Cebra"),
    ("10-01", "cortantes-10-circo", "León"),
    ("14-05", "cortantes-14-disney", "Guante"),
    ("28-04", "cortantes-28-minecraft", "Hombre"),
]

NAVIDAD_PRODUCTS = [
    ("45-01", "Papá Noel"),
    ("45-02", "Muñeco"),
    ("45-03", "Galleta"),
    ("45-04", "Media"),
    ("45-05", "Caramelo"),
    ("45-06", "Regalo"),
    ("45-07", "Árbol"),
    ("45-08", "Gorro"),
    ("45-09", "Adorno Bola"),
    ("45-10", "Adorno Estrella"),
]

GENERIC_PRICE = Decimal("1500.00")
GENERIC_STOCK = 50


def norm_tokens(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return set(w for w in s.split() if w and w not in STOPWORDS)


def resolve_roles(resources):
    """Determina qué recurso va a channel=ml (PNG), cuál a channel=web
    (primer jpg) y cuáles son "extra" (resto de los jpg) — estos últimos se
    cargan EN LOS DOS canales (una fila channel=web y otra channel=ml, mismo
    archivo) para no perder fotos ML-elegibles respecto al comportamiento
    viejo (antes existía un tercer canal "both" que cubría este caso; se
    eliminó a favor de dos apartados channel-puros en el admin, ver
    `products/admin.py`). Filtra además archivos sueltos que no correspondan
    a este producto (se queda con el código mayoritario entre los recursos)."""

    def code_of(public_id):
        name = public_id.rsplit("/", 1)[-1]
        name = re.sub(r"_png$", "", name)
        name = re.sub(r"_\d+$", "", name)
        return name

    codes = Counter(code_of(r["public_id"]) for r in resources)
    if not codes:
        return None, None, []
    main_code, _ = codes.most_common(1)[0]
    filtered = [r for r in resources if code_of(r["public_id"]) == main_code]

    png = [r for r in filtered if r["format"] == "png"]
    jpgs = [r for r in filtered if r["format"] != "png"]

    def trailing_num(r):
        m = re.search(r"_(\d+)$", r["public_id"].rsplit("/", 1)[-1])
        return int(m.group(1)) if m else 1

    jpgs.sort(key=trailing_num)
    ml_resource = png[0] if png else None
    web_resource = jpgs[0] if jpgs else None
    both_resources = jpgs[1:]
    return ml_resource, web_resource, both_resources


class Command(BaseCommand):
    help = (
        "Trae las fotos de Lumy/Cortantes en Cloudinary y las asigna a cada "
        "Product (PNG -> channel=ml, primer JPG -> channel=web, resto de JPG "
        "-> una fila channel=web + una fila channel=ml cada uno, mismo "
        "archivo). Crea los productos/categoría que todavía no existen "
        "(nombres y precios genéricos, confirmado con el dueño). Re-ejecutable."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", help="No sube nada, solo lista qué haría."
        )

    def handle(self, *args, **options):
        if not getattr(settings, "CLOUDINARY_URL", None):
            raise CommandError("CLOUDINARY_URL no está configurado en el .env.")

        import cloudinary.api

        dry_run = options["dry_run"]
        lumy = Brand.objects.get(slug="lumy")
        cortantes = Category.objects.get(brand=lumy, slug="cortantes", parent__isnull=True)

        for codigo, cat_slug, label in NEW_PRODUCTS:
            cat = Category.objects.get(slug=cat_slug)
            name = f"Cortante {label}"
            product, created = Product.objects.get_or_create(
                name=name,
                category=cat,
                defaults=dict(
                    brand=lumy,
                    price=GENERIC_PRICE,
                    stock=GENERIC_STOCK,
                    is_available=True,
                    description=(
                        f"Cortante 3D de {label.lower()} — colección {cat.name}. "
                        "Ideal para galletitas, fondant y masas. Tamaño a elección "
                        f"(4 a 12 cm). Código interno {codigo}."
                    ),
                ),
            )
            if created:
                self.stdout.write(f"  + creado producto: {product.name} (pk={product.pk})")

        navidad_cat, cat_created = Category.objects.get_or_create(
            brand=lumy,
            slug="cortantes-45-navidad",
            defaults=dict(name="Navidad", parent=cortantes, sku_prefix="45"),
        )
        if cat_created:
            self.stdout.write(f"  + creada categoría: {navidad_cat.name}")
        elif not navidad_cat.sku_prefix:
            navidad_cat.sku_prefix = "45"
            navidad_cat.save(update_fields=["sku_prefix"])

        for codigo, label in NAVIDAD_PRODUCTS:
            name = f"Cortante {label}"
            product, created = Product.objects.get_or_create(
                name=name,
                category=navidad_cat,
                defaults=dict(
                    brand=lumy,
                    price=GENERIC_PRICE,
                    stock=GENERIC_STOCK,
                    is_available=True,
                    description=(
                        f"Cortante 3D de {label.lower()} — colección Navidad. "
                        "Ideal para galletitas, fondant y masas. Tamaño a elección "
                        f"(4 a 12 cm). Código interno {codigo}."
                    ),
                ),
            )
            if created:
                self.stdout.write(f"  + creado producto: {product.name} (pk={product.pk})")

        subfolders = cloudinary.api.subfolders("Lumy/Cortantes")["folders"]
        attached = 0
        products_touched = 0
        skipped = []

        for sf in subfolders:
            sub_code = sf["name"].split("-")[0]
            category = Category.objects.filter(
                brand=lumy, parent=cortantes, sku_prefix=sub_code
            ).first()
            if not category:
                skipped.append((sf["path"], "sin categoría"))
                continue

            db_products = list(Product.objects.filter(category=category).order_by("pk"))
            db_tokens = [(p, norm_tokens(p.name.replace("Cortante", ""))) for p in db_products]

            product_folders = cloudinary.api.subfolders(sf["path"])["folders"]
            for pf in product_folders:
                parts = pf["name"].split(" ", 1)
                codigo = parts[0]
                label = parts[1] if len(parts) > 1 else ""

                product = None
                if codigo in FOLDER_PK_OVERRIDES:
                    product = Product.objects.get(pk=FOLDER_PK_OVERRIDES[codigo])
                else:
                    key = norm_tokens(label)
                    exact = [p for p, t in db_tokens if t == key]
                    if len(exact) == 1:
                        product = exact[0]
                    else:
                        cands = [p for p, t in db_tokens if key and (key <= t or t <= key)]
                        if len(cands) == 1:
                            product = cands[0]

                if product is None:
                    skipped.append((pf["path"], "sin match"))
                    continue

                resources = cloudinary.api.resources_by_asset_folder(
                    pf["path"], max_results=50
                )["resources"]
                ml_r, web_r, both_rs = resolve_roles(resources)
                if not (ml_r and web_r):
                    skipped.append(
                        (pf["path"], f"archivos incompletos ({len(resources)} recursos)")
                    )
                    continue

                if dry_run:
                    self.stdout.write(
                        f"  [dry-run] {pf['path']} -> {product.name} (pk={product.pk}): "
                        f"ml={ml_r['public_id']} web={web_r['public_id']} "
                        f"both={[r['public_id'] for r in both_rs]}"
                    )
                    products_touched += 1
                    continue

                with transaction.atomic():
                    product.images.all().delete()
                    self._attach(product, ml_r, channel="ml", order=0)
                    self._attach(product, web_r, channel="web", order=0)
                    for i, r in enumerate(both_rs, start=1):
                        # Antes era un tercer canal "both" (ver resolve_roles) —
                        # ahora se carga una fila en cada canal, mismo archivo.
                        self._attach(product, r, channel="web", order=i)
                        self._attach(product, r, channel="ml", order=i)

                attached += 2 + 2 * len(both_rs)
                products_touched += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Productos con fotos nuevas: {products_touched}. Imágenes subidas: {attached}."
            )
        )
        if skipped:
            self.stdout.write(self.style.WARNING(f"Carpetas sin procesar ({len(skipped)}):"))
            for path, reason in skipped:
                self.stdout.write(f"   - {path}: {reason}")

    def _attach(self, product, resource, channel, order):
        resp = requests.get(resource["secure_url"], timeout=30)
        resp.raise_for_status()
        filename = resource["public_id"].rsplit("/", 1)[-1] + "." + resource["format"]
        img = ProductImage(product=product, channel=channel, order=order)
        img.image.save(filename, ContentFile(resp.content), save=True)
