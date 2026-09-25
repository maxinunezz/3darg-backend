from django.core.management.base import CommandError, BaseCommand
from brands.models import Brand
from cms.models import Page, Section


# Contenido semilla = copia exacta del texto hardcodeado actual en las 5 páginas
# "marca madre" del frontend (ecommerce-frontend/app/(main)/*). Se usa get_or_create
# por (page, type) para no duplicar secciones al re-correr el comando.
#
# Varias de estas secciones ya existían antes de esta revisión (proceso, detalle,
# intro, timeline, equipo, materials, technologies, projects) y se les sumaron
# claves nuevas (eyebrow/title/paragraph, etc.) que hasta ahora vivían
# hardcodeadas en el .tsx. Como esas Sections ya pueden existir en la base (y
# pudieron haber sido editadas desde el admin), el comando NUNCA pisa una clave
# ya presente: solo agrega las que falten (merge aditivo, ver `handle()`).
PAGES_SEED = {
    "home": {
        "title": "Inicio",
        "sections": [
            (
                "hero",
                {
                    "eyebrow": "Impresión 3D · Diseño paramétrico · Argentina",
                    "headline": "Traenos el problema que nadie pudo resolver",
                    "subheadline": (
                        "Diseñamos y fabricamos piezas a medida cuando el catálogo se queda "
                        "corto. Tolerancias verificadas, materiales técnicos y entregas puntuales."
                    ),
                    "cta_primary": "Ver productos",
                    "cta_secondary": "Casos de éxito",
                },
            ),
            (
                "que-hacemos",
                {
                    "eyebrow": "Qué hacemos",
                    "title": "Precisión de ingeniero, alma de artista",
                    "items": [
                        {
                            "icon": "layers",
                            "title": "Piezas y prototipos",
                            "items": [
                                "Repuestos descontinuados",
                                "Prototipos funcionales",
                                "Series cortas a medida",
                            ],
                        },
                        {
                            "icon": "ruler",
                            "title": "Diseño y medición",
                            "items": [
                                "Escaneo y relevamiento",
                                "Modelado paramétrico",
                                "Ajuste por iteración",
                            ],
                        },
                        {
                            "icon": "graduation",
                            "title": "Enseñanza abierta",
                            "items": [
                                "Video tutoriales gratis",
                                "Consejos de impresión",
                                "Comunidad en redes",
                            ],
                        },
                    ],
                },
            ),
            (
                "proceso",
                {
                    "eyebrow": "Proceso",
                    "title": "De la idea a la pieza terminada",
                    "items": [
                        {"t": "Consulta", "d": "Nos contás el problema: pieza rota, idea nueva o proyecto en curso."},
                        {"t": "Diseño", "d": "Modelamos o ajustamos el archivo 3D según tolerancias reales."},
                        {"t": "Impresión", "d": "Elegimos material y capa según el uso final de la pieza."},
                        {"t": "Terminación", "d": "Lijado, chanfles y ajuste fino a mano, pieza por pieza."},
                        {"t": "Entrega", "d": "Control de calidad y envío en 24–72 hs."},
                    ],
                },
            ),
            (
                "detalle",
                {
                    "eyebrow": "El detalle, de cerca",
                    "title": "Lo que se nota al tocarlo",
                    "items": [
                        {"t": "La capa que no se ve", "spec": "0.12 mm · pared 1.6 mm"},
                        {"t": "El borde lijado a mano", "spec": "Lija 400 → 800 · chanfle 0.8 mm"},
                        {"t": "El encastre que entra justo", "spec": "Tolerancia 0.15 mm · 3 iteraciones"},
                    ],
                },
            ),
            (
                "enseñanza",
                {
                    "eyebrow": "Enseñanza",
                    "title": "Lo que sabemos, lo compartimos gratis",
                    "paragraph": (
                        "No damos talleres pagos: enseñamos en video por redes, con lo que "
                        "aprendimos imprimiendo todos los días. Materiales, ajustes de máquina y "
                        "errores comunes, explicados sin vueltas."
                    ),
                    "cta_instagram": "Instagram",
                    "cta_youtube": "YouTube",
                },
            ),
            (
                "cierre",
                {
                    "title": "Tu imaginación es nuestro desafío",
                    "paragraph": "Contanos tu idea lo más detallada posible y la materializamos.",
                    "cta_primary": "Contanos tu idea",
                    "cta_secondary": "Ver productos",
                },
            ),
        ],
    },
    "nosotros": {
        "title": "Nosotros",
        "sections": [
            (
                "intro",
                {
                    "eyebrow": "Nosotros",
                    "title": "El taller detrás de las piezas",
                    "lead": (
                        "Empezamos con una máquina en un comedor y la obsesión de que una pieza "
                        "impresa aguante lo mismo que una mecanizada."
                    ),
                    "paragraph1": (
                        "3DARG nació de la frustración de no conseguir un repuesto a tiempo. Desde "
                        "entonces trabajamos con la misma lógica: entender la pieza antes de "
                        "imprimirla, medir antes de entregar y no llamar \"terminado\" a algo que "
                        "salió crudo de la impresora."
                    ),
                    "paragraph2": (
                        "Hoy fabricamos para talleres, estudios de diseño y clientes particulares "
                        "desde cinco marcas propias, pero el criterio técnico es el mismo en todas: "
                        "tolerancias verificadas una por una, materiales elegidos según el uso real "
                        "de la pieza, y plazos que cumplimos."
                    ),
                },
            ),
            (
                "timeline",
                {
                    "eyebrow": "Cómo llegamos hasta acá",
                    "items": [
                        {
                            "year": "2019",
                            "title": "Una máquina en el comedor",
                            "text": (
                                "Arrancamos con una sola impresora FDM, aprendiendo a los golpes qué "
                                "configuración aguanta una pieza real y cuál se rompe al primer uso."
                            ),
                        },
                        {
                            "year": "2021",
                            "title": "Del repuesto al producto",
                            "text": (
                                "Los primeros clientes llegaron pidiendo repuestos imposibles de "
                                "conseguir. Ahí entendimos que el negocio no era la máquina, era "
                                "resolver el problema."
                            ),
                        },
                        {
                            "year": "2023",
                            "title": "Del objeto crudo al terminado",
                            "text": (
                                "Sumamos lijado, tratamiento de superficie y control dimensional. Una "
                                "pieza recién impresa no es una pieza terminada."
                            ),
                        },
                        {
                            "year": "2025",
                            "title": "Enseñar lo que sabemos",
                            "text": (
                                "Empezamos a compartir en video todo lo que aprendimos, gratis, para "
                                "que el que arranca no tenga que romper tanto como rompimos nosotros."
                            ),
                        },
                    ],
                },
            ),
            (
                "equipo",
                {
                    "eyebrow": "Quiénes lo hacemos",
                    "items": [
                        {"nombre": "Equipo de diseño", "rol": "Modelado paramétrico y preparación de archivos"},
                        {"nombre": "Equipo de producción", "rol": "Impresión, postproceso y control de calidad"},
                        {"nombre": "Equipo de atención", "rol": "Cotización técnica y seguimiento de pedidos"},
                    ],
                },
            ),
            (
                "cierre",
                {
                    "title": "Que fabricar deje de ser un privilegio",
                    "paragraph": "Creemos que cualquiera con una idea clara debería poder hacerla pieza. Ese es el trabajo.",
                    "cta": "Hablemos de tu proyecto",
                },
            ),
        ],
    },
    "casos-de-exito": {
        "title": "Casos de éxito",
        "sections": [
            (
                "hero",
                {
                    "eyebrow": "Casos de éxito",
                    "title": "Problemas reales, piezas reales",
                    "subtitle": "Nada de renders. Estas son piezas que salieron de nuestra planta y siguen funcionando hoy.",
                },
            ),
            (
                "casos",
                {
                    "items": [
                        {
                            "rubro": "Gastronomía",
                            "cliente": "Cocina industrial de un restaurante porteño",
                            "problema": (
                                "Un soporte de motor de una batidora industrial se rompió y el "
                                "repuesto original tardaba seis semanas en llegar de Alemania."
                            ),
                            "solucion": (
                                "Escaneamos la pieza original, la rediseñamos en un material más "
                                "resistente al calor y la imprimimos en 48 hs con refuerzos internos "
                                "que la pieza de fábrica no tenía."
                            ),
                            "resultado": "La cocina volvió a operar en dos días. Llevan 8 meses con la pieza sin fallas.",
                            "tecnicas": ["Escaneo 3D", "PETG-CF", "Relleno 60%"],
                        },
                        {
                            "rubro": "Deporte",
                            "cliente": "Club de básquet barrial",
                            "problema": (
                                "Los aros de entrenamiento comerciales se deformaban con el uso "
                                "diario y no había repuesto de la red de sujeción."
                            ),
                            "solucion": (
                                "Diseñamos desde cero un sistema de anclaje modular, imprimible por "
                                "partes, para que se pueda reemplazar solo la pieza dañada sin cambiar "
                                "el aro completo."
                            ),
                            "resultado": "Redujeron el costo de mantenimiento un 70% y ahora piden las piezas de recambio directo a nosotros.",
                            "tecnicas": ["Diseño paramétrico", "Nylon", "Ensamble modular"],
                        },
                        {
                            "rubro": "Industria",
                            "cliente": "Taller mecánico de zona norte",
                            "problema": (
                                "Necesitaban un gabarito de posicionamiento para una tarea de "
                                "soldadura repetitiva que hacían a ojo."
                            ),
                            "solucion": (
                                "Medimos la pieza a soldar en el taller y diseñamos un gabarito con "
                                "tolerancia de 0.15 mm que se ajusta a presión, sin tornillos."
                            ),
                            "resultado": "El tiempo de armado de cada pieza bajó de 12 a 4 minutos, con cero rechazos por desalineación.",
                            "tecnicas": ["Medición en sitio", "ABS", "Tolerancia 0.15 mm"],
                        },
                    ]
                },
            ),
            (
                "cierre",
                {
                    "title": "Tu imaginación es nuestro desafío",
                    "paragraph": "Contanos tu idea lo más detallada posible y la materializamos.",
                    "cta": "Contanos tu idea",
                },
            ),
        ],
    },
    "capacidades": {
        "title": "Capacidades",
        "sections": [
            (
                "hero",
                {
                    "eyebrow": "Capacidades",
                    "title": "Fabricamos lo que otros no pueden",
                    "subtitle": (
                        "Somos un estudio de manufactura aditiva industrial con base en Buenos "
                        "Aires. Trabajamos con empresas que necesitan precisión, escala y "
                        "velocidad — no con hobbyistas que copian archivos de internet."
                    ),
                },
            ),
            (
                "stats",
                {
                    "items": [
                        {"value": "+500", "label": "Proyectos entregados"},
                        {"value": "±0.05mm", "label": "Tolerancia mínima"},
                        {"value": "300×300×400", "label": "Volumen máx. (mm)"},
                        {"value": "24hs", "label": "Respuesta express"},
                    ]
                },
            ),
            (
                "quienes-somos",
                {
                    "eyebrow": "Industria, no hobby",
                    "title": "Quiénes somos",
                    "paragraph1": (
                        "3DARG nació para cambiar la percepción de la impresión 3D en Argentina. "
                        "Mientras el mercado estaba lleno de emprendedores con una sola máquina y "
                        "archivos descargados, nosotros apostamos a construir un estudio técnico "
                        "de manufactura aditiva con capacidad industrial real."
                    ),
                    "paragraph2": (
                        "Hoy trabajamos con empresas del sector automotriz, médico, energético, "
                        "arquitectónico y de investigación. Nuestros clientes son equipos de "
                        "ingeniería, estudios de diseño y áreas de I+D que necesitan piezas "
                        "funcionales — no decorativas."
                    ),
                    "paragraph3": (
                        "Cada proyecto empieza con un brief técnico. Evaluamos material, "
                        "tolerancias, geometría y uso final antes de emitir cualquier presupuesto. "
                        "No fabricamos sin entender qué va a hacer la pieza."
                    ),
                },
            ),
            (
                "technologies",
                {
                    "eyebrow": "Tecnologías",
                    "title": "Cuatro procesos, un solo criterio técnico",
                    "items": [
                        {
                            "code": "FFF / FDM",
                            "name": "Deposición de material fundido",
                            "detail": (
                                "Alta resistencia mecánica. Materiales técnicos: PETG-CF, ABS, ASA, "
                                "PC, PA12. Ideal para piezas funcionales y series cortas."
                            ),
                        },
                        {
                            "code": "SLA / MSLA",
                            "name": "Estereolitografía y fotopolimerización",
                            "detail": (
                                "Resolución extrema. Superficies lisas sin postproceso. Ideal para "
                                "moldes, joyería técnica y piezas de detalle fino."
                            ),
                        },
                        {
                            "code": "SCAN 3D",
                            "name": "Digitalización y reverse engineering",
                            "detail": (
                                "Captura geométrica de piezas físicas para reingeniería, control "
                                "dimensional o reproducción exacta."
                            ),
                        },
                        {
                            "code": "CAD / CAM",
                            "name": "Diseño y preparación de manufactura",
                            "detail": (
                                "Modelado paramétrico, optimización topológica y preparación de "
                                "archivos para producción. Trabajo con SolidWorks, Fusion 360 y "
                                "FreeCAD."
                            ),
                        },
                    ],
                },
            ),
            (
                "projects",
                {
                    "eyebrow": "Proyectos destacados",
                    "title": "Casos reales, no renders",
                    "items": [
                        {
                            "client": "Sector automotriz",
                            "title": "Herramentales de ensamble",
                            "description": (
                                "Diseño y fabricación de útiles de montaje y plantillas de "
                                "verificación en ABS-CF para línea de producción. Lote de 120 "
                                "unidades con tolerancia ±0.1mm. Reemplazo de piezas mecanizadas con "
                                "reducción de costo del 60%."
                            ),
                            "tags": ["FDM", "ABS-CF", "Serie", "Herramental"],
                        },
                        {
                            "client": "Industria médica",
                            "title": "Prótesis y ortesis customizadas",
                            "description": (
                                "Producción de dispositivos ortopédicos personalizados a partir de "
                                "escaneo 3D del paciente. Material biocompatible PA12. Entrega en "
                                "48hs con ajuste perfecto a la morfología individual."
                            ),
                            "tags": ["SLA", "PA12", "Scan 3D", "Biocompatible"],
                        },
                        {
                            "client": "Arquitectura & construcción",
                            "title": "Maquetas técnicas a escala",
                            "description": (
                                "Modelos arquitectónicos de alta fidelidad para presentación a "
                                "inversores y aprobación municipal. Escala 1:100 con detalles de "
                                "fachada, estructuras internas y vegetación. Impresión multipieza "
                                "ensamblada."
                            ),
                            "tags": ["FDM", "Resina", "Multipieza", "1:100"],
                        },
                        {
                            "client": "Sector energético",
                            "title": "Piezas de repuesto para equipos",
                            "description": (
                                "Reverse engineering y reproducción de componentes fuera de catálogo "
                                "para maquinaria industrial de producción. Reducción de tiempos de "
                                "parada de planta de semanas a 72 horas."
                            ),
                            "tags": ["Scan 3D", "PETG-CF", "Repuesto", "Urgente"],
                        },
                        {
                            "client": "Electrónica & IoT",
                            "title": "Carcasas y gabinetes a medida",
                            "description": (
                                "Diseño y producción de enclosures para dispositivos electrónicos en "
                                "series de 1 a 500 unidades. Integración de insertos metálicos, "
                                "tolerancias para PCB y tratamiento superficial."
                            ),
                            "tags": ["FDM", "ASA", "Serie", "Electrónica"],
                        },
                        {
                            "client": "Investigación & universidad",
                            "title": "Prototipos funcionales para I+D",
                            "description": (
                                "Soporte a equipos de investigación en universidades nacionales y "
                                "privadas. Prototipado rápido de conceptos mecánicos, dispositivos de "
                                "laboratorio y modelos de prueba."
                            ),
                            "tags": ["FDM", "SLA", "Prototipo", "I+D"],
                        },
                    ],
                },
            ),
            (
                "materials",
                {
                    "eyebrow": "Materiales disponibles",
                    "items": [
                        {"name": "PLA", "use": "Prototipado visual"},
                        {"name": "PETG", "use": "Piezas funcionales generales"},
                        {"name": "PETG-CF", "use": "Alta rigidez, bajo peso"},
                        {"name": "ABS", "use": "Resistencia térmica y química"},
                        {"name": "ASA", "use": "Exterior, UV estable"},
                        {"name": "PC", "use": "Impacto y temperatura extrema"},
                        {"name": "PA12", "use": "Biocompatible, flexible-rígido"},
                        {"name": "Resina estándar", "use": "Detalle fino, acabado liso"},
                        {"name": "Resina ABS-like", "use": "Resistencia + detalle"},
                    ],
                },
            ),
            (
                "cta",
                {
                    "eyebrow": "Siguiente paso",
                    "title": "¿Cuál es tu proyecto?",
                    "paragraph": (
                        "Contanos qué necesitás fabricar — material, medidas, cantidad y plazo — y "
                        "te respondemos con una cotización técnica el mismo día hábil."
                    ),
                },
            ),
        ],
    },
    "footer": {
        "title": "Footer (global, todas las páginas)",
        "sections": [
            (
                "footer",
                {
                    "tagline": "Walk into the future.",
                    "description": "Impresión 3D personalizada en Argentina. Diseños únicos para cada necesidad.",
                    "email": "contacto@3darg.com",
                    "instagram_url": "https://instagram.com/3darg",
                    "whatsapp_url": "https://wa.me/5491100000000",
                    "made_in": "Hecho en Argentina",
                },
            ),
        ],
    },
    "contacto": {
        "title": "Contacto",
        "sections": [
            (
                "hero",
                {
                    "eyebrow": "Contacto",
                    "title": "Contanos tu idea",
                    "subtitle": "Cuanto más detalle nos des, más rápido te cotizamos. Respondemos el mismo día hábil.",
                },
            ),
            (
                "motivos",
                {
                    "items": [
                        "Cotizar una pieza",
                        "Consulta sobre un pedido",
                        "Quiero ser socio",
                        "Propuesta para una marca",
                        "Prensa",
                        "Otro",
                    ]
                },
            ),
            (
                "canales",
                {
                    "items": [
                        {"label": "WhatsApp", "value": "+54 9 11 0000-0000", "href": "https://wa.me/5491100000000"},
                        {"label": "Mail", "value": "contacto@3darg.com", "href": "mailto:contacto@3darg.com"},
                        {"label": "Instagram", "value": "@3darg", "href": "https://instagram.com/3darg"},
                        {"label": "YouTube", "value": "3DARG", "href": "https://youtube.com"},
                        {"label": "Ubicación", "value": "Buenos Aires, Argentina", "href": ""},
                    ]
                },
            ),
        ],
    },
}


class Command(BaseCommand):
    help = "Crea/actualiza las Pages y Sections de CMS para las páginas marca madre (3DARG) + el footer global, con el contenido hoy hardcodeado en el frontend."

    def handle(self, *args, **options):
        try:
            brand = Brand.objects.get(slug="3darg")
        except Brand.DoesNotExist:
            raise CommandError("No existe la marca con slug='3darg'. Creala antes de correr este comando.")

        for page_slug, page_data in PAGES_SEED.items():
            page, created = Page.objects.get_or_create(
                brand=brand,
                slug=page_slug,
                defaults={"title": page_data["title"]},
            )
            action = "creada" if created else "ya existía"
            self.stdout.write(f"Page '{page_slug}' {action}.")

            for order, (section_type, data) in enumerate(page_data["sections"]):
                section, s_created = Section.objects.get_or_create(
                    page=page,
                    type=section_type,
                    defaults={"order": order, "data": data},
                )
                if s_created:
                    self.stdout.write(f"  Section '{section_type}' creada.")
                    continue

                # Merge aditivo: agregamos solo las claves de "data" que todavía
                # no existan en la Section (nunca pisamos algo ya editado desde
                # el admin). Así el comando queda idempotente y a la vez permite
                # sumar campos nuevos (eyebrow/title/paragraph, etc.) a secciones
                # que ya existían antes de esta revisión.
                missing_keys = {k: v for k, v in data.items() if k not in section.data}
                if missing_keys:
                    section.data = {**section.data, **missing_keys}
                    section.save(update_fields=["data"])
                    self.stdout.write(
                        f"  Section '{section_type}' ya existía: agregadas claves {list(missing_keys.keys())}."
                    )
                else:
                    self.stdout.write(f"  Section '{section_type}' ya existía (sin cambios).")

        self.stdout.write(self.style.SUCCESS("Seed de CMS completo."))
