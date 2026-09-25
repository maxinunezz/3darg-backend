from django.db import models


class Page(models.Model):
    brand = models.ForeignKey(
        "brands.Brand",
        related_name="pages",
        on_delete=models.CASCADE,
    )
    slug = models.SlugField(max_length=100)  # home, about, contact
    title = models.CharField(max_length=150)

    is_published = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("brand", "slug")
        ordering = ["brand", "slug"]

    def __str__(self):
        return f"{self.brand.name} / {self.slug}"


class Section(models.Model):
    page = models.ForeignKey(
        Page,
        related_name="sections",
        on_delete=models.CASCADE,
    )

    # Ej: "hero", "services", "gallery", "faq", "cta"
    type = models.CharField(max_length=50)
    order = models.PositiveIntegerField(default=0)

    # Contenido/config flexible (textos, imágenes, colores, layouts)
    data = models.JSONField(default=dict, blank=True)

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.page} - {self.type} ({self.order})"


class SectionImage(models.Model):
    section = models.ForeignKey(Section, related_name="images", on_delete=models.CASCADE)
    # Direcciona la imagen dentro de una sección con varias (ej. "team_1", "cover").
    # Vacío = imagen única/principal de la sección.
    key = models.SlugField(max_length=60, blank=True)
    image = models.ImageField(upload_to="cms/sections/")
    alt_text = models.CharField(max_length=200, blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.section} - {self.key or 'main'}"