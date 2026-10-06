import json

from django.core.management.base import BaseCommand, CommandError

from products.models import Product


class Command(BaseCommand):
    help = (
        "Setea (o limpia) los tramos de descuento por volumen (bundle_discounts) "
        "para todos los productos disponibles de una marca. Pensado para activar "
        "la oferta 'Llevá 2/3 con descuento' de una sola vez sobre todo un catálogo "
        "(después se puede ajustar producto por producto desde el admin)."
    )

    def add_arguments(self, parser):
        parser.add_argument("brand_slug", type=str, help="Slug de la marca (ej: lumy)")
        parser.add_argument(
            "--tiers",
            type=str,
            default='[{"quantity": 2, "discount_percent": 10}, {"quantity": 3, "discount_percent": 15}]',
            help="JSON con los tramos a aplicar. Default: 10%% desde 2, 15%% desde 3.",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="En vez de setear tiers, los vacía (apaga el selector de cantidad para la marca).",
        )

    def handle(self, *args, **options):
        brand_slug = options["brand_slug"]
        tiers = [] if options["clear"] else json.loads(options["tiers"])

        qs = Product.objects.filter(brand__slug=brand_slug, is_available=True)
        count = qs.count()
        if count == 0:
            raise CommandError(f"No hay productos disponibles para la marca '{brand_slug}'.")

        updated = qs.update(bundle_discounts=tiers)

        action = "vaciados" if options["clear"] else f"seteados a {tiers}"
        self.stdout.write(self.style.SUCCESS(
            f"bundle_discounts {action} en {updated} producto(s) de '{brand_slug}'."
        ))
