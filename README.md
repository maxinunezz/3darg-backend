# 3DARG — Backend

API REST de 3DARG. **Django 5 + DRF + PostgreSQL 16**, expuesta en `:8000`. Sirve a la marca madre **3DARG** y a todas las sub-marcas (Lumy, MiniSlam, Print&Gym, CyberWeed, etc.). Consumidor: `../ecommerce-frontend/` (Next.js).

> Contexto de negocio y reglas transversales: ver el [README del monorepo](../README.md).

---

## Stack

| Pieza        | Detalle                                          |
|--------------|--------------------------------------------------|
| Django       | 5.x                                              |
| DRF          | 3.15+ con SimpleJWT y django-filter              |
| DB           | PostgreSQL 16 (`psycopg[binary]`)                |
| Server       | gunicorn + whitenoise (estáticos del admin)      |
| Pagos        | `mercadopago` SDK (Checkout Pro)                 |
| Python       | 3.12-slim (Dockerfile)                           |
| Idioma / TZ  | `es-ar` · `America/Argentina/Buenos_Aires`       |

---

## Cómo correr

El backend corre dentro de Docker Compose. Desde la **raíz del monorepo** (`../`):

```bash
docker compose up -d                                  # arranca db + web (+ frontend)
docker compose logs -f web                            # logs del backend
docker compose restart web                            # reiniciar tras cambios de código
docker compose build web && docker compose up -d      # rebuild tras tocar requirements.txt / Dockerfile

docker compose exec web python manage.py migrate
docker compose exec web python manage.py makemigrations <app>
docker compose exec -it web python manage.py createsuperuser
docker compose exec web python manage.py shell
```

El contenedor `web` monta `./3darg-backend:/app` como bind volume: los cambios de código toman efecto al **reiniciar gunicorn** (`docker compose restart web`). Solo hace falta rebuildear si cambia `requirements.txt` o el `Dockerfile`.

> No hay test suite real configurada (los `tests.py` están vacíos por defecto).

---

## Variables de entorno (`.env`)

```
DJANGO_SECRET_KEY=...
DJANGO_DEBUG=1
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0,web,.ngrok-free.app

POSTGRES_DB=...  POSTGRES_USER=...  POSTGRES_PASSWORD=...
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
```

El mismo `.env` lo leen los servicios `db` y `web` en `docker-compose.yml`.

---

## Apps y endpoints

Todas las rutas se montan en `config/urls.py` con prefijo común `/api/`.

| App        | Base            | Endpoints clave |
|------------|-----------------|-----------------|
| auth (JWT) | `/api/auth/`    | `POST /token/`, `POST /token/refresh/` |
| `users`    | `/api/users/`   | `POST /register/` (alta + opcional `brand_slug`), `GET\|PATCH /me/`, `GET\|POST /favorites/`, `DELETE /favorites/<product_id>/` |
| `brands`   | `/api/brands/`  | `GET /` — marcas **root** activas + `children` anidados |
| `products` | `/api/`         | `GET /products/` (filtros: `?search=`, `?brand_slug=`, `?is_featured=`, `?is_available=`, `?category__slug=`), `GET /products/<slug>/`, `GET /categories/?brand_slug=` |
| `cart`     | `/api/cart/`    | `GET\|DELETE /`, `POST /items/`, `PATCH\|DELETE /items/<id>/` — **todo requiere auth** |
| `orders`   | `/api/orders/`  | `GET /` (lista del usuario, `?status=`), `GET /<uuid>/`, `GET /summary/` |
| `payments` | `/api/payments/`| `POST /mp/checkout-pro/`, `POST /mp/webhook/`, `GET /checkout/success/` (HTML) |
| `cms`      | `/api/cms/`     | `GET /pages/<brand_slug>/<page_slug>/` |
| `contact`  | `/api/contact/` | `POST /` — email a `CONTACT_EMAIL` + confirmación (throttle 5/h por IP) |

---

## Modelos clave

### `brands.Brand` (corazón del sistema)
- **Jerarquía** vía `parent` (FK a sí mismo). 3DARG es el único root; las sub-marcas apuntan a él (`on_delete=PROTECT`).
- `brand_type`: `services | ecommerce | hybrid`. **`services` no permite checkout** (lo bloquea `payments`).
- `theme` (JSON): CSS custom properties que el frontend inyecta en `[brand]/layout.tsx`.
- `page_config` (JSON): copy + secciones de la landing (`sections`, `hero_style`, `features`, `stats`, etc.). El frontend lo consume tal cual.
- `social_links` (JSON) y `BrandLink` (links extra tipo Linktree, serializados como `links`).

### `users.User`
- `AbstractUser` con `email` como `USERNAME_FIELD` (login con email).
- `registered_brand`: FK opcional — guarda en qué marca se registró (info, no scoping).
- `Favorite`: `unique_together(user, product)`. Devuelve **todos** los favoritos; el filtrado por marca lo hace el frontend.

### `products.Product`
- `slug` único, autogenerado desde `name` si está vacío.
- FK opcional a `Brand`. **`brand` se serializa como slug** (`SlugRelatedField`) para que el frontend compare `product.brand === params.brand` directo.
- `ProductImage` con `order`, accedida vía `images` (prefetcheada).
- **Productos para socios:**
  - `members_only` (bool): el producto solo es visible y comprable por usuarios autenticados. El queryset lo oculta a anónimos vía `Product.objects.visible_to(user)` (listado y detalle devuelven 404 a anónimos).
  - `member_discount_percent` (0–100): descuento que reciben los usuarios con cuenta.
  - `price_for(user)` es la **única fuente de verdad del cobro** (anónimo → `price`, socio → `member_price`); la usan el serializer (`final_price`), el carrito y el checkout. El serializer expone además `member_price`, `members_only`, `member_discount_percent` y `has_member_discount`.
  - El checkout (`payments`) bloquea con 403 que un anónimo compre productos `members_only`.

### `cart.Cart`
- `OneToOne(User)` — **un solo carrito por usuario**, no por marca. `get_or_create_cart(user)` es el único punto de entrada.
- `CartItem(cart, product, quantity)` con `unique_together(cart, product)`.

### `orders.Order`
- **PK = UUID**; las URLs usan `<uuid:id>`.
- `status`: `DRAFT | PENDING | PAID | REJECTED | CANCELLED`.
- `brand` con `on_delete=PROTECT`; `user` puede ser `null` (`SET_NULL`) → checkout de guest soportado.
- `external_reference` (UUID hex): el ID que se comparte con MercadoPago; el webhook lo usa para matchear.
- **El stock se descuenta vía signal**, no en el checkout (ver flujo de pagos).

### `payments.MercadoPagoPayment`
- `OneToOne(Order)`. Guarda `preference_id`, `init_point`, `sandbox_init_point`, `mp_payment_id`, `status` y `raw`.

### `cms.Page` / `cms.Section`
- Páginas flexibles por marca (`Section.data` en JSON). Poco usado por ahora — la mayoría del copy va en `Brand.page_config`.

---

## Auth (JWT)

- Default DRF: `IsAuthenticatedOrReadOnly`. Las vistas que requieren auth lo declaran explícito; pagos y contacto usan `AllowAny`.
- `ACCESS_TOKEN_LIFETIME=2h`, `REFRESH_TOKEN_LIFETIME=7d`, `ROTATE_REFRESH_TOKENS=True`.
- Throttling: anónimos `10000/day`, usuarios `50000/day`; `contact` añade `5/hour` por IP.
- CORS: solo `http://localhost:3000` (cambiar en prod). CSRF acepta `*.ngrok-free.app` para los webhooks de MP en dev.

---

## Flujo de pagos (MercadoPago Checkout Pro)

1. **`POST /api/payments/mp/checkout-pro/`** (`AllowAny`, atómico): valida `brand_slug`, que el brand no sea `services`, y stock/disponibilidad de cada producto. Crea `Order` en `PENDING` con `external_reference`, genera la preferencia con `back_urls` a `FRONTEND_BASE_URL/checkout/{success|failure|pending}/?order_id=<uuid>`, guarda `MercadoPagoPayment` y devuelve el `init_point`.
2. **`POST /api/payments/mp/webhook/`** (sin auth, lo invoca MP): filtra topics, **valida firma HMAC** con `MP_WEBHOOK_SECRET` (sin firma válida → 403), consulta el pago, matchea por `external_reference` y actualiza `Order.status` (`approved → PAID`, `rejected|cancelled → REJECTED`). **Idempotente**.
3. **`orders/signals.py`** (post-save de `Order`): al pasar a `PAID` **descuenta stock** (`select_for_update`, atómico) y **manda email** de confirmación. De `PAID → REJECTED|CANCELLED` **restituye stock**.

> Si tocás `orders.Order.status`, **el signal corre**. No descontar stock manualmente desde otro lado.

---

## Brand scoping en el backend

El backend **no impone silos por marca** — devuelve toda la data del usuario; el filtrado lo hace el frontend.

- `GET /api/users/favorites/` y `GET /api/orders/` → **todo** el usuario, sin filtrar.
- Los serializers de `Product` y `Order` exponen `brand` como **slug** para que el frontend filtre con `.filter(x => x.brand === brandSlug)`.

Donde **sí** hay scoping en backend:
- `/api/products/?brand_slug=lumy` filtra a nivel queryset.
- Checkout exige `brand_slug` y valida que los productos pertenezcan a esa marca antes de cobrar.

---

## Estáticos del admin

`whitenoise` sirve los estáticos detrás de gunicorn; `start-server.sh` corre `collectstatic --noinput` al arrancar. Si el admin se ve sin estilos: verificar el orden de `WhiteNoiseMiddleware` (después de `SecurityMiddleware`), que `STORAGES["staticfiles"]` use `CompressedManifestStaticFilesStorage`, y reiniciar `web`.

`media/` se monta como volumen → los uploads sobreviven el rebuild del container.

---

## Convenciones

- **Idioma:** comentarios en código y strings al usuario final (mails, errores visibles) en español.
- **FKs públicas** (`brand`, `category`): serializar con `SlugRelatedField(slug_field="slug")`, no IDs.
- **Imágenes:** `ImageField` → URL absoluta. No construir URLs manualmente; el frontend usa `resolveMediaUrl()`.
- **DELETE devuelve 204 sin body.** No agregar `Response({...})` salvo razón explícita.
- **Status de Order:** pasa siempre por el signal (mails + stock). No bypassear.
- **Transacciones atómicas** en checkout y descuento/restitución de stock (`@transaction.atomic`).
- **Logging:** `logger = logging.getLogger(__name__)`, nunca `print`.

---

## En producción

- `DJANGO_DEBUG=0`, rotar `DJANGO_SECRET_KEY`, ajustar `CORS_ALLOWED_ORIGINS`, configurar SMTP real.
- El webhook de MP requiere URL pública → **ngrok** en dev.
- `volumes.postgres_data` es `external: true`: persiste aunque hagas `docker compose down -v`.
- `Brand.parent` es `on_delete=PROTECT`: no se puede borrar 3DARG con sub-marcas colgando.
