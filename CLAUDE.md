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

EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend   # default: console
EMAIL_HOST=smtp.gmail.com  EMAIL_PORT=587
EMAIL_HOST_USER=...  EMAIL_HOST_PASSWORD=...
DEFAULT_FROM_EMAIL="3DARG <noreply@3darg.com>"
CONTACT_EMAIL=3darg1@gmail.com
TELEGRAM_URL=https://t.me/3darg

MP_ACCESS_TOKEN=...             # MercadoPago — sin esto los pagos rompen
MP_WEBHOOK_SECRET=...           # firma HMAC del webhook
MP_NOTIFICATION_URL=https://<ngrok>/api/payments/mp/webhook/
MP_CURRENCY=ARS
FRONTEND_BASE_URL=http://localhost:3000   # usado para back_urls de MP

GOOGLE_OAUTH_CLIENT_ID=...      # Client ID de Google Cloud Console (login "Continuar con Google")
                                 # Vacío = /api/users/google/ responde 400 explicando que falta config
```

El mismo `.env` es leído por los servicios `db` y `web` en `docker-compose.yml`.

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
| `cart` | `/api/cart/` | `GET\|DELETE /`, `POST /items/`, `PATCH\|DELETE /items/<id>/` — **todo requiere auth** |
| `orders` | `/api/orders/` | `GET /` (lista del usuario, filtrable por `?status=`), `GET /<uuid>/`, `GET /summary/` (totales + counts por status) |
| `payments` | `/api/payments/` | `POST /mp/checkout-pro/`, `POST /mp/webhook/`, `GET /checkout/success/` (template HTML server-rendered) |
| `cms` | `/api/cms/` | `GET /pages/<brand_slug>/<page_slug>/` |
| `contact` | `/api/contact/` | `POST /` — manda email a `CONTACT_EMAIL` + confirmación al usuario (throttle 5/h por IP) |

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

### `products.Product`
- `slug` único, autogenerado desde `name` en `save()` si está vacío.
- FK opcional a `Brand` (productos sin marca existen, pero no se ven en `?brand_slug=`).
- **`brand` se serializa como slug** (no ID) → `SlugRelatedField`. El frontend compara `product.brand === params.brand` directo.
- `ProductImage` con `order`, accedida vía `images` (prefetcheada en list/detail).
- **Productos para socios** (transversal a todas las marcas):
  - `members_only` (bool): solo visible/comprable con cuenta. Filtrado por `Product.objects.visible_to(user)` (manager `ProductQuerySet`) en list y detail → 404 a anónimos.
  - `member_discount_percent` (0–100): descuento para usuarios autenticados.
  - **`price_for(user)` es la fuente de verdad del cobro** (anónimo `price`, socio `member_price`). La usan serializer (`final_price`), `cart` (subtotal/total) y `payments` (checkout). No replicar el cálculo de descuento en otro lado.
  - El checkout bloquea con 403 que un anónimo compre `members_only`.
  - El `CartSerializer` necesita `context={"request": request}` para resolver el precio de socio (ya pasado en `cart/views.py`).

### `cart.Cart`
- `OneToOne(User)` — **un solo carrito por usuario**, no por marca. La marca queda en `cart.brand` como contexto del último add.
- `CartItem(cart, product, quantity)` con `unique_together(cart, product)`.
- `get_or_create_cart(user)` en `cart/views.py` es el único punto de entrada.

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
   - Si vuelve de `PAID → REJECTED|CANCELLED`, **restituye stock**.
   - El status se cachea en `pre_save` (`instance._old_status`) para detectar el cambio.

> Si tocás `orders.Order.status`, **el signal corre**. No descontar stock manualmente desde otro lado.

---

## Brand scoping en el backend

El backend **no impone silos por marca** — devuelve toda la data del usuario. El filtrado por marca lo hace el frontend (regla del monorepo). Eso significa:

- `GET /api/users/favorites/` → **todos** los favoritos del usuario, sin filtrar.
- `GET /api/orders/` → **todas** las órdenes del usuario, sin filtrar.
- Los serializers de `Product` y `Order` exponen `brand` como **slug** (no ID) precisamente para que el frontend pueda filtrar con `.filter(p => p.brand === brandSlug)`.

Donde sí hay scoping en backend:
- `/api/products/?brand_slug=lumy` filtra por marca a nivel queryset.
- Checkout exige `brand_slug` y valida que los productos pertenezcan a esa marca antes de cobrar.

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
