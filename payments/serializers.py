from rest_framework import serializers


class CheckoutProCreateSerializer(serializers.Serializer):
    brand_slug = serializers.SlugField()
    customer_email = serializers.EmailField(required=False, allow_blank=True)

    # items simples (fase 1)
    items = serializers.ListField(
        child=serializers.DictField(),
        min_length=1,
    )

    def validate_items(self, items):
        # validación mínima para evitar basura
        normalized = []
        for it in items:
            title = str(it.get("title", "")).strip()
            qty = int(it.get("qty", 0))
            unit_price = float(it.get("unit_price", 0))
            if not title or qty <= 0 or unit_price <= 0:
                raise serializers.ValidationError("Cada item requiere title, qty>0, unit_price>0")
            normalized.append({"title": title, "quantity": qty, "unit_price": round(unit_price, 2)})
        return normalized