from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError

from products.models import ProductImage


class Command(BaseCommand):
    help = (
        "Migración one-shot: sube a Cloudinary las imágenes de producto que hoy "
        "viven en disco local (media/products/images/) y repunta cada ProductImage.image "
        "al archivo ya alojado en Cloudinary. Correr una sola vez, después de configurar "
        "CLOUDINARY_URL en el .env y reiniciar 'web' (STORAGES['default'] pasa a Cloudinary "
        "automáticamente en ese momento — ver config/settings.py)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="No sube nada, solo lista qué se migraría.",
        )

    def handle(self, *args, **options):
        if not settings.CLOUDINARY_URL:
            raise CommandError(
                "CLOUDINARY_URL no está configurado en el .env. Configuralo y "
                "reiniciá \'web\' antes de correr esta migración (si no, el comando "
                "subiría contra el storage local, no contra Cloudinary)."
            )

        dry_run = options["dry_run"]
        qs = ProductImage.objects.select_related("product").order_by("id")
        total = qs.count()
        if total == 0:
            self.stdout.write(self.style.WARNING("No hay ProductImage en la base."))
            return

        migrated = 0
        skipped_missing = 0
        errors = 0

        for pi in qs:
            name = pi.image.name  # ej: "products/images/foo.jpg"
            if not name:
                continue

            local_path = Path(settings.MEDIA_ROOT) / name
            if not local_path.exists():
                # Ya migrada en una corrida anterior, o el nombre ya no apunta a un
                # archivo local (ej: ya es una URL/public_id de Cloudinary).
                skipped_missing += 1
                continue

            if dry_run:
                self.stdout.write(f"[dry-run] subiría: {name} (producto: {pi.product.name})")
                migrated += 1
                continue

            try:
                with open(local_path, "rb") as f:
                    content = ContentFile(f.read())
                filename = local_path.name
                # save=True: guarda el archivo con el storage default actual
                # (Cloudinary, ya que CLOUDINARY_URL está seteado) y persiste el
                # modelo con el nuevo name/url que devuelve Cloudinary.
                pi.image.save(filename, content, save=True)
                migrated += 1
                if migrated % 20 == 0:
                    self.stdout.write(f"  ... {migrated}/{total} subidas")
            except Exception as exc:
                errors += 1
                self.stderr.write(self.style.ERROR(f"Error en ProductImage id={pi.id} ({name}): {exc}"))

        action = "Se migrarían" if dry_run else "Migradas"
        self.stdout.write(self.style.SUCCESS(
            f"{action} {migrated} imagen(es) a Cloudinary. "
            f"Saltadas (sin archivo local, ya migradas): {skipped_missing}. Errores: {errors}."
        ))
