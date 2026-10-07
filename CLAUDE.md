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
```

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
- `ProductImage` con `order`, accedida vía `images` (prefetcheada en list/detail). `channel` (`both|web|ml`) controla dónde se muestra cada foto — las marcadas `ml` quedan afuera de la web/el feed de Google-Meta (`WEB_IMAGES_PREFETCH` en `products/views.py`); `ml_order` permite un orden distinto al de la web en la publicación de Mercado Libre (vacío = mismo orden).
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

Publicación **manual** de productos en Mercado Libre, disparada desde el admin — no es un sync automático ni programado. Es una sola cuenta de vendedor para todo el grupo 3darg (no está scopeada por marca, a diferencia del resto del sistema).

- **Conexión (OAuth2)**: `GET /api/mercadolibre/authorize/` redirige al login de Mercado Libre; `GET /api/mercadolibre/callback/` recibe el `code` y lo canjea por `access_token`/`refresh_token`, guardados en `MLCredentials` (modelo singleton, `MLCredentials.load()`). El `refresh_token` rota en cada uso — `mercadolibre/services.py::_refresh_access_token()` siempre guarda el que vuelve en la respuesta, nunca reusa el anterior. `get_valid_access_token()` lo renueva solo si está por vencer (margen de 5 minutos).
- **Publicar/actualizar**: acción de admin *"Publicar/Actualizar en Mercado Libre"* sobre `Product` (`products/admin.py::publicar_en_mercadolibre`) → `mercadolibre/services.py::sync_product(product)`. Primera vez: `POST /items` y guarda el `ml_item_id` devuelto. Siguientes veces: `PUT /items/{id}` con los mismos datos (precio, stock, fotos). `family_name`, `listing_type_id` y `shipping.dimensions` son inmutables en ML una vez creado el ítem — el `PUT` los excluye a propósito.
- **Pausado/reactivado vía `is_available_ml`**: si el producto tiene `is_available_ml=False`, `sync_product()` no actualiza nada — manda `PUT /items/{id} {"status": "paused"}` y listo (requiere que ya exista `ml_item_id`; si todavía no se publicó nunca, tira `MLSyncError` pidiendo prender el canal antes). Si `is_available_ml=True` y el ítem ya existe, el `PUT` normal fuerza `"status": "active"` además de los datos — así reactiva un ítem que estaba pausado. Ver "Canales de venta por producto" en el modelo `Product` más arriba.
- **Requisitos para poder publicar**: `ml_category_id` cargado en el producto (default `MLA375405` = "Cortantes") y al menos una imagen con `channel` en `both`/`ml`. Sin eso, `MLSyncError` con mensaje en español, mostrado en el admin.
- **Atributos que se mandan**: `BRAND` (fijo "3DARG"), `MODEL` (= `product.sku`, atributo genérico de catálogo) y `SELLER_SKU` (= `product.sku` también, el campo que ML reserva específicamente para el código interno del vendedor — se mandan ambos por compatibilidad, sin tocar `MODEL` por las dudas de que algún listing viejo dependa de él), más `HEIGHT`/`WIDTH`/`DEPTH` si están cargadas las dimensiones (si no, ML marca el ítem `incomplete_technical_specs` y puede quedar en revisión manual).
- **Fotos por canal**: `ProductImage.channel` (`both|web|ml`) permite tener fotos exclusivas de Mercado Libre (ej: con medidas o marca de agua) sin que aparezcan en la web ni en el feed de Google/Meta. `ml_order` permite un orden de fotos distinto al de la web en la publicación.
- **`MLListingTemplate`**: plantilla única (singleton, igual patrón que `MLCredentials`) con el texto fijo de la descripción (`Template.safe_substitute()` con `$modelo`/`$medidas`), editable desde el admin.
- Sin `ML_CLIENT_ID`/`ML_CLIENT_SECRET` configurados en `.env`, cualquier intento de publicar tira `MLSyncError` explicando que falta la config — mismo criterio "vacío = apagado" que el resto de las integraciones.
- **Webhook (`POST /api/mercadolibre/webhook/`)**: ML notifica acá cuando un ítem cambia de estado (pausado, cerrado, eliminado, reactivado), sin depender de que alguien entre al admin a revisar a mano. A diferencia del webhook de MercadoPago, **ML no firma el payload** — por eso `mercadolibre/views.py::webhook()` no confía en el body recibido, solo lo usa para saber qué `item_id` volver a consultar: si `topic == "items"`, extrae el id de `resource` (`/items/{id}`) y llama a `mercadolibre/services.py::handle_item_notification(item_id)`, que pide el ítem de nuevo por API con nuestro propio `access_token` y recién ahí decide. Si el status real ya no es `active`, apaga `is_available_ml` del producto asociado (match por `ml_item_id`); si volvió a estar activo (lo reactivaron directo en ML), lo prende de nuevo. No hace nada si el `item_id` no matchea ningún producto nuestro. Siempre responde 200 (ML reintenta si no, el body de la respuesta no le importa).
  - **Setup manual pendiente** (no automatizable desde acá): registrar esta URL —pública, en dev vía **ngrok**, mismo mecanismo que `MP_NOTIFICATION_URL`— en el panel de la app en Mercado Libre Developers → Notificaciones, suscripta al menos al tópico `items`.
- **No hay conexión con `presupuestos3d`**: el SKU que viaja a Mercado Libre es el mismo `Product.sku` que ya usa el feed de Google/Meta, pero no hay ningún sync automático entre esta app y el sistema interno de costeo — si corresponde, se carga a mano ahí (ver `presupuestos3d/CLAUDE.md`, campo `Producto.sku`).

---

## Integración con presupuestos3d (aviso de venta online)

`orders/signals.py::_notify_presupuestos3d()` — cuando una `Order` pasa a `PAID`, le avisa al sistema interno de gestión (`presupuestos3d`, repo aparte, ver `../CLAUDE.md`) para que el dueño la revise y la cargue a mano. Mismo patrón no-bloqueante que `_trigger_bambuddy_print`: gateado por env vars, nunca lanza excepción.

- **A propósito no dispara nada automático del lado de presupuestos3d** (ni `Presupuesto`, ni costeo, ni cola de impresión) — solo crea un registro de solo-alta (`budgets.PedidoOnline`, visible en su admin) con los datos necesarios para cargar el pedido a mano. La decisión de aprobar/producir la toma el dueño.
- `POST {PRESUPUESTOS3D_API_URL}/api/pedidos-online/` con `Authorization: Token {PRESUPUESTOS3D_API_TOKEN}` (DRF Token de un usuario staff creado especialmente para esta integración en presupuestos3d). Payload: `external_reference`, `brand_slug`/`brand_name`, `customer_email`, `items` (snapshot `product_name`/`quantity`/`unit_price`), `total_amount`, `currency`, `order_created_at`, `raw_payload`.
- **Idempotente** por `external_reference` del lado de presupuestos3d: un reintento no duplica el aviso.
- Vacío `PRESUPUESTOS3D_API_URL`/`PRESUPUESTOS3D_API_TOKEN` en `.env` = integración apagada, no rompe nada (mismo criterio que BamBuddy/Meta/Google).
- El aviso "por mail" de la misma venta ya lo cubre `_send_owner_notification_email` (manda a `CONTACT_EMAIL`/`<SLUG>_CONTACT_EMAIL`); si la integración con presupuestos3d está configurada, ese mismo mail suma una línea recordando que ya está cargado en su admin.

---

## Deploy en producción (`deploy/`)

El **frontend va a Vercel** (fuera de este repo). Este backend se despliega en un **VPS propio** con su propio stack, separado del `docker-compose.yml` de desarrollo:

- `deploy/docker-compose.prod.yml`: `db` (Postgres 16) + `web` (build de este repo, código empaquetado en la imagen — **no** bind mount como en dev) + `caddy` (HTTPS automático + reverse proxy + sirve `media/` directo).
- `deploy/Caddyfile`: config del reverse proxy/TLS.
- `deploy/deploy.sh`: script de despliegue.
- `deploy/backup-db.sh` (pg_dump diario), `deploy/backup-media.sh` (tar.gz diario de `media/` — las imágenes de producto), `deploy/reconcile-cron.sh`: mantenimiento programado por cron (instalado por `deploy.sh`; ambos backups van a `deploy/backups/` con retención de 14 días). Guardan **en el mismo VPS** — para estar cubierto ante una falla de disco, copiar `deploy/backups/` periódicamente a otro lado (scp, S3, Backblaze).
- Se corre desde `deploy/` (contexto de build `..`, o sea la raíz de este repo): `docker compose -f docker-compose.prod.yml up -d --build`.
- Volúmenes persistentes: `postgres_data`, `caddy_data`, `caddy_config` — **no** `external: true` acá (a diferencia del compose de dev), porque en el VPS arrancan vacíos.

---

## Auth (JWT)

- DRF default: `IsAuthenticatedOrReadOnly`. Las vistas que necesitan auth lo declaran explícito (`permissions.IsAuthenticated`).
- Las vistas de pagos y contacto declaran `AllowAny` porque pueden invocarse sin sesión.
- JWT: `ACCESS_TOKEN_LIFETIME=2h`, `REFRESH_TOKEN_LIFETIME=7d`, `ROTATE_REFRESH_TOKENS=True`.
- Throttling: anónimos `10000/day`, usuarios `50000/day`. `contact` aplica un throttle adicional de `5/hour` por IP.
- CORS: solo `http://localhost:3000` (cambiar en prod). CSRF acepta `*.ngrok-free.app` para los webhooks de MP en desarrollo.

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
   - Llama a `services.mercadopago.create_preference()` con `back_urls` apuntando a `FRONTEND_BASE_URL/checkout/{success|failure|pending}/?order_id=<uuid>`.
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
- En producción: `DJANGO_DEBUG=0`, rotar `DJANGO_SECRET_KEY`, ajustar `CORS_ALLOWED_ORIGINS`, configurar SMTP real (default es `console`).
- El webhook de MP requiere URL pública. En dev se usa **ngrok** (whitelisteado en `DJANGO_ALLOWED_HOSTS` y `CSRF_TRUSTED_ORIGINS`).
- `volumes.postgres_data` está marcado como `external: true` en `docker-compose.yml` — el volumen es persistente y no se borra con `docker compose down -v`.
- `Brand.parent` es `on_delete=PROTECT`: no se puede borrar 3DARG si tiene sub-marcas colgando.
