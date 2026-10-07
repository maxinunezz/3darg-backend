from django.db import models
from django.utils import timezone

DEFAULT_DESCRIPTION_TEMPLATE = """Dale a tus galletitas, tortas y piezas de cerámica un acabado profesional con este set de cortante + marcador. Diseñado para lograr cortes limpios y detalles bien definidos en cada pieza, de forma simple y rápida.

-----------------------------------
¿QUÉ INCLUYE?
-----------------------------------
- 1 (un) cortante: corta el contorno de la pieza.
- 1 (un) marcador / sello: imprime el diseño y los detalles sobre la masa.

Primero marcás, después cortás: así obtenés piezas prolijas, con relieve y todas iguales.

-----------------------------------
FICHA TÉCNICA
-----------------------------------
- Material: PLA (ácido poliláctico), plástico biodegradable de origen vegetal.
- Apto para contacto con alimentos.
- Medidas: $medidas.
- Composición: 2 piezas (marcador + cortante).
- Diseño: $modelo
- Fabricación: Impresión 3D.

-----------------------------------
USOS RECOMENDADOS
-----------------------------------
- Masa para galletitas (de manteca, de jengibre, decoradas, etc.).
- Pasta de azúcar / fondant para decorar tortas, cupcakes y cookies.
- Arcilla, porcelana fría y cerámica.
- Masas de modelar y actividades con chicos.

Ideal para pastelería profesional, emprendimientos de cookies decoradas, mesas dulces, eventos, ceramistas y para usar en casa.

-----------------------------------
CUIDADO Y LIMPIEZA
-----------------------------------
- Lavar únicamente con AGUA FRÍA y detergente suave.
- NO usar agua caliente, lavavajillas ni microondas.
- NO llevar al horno ni exponer a fuentes de calor (el PLA puede deformarse).
- Secar bien antes de guardar.
- Tip: enharinar levemente el cortante y el marcador antes de usar para que la masa no se pegue.

-----------------------------------
¿POR QUÉ COMPRARNOS?
-----------------------------------
- TRABAJAMOS CON STOCK PERMANENTE: despachamos tu compra rápido, sin demoras de fabricación.
- Cada pieza es revisada antes del envío para garantizar bordes limpios y buena terminación.
- Materiales seguros y amigables con el medio ambiente.
- Atención personalizada: respondemos todas tus consultas a la brevedad.
- Ventas mayoristas y por cantidad para emprendedores y comercios: consultanos.

-----------------------------------
PREGUNTAS FRECUENTES
-----------------------------------
¿Es apto para alimentos?
Sí, está fabricado en PLA, material apto para contacto con alimentos.

¿Se puede lavar en lavavajillas?
No. Recomendamos lavar a mano con agua fría para conservar su forma.

¿Sirve para fondant y cerámica?
Sí, funciona tanto en masas comestibles como en arcilla, porcelana fría y cerámica. Recomendamos usar piezas distintas para alimentos y para cerámica.

¿Tienen stock?
Sí, trabajamos con stock disponible para que recibas tu pedido lo antes posible.

¿Hacen descuentos por cantidad?
Sí, consultanos por compras mayoristas.

-----------------------------------
Si tenés alguna duda, escribinos por la sección de preguntas. ¡Estamos para ayudarte!"""


class MLCredentials(models.Model):
    """Credenciales OAuth de la única cuenta de Mercado Libre del grupo (3darg).

    Singleton (siempre pk=1, ver `load()`) — no es por marca, ver CLAUDE.md
    raíz: se decidió una sola cuenta de vendedor ML para todo 3DARG.
    """

    ml_user_id = models.BigIntegerField(null=True, blank=True)
    access_token = models.CharField(max_length=255, blank=True)
    refresh_token = models.CharField(max_length=255, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Credenciales de Mercado Libre"
        verbose_name_plural = "Credenciales de Mercado Libre"

    def __str__(self):
        return f"Cuenta ML #{self.ml_user_id}" if self.ml_user_id else "Sin conectar"

    @property
    def is_connected(self):
        return bool(self.refresh_token)

    @property
    def is_expired(self):
        return not self.expires_at or timezone.now() >= self.expires_at

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class MLListingTemplate(models.Model):
    """Plantilla de descripción para publicaciones de Mercado Libre (singleton).

    Texto editable desde el admin (no hardcodeado en Python) para que el dueño
    pueda ajustar política de cuidado/FAQ/etc. sin pedir un cambio de código.
    Admite los placeholders $modelo (nombre del producto) y $medidas (armadas
    desde length_cm/width_cm/height_cm), sustituidos por `services.py` al
    generar la descripción real de cada publicación.
    """

    description_template = models.TextField(default=DEFAULT_DESCRIPTION_TEMPLATE)

    class Meta:
        verbose_name = "Plantilla de descripción ML"
        verbose_name_plural = "Plantilla de descripción ML"

    def __str__(self):
        return "Plantilla de descripción ML"

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
