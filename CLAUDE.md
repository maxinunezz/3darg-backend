# CLAUDE.md — 3darg-backend

API REST de 3DARG. Django 5 + DRF + PostgreSQL 16, expuesto en `:8000`. Sirve a la marca madre **3DARG** y a todas las **sub-marcas** (Lumy, MiniSlam, Print&Gym, CyberWeed, etc.). Frontend consumidor: `ecommerce-frontend/` (Next.js).

> Contexto de negocio y reglas transversales: ver `../CLAUDE.md` (raíz del monorepo). Este archivo cubre solo el backend.

---

## Commands

Desde la **raíz del monorepo** (`../`):

```bash
docker compose up -d                                  # arranca db + web (+ frontend)
docker compose logs -f web                            # logs del backend
docker compose build web && docker compose up -d      # rebuild tras tocar requirements.txt
docker compose exec web python manage.py migrate
docker compose exec web python manage.py makemigrations <app>
docker compose exec -it web python manage.py createsuperuser
docker compose exec web python manage.py shell
```

El contenedor `web` monta `./3darg-backend:/app` como bind, así que los cambios de código toman efecto al reiniciar gunicorn (`docker compose restart web`). **Solo hay que rebuildear si cambia `requirements.txt` o el `Dockerfile`.**

No hay test suite real configurada (los `tests.py` están vacíos por defecto).

---

## Environment (`.env` en `3darg-backend/`)

```
DJANGO_SECRET_KEY=...
DJANGO_DEBUG=1
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0,web,.ngrok-free.app

POSTGRES_DB=... POSTGRES_USER=... POSTGRES_PASSWORD=...
POSTGRES_HOST=db                # nombre del servicio en docker-compose
POSTGRES_PORT=5432

EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend   # OFF a propósito, ver abajo
EMAIL_HOST=smtp.resend.com  EMAIL_PORT=587  EMAIL_HOST_USER=resend
EMAIL_HOST_PASSWORD=...     # API key de Resend, vacío hasta activar
DEFAULT_FROM_EMAIL="Lumy <noreply@lumy.com>"
CONTACT_EMAIL=3darg1@gmail.com
TELEGRAM_URL=https://t.me/3darg

MP_ACCESS_TOKEN=...             # MercadoPago — sin esto los pagos rompen
MP_WEBHOOK_SECRET=...           # firma HMAC del webhook
MP_NOTIFICATION_URL=https://<ngrok>/api/payments/mp/webhook/
MP_CURRENCY=ARS
FRONTEND_BASE_URL=http://localhost:3000   # usado para back_urls de MP

GOOGLE_OAUTH_CLIENT_ID=...      # Client ID de Google Cloud Console (login "Continuar con Google")
                                 # Vacío = /api/users/google/ responde 400 explicando que falta config

ML_CLIENT_ID=...  ML_CLIENT_SECRET=...  ML_REDIRECT_URI=...  ML_SITE_ID=MLA   # Mercado Libre, ver sección dedicada
BAMBUDDY_URL=...  BAMBUDDY_API_KEY=...  BAMBUDDY_PRINTER_ID=1   # cola de impresión automática, vacío = apagado
PRESUPUESTOS3D_API_URL=...  PRESUPUESTOS3D_API_TOKEN=...        # aviso de venta online, vacío = apagado (ver sección dedicada)

SHIPPING_FALLBACK_RATES_JSON={"default": 6500, "zones": {}}   # tarifa de emergencia si falta el código postal (caso límite, ya no es de Andreani)

CORREO_ARGENTINO_TEST_MODE=1          # usa apitest.correoargentino.com.ar/micorreo/v1 mientras se prueba
CORREO_ARGENTINO_BASE_URL=            # vacío = default según TEST_MODE (test o api.correoargentino.com.ar/micorreo/v1)
CORREO_ARGENTINO_USER=  CORREO_ARGENTINO_PASSWORD=   # credenciales reales de MiCorreo (HTTP Basic contra POST /token)
CORREO_ARGENTINO_CUSTOMER_ID=         # customerId de la cuenta MiCorreo del dueño — vacío = alta/agencies/rates reales apagados
CORREO_ARGENTINO_PRODUCT_TYPE=CP      # "Correo Argentino Clásico"
CORREO_ARGENTINO_TIMEOUT=8
CORREO_ARGENTINO_SENDER_NAME=  CORREO_ARGENTINO_SENDER_PHONE=  CORREO_ARGENTINO_SENDER_EMAIL=
CORREO_ARGENTINO_SENDER_STREET=  CORREO_ARGENTINO_SENDER_STREET_NUMBER=  CORREO_ARGENTINO_SENDER_CITY=
CORREO_ARGENTINO_SENDER_PROVINCE=     # código AR_PROVINCES
CORREO_ARGENTINO_SENDER_ZIP=          # también es el postalCodeOrigin que se manda a POST /rates
CORREO_ARGENTINO_TARIFF_JSON={"1":20400,"5":32000,"10":45200,"15":56000,"20":65800,"25":80900}   # tabla de respaldo, ver abajo
CORREO_ARGENTINO_VALOR_DECLARADO_JSON={"brackets":[[20000,600],[200000,"3%"]]}                    # idem, cargo adicional
SHIPPING_CORREO_ARGENTINO_VOLUMETRIC_DIVISOR=6000
```

Ver sección dedicada "Envíos — Correo Argentino directo (API MiCorreo), sucursal Y domicilio" más abajo.

El mismo `.env` es leído por los servicios `db` y `web` en `docker-compose.yml`.

### Email — Resend (preparado, no activo)

Proveedor elegido para el lanzamiento: **Resend** (SMTP relay), ya "cableado" en `settings.py`/`.env` con los defaults correctos (`smtp.resend.com`, usuario `resend`, `DEFAULT_FROM_EMAIL=Lumy <noreply@lumy.com>` — se eligió el dominio de Lumy y no `3darg.com` porque Lumy lanza primero y es el dominio que realmente se va a verificar). **`EMAIL_BACKEND` sigue en `console` a propósito** — no se activa hasta no tener DNS. Los tres puntos que mandan mail (`orders/signals.py`, `contact/views.py`, `vending/views.py`) ya están todos en `try/except`, así que activar/desactivar esto no rompe nada funcional, sean cuales sean sus logs.

Pasos manuales pendientes para activar (no automatizables desde acá — requieren cuenta y acceso a DNS):
1. Crear cuenta en resend.com (owner).
2. Verificar el dominio `lumy.com` en Resend (agrega registros TXT/DKIM) — depende de tener acceso al DNS de `lumy.com`, todavía no disponible.
3. Generar una API key en Resend y pegarla en `EMAIL_HOST_PASSWORD` (`.env`).
4. Cambiar `EMAIL_BACKEND` a `django.core.mail.backends.smtp.EmailBackend`.
5. `docker compose restart web`.

---

## Stack

| Pieza | Versión / detalle |
|-------|-------------------|
| Django | 5.x |
| DRF | 3.15+ con SimpleJWT, django-filter |
| DB | PostgreSQL 16 (`psycopg[binary]`) |
| Server | gunicorn + whitenoise para estáticos del admin |
| Pagos | `mercadopago` SDK (Checkout Pro) |
| Idioma / TZ | `es-ar`, `America/Argentina/Buenos_Aires` |
| Python | 3.12-slim (Dockerfile) |

---

## Apps y endpoints

Todas las rutas montadas en `config/urls.py`. Prefijo común: `/api/`.

| App | Endpoint base | Endpoints clave |
|-----|---------------|-----------------|
| (auth JWT) | `/api/auth/` | `POST /token/`, `POST /token/refresh/` |
| `users` | `/api/users/` | `POST /register/` (alta + opcional `brand_slug`), `POST /google/` (login/registro con Google ID token + opcional `brand_slug`), `GET\|PATCH /me/`, `GET\|POST /favorites/`, `DELETE /favorites/<product_id>/` |
| `brands` | `/api/brands/` | `GET /` — lista de marcas **root** activas + sus `children` anidados recursivamente |
| `products` | `/api/` | `GET /products/` (filtros: `?search=`, `?brand_slug=`, `?is_featured=`, `?is_available=`, `?category__slug=`), `GET /products/<slug>/`, `GET /categories/?brand_slug=` |
| `cart` | `/api/cart/` | `GET\|DELETE /` (exigen `?brand_slug=`), `POST /items/` (exige `brand_slug` en el body), `PATCH\|DELETE /items/<id>/` — **todo requiere auth**. Sin `brand_slug` → 400 |
| `orders` | `/api/orders/` | `GET /` (lista del usuario, filtrable por `?status=`), `GET /<uuid>/`, `GET /summary/` (totales + counts por status) |
| `shipping` | `/api/shipping/` | `POST /calculate/` — cotización de Correo Argentino a sucursal y a domicilio (en vivo contra `POST /rates` si hay CP+credenciales, si no tabla de respaldo), `AllowAny`; `GET /agencies/?province=<code>` — sucursales reales de Correo Argentino (API MiCorreo), `[]` sin credenciales cargadas (ver sección "Envíos" más abajo) |
| `payments` | `/api/payments/` | `POST /mp/checkout-pro/`, `POST /mp/webhook/`, `GET /checkout/success/` (template HTML server-rendered) |
| `cms` | `/api/cms/` | `GET /pages/<brand_slug>/<page_slug>/` |
| `contact` | `/api/contact/` | `POST /` — manda email a `CONTACT_EMAIL` + confirmación al usuario (throttle 5/h por IP) |
| `vending` | `/api/vending/` | `POST /leads/` — captura leads de la máquina expendedora (`AllowAny`, throttle 5/h por IP), manda mail a `CONTACT_EMAIL`. Consumido por la landing `/maquina-expendedora` del frontend |
| `mercadolibre` | `/api/mercadolibre/` | `GET /authorize/`, `GET /callback/` — handshake OAuth para conectar la cuenta de vendedor; `POST /webhook/` — notificaciones push de ML sobre cambios de estado de ítems (ver sección dedicada) |

---

## Modelos clave

### `brands.Brand` (corazón del sistema)
- **Jerarquía** vía `parent` (FK a `self`). 3DARG es el único root; las sub-marcas apuntan a él.
- `brand_type`: `services | ecommerce | hybrid`. **`services` no permite checkout** — `payments` lo bloquea explícito.
- `theme` (JSONField): CSS custom properties que el frontend inyecta en `[brand]/layout.tsx`.
- `page_config` (JSONField): copy + secciones de la landing (`sections`, `hero_style`, `lifestyle_*`, `features`, `stats`, `newsletter_*`). El frontend lo consume tal cual.
- `social_links` (JSONField): `{instagram, tiktok, web, ...}`.
- `BrandLink`: items extra (Linktree, marketplace, etc.), serializados como `links`.

### `users.User`
- `AbstractUser` con `email` como `USERNAME_FIELD` (login con email, no username).
- `registered_brand`: FK opcional a `Brand` — guarda **en qué marca se registró** el usuario (info, no scoping).
- `Favorite`: `unique_together(user, product)`. Devuelve todos los favoritos del usuario; el filtrado por marca se hace en el frontend.

### `products.Category`
- Jerarquía de un solo nivel vía `parent` (FK a `self`, `null=True` = raíz). Hoy la usa Lumy: **Cortantes** y **Rodillos Texturizadores** son categorías raíz con subcategorías temáticas (Halloween, Disney, Animales, etc.) + dos subcategorías fijas en cada una:
  - **Todos**: no es "lo que no encaja en ningún tema" — en el shop, el link "Todos" de cada grupo filtra por el slug de la categoría **raíz** (`cortantes`/`rodillos-texturizadores`), no por su propio slug (`cortantes-00-todos`), así que trae TODOS los productos de esa raíz y de cada una de sus subcategorías temáticas (ver `ProductListAPIView.get_queryset` abajo). La categoría `Todos` en sí (slug `cortantes-00-todos` / `rodillos-texturizadores-00-todos`, `sku_prefix="00"`) sigue existiendo como tag asignable en el admin para productos sin tema puntual — simplemente queda incluida en el agregado como una subcategoría más, no es un filtro aparte.
  - **Sets**: productos vendidos en combo. En Cortantes es la vieja categoría raíz "Set de cortantes" reparentada (mismo `pk`/slug `set-de-cortantes`, para no romper sus 3 productos ni un link viejo a esa URL) — en Rodillos es una categoría nueva, todavía sin productos cargados. A diferencia de "Todos", su link del shop sí filtra por su propio slug (exacto, sin agregar).
  - Migración `products/migrations/0022_subcategorias_todos_y_sets.py` (reversible, `revertir()` deshace todo).
  - Otras marcas (3DARG, Print&Gym) no tienen esta estructura — sus categorías son todas raíz, sin subcategorías, y se listan sueltas donde corresponda.
- **Dropdown de categoría agrupado en el admin** (`ProductAdmin.formfield_for_foreignkey` + `_GroupedCategoryIterator` en `products/admin.py`): usa `<optgroup>` nativo del `<select>` (Django ya sabe renderizar choices anidados, no se tocó el widget) para mostrar cada categoría raíz con subcategorías (ej. CORTANTES) como título de grupo no seleccionable, con sus hijas debajo — "Todos"/"Sets" primero, el resto alfabético. Una raíz sin subcategorías (ej. "shaker" de Print&Gym) se lista suelta. El mismo criterio de orden ("Todos"/"Sets" primero) se replica en el sidebar de categorías de la tienda (`sortSubcategories()` en `ecommerce-frontend/app/[brand]/shop/page.tsx`). Este dropdown sigue ofreciendo "Todos" como una subcategoría tageable más (no se tocó) — es el filtro del shop el que la trata distinto.
- **`ProductListAPIView.get_queryset()` (`products/views.py`) resuelve `?category__slug=` a mano**, fuera de `filterset_fields` (django-filter solo hace match exacto): si el slug recibido es una categoría **raíz** (sin `parent`), filtra por esa raíz + todas sus hijas (`category_id__in=[raíz, *hijas]`); si es una subcategoría (ej. un tema puntual o "Sets"), filtra exacto por esa sola categoría. El link "Todos" del sidebar (`[brand]/shop/page.tsx`) es el que arma la URL con el slug de la raíz para activar el primer caso.
- `sku_prefix`: ver `Product.generate_sku()`/`root_sku_prefix()` más abajo — solo hace falta cargarlo en la raíz (código de marca del SKU) y, opcionalmente, en cada subcategoría (segmento extra + numeración local).

### `products.Product`
- `slug` único, autogenerado desde `name` en `save()` si está vacío.
- FK opcional a `Brand` (productos sin marca existen, pero no se ven en `?brand_slug=`).
- **`sku`**: identificador único de catálogo, **compartido entre la web, el feed de Google/Meta, Mercado Libre y presupuestos3d** (se carga a mano ahí, ver `presupuestos3d/CLAUDE.md`). Formato `MARCA-CATEGORIA[-ID_SUBCATEGORIA]-NNNNNN[-VARIANTE]` (ej. `LUMY-COR-000037`, `LUMY-COR-04-000037` si la subcategoría tiene código propio, `MSL-ARO-000401-VERDE-M`), armado por `Product.generate_sku()`:
  - `MARCA` = `Brand.sku_prefix` (código corto fijo por marca, ej. `LUMY`, `PYG`, `MSL`, `CYW`, `DRG` — cargado a mano en el admin, fallback al slug si está vacío).
  - `CATEGORIA` = `Category.root_sku_prefix()`: código de la categoría **raíz** del producto (sube por `parent` hasta el nivel superior), no de la subcategoría puntual — así el SKU no se vuelve obsoleto si se reordenan subcategorías.
  - `ID_SUBCATEGORIA` (opcional) = `Category.sku_prefix` **propio de la subcategoría** (no la raíz), solo si está cargado — hoy solo lo tienen las ~44 subcategorías de Cortantes en Lumy (`01`..`44`, seedeadas desde el número que ya tenían en el slug, ej. `cortantes-04-animales-de-la-selva` → `04`). Si la subcategoría no tiene `sku_prefix` propio, este segmento no aparece.
  - `NNNNNN`: **si el producto tiene `ID_SUBCATEGORIA`**, es un contador LOCAL a esa subcategoría (1, 2, 3... el próximo número libre dentro de ese mismo prefijo, calculado por `Product._next_subcategory_sku_number()` tomando el máximo ya usado en los SKU de esa categoría) — para que una subcategoría chica (ej: Navidad, 10 productos) quede numerada `000001`..`000010` y no arrastre números de 3 cifras sin sentido para esa colección puntual. **Si no tiene subcategoría**, sigue siendo `Product.pk` (comportamiento histórico, sin tocar). Este cambio de numeración rige desde que se agregó — los SKU ya asignados antes no se regeneran retroactivamente (evita romper publicaciones ya hechas en Mercado Libre/el feed). *Ojo si regenerás varios productos de la misma subcategoría en un mismo lote*: el cálculo es secuencial (lee los SKU ya guardados de los hermanos), así que regenerar de a uno por vez sobre datos ya consistentes da el resultado esperado, pero regenerar un lote entero de golpe puede arrastrar números viejos de los hermanos que todavía no se actualizaron — en ese caso, asignar los números a mano en orden (ver cómo se corrigió el lote de Navidad al crearlo).
  - `VARIANTE` (opcional) = `color`/`size`, **solo informativos** (no son variantes con stock propio — eso requeriría un modelo de variantes que hoy no existe).
  - **El SKU se genera una sola vez al crear el producto y después queda fijo** — no se recalcula solo si cambiás marca/categoría/color/tamaño más tarde (evita romper el matching con Mercado Libre o el historial del feed). Para actualizarlo a propósito: acción de admin *"Regenerar SKU"* sobre `Product` (`products/admin.py`).
  - Migración `products/migrations/0018_regenerar_skus.py`: regeneró en lote los ~380 SKU existentes (antes puramente secuenciales, `3DARG-000037`) al formato nuevo — corrida una única vez, ventana elegida porque el campo no se usa en el frontend y casi nada estaba publicado todavía en Mercado Libre. Migraciones `0019`/`0020`: sumaron el segmento `ID_SUBCATEGORIA` para Cortantes y regeneraron solo los SKU afectados. Migración `0021_canales_disponibilidad.py`: agregó `is_available_web`/`is_available_ml` (ver "Productos para socios" abajo) y el cambio de `NNNNNN` a contador local descripto arriba (sin regenerar nada retroactivo, solo altera `generate_sku()` para productos nuevos).
- **`brand` se serializa como slug** (no ID) → `SlugRelatedField`. El frontend compara `product.brand === params.brand` directo.
- `ProductImage` con `order`, accedida vía `images` (prefetcheada en list/detail). `channel` (`web|ml`) controla a qué canal pertenece cada foto — **cada foto es de un solo canal**, no existe más un tercer valor "ambos" (eliminado en la migración `0032_eliminar_canal_ambos.py`/`0033_eliminar_ml_order_y_both.py`, que de paso borró el campo `ml_order`): si una foto tiene que verse en los dos canales, se carga una vez en cada uno (dos filas, mismo archivo). Las de `channel=ml` quedan afuera de la web/el feed de Google-Meta (`WEB_IMAGES_PREFETCH` en `products/views.py`, que ahora equivale a `channel=web`). `order` es el único campo de orden, ya sin ambigüedad porque es por canal.
- `ml_item_id`, `ml_category_id`, `weight_kg`/`length_cm`/`width_cm`/`height_cm`: datos para publicar en Mercado Libre, ver sección dedicada más abajo.
- **Canales de venta por producto** (`is_available_web`, `is_available_ml`, default `True` los dos): permiten prender/apagar un producto en la web o en Mercado Libre de forma independiente, sin afectar al otro canal — sección "Canales de venta" en el admin. `is_available` (el campo viejo) sigue siendo el apagado general: si está en `False`, no se vende en ningún lado sin importar estos dos.
  - **Web**: `is_available_web=False` **o** `is_available=False` hacen que el producto devuelva 404 en `ProductListAPIView`/`ProductDetailAPIView` (mismo criterio que `members_only` para anónimos; ambas vistas filtran `is_available=True, is_available_web=True` — antes solo filtraban el canal, y un producto con `is_available=False` pero `is_available_web=True` seguía viéndose en la tienda aunque no se pudiera comprar, bug corregido), se excluye de `ProductFeedAPIView` (feed Google/Meta) y no se puede agregar al carrito ni comprar (`cart/views.py`, `payments/views.py`).
  - **Mercado Libre**: `is_available_ml=False` no borra la publicación — la próxima vez que corra `sync_product()` (acción de admin *"Publicar/Actualizar en Mercado Libre"*) la **pausa** (`PUT /items/{id} {"status": "paused"}`) sin tocar precio/stock/fotos. Reactivar (`is_available_ml=True`) y volver a correr la acción la reactiva. No es automático — hay que correr la acción después de cambiar el campo.
  - **Se apaga solo**: ver webhook de Mercado Libre en la sección dedicada más abajo — si el ítem se pausa/cierra/elimina directo en ML, `is_available_ml` se pone en `False` solo, sin que nadie tenga que revisar a mano.
  - **La relación es unidireccional**: `is_available` manda sobre los canales (apagado general = apagado en todos lados), pero apagar un canal puntual nunca toca `is_available` ni el otro canal — son independientes entre sí.
- **`is_available` e `is_featured` editables inline desde la lista del admin** (`list_editable`, junto con `members_only`/los dos canales), con una validación cruzada en `Product.clean()`: no se puede guardar `is_featured=True` si `is_available=False` (no tiene sentido destacar un producto apagado) — tira `ValidationError` tanto en el form de edición completo como al editar inline desde la lista. Se corre automáticamente vía `ModelForm.full_clean()` en los dos casos, no hace falta lógica extra en `ProductAdmin`.
- **Productos para socios** (transversal a todas las marcas):
  - `members_only` (bool): solo visible/comprable con cuenta. Filtrado por `Product.objects.visible_to(user)` (manager `ProductQuerySet`) en list y detail → 404 a anónimos.
  - `member_discount_percent` (0–100): descuento para usuarios autenticados.
  - **`price_for(user)` es la fuente de verdad del cobro** (anónimo `price`, socio `member_price`). La usan serializer (`final_price`), `cart` (subtotal/total) y `payments` (checkout). No replicar el cálculo de descuento en otro lado.
  - El checkout bloquea con 403 que un anónimo compre `members_only`.
  - El `CartSerializer` necesita `context={"request": request}` para resolver el precio de socio (ya pasado en `cart/views.py`).

### `products.ProductVariant` / `products.CostTemplate`

Infraestructura para que un mismo presupuesto de costeo de `presupuestos3d` fije el precio de muchos productos de catálogo a la vez (ver "Integración inversa: sync de costeo → ecommerce" más abajo).

- **`CostTemplate`**: "plantilla de costo" compartida por muchas `ProductVariant` — el equivalente, acá, a un `Producto` de costeo marcado `es_producto_ecommerce=True` en presupuestos3d. Campos: `nombre` (único, descriptivo), `external_ref` (único, **clave real de upsert** — referencia estable al `Producto` de costeo en presupuestos3d, no al nombre, que puede cambiar), `sale_price` (se propaga a las variantes vinculadas), `weight_kg`/`length_cm`/`width_cm`/`height_cm`, `legacy_cutter_size` (solo trazabilidad: la migración `0034_crear_productvariant_y_costtemplate` creó un `CostTemplate` por cada `Product.cutter_size` en uso, para no perder la agrupación histórica del mecanismo viejo).
- **`ProductVariant`**: unidad vendible real de un `Product` — `product` (FK), `color`/`size`, `sku` propio (único), `price`, `stock`, `cost_template` (FK opcional a `CostTemplate`, `on_delete=SET_NULL` — vacío = variante con precio propio, no ligada a ningún presupuesto compartido), medidas propias, `gtin`, `is_available`, `ml_variation_id` (reservado, no usado todavía).
- **Fase 1**: cada `Product` existente tiene EXACTAMENTE una `ProductVariant` (migración 1:1 `0035_migrar_productos_a_variantes_y_costtemplate`). Nada del cart/checkout/Mercado Libre/el feed lee `ProductVariant` todavía — siguen leyendo `Product.price` y compañía. Las fases siguientes van a conectar esos consumidores a `ProductVariant`, y recién ahí un mismo `Product` podrá tener variantes reales de color/tamaño con stock propio.
- **Vincular una variante a un template** (manual, una vez por variante): admin de `ProductVariant` → seleccionar fila(s) → acción *"Asignar template de costo a las variantes seleccionadas"* (`products/admin.py::AsignarCostTemplateForm`, con página de confirmación intermedia tipo `delete_selected`). Si el template ya tiene `sale_price` cargado, también actualiza el `Product` subyacente en el momento (mismo criterio que usa el sync automático).
- **Resumen de variante en `ProductAdmin`**: cada `Product` muestra un campo de solo lectura ("Variante / template de costo") que linkea a su `ProductVariant` y, si tiene, a su `CostTemplate` — atajo de navegación, no reemplaza nada de lo de arriba.
- **`ProductVariant.save()` propaga precio y medidas del template SIEMPRE que haya `cost_template` cargado**, sin importar por dónde se guarde la variante (form de edición normal del admin, shell, `list_editable`, una API futura) — copia `price` y, si están cargados, `weight_kg`/`length_cm`/`width_cm`/`height_cm` (mismo criterio "solo si `is_not None`" que usa `CosteoSyncAPIView`, no pisa una medida propia con un campo vacío del template) y espeja los mismos campos en el `Product` subyacente vía `.update()` (mientras dure la Fase 1). Se agregó porque vincular una variante a un template **desde el form de edición plano de `ProductVariant`** (no desde la acción de bulk de arriba) dejaba el precio desactualizado en silencio — así pasó con "Adorno Bola", vinculado a mano sin pasar por la acción, precio stale hasta que se detectó por los logs del admin (`LogEntry`). La acción de bulk y `CosteoSyncAPIView` siguen actualizando con `.update()` a propósito (no llaman a `save()`, son operaciones en lote sobre muchas variantes) — este `save()` cubre el resto de los casos, que antes no tenían ninguna garantía.
- **Por qué el template cuelga de `ProductVariant` y no de `Product`** (decisión de arquitectura, confirmada, sin cambios): un `CostTemplate` modela un **perfil físico de costo/tamaño** (ej. "cortante mediano 8cm"), no un diseño — distintos diseños sin relación entre sí (Jirafa, Cebra, León...) comparten un mismo template por tamaño físico, que es la razón de ser de todo el mecanismo. Si colgara de `Product` en cambio de `ProductVariant`, el día que la Fase 2 habilite variantes reales de un mismo `Product` (ej. el mismo diseño en 3 tamaños), todas esas variantes quedarían forzadas a compartir un solo template/precio aunque tengan tamaños físicos distintos. Dejarlo en `ProductVariant` es compatible con los dos casos: diseños distintos compartiendo tamaño (hoy) y un mismo diseño con variantes de tamaños distintos (fases futuras).

### `cart.Cart`
- `ForeignKey(User, related_name="carts")` + `ForeignKey(Brand, related_name="carts")` **no nullable**, `unique_together(user, brand)` — **un carrito por (usuario, marca)**. Cada espacio de marca (3DARG incluida) tiene el suyo, aislado del resto.
- `CartItem(cart, product, quantity)` con `unique_together(cart, product)`.
- `get_or_create_cart(user, brand)` en `cart/views.py` recibe `brand` (objeto `Brand`) obligatorio — ya no hay overload sin marca. Las vistas resuelven `brand_slug` de `query_params` (GET/DELETE) o del body (POST `/items/`); si falta o no existe esa Brand → 400 en español.
- Al agregar un item se valida que `product.brand` (si tiene) coincida con la `brand` del carrito — si no, 400 ("Este producto no pertenece a la marca actual").
- Migración `cart/migrations/0003_cart_por_marca.py` + `0004_cart_por_marca_schema.py`: backfillean los `Cart` viejos con `brand=null` a la marca raíz (`slug="3darg"`) y fusionan duplicados por `(user, brand)` antes de aplicar el `unique_together`. Separadas en dos migraciones porque Postgres no permite `ALTER TABLE` en la misma transacción que el `RunPython` (pending trigger events).

### `orders.Order`
- **PK = UUID** (no integer). Las URLs usan `<uuid:id>`.
- `status`: `DRAFT | PENDING | PAID | REJECTED | CANCELLED`.
- `brand` con `on_delete=PROTECT` (no se puede borrar una marca con órdenes).
- `user` puede ser `null` (`SET_NULL`) — checkout de guest está soportado en `payments`.
- `external_reference`: UUID hex único, **es el ID que comparte con MercadoPago**. El webhook lo usa para matchear el pago.
- `items` (JSONField): snapshot por si querés histórico; los items reales están en `OrderItem` (FK).
- **Stock se descuenta vía signal**, no en el checkout. Ver abajo.

### `payments.MercadoPagoPayment`
- `OneToOne(Order)`. Guarda `preference_id`, `init_point`, `sandbox_init_point`, `mp_payment_id`, `status`, y `raw` (JSON con payloads/eventos crudos).

### `cms.Page` / `cms.Section`
- Sistema flexible de páginas por marca. `Section.data` (JSONField) tiene la config de cada sección. Por ahora poco usado — la mayoría del copy va en `Brand.page_config`.

### `vending.VendingLead`
- Modelo simple de captura de leads para la línea de negocio "máquina expendedora de impresión 3D" (todavía en validación, no es una sub-marca de ecommerce).
- `segmento` (choices): `cotillon` (venta bajo pedido), `empresa` (máquina in-situ, impresión remota), `submarca` (uso interno del grupo: shopping, gimnasio, etc.), `alquiler` (marca privada, edición limitada), `otro`.
- Sin auth (`AllowAny` + throttle `5/hour` por IP, igual patrón que `contact`). Al crear un lead, `VendingLeadAPIView.post()` manda mail a `CONTACT_EMAIL` con `fail_silently=True` (un fallo de email no rompe la captura del lead).
- No tiene relación con `Brand`/`products` — es standalone, todavía no hay modelo de negocio ni pricing definido.

---

## Integración Meta Business (Pixel + Conversions API)

`brands/services/meta_conversions.py::send_event()` — envía eventos server-side a Meta Conversions API usando `pixel_id` + `conversions_api_access_token` que cada `Brand` guarda en `meta_config` (JSONField). Mismo patrón que Google OAuth: si la marca no tiene `meta_config` cargado, la función es un no-op (`return False`), no rompe el flujo.

- Se dispara desde `orders/signals.py` en la confirmación de pago (evento `Purchase`), con `event_id = order.external_reference` para que Meta deduplique contra el Pixel client-side que dispara el mismo evento en el frontend.
- PII (`email`, `phone`) se hashea SHA256 antes de mandarse (`hash_user_data()`), como exige Meta.
- **Nunca lanza excepción** — cualquier error de red/API se loguea (`logger.error`) y devuelve `False`; el pago sigue su curso igual.
- `meta_config` también trae `catalog_id` y `whatsapp_business_phone_id`, reservados para integraciones futuras (catálogo de productos en Meta, WhatsApp Business) — hoy solo se usa `pixel_id`/`conversions_api_access_token`.

---

## Integración con Mercado Libre (app `mercadolibre`)

Publicación **manual** de productos en Mercado Libre, disparada desde el admin — no es un sync automático ni programado. Es una sola cuenta de vendedor para todo el grupo 3darg (no está scopeada por marca, a diferencia del resto del sistema). Pensada para cargar **toda** la info relevante desde el admin de Django, sin tener que entrar nunca al panel de vendedor de Mercado Libre.

- **App ML en uso**: "3DARG Integracion ML" (Client ID `1453536118698846`), app dedicada en el DevCenter de Mercado Libre — separada de cualquier otra app vieja del grupo (ej: la de MercadoPago). `ML_CLIENT_ID`/`ML_CLIENT_SECRET` en Railway apuntan a esta app.
- **Conexión (OAuth2)**: `GET /api/mercadolibre/authorize/` redirige al login de Mercado Libre; `GET /api/mercadolibre/callback/` recibe el `code` y lo canjea por `access_token`/`refresh_token`, guardados en `MLCredentials` (modelo singleton, `MLCredentials.load()`). El `refresh_token` rota en cada uso — `mercadolibre/services.py::_refresh_access_token()` siempre guarda el que vuelve en la respuesta, nunca reusa el anterior. `get_valid_access_token()` lo renueva solo si está por vencer (margen de 5 minutos).
- **Publicar/actualizar**: acción de admin *"Publicar/Actualizar en Mercado Libre"* sobre `Product` (`products/admin.py::publicar_en_mercadolibre`) → `mercadolibre/services.py::sync_product(product)`. Primera vez: `POST /items` y guarda el `ml_item_id` devuelto. Siguientes veces: `PUT /items/{id}` con los mismos datos (precio, stock, fotos, garantía, envío gratis). `family_name`, `listing_type_id` y `shipping.mode`/`dimensions` son inmutables en ML una vez creado el ítem — el `PUT` los excluye a propósito (`shipping.free_shipping` sí es mutable, se conserva aparte).
- **`sync_product()` devuelve `(ml_item_id, warnings)`**: `warnings` es una lista (puede estar vacía) de avisos NO bloqueantes que Mercado Libre devuelve en el body de una respuesta 200 cuando acepta el request pero ignora en silencio una parte del payload — el caso real encontrado: **`shipping.free_shipping.cost_exceeded`** (no activa envío gratis si el precio del producto no alcanza a cubrir el costo de envío). La acción de admin los muestra como mensaje de warning por producto — prestarles atención, porque sin esto un campo puede quedar "prendido" en el admin sin tener efecto real en la publicación.
- **Pausado/reactivado vía `is_available_ml`**: si el producto tiene `is_available_ml=False`, `sync_product()` no actualiza nada — manda `PUT /items/{id} {"status": "paused"}` y listo (requiere que ya exista `ml_item_id`; si todavía no se publicó nunca, tira `MLSyncError` pidiendo prender el canal antes). Si `is_available_ml=True` y el ítem ya existe, el `PUT` normal fuerza `"status": "active"` además de los datos — así reactiva un ítem que estaba pausado. Ver "Canales de venta por producto" en el modelo `Product` más arriba.
- **Requisitos para poder publicar**: `ml_category_id` cargado en el producto (default `MLA375405` = "Cortantes") y al menos `MIN_ML_PICTURES` (hoy 3) imágenes con `channel="ml"` — Mercado Libre penaliza el "quality score" de la publicación con menos fotos (regla `PICTURES_QUANTITY_MIN`). Sin eso, `MLSyncError` con mensaje en español, mostrado en el admin. **Este mismo piso de 3 fotos se exige también al GUARDAR el producto desde el admin** (no solo al publicar): si `is_available_ml=True`, `products/admin.py::ProductImageMLFormSet` (el formset del apartado "Imágenes — Mercado Libre") bloquea el guardado del form completo hasta que haya al menos 3 imágenes cargadas ahí — evita dejar cargado un producto "ML-habilitado" que después va a fallar al intentar publicarlo. No afecta la edición rápida de `list_editable` en la lista (esa no toca los inlines de fotos). Migración `0028_apagar_ml_sin_fotos_suficientes.py`: al subir el piso de 1 a 3 fotos, apagó `is_available_ml` en los productos existentes que no llegaban (364 de 393 en producción) — se reactivan a mano a medida que se les cargan las fotos que faltan.
- **Atributos que se mandan**: `BRAND` (fijo "3DARG"), `MODEL` (= `product.sku`, atributo genérico de catálogo) y `SELLER_SKU` (= `product.sku` también, el campo que ML reserva específicamente para el código interno del vendedor — se mandan ambos por compatibilidad, sin tocar `MODEL` por las dudas de que algún listing viejo dependa de él), `HEIGHT`/`WIDTH`/`DEPTH` si están cargadas las dimensiones (si no, ML marca el ítem `incomplete_technical_specs` y puede quedar en revisión manual), y `GTIN` si el producto tiene `Product.gtin` cargado (código de barras real, opcional en esta categoría — no inventar uno, ML valida el checksum).
  - **Ojo con el mapeo `height_cm`/`width_cm`/`length_cm` → `HEIGHT`/`WIDTH`/`DEPTH`** (`mercadolibre/services.py::_build_payload()`): `HEIGHT`="Altura"=`product.height_cm`, `WIDTH`="Ancho"=`product.width_cm`, `DEPTH`="Profundidad"=`product.length_cm` (ojo acá, no es `height_cm` el que arma `DEPTH`). Se encontró un `CostTemplate` real con `length_cm`/`height_cm` cruzados (Cortantes: cargado como alto=1cm/profundidad=5cm cuando el cortante real es alto=5cm/ancho=5cm/profundidad=1cm — plano, no al revés) — el panel "Dimensiones" de la publicación terminó mostrando "1cm x 5cm x 5cm" en vez de "5cm x 5cm x 1cm". Al corregir el `CostTemplate` y volver a correr `sync_product()`, el `PUT` SÍ actualiza `HEIGHT`/`WIDTH`/`DEPTH` en una publicación ya existente (son atributos normales, no están en la lista de inmutables) — **pero `shipping.dimensions`** (el string `LxWxH,peso` que arma el costo de envío, ver más abajo) **no se corrige solo en los ítems ya publicados**, porque es parte de `shipping.mode`/`dimensions`, inmutable una vez creado el ítem (el `PUT` lo excluye a propósito). Si hace falta corregir el envío de una publicación vieja con medidas mal cargadas, hay que recrearla o contactar soporte de ML — no hay forma de pisarlo vía API.
- **`color`/`size`/`shape`/`is_dishwasher_safe` → atributos de ML, condicionados a la categoría**: estos cuatro campos de `Product` (`color`/`size` también arman el SKU, ver `generate_sku()`) se mandan como atributos reales de la publicación — `COLOR`, `SIZE`, `COOKIE_CUTTER_SHAPE` ("Forma") e `IS_DISHWASHER_SAFE` ("Es apto para lavavajillas") — **solo si la categoría cargada en `ml_category_id` admite ese atributo puntual**. Se verifica en vivo contra `GET /categories/{id}/attributes` (endpoint público, sin token) vía `_fetch_category_attribute_ids()` (cacheada en memoria por categoría con `lru_cache`, para no pegarle a la API una vez por producto en una publicación en lote). Confirmado en vivo para `MLA375405` ("Cortantes", la categoría default de Lumy): tiene `COLOR`, `COOKIE_CUTTER_SHAPE` e `IS_DISHWASHER_SAFE`, pero NO tiene ningún atributo de tamaño/talle — así que hoy `color`/`shape`/`is_dishwasher_safe` viajan a la publicación y `size` queda solo informativo/para el SKU. `shape` se manda como texto libre (`value_name`, no hace falta matchear las opciones sugeridas de ML); `is_dishwasher_safe` es un `BooleanField` NULLABLE (`None` = "no corresponde informarlo", no se manda nada — distinto de `False`) y usa `value_id` explícito (`ML_DISHWASHER_SAFE_VALUE_IDS`, confirmado en vivo) porque ML lo pide así para atributos `boolean`. `shape`/`is_dishwasher_safe` viven en la sección "Características secundarias" del panel nativo de ML (suman al puntaje de "calidad de la publicación", no son obligatorios). Si en el futuro una sub-marca publica en otra categoría con atributos distintos (ej. `SIZE` en indumentaria de Print&Gym), empiezan a mandarse solos con cargar esa `ml_category_id`, sin tocar código.
- **Garantía (`sale_terms`)**: si `Product.warranty_months` está cargado, se manda `sale_terms` (clave aparte de `attributes`, confirmado en vivo contra `GET /categories/{id}/sale_terms`) con `WARRANTY_TYPE="Garantía del vendedor"` + `WARRANTY_TIME` (`value_struct: {number, unit}`).
- **`PACKS_NUMBER` ("Cantidad de packs") fijo en `"1"`, condicionado a la categoría igual que `COLOR`/`SIZE`/etc.**: atributo `value_type="number"` sin `value_id` para "No aplica" — confirmado en vivo que mandar texto libre `"No aplica"` tira `item.attribute.invalid` ("is not a valid number"); la única forma de marcarlo como completo (y sacar el cartel naranja de "calidad de la publicación" en el panel de ML) es un número real. Como ningún producto nuestro se vende como "más de 1 pack idéntico" en una misma publicación (eso es lo que mide este atributo puntual — distinto de "Sets", que es un combo de piezas DISTINTAS, no packs duplicados), se manda `"1"` fijo cuando la categoría lo admite, sin agregar ningún campo nuevo a `Product`.
- **Cuotas sin interés ("Agregá cuotas..." en el panel de ML) — NO es configurable desde la API, confirmado en vivo**: `GET /categories/{id}/sale_terms` solo trae `INSTALLMENTS_CAMPAIGN` (campaña de cuotas, ej. "Ahora 12") y viene `read_only=true` — no hay ningún `sale_term` que el vendedor pueda escribir para absorber el costo de cuotas sin interés por ítem. Ese panel ("Cuotas y cargos", con 3/6/9/12 cuotas y su % de costo) es exclusivo del seller panel web de Mercado Libre — no hay nada para implementar acá.
- **Envío gratis (`shipping.free_shipping`)**: si `Product.free_shipping_seller_paid=True`, se manda `shipping.free_shipping=True` — a diferencia de `mode`/`dimensions`, este campo SÍ se puede actualizar en publicaciones ya existentes. Mercado Libre puede ignorarlo en silencio si el precio no cubre el costo de envío (ver "warnings" arriba).
- **Fotos por canal, dos apartados separados en el admin**: `ProductAdmin.inlines = [ProductImageWebInline, ProductImageMLInline]` — cada uno lista/edita solo las `ProductImage` de su propio `channel` (`web`/`ml`), sin selector de canal en el form (lo fija el formset al guardar una fila nueva en ese apartado, ver `ProductImageWebFormSet`/`ProductImageMLFormSet`). Esto permite tener fotos exclusivas de Mercado Libre (ej: con medidas o marca de agua) sin que aparezcan en la web ni en el feed de Google/Meta, y viceversa; si una foto tiene que verse en los dos canales se carga una vez en cada apartado (dos filas, mismo archivo — ya no existe un tercer valor "ambos"). `order` es el único campo de orden (ya no hay `ml_order`): como cada fila es de un solo canal, ordena sin ambigüedad dentro de ese canal.
- **`MLListingTemplate`**: plantilla única (singleton, igual patrón que `MLCredentials`) con el texto fijo de la descripción (`Template.safe_substitute()` con `$modelo`/`$medidas`), editable desde el admin.
  - **Es completamente independiente de `Product.description`** (el campo de la ficha web/feed) — `_build_description(product)` arma el texto SOLO a partir de esta plantilla + `product.name`/medidas, nunca lee `Product.description`. `sync_product()` manda ese texto a ML vía `PUT /items/{id}/description` en **cada** sync real (POST y PUT), así que la descripción de la publicación en ML siempre se regenera sola — no hace falta "conectar" nada a mano por producto.
  - **`Product.description` SÍ hubo que poblarlo a mano una vez** para que la ficha web tuviera el mismo texto (coherencia web/ML, pedido explícito del dueño): se corrió un script puntual (no una migración ni una acción de admin reutilizable) que sobreescribió `description` de los ~300 productos de Cortantes con el resultado de `_build_description(product)` — mismo texto que ve ML, pero congelado en ese momento; si la plantilla de `MLListingTemplate` cambia después, NO se repropaga sola a `Product.description` (ni al revés) — son dos copias independientes desde ese punto.
  - **Gotcha real encontrado: ítems con `ml_item_id` cargado pero `ml_last_synced_at=None` nunca recibieron la descripción de la plantilla** — son productos que quedaron con un `ml_item_id` puesto por algún camino que no pasó por `sync_product()` (publicación vieja/manual), así que el `PUT /items/{id}/description` nunca se ejecutó para ellos y la publicación en ML puede tener la descripción vacía o desactualizada aunque el resto de los datos esté bien. Se detectaron 2 casos reales en Cortantes ("Jirafa", "Cebra") filtrando `Product.objects.exclude(ml_item_id="").filter(ml_last_synced_at__isnull=True)`. Se arregla simplemente corriendo `sync_product(product)` de nuevo (requiere que ya cumpla el mínimo de `MIN_ML_PICTURES` en el canal `ml` — si no, tira `MLSyncError` y hay que cargar fotos antes).
  - **Las páginas `/up/<ID>` de Mercado Libre ("producto unificado"/catálogo) son distintas del permalink real del ítem** (`articulo.mercadolibre.com.ar/MLA-<id>-.../_JM`, el que devuelve `GET /items/{id}` en el campo `permalink`) y **pueden mostrar datos desactualizados por cache propio de ML**, incluso cuando el ítem real ya está al día (confirmado: la publicación de "Cruz" tenía la descripción correcta vía API mientras la página `/up/` todavía no la reflejaba). No usar esas URLs `/up/` para diagnosticar si algo "no se guardó" — chequear siempre el `permalink` real (o la API) antes de asumir un bug de nuestro lado.
- Sin `ML_CLIENT_ID`/`ML_CLIENT_SECRET` configurados en `.env`, cualquier intento de publicar tira `MLSyncError` explicando que falta la config — mismo criterio "vacío = apagado" que el resto de las integraciones.
- **Webhook (`POST /api/mercadolibre/webhook/`)**: ML notifica acá cuando un ítem cambia de estado (pausado, cerrado, eliminado, reactivado), sin depender de que alguien entre al admin a revisar a mano. A diferencia del webhook de MercadoPago, **ML no firma el payload** — por eso `mercadolibre/views.py::webhook()` no confía en el body recibido, solo lo usa para saber qué `item_id` volver a consultar: si `topic == "items"`, extrae el id de `resource` (`/items/{id}`) y llama a `mercadolibre/services.py::handle_item_notification(item_id)`, que pide el ítem de nuevo por API con nuestro propio `access_token` y recién ahí decide. Si el status real ya no es `active`, apaga `is_available_ml` del producto asociado (match por `ml_item_id`); si volvió a estar activo (lo reactivaron directo en ML), lo prende de nuevo. No hace nada si el `item_id` no matchea ningún producto nuestro. Siempre responde 200 (ML reintenta si no, el body de la respuesta no le importa).
  - **Configurado y verificado en producción** (ya no es setup pendiente): la URL pública `https://api.3darg.com/api/mercadolibre/webhook/` está cargada en el panel de la app ML (DevCenter → Notificaciones → "Notificaciones callbacks URL"), suscripta al tópico `items`, confirmado vía `GET /applications/{app_id}` con el `access_token` real.
- **No hay conexión con `presupuestos3d`**: el SKU que viaja a Mercado Libre es el mismo `Product.sku` que ya usa el feed de Google/Meta, pero no hay ningún sync automático entre esta app y el sistema interno de costeo — si corresponde, se carga a mano ahí (ver `presupuestos3d/CLAUDE.md`, campo `Producto.sku`).
- **Ficha del producto en el admin, organizada por canal de venta**: `products/admin.py::ProductAdmin.fieldsets` agrupa TODO lo que hace falta cargar para cada canal en un único apartado (en vez de tenerlo repartido en varias secciones sueltas) — "Página web" (canal, categoría de Google/Meta Catalog, gastos y ganancia) y "Mercado Libre" (canal, `ml_item_id`/`ml_category_id`, color/tamaño, dimensiones/peso, GTIN/garantía/envío gratis, gastos y ganancia), además de "Precio y stock" (cosas comunes a ambos canales: precio, stock, tamaño de costeo) y "Descuento por volumen"/"Socios" aparte. Objetivo: poder cargar una publicación de punta a punta sin saltar entre secciones.
- **`Product.ml_last_synced_at`**: timestamp informativo (no editable a mano) que `sync_product()` pisa en sus tres caminos reales — alta (POST), actualización (PUT) y pausado/reactivado — nunca en un guardado cualquiera del producto. Sirve para saber de un vistazo cuándo se tocó por última vez la publicación real en Mercado Libre.
- **Vista de admin separada "Productos publicados en Mercado Libre"**: proxy model `ProductoEnMercadoLibre` (`products/models.py`, misma tabla que `Product`, sin migrar datos) + `ProductoEnMercadoLibreAdmin` (`products/admin.py`), que hereda TODO de `ProductAdmin` (fieldsets, inlines de fotos, acciones "Publicar/Actualizar en Mercado Libre" y "Regenerar SKU") y solo cambia el recorte: `get_queryset()` filtra a los que ya tienen `ml_item_id` cargado, el listado muestra `ml_item_id`/`ml_last_synced_at` en primer plano y ordena por sincronización más reciente. No permite alta (`has_add_permission=False`) — los productos nuevos se siguen creando desde "Productos" y aparecen acá solos una vez publicados. Pensada para el uso diario de entrar a lo ya publicado, editarlo y republicar sin buscarlo entre todo el catálogo.
- **`ml_price` — precio propio de Mercado Libre, independiente de `price`**: `Product.ml_price` (nullable, vacío por default) permite publicar en ML a un precio distinto del de la web, pensado para compensar que ML cobra más comisión/impuestos que una venta directa — `Product.sale_price_for("ml")` devuelve `ml_price` si está cargado, si no cae a `price` (comportamiento histórico, sin romper nada). `price` sigue siendo la única base que lee `presupuestos3d` en cada sync y la que se usa siempre en la web; `sync_product()` (ver arriba) ya publica `sale_price_for("ml")`, no `price`, al mandar el precio a Mercado Libre.
- **Gastos por canal + ganancia neta, editables por producto**: cada `Product` tiene un set paralelo de campos `ml_*`/`web_*` (`commission_percent`, `fixed_fee`, `vat_percent`, `gross_income_tax_percent`, `other_variable_percent`, `shipping_cost` — todos `DecimalField` con `default=0`, sin default de IVA/IIBB a propósito porque dependen de la situación impositiva real del dueño) que modelan el desglose real de costos de vender en cada canal. `channel_total_expenses(channel)` los suma sobre `sale_price_for(channel)`; `channel_net_profit(channel, cost)`/`channel_net_profit_percent(...)` restan el costo de fabricación (de `cost_sku()`/presupuestos3d) para dar la ganancia neta real. El admin muestra esto como un resumen de solo lectura en cada ficha de canal (`ProductAdmin._channel_resumen()`).
  - **`channel_expense_breakdown(channel)`**: desglose línea por línea (Comisión, IVA, Ingresos Brutos, Otro costo variable, Cargo fijo, Costo de envío), cada uno con su monto en $ sobre `sale_price_for(channel)` y qué % del precio representa — puramente informativo, no participa en ningún cálculo de ganancia (`channel_total_expenses()` sigue siendo la única fuente de verdad del total). Se muestra como tabla debajo del resumen de cada canal en el admin.
  - **Ojo: `ml_price` no se autopropaga a una publicación ya existente** — para que un cambio de `ml_price`/gastos llegue a un ítem ya publicado en Mercado Libre hay que volver a correr la acción *"Publicar/Actualizar en Mercado Libre"* sobre ese producto (o esperar al próximo sync de `presupuestos3d`, que solo republica si cambia `price`, no `ml_price`).

---

## Integración con presupuestos3d (aviso de venta online)

`orders/signals.py::_notify_presupuestos3d()` — cuando una `Order` pasa a `PAID`, le avisa al sistema interno de gestión (`presupuestos3d`, repo aparte, ver `../CLAUDE.md`) para que el dueño la revise y la cargue a mano. Mismo patrón no-bloqueante que `_trigger_bambuddy_print`: gateado por env vars, nunca lanza excepción.

- **A propósito no dispara nada automático del lado de presupuestos3d** (ni `Presupuesto`, ni costeo, ni cola de impresión) — solo crea un registro de solo-alta (`budgets.PedidoOnline`, visible en su admin) con los datos necesarios para cargar el pedido a mano. La decisión de aprobar/producir la toma el dueño.
- `POST {PRESUPUESTOS3D_API_URL}/api/pedidos-online/` con `Authorization: Token {PRESUPUESTOS3D_API_TOKEN}` (DRF Token de un usuario staff creado especialmente para esta integración en presupuestos3d). Payload: `external_reference`, `brand_slug`/`brand_name`, `customer_email`, `items` (snapshot `product_name`/`quantity`/`unit_price`), `total_amount`, `currency`, `order_created_at`, `raw_payload`.
- **Idempotente** por `external_reference` del lado de presupuestos3d: un reintento no duplica el aviso.
- Vacío `PRESUPUESTOS3D_API_URL`/`PRESUPUESTOS3D_API_TOKEN` en `.env` = integración apagada, no rompe nada (mismo criterio que BamBuddy/Meta/Google). **Activa en producción desde 2026-10-08**: Railway (servicio `web`) tiene ambas vars seteadas + token del usuario staff `integracion_3darg` en su Postgres de Railway, verificado con un `POST` de prueba real al endpoint (201). **`PRESUPUESTOS3D_API_URL` repuntada el 2026-10-13** de `https://presupuestos3d.vercel.app` a `https://presupuestos3d-web-production.up.railway.app`: presupuestos3d movió su propio servicio web de Vercel a Railway (mismo proyecto que su Postgres, para evitar la latencia cross-region del proxy público) — Vercel sigue activo como respaldo pero ya no es la URL de uso diario del otro lado. Ver `presupuestos3d/CLAUDE.md` → "Deploy en producción" para el detalle completo de esa migración.
- El aviso "por mail" de la misma venta ya lo cubre `_send_owner_notification_email` (manda a `CONTACT_EMAIL`/`<SLUG>_CONTACT_EMAIL`); si la integración con presupuestos3d está configurada, ese mismo mail suma una línea recordando que ya está cargado en su admin.

### Integración inversa: sync de costeo → ecommerce (`POST /api/products/costeo-sync/`)

Dirección opuesta a la de arriba: acá es `presupuestos3d` el que empuja datos hacia `3darg-backend`, no al revés. La invoca `presupuestos3d/config/api_3darg.py::sync_costeo_ecommerce()` cuando se guarda ahí un `Producto` de costeo marcado `es_producto_ecommerce=True` (checkbox en su admin).

> Mecanismo vigente desde la Fase 1 de `ProductVariant`/`CostTemplate` (ver "Modelos clave" arriba). El mecanismo original, por `cutter_size`, quedó reemplazado — se menciona al final solo como trazabilidad histórica.

- **Qué representa el disparador**: ese `Producto` de costeo es un **presupuesto/perfil de costo compartido** por muchos diseños del catálogo (ej: "Cortante mediano", "Shaker grande") — no un producto puntual. Del lado de acá se modela como `CostTemplate`: un perfil de precio/medidas al que se vinculan muchas `ProductVariant`, sin importar marca, categoría o diseño.
- **`CosteoSyncAPIView`** (`products/views.py`): recibe `external_ref` (obligatorio — referencia estable del `Producto` de costeo, ej. `"presupuestos3d:42"`; **no** el nombre, que puede cambiar), `nombre` (obligatorio, se refresca en cada sync) y `sale_price` (obligatorio), más `weight_kg`/`length_cm`/`width_cm`/`height_cm` opcionales (si no vienen, no se tocan — no se asume "falta = borrar"). Hace **upsert de un `CostTemplate` por `external_ref`** y propaga el precio/medidas nuevos a TODAS las `ProductVariant` ya vinculadas a ese template.
- **El vínculo variante↔template es manual, una sola vez por variante**: se arma desde el admin de `ProductVariant` (acción *"Asignar template de costo a las variantes seleccionadas"*, ver "Modelos clave" arriba). Si el `CostTemplate` recién se creó (primer sync de un presupuesto nuevo) y todavía no tiene ninguna variante vinculada, la vista devuelve `actualizados: 0` — es esperable, no un error.
- **A propósito NO toca `category`/`sku`/`ml_category_id`** de ningún `Product` — esos son del diseño puntual, no del template compartido; pisarlos en bloque rompería el catálogo. Tampoco crea `Product`/`ProductVariant` nuevos: solo actualiza las variantes que ya están vinculadas.
- **Espejo a `Product` (mientras dure la Fase 1)**: cada `ProductVariant` corresponde 1:1 a un `Product`, y nada del checkout/Mercado Libre/el feed lee `ProductVariant` todavía — por eso la vista actualiza la variante Y el `Product` subyacente en el mismo golpe, para que el precio tenga efecto real hoy mismo. Cuando el catálogo tenga variantes de verdad (fases siguientes), este espejo deja de hacer falta.
- **Republica en Mercado Libre automáticamente**: para cada `Product` afectado con `is_available_ml=True`, corre `sync_product()` después de propagar el precio, para que el precio/medidas nuevos lleguen a la publicación real sin acción manual. Los errores de un producto puntual (ej: le faltan fotos, o falta configurar `ML_CLIENT_ID`/`ML_CLIENT_SECRET`) no frenan al resto del lote — se devuelven en `ml_errores` junto con la respuesta (`{"actualizados", "ml_republicados", "ml_errores"}`).
- **Auth**: `TokenAuthentication` + `IsAdminUser`, con el token del usuario staff dedicado `integracion_presupuestos3d` (mismo patrón que la integración de arriba, pero en sentido inverso — token generado acá, usado por `presupuestos3d`). Requiere `rest_framework.authtoken` en `INSTALLED_APPS` (agregado específicamente para esto; el resto del backend usa `JWTAuthentication`).
- Del lado de `presupuestos3d`: vacío `API_3DARG_URL`/`API_3DARG_TOKEN` = integración apagada, nunca rompe el guardado del `Producto` (mismo criterio "vacío = apagado" de siempre). Ver `presupuestos3d/CLAUDE.md` para el detalle del lado emisor (campos del modelo, feedback en el admin).
- **Trazabilidad del mecanismo viejo**: antes de esta fase, `CosteoSyncAPIView` recibía `cutter_size` (`Product.CutterSize`) y hacía `Product.objects.filter(cutter_size=...).update(...)` en bloque — agrupaba por un enum fijo de 5 tamaños en vez de por template libre. La migración `0034_crear_productvariant_y_costtemplate` creó un `CostTemplate` por cada `cutter_size` en uso (`legacy_cutter_size`) para no perder esa agrupación histórica al migrar.

---

## Envíos — Correo Argentino directo (API MiCorreo), sucursal Y domicilio

Se descartó **Envíopack** (agregador, trámite comercial nunca se destrabó) a favor de una integración **directa** con la API real de Correo Argentino (**API MiCorreo**, cuenta del dueño en el panel de MiCorreo, `customerId` propio). **Andreani se reemplazó por completo** — el dueño recibió de Andreani un pedido de reunión comercial (CUIT, volumen mensual, logística actual, etc.) para dar de alta la cuenta, y en cambio se optó por consolidar todo en un solo courier: Correo Argentino cubre **las dos modalidades de entrega** (sucursal y domicilio).

> Ojo si leés historial de git/commits viejos de esta sección: la primera integración se escribió contra una API asumida ("PaqAr v2", `Apikey`/`agreement`, `create_order()`/`get_labels()`/`cancel_order()`) que **no es la API real** — se reescribió de punta a punta contra el PDF oficial "Correo Argentino - API MiCorreo" y el panel real del dueño. Lo que sigue describe la versión real, vigente.

El carrito deja elegir entre **"Retirar en sucursal"** (default, desplegado) y **"Envío a domicilio"**, las dos con Correo Argentino.

- **Auth** (`shipping/services/correo_argentino.py`): `POST /token` con HTTP Basic (`CORREO_ARGENTINO_USER`/`CORREO_ARGENTINO_PASSWORD`) devuelve un JWT de corta duración. `_get_token()` lo cachea en memoria (thread-safe, `threading.Lock()`, mismo patrón que ya usa la integración de Mercado Libre para su `access_token`) y lo renueva solo cuando está por vencer — no pide un token nuevo en cada request.
- **Cotización** (`shipping/services/quote.py::get_quotes()`): intenta primero cotización **EN VIVO** contra `POST /rates` (`correo_argentino.py::get_rates()`) cuando se conoce el código postal de destino y hay credenciales cargadas. Si no — sin CP, sin credenciales, o falla la consulta — cae a la tabla estática de respaldo (`tariff.py::correo_argentino_fallback_price()`), por cada modalidad por separado: nunca deja una modalidad sin cotizar. `payments/views.py::MercadoPagoCheckoutProCreateAPIView` llama a `get_quotes()` SIEMPRE que no aplique el umbral de envío gratis. Si viene `shipping_method_id` (del selector del carrito) matchea contra `select_methods()`; si no matchea nada, cae al más barato (`cheapest_price()`).
  - **El CP de destino que dispara la cotización en vivo sale distinto según la modalidad, resuelto del lado del frontend** (`effectivePostalCode` en `ecommerce-frontend/components/shipping-estimator.tsx`, ver su `CLAUDE.md`): para domicilio, el CP que tipea el comprador; para sucursal, el CP de la agencia elegida (ya viene en la respuesta de `GET /agencies`) — ninguna de las dos modalidades le pide un CP aparte al comprador. **Hasta 2026-10-21 el carrito nunca mandaba `postal_code` en ninguna modalidad**, así que el preview del carrito (y, en la práctica, también el cobro real en varios casos) caía siempre a la tabla de respaldo — que cobra el mismo monto en las dos modalidades por diseño (ver `tariff.py` abajo), lo que se vio como un precio llamativamente alto e idéntico entre "sucursal" y "domicilio" en producción. El backend no cambió nada para este fix — ya soportaba `postal_code` opcional en `ShippingCalculateSerializer`; el bug era 100% de wiring en el frontend.
  - `tariff.py::correo_argentino_fallback_price()`: tabla de tramos por peso facturable (hasta 1/5/10/15/20/25 kg, columna "Nacional" del tarifario real de Correo Clásica) + cargo por "Valor Declarado" sobre el subtotal del carrito (`CORREO_ARGENTINO_TARIFF_JSON`/`CORREO_ARGENTINO_VALOR_DECLARADO_JSON`, configurables sin tocar código). Usa divisor volumétrico **6000** (no 5000, el del resto) — `calculate_billable_weight(items, divisor=...)` quedó parametrizado en `shipping/services/volumetric.py`.
  - `select_methods()` siempre devuelve las dos entradas (`correoargentino_sucursal` y `correoargentino_domicilio`), cada una con su propio `is_fallback` según si esa modalidad puntual se resolvió con `/rates` en vivo o con la tabla de respaldo.
- **Dirección del comprador — distinta según la modalidad** (la API real NO exige dirección completa para sucursal, a diferencia de lo que asumía la integración vieja): `payments/views.py` valida distinto por modalidad:
  - **sucursal**: solo `full_name` + `phone` + `province` + `agency_id` (elegido de `GET /api/shipping/agencies/`) — `correo_argentino.py::_build_shipment_payload()` manda `shipping.agency = order.shipping_agency_id`, sin armar ninguna dirección aproximada.
  - **domicilio**: `full_name` + `phone` + `street` + `street_number` + `city` + `province` (dirección real del comprador, sin `agency_id`) — `_build_shipment_payload()` manda `shipping.address` con esos campos.
  - Se persiste en `Order` (`shipping_full_name`/`shipping_phone`/`shipping_street`/`shipping_street_number`/`shipping_floor`/`shipping_department`/`shipping_city`/`shipping_province`/`shipping_agency_id`).
- **Catálogo de provincias**: `shipping/services/postal.py::AR_PROVINCES` (24 provincias, código ISO 3166-2:AR de una letra) — espejo exacto de `ecommerce-frontend/types/shipping.ts::AR_PROVINCES`, no tocar uno sin el otro.
- **Sucursales reales**: `GET /api/shipping/agencies/?province=<code>` (`AgenciesListAPIView`) → `correo_argentino.py::list_agencies(province_code)` → `GET /agencies` de la API real (respuesta anidada: `code`, `name`, `services.pickupAvailability`, `location.address.{streetName,streetNumber,city,...}`, ver el tipo `Agency` en `shipping-estimator.tsx`). Solo tiene sentido para la modalidad sucursal. Sin credenciales cargadas devuelve `[]` sin romper (mismo criterio "vacío = apagado" de siempre).
- **Alta real del envío** (`correo_argentino.py::create_shipment(order)`): `POST /shipping/import`, usa `order.external_reference` como `extOrderId` (idempotente ante reintentos — la API responde "La orden ya fue importada con anterioridad" si se repite, no es un error real). **La respuesta real de éxito es solo `{"createdAt": ...}` — no devuelve ningún tracking number.** Por eso `correo_argentino_tracking_number` (nombre de campo heredado, no se migra) en realidad guarda nuestro propio `extOrderId` (= `order.external_reference`), que es el identificador real que tiene Correo Argentino de ese envío — no lo uses para buscarlo en el panel de MiCorreo salvo que confirmes que ahí también se indexa por `extOrderId`.
- **No hay endpoint de generación de etiquetas ni de cancelación en la API real** (a diferencia de lo que asumía la integración vieja) — no hay nada que llamar para esos dos casos:
  - `orders/signals.py::_cancel_correo_argentino_shipment()`: si el pedido pasa `PAID → REJECTED/CANCELLED` y ya tenía un envío dado de alta, solo **loguea un warning** para que el dueño lo cancele a mano desde el panel de MiCorreo.
  - No existe acción de admin "Generar etiqueta" (se eliminó, junto a su template).
- **Tracking**: `correo_argentino.py::get_tracking(shipping_id)` → `GET /shipping/tracking` (toma un solo `shippingId` por llamada, pese al verbo GET el filtro va en el body — confirmado en la doc). El admin (`orders/admin.py::consultar_tracking_correo_argentino`) lo llama una vez por orden seleccionada, no en batch.
- **Alta en el signal** (`orders/signals.py::_create_correo_argentino_shipment`): al confirmarse el pago (`PAID`), si `order.shipping_method == "correoargentino"` (cualquiera de las dos modalidades) se llama `create_shipment(order)` en try/except no bloqueante — guarda `correo_argentino_tracking_number = order.external_reference` en éxito, o el mensaje en `correo_argentino_sync_error` si falla (nunca rompe la confirmación de pago ni el mail de confirmación).
- **Admin** (`orders/admin.py`): ficha de `Order` muestra todos los campos de dirección + `correo_argentino_tracking_number`/`correo_argentino_sync_error`. Acciones: *"Reintentar alta en Correo Argentino"* y *"Consultar estado de envío en Correo Argentino"* — no hay "Generar etiqueta" (no existe ese endpoint).
- **Vacío `CORREO_ARGENTINO_USER`/`CORREO_ARGENTINO_PASSWORD`/`CORREO_ARGENTINO_CUSTOMER_ID` = alta real/`agencies`/`rates` en vivo apagados** (mismo criterio de siempre) — hoy están cargados (ver abajo), así que esto describe solo el comportamiento si algún día se vacían: la cotización no se cae, sigue funcionando vía la tabla de respaldo, solo que sin `/rates` en vivo.

### Estado actual: integración completa y probada en vivo (2026-10-21) — `/token`, `/agencies` y `/rates` funcionando de punta a punta

Credenciales de **API** reales cargadas (`CORREO_ARGENTINO_USER=LToledoAPI`, distintas del login del panel de MiCorreo que daba 401) con `CORREO_ARGENTINO_TEST_MODE=0`. **Son credenciales de PRODUCCIÓN, no de test** — el JWT que devuelve `POST /token` trae el claim `"member of": "ApiMiCorreoProd"`, y contra `apitest.correoargentino.com.ar` el `customerId` real (`0002005182`) no existe (`/agencies` devolvía `200 []`, sin error). El dueño avisó después que, según le dijeron, las credenciales valdrían para los dos ambientes — no se volvió a probar `apitest.*` tras cargar la dirección de remitente porque el ambiente de producción ya da datos reales confirmados y es el que corresponde usar de todos modos.

Se completaron también los datos de **remitente** (dirección real de despacho del dueño, la misma que usó para darse de alta en MiCorreo: Santa Rosa 828, Córdoba Capital, CP 5000) en `CORREO_ARGENTINO_SENDER_*` — probado en vivo que `/rates` acepta tanto CP numérico de 4 dígitos como CPA alfanumérico completo (`X5000ESR`) para `postalCodeOrigin`/`postalCodeDestination`; se usa el formato numérico de 4 dígitos por consistencia con `shipping/services/postal.py`. El piso/depto ("4") no tiene campo en `sender.originAddress` de la API, queda fuera a propósito (no afecta cotización ni alta de envío). **Solo se ofrece el servicio Clásico** (`CORREO_ARGENTINO_PRODUCT_TYPE=CP`, decisión explícita del dueño) — ya era el default, sin cambios de código.

Probado en vivo contra la API real (2026-10-21):
- `POST /token` → OK, token válido.
- `GET /agencies` → OK, datos reales (307 sucursales en CABA, 1326 en Buenos Aires, 388 en Córdoba — forma de dato confirmada igual a la documentada).
- `POST /rates` (probado directo) → OK, devuelve `rates[]` real con 4 entradas (CP/EP × sucursal/domicilio) — **se encontró y corrigió un bug real**: el matching de `quote.py` solo filtraba por `deliveredType`, no por `productType`, así que podía quedar a merced del orden de la respuesta y cotizar "Correo Argentino Expreso" (más caro) en vez de "Clásico" — ya filtra por los dos campos.
- `quote.py::get_quotes()` (el camino real del checkout) y `POST /api/shipping/calculate/` (el endpoint HTTP que llama el frontend) → **confirmado cotizando en vivo de punta a punta**, las dos modalidades con `is_fallback: false` (ej. CP 1000 desde origen CP 5000: sucursal $6480, domicilio $9492). `GET /api/shipping/agencies/?province=X` también confirmado con sucursales reales de Córdoba.
- **`SHIPPING_TEMP_FIXED_RATES_JSON` vaciado** (`{}` en `.env`) ahora que la cotización en vivo está confirmada — si alguna vez falla `/rates` (sin red, token sin renovar, etc.), el fallback real pasa a ser la tabla de `CORREO_ARGENTINO_TARIFF_JSON`/`tariff.py`, no un monto fijo arbitrario.
- **No se probó `POST /shipping/import`** (alta real de un envío) porque es la única llamada no idempotente/con efecto real fuera de nuestro sistema — se prueba con un pedido real pagado, no con datos sintéticos.

**Pendiente, no bloquea nada**: replicar `CORREO_ARGENTINO_*` (incluidos los `SENDER_*` y `SHIPPING_TEMP_FIXED_RATES_JSON={}`) en Railway (prod) — hoy solo están en el `.env` de dev.

**Fix de wiring en el carrito real (2026-10-21)**: la cotización en vivo de arriba estaba probada y funcionando contra la API directa (`quote.py`/`/api/shipping/calculate/` llamados a mano), pero el carrito real (`ShippingEstimator`) todavía no mandaba ningún `postal_code` en ninguna modalidad — por eso el comprador veía siempre el precio de la tabla de respaldo, idéntico en sucursal y domicilio. Ya corregido del lado del frontend (`effectivePostalCode`, ver `ecommerce-frontend/CLAUDE.md` → "Selector de método de envío") — sin cambios de este lado, el carrito ahora cotiza en vivo en las dos modalidades apenas se conoce un CP real de destino.

**Andreani queda completamente fuera del selector del carrito** — no hay plan de volver a integrarlo salvo que el dueño decida lo contrario más adelante (su código sigue recuperable del historial de git si hiciera falta).

---

## Deploy en producción

**En producción real (2026-10-08): Railway, no el VPS.** El **frontend va a Vercel** (`ecommerce-frontend`, fuera de este repo, dominio `3darg.com`/`www.3darg.com`). Este backend corre en **Railway**:

- Proyecto Railway `3darg-backend`, servicio `web` conectado por git a `maxinunezz/3darg-backend` rama `main` (autodeploy en cada push), builder `DOCKERFILE`. Servicio `Postgres` (template `postgres-ssl:18`) en el mismo proyecto — las env vars de Django apuntan a él vía referencias (`${{Postgres.POSTGRES_DB}}`, etc.), sin red pública expuesta (conexión interna `postgres.railway.internal`).
- Dominio propio `api.3darg.com` (CNAME hacia el target `*.up.railway.app` que da Railway, gestionado desde la pestaña DNS de Vercel Domains porque `3darg.com` usa nameservers de Vercel). `DJANGO_ALLOWED_HOSTS=api.3darg.com`, `CORS_ALLOWED_ORIGINS`/`CSRF_TRUSTED_ORIGINS=https://3darg.com,https://www.3darg.com`, `FRONTEND_BASE_URL=https://3darg.com`, `MP_NOTIFICATION_URL=https://api.3darg.com/api/payments/mp/webhook/` — ya seteadas en Railway (no son el placeholder que describía esta sección antes).
- Media: Cloudinary (`django-cloudinary-storage`, `CLOUDINARY_URL` en Railway) — las imágenes no viven en un volumen local, sobreviven a cualquier redeploy.
- Deploy manual puntual desde el repo local: `railway up --service web --ci --yes` (ojo: `railway service redeploy` **no** trae el último commit de git, hay que usar `up --ci`). El flujo normal es simplemente `git push` a `main`.

**`deploy/` (VPS + Caddy) quedó abandonado, nunca se usó en producción** — se preparó un stack alternativo (`docker-compose.prod.yml` con `db`+`web`+`caddy`, `backup-db.sh`/`backup-media.sh`/`reconcile-cron.sh` por cron) pero nunca se ejecutó: sin backups reales, sin DNS propio, dominio placeholder. Se decidió Railway en su lugar porque da Postgres gestionado + HTTPS automático + deploy por git push sin mantener VPS/Caddy/cron a mano. La carpeta se deja de referencia por si se reconsidera algún día, pero no reflejes este `deploy/` como el mecanismo real si te preguntan cómo se despliega.

### Monitoreo de errores (Sentry)

`config/settings.py` inicializa `sentry_sdk` (paquete `sentry-sdk[django]` en `requirements.txt`) al arrancar, **solo si `SENTRY_DSN` está cargado** en el `.env`/Railway — mismo criterio "vacío = apagado" que el resto de las integraciones (Meta, Google OAuth, BamBuddy, etc.). **Ya está activo en producción** (Railway tiene `SENTRY_DSN`/`SENTRY_TRACES_SAMPLE_RATE`/`SENTRY_PROFILE_SAMPLE_RATE` seteadas).

- `send_default_pii=True` y `enable_logs=True`: Sentry recibe datos de request/usuario y los logs de Django, no solo excepciones no manejadas.
- `environment` se resuelve solo (`"development"` si `DJANGO_DEBUG=1`, si no `"production"`) — no hace falta setearlo a mano.
- `traces_sample_rate`/`profile_session_sample_rate` (tracing de performance) son configurables por env var, default `1.0` (100%) los dos — revisar si conviene bajarlos cuando haya volumen real de tráfico, hoy está así porque el proyecto es chico.
- El **frontend (`ecommerce-frontend`) tiene su propia integración de Sentry, independiente de esta** (`sentry.server.config.ts`, `sentry.edge.config.ts`, `instrumentation-client.ts`, `app/global-error.tsx`, env vars `SENTRY_DSN`/`NEXT_PUBLIC_SENTRY_DSN` en Vercel) — dos proyectos de Sentry separados, uno por servicio, sin relación de código entre sí.

---

## Auth (JWT)

- DRF default: `IsAuthenticatedOrReadOnly`. Las vistas que necesitan auth lo declaran explícito (`permissions.IsAuthenticated`).
- Las vistas de pagos y contacto declaran `AllowAny` porque pueden invocarse sin sesión.
- JWT: `ACCESS_TOKEN_LIFETIME=2h`, `REFRESH_TOKEN_LIFETIME=7d`, `ROTATE_REFRESH_TOKENS=True`.
- Throttling: anónimos `10000/day`, usuarios `50000/day`. `contact` aplica un throttle adicional de `5/hour` por IP.
- CORS: `http://localhost:3000` en dev; en producción (Railway) `CORS_ALLOWED_ORIGINS=https://3darg.com,https://www.3darg.com`. CSRF acepta `*.ngrok-free.app` para los webhooks de MP en desarrollo; en prod, `https://3darg.com,https://www.3darg.com`.

### Login con Google (`POST /api/users/google/`)

- `AllowAny`. Recibe `{id_token, brand_slug?}`, verifica el token con `google.oauth2.id_token.verify_oauth2_token()` contra `settings.GOOGLE_OAUTH_CLIENT_ID` y exige `email_verified`.
- `GoogleAuthSerializer` (`users/serializers.py`) hace **get_or_create por email** — mismo `User` unificado usado en todo el Grupo, no crea identidades separadas por marca. Si es un alta nueva: genera `username` único desde el email (`_generate_username`) y setea `registered_brand` con el `brand_slug` recibido (igual que `RegisterSerializer`).
- Devuelve el mismo shape `{access, refresh}` que `/api/auth/token/` — el frontend no necesita lógica de sesión distinta.
- Sin `GOOGLE_OAUTH_CLIENT_ID` configurado, el endpoint responde 400 con mensaje claro. Es el mecanismo por el que la feature queda "apagada" hasta configurar Google Cloud Console.

---

## Flujo de pagos (MercadoPago Checkout Pro)

1. **`POST /api/payments/mp/checkout-pro/`** (`AllowAny`, transacción atómica):
   - Valida `brand_slug`, que el brand no sea `services`, que cada producto exista, esté disponible y tenga stock.
   - Crea `Order` en `PENDING` con `external_reference = uuid.uuid4().hex` y `OrderItem`s.
   - Llama a `services.mercadopago.create_preference()` con `back_urls` apuntando a `FRONTEND_BASE_URL/checkout/{success|failure|pending}/?order_id=<uuid>&brand=<slug>` — el `brand` es necesario porque esas páginas viven en la ruta raíz del frontend (compartidas por todas las marcas) y lo usan para saber a qué espacio de marca volver y qué carrito limpiar (ver `ecommerce-frontend/CLAUDE.md` → "Selector de forma de pago").
   - Guarda `MercadoPagoPayment` y devuelve `init_point` (sandbox o real) al frontend.

2. **`POST /api/payments/mp/webhook/`** (sin auth, lo invoca MP):
   - Filtra topics: `payment`, `opened_dispute`, `dispute`. El resto se ignora con 200.
   - **Valida firma HMAC** con `MP_WEBHOOK_SECRET` (`is_valid_webhook_signature`). Sin firma válida → 403.
   - Consulta el pago a MP, matchea por `external_reference`, actualiza `Order.status` (`approved → PAID`, `rejected|cancelled → REJECTED`).
   - **Idempotente**: si el `mp_payment_id` + `status` ya están guardados, devuelve 200 sin hacer nada.

3. **`orders/signals.py`** (post-save de `Order`): cuando el status pasa a `PAID`:
   - **Descuenta stock** de cada producto con `select_for_update()` (atomic).
   - **Manda email** de confirmación a `customer_email`.
   - **Manda email** al dueño (`_send_owner_notification_email`) y **avisa a presupuestos3d** (`_notify_presupuestos3d`) — ver sección dedicada más abajo.
   - Si vuelve de `PAID → REJECTED|CANCELLED`, **restituye stock**.
   - El status se cachea en `pre_save` (`instance._old_status`) para detectar el cambio.

> Si tocás `orders.Order.status`, **el signal corre**. No descontar stock manualmente desde otro lado.

---

## Flujo de pagos — Transferencia bancaria ("Opción 1")

Canal alternativo a MercadoPago, pensado para compradores que no quieren pagar
con tarjeta/MP: transfieren a mano a una cuenta real del Grupo y el dueño
confirma el ingreso desde el admin — **no hay ninguna API de banco de por
medio**. Una sola cuenta para **todo el Grupo** (no es por marca, a diferencia
de `Brand.transfer_discount_percent`, que sí lo es). Mismo criterio stock que
MercadoPago: nunca se descuenta mientras el pedido está `PENDING`, solo al
pasar a `PAID`.

1. **`GET /api/payments/transfer/availability/`** (`AllowAny`): le dice al
   frontend si el canal existe hoy — `{"available": bool}`, sin exponer alias/CBU
   (esos solo se devuelven al confirmarse el checkout). El selector de forma de
   pago del carrito lo consulta antes de mostrar la opción "Transferencia".

2. **`POST /api/payments/transfer/checkout/`** (`AllowAny`, transacción
   atómica, mismo `CheckoutThrottle` que MercadoPago, mismo body que
   `/mp/checkout-pro/` — `TransferCheckoutCreateSerializer` es un subclase
   vacía de `CheckoutProCreateSerializer`):
   - **"Vacío = apagado"**: si faltan `TRANSFER_BANK_ALIAS`/`TRANSFER_BANK_CBU`
     en el `.env`, responde 400 ("no disponible todavía") antes de tocar la DB.
   - Valida brand/productos/stock igual que MercadoPago, crea `Order` en
     `PENDING` con `payment_channel = TRANSFER` y `external_reference` propio.
   - Aplica `payments/services/transfer_discount.py::apply_transfer_discount()`
     sobre el `total` que ya salió de `compute_cart_pricing()` (orden de
     operaciones: precio de lista/socio → descuento por cantidad del carrito →
     **descuento por transferencia** → + envío = total a cobrar; el umbral de
     envío gratis se evalúa ANTES de este descuento, a propósito).
   - Manda `send_transfer_instructions_email()` (al comprador, con alias/CBU/
     referencia) y `send_transfer_pending_owner_email()` (al dueño, para que
     sepa que hay un ingreso esperado).
   - Devuelve `order_id`, `reference` (código corto para que el comprador lo
     ponga en el concepto de la transferencia, ver `reference_code()` en
     `payments/services/transfer_notifications.py`), `total_amount`,
     `transfer_discount_percent`, `expires_in_hours`, y los datos de banco.

3. **`POST /api/payments/orders/<uuid>/reconcile/`** (ya existente, extendido):
   para un pedido `TRANSFER` suma `payment_channel`, `reference`, `bank`,
   `transfer_discount_percent`, `expires_in_hours`, `created_at` a la
   respuesta — permite que la página de instrucciones del frontend
   (`/checkout/transfer`) sea recargable sin perder esos datos, incluso sin
   sesión. Para este canal `reconcile_order()` nunca encuentra un pago de MP
   que concilie (no existe ninguno), así que es un no-op seguro: solo
   devuelve el estado actual del pedido.

4. **`orders/admin.py` → acción "Confirmar transferencia recibida"**
   (`confirmar_transferencia_recibida`): el dueño la ejecuta a mano sobre uno o
   varios pedidos `PENDING` de canal `TRANSFER` tras revisar el movimiento en
   el banco. Pasa `Order.status = PAID`, lo que dispara el mismo signal de
   `orders/signals.py` que usa MercadoPago (descuenta stock, manda emails,
   avisa a presupuestos3d/Meta CAPI) — no duplica esa lógica.

5. **`python manage.py expire_pending_transfers`** (pensado para cron, cada
   hora): cancela pedidos `TRANSFER` que quedaron `PENDING` más de
   `TRANSFER_PENDING_EXPIRATION_HOURS` (default 48) sin confirmación — no hay
   un campo `expires_at`, se calcula siempre contra `created_at`. No restituye
   stock (nunca se descontó en `PENDING`), solo evita que el panel se llene de
   pedidos zombies.

**Env vars** (`.env`, "vacío = apagado" — sin esto el canal no aparece como
disponible, pero el resto del sitio sigue funcionando):
```
TRANSFER_BANK_ALIAS=
TRANSFER_BANK_CBU=
TRANSFER_BANK_HOLDER_NAME=
TRANSFER_BANK_CUIT=
TRANSFER_PENDING_EXPIRATION_HOURS=48
```

---

## Brand scoping en el backend

Para `users.Favorite` y `orders.Order` el backend **sigue sin imponer silos por marca a nivel de queryset** — devuelve toda la data del usuario, y el filtrado por marca (incluida 3DARG, que ya NO ve todo) lo hace el frontend. Eso significa:

- `GET /api/users/favorites/` → **todos** los favoritos del usuario, sin filtrar.
- `GET /api/orders/` → **todas** las órdenes del usuario, sin filtrar.
- Los serializers de `Product` y `Order` exponen `brand` como **slug** (no ID) precisamente para que el frontend pueda filtrar con `.filter(p => p.brand === brandSlug)`. `/(main)/profile` filtra por `brand === "3darg" || brand == null` (igual criterio que `/[brand]/profile`, aplicado a la marca raíz).

Donde sí hay scoping en backend:
- `/api/products/?brand_slug=lumy` filtra por marca a nivel queryset.
- Checkout exige `brand_slug` y valida que los productos pertenezcan a esa marca antes de cobrar.
- **`cart` sí es un silo real en el backend** (a diferencia de favorites/orders): `Cart` es `unique_together(user, brand)` y todos sus endpoints exigen `brand_slug` — no hay forma de pedir "el carrito sin especificar marca". Ver `cart.Cart` arriba.

---

## Estáticos (admin de Django)

`whitenoise` sirve los estáticos detrás de gunicorn. `start-server.sh` corre `collectstatic --noinput` al arrancar.

Si el admin se ve sin estilos:
1. Verificar que `WhiteNoiseMiddleware` esté **después** de `SecurityMiddleware` en `settings.MIDDLEWARE`.
2. `STORAGES["staticfiles"]` debe ser `whitenoise.storage.CompressedManifestStaticFilesStorage`.
3. Reiniciar `web` para que se re-ejecute `collectstatic`.

`media/` se monta como volumen (`./3darg-backend/media:/app/media`) — los uploads sobreviven el rebuild del container.

---

## Convenciones

- **Idioma del owner**: respuestas y comentarios en código en español. Strings del usuario final (mails, mensajes de error visibles) también en español.
- **Serialización de FKs públicas** (`brand`, `category`): usar `SlugRelatedField(slug_field="slug")` en vez de IDs. El frontend compara contra slugs.
- **Imágenes**: `ImageField` se serializa como URL absoluta. **No construir URLs manualmente** en serializers — DRF lo hace bien con `request` en contexto. El frontend usa `resolveMediaUrl()` para reescribir `web:8000` → `localhost:8000` cuando hace falta.
- **DELETE devuelve 204 sin body**. No agregar `Response({...})` en `delete()` salvo que haya razón explícita.
- **Cambios de status de Order**: pasan por el signal. No bypass salvo que sepas exactamente qué estás evitando (mails, stock).
- **Transacciones atómicas** en checkout, descuento/restitución de stock y cualquier operación multi-tabla. Usar `@transaction.atomic` o `with transaction.atomic():`.
- **Logging**: usar `logger = logging.getLogger(__name__)` y `logger.info/warning/error`. No `print`. Format definido en `LOGGING` (settings).
- **Migraciones**: una por cambio lógico. Nombrar con `--name` cuando agregás un campo importante.

---

## Cosas a tener en cuenta

- `REDME.md` (sic) en este directorio es un typo histórico. Ignorar o renombrar.
- En producción (Railway): `DJANGO_DEBUG=0` y `CORS_ALLOWED_ORIGINS` ya están seteados — ver sección de Deploy. Pendiente real: SMTP sigue en `console` (Resend preparado pero no activado, ver sección Email arriba), y falta rotar `DJANGO_SECRET_KEY` del valor usado en dev.
- El webhook de MP requiere URL pública. En dev se usa **ngrok** (whitelisteado en `DJANGO_ALLOWED_HOSTS` y `CSRF_TRUSTED_ORIGINS`); en producción es `https://api.3darg.com/api/payments/mp/webhook/` directo.
- `volumes.postgres_data` está marcado como `external: true` en el `docker-compose.yml` de **dev** — el volumen es persistente y no se borra con `docker compose down -v`. En producción no aplica (Postgres es un servicio gestionado de Railway, no un volumen local).
- `Brand.parent` es `on_delete=PROTECT`: no se puede borrar 3DARG si tiene sub-marcas colgando.
