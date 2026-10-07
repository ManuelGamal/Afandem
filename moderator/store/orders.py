"""Order book on SQLite. State transitions are enforced here, never by the model."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta

from moderator.store.catalog import Catalog, Zone
from moderator.text import clean_digits, fold_text, norm_phone

STATUSES = ["draft", "pending_confirmation", "confirmed", "shipped", "cancelled", "needs_human"]
TRANSITIONS: dict[str, set[str]] = {
    "draft": {"pending_confirmation", "confirmed", "cancelled", "needs_human"},
    "pending_confirmation": {"confirmed", "cancelled", "needs_human"},
    "confirmed": {"shipped", "cancelled", "needs_human"},
    "needs_human": {"confirmed", "cancelled"},
    "shipped": set(),
    "cancelled": set(),
}
OPEN_STATUSES = {"draft", "pending_confirmation"}
EDITABLE_STATUSES = {"draft", "pending_confirmation"}
MAX_QTY = 5


class OrderError(Exception):
    def __init__(self, code: str, message: str, **details):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = details

    def to_dict(self) -> dict:
        return {"ok": False, "error": self.code, "message": self.message, **self.details}


@dataclass
class Order:
    id: int
    conversation_id: str
    status: str
    source: str
    customer_name: str
    phone: str
    address: str
    area: str
    zone_id: str
    items: list[dict]
    delivery_fee: int
    subtotal: int
    total: int
    delivery_date: str | None = None
    cancel_reason: str | None = None
    risk_notes: list[str] = field(default_factory=list)
    created_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class OrderBook:
    def __init__(self, catalog: Catalog, path: str = ":memory:"):
        self.catalog = catalog
        # Orders live in the shop's own database, so stock and orders change in one transaction.
        self._lock = catalog.db.lock
        self._db = catalog.db.conn
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " conversation_id TEXT, status TEXT, phone TEXT, data TEXT)"
        )

    # --- helpers -----------------------------------------------------------
    def _zone(self, area: str) -> Zone:
        zone = self.catalog.find_zone(area or "")
        if zone is None:
            served = [z.name_ar for z in self.catalog.zones]
            raise OrderError("area_not_served", f"we do not deliver to '{area}'", served=served)
        return zone

    def _order_zone(self, area: str, address: str) -> Zone:
        """The area's zone, unless the area is only a city name (or unknown) and the address names a
        district in another zone: "القاهرة" + "… الدقي" ships to Giza."""
        by_address = self.catalog.find_zone(address or "")
        by_area = self.catalog.find_zone(area or "")
        if by_address and (by_area is None or (by_address.id != by_area.id
                                                and self.catalog.is_city_name(area))):
            return by_address
        return self._zone(area)

    def _items(self, items: list[dict]) -> list[dict]:
        if not items:
            raise OrderError("missing_field", "order has no items")
        out = []
        for it in items:
            p = self.catalog.get(it.get("product_id", ""))
            if p is None:
                raise OrderError("unknown_product", f"no product {it.get('product_id')}")
            size = clean_digits(str(it.get("size", ""))).strip().upper() or ("ONE" if "ONE" in p.stock else "")
            if size not in p.stock:
                raise OrderError("unknown_size", f"{p.id} has no size {size}",
                                 available=p.available_sizes())
            qty = it.get("qty", 1)
            if not isinstance(qty, int) or not 1 <= qty <= MAX_QTY:
                raise OrderError("bad_quantity", f"quantity must be 1..{MAX_QTY}")
            if p.stock[size] < qty:
                raise OrderError("out_of_stock", f"{p.id} size {size}: only {p.stock[size]} in stock",
                                 in_stock=p.stock[size], requested=qty, available=p.available_sizes())
            color = str(it.get("color", "")).strip()
            if color not in p.colors:
                raise OrderError("unknown_color", f"{p.id} has no colour '{color}'", colors=p.colors)
            out.append({"product_id": p.id, "name_ar": p.name_ar, "size": size, "color": color,
                        "qty": qty, "unit_price": p.price})
        return out

    def _save(self, order: Order) -> Order:
        self._db.execute(
            "UPDATE orders SET conversation_id=?, status=?, phone=?, data=? WHERE id=?",
            (order.conversation_id, order.status, order.phone,
             json.dumps(order.to_dict(), ensure_ascii=False), order.id),
        )
        self._db.commit()
        return order

    @staticmethod
    def _price(order: Order, zone: Zone) -> None:
        order.subtotal = sum(i["qty"] * i["unit_price"] for i in order.items)
        order.delivery_fee = zone.fee
        order.zone_id = zone.id
        order.total = order.subtotal + order.delivery_fee

    # --- API ---------------------------------------------------------------
    def create(self, conversation_id: str, customer_name: str, phone: str, address: str,
               area: str, items: list[dict], source: str = "chat",
               now: datetime | None = None) -> Order:
        for name, value in (("customer_name", customer_name), ("phone", phone),
                            ("address", address)):
            if not str(value or "").strip():
                raise OrderError("missing_field", f"{name} is required", field=name)
        zone = self._order_zone(area, address)
        parsed = self._items(items)
        with self._lock:
            existing = self.open_for(conversation_id)
            if existing and existing.status != "draft":
                raise OrderError("order_exists", "this conversation already has an open order",
                                 order_id=existing.id)
            if existing is None:
                cur = self._db.execute("INSERT INTO orders (conversation_id, status) VALUES (?, ?)",
                                       (conversation_id, "draft"))
                order = Order(id=cur.lastrowid, conversation_id=conversation_id, status="draft",
                              source=source, customer_name="", phone="", address="", area="",
                              zone_id="", items=[], delivery_fee=0, subtotal=0, total=0,
                              created_at=(now or datetime.now()).isoformat(timespec="minutes"))
            else:
                order = existing
            order.customer_name = customer_name.strip()
            order.phone = norm_phone(phone) or str(phone)
            order.address = address.strip()
            order.area = area.strip()
            order.items = parsed
            self._price(order, zone)
            return self._save(order)

    def update(self, order_id: int, changes: dict) -> Order:
        with self._lock:
            order = self.get(order_id)
            if order.status not in EDITABLE_STATUSES:
                raise OrderError("order_locked", f"order is {order.status}; it can't be edited",
                                 status=order.status)
            if "items" in changes:
                order.items = self._items(changes["items"])
            for key in ("customer_name", "address"):
                if changes.get(key):
                    setattr(order, key, str(changes[key]).strip())
            if changes.get("phone"):
                order.phone = norm_phone(changes["phone"]) or str(changes["phone"])
            if changes.get("area"):
                order.area = str(changes["area"]).strip()
            self._price(order, self._order_zone(order.area, order.address))
            return self._save(order)

    def set_status(self, order_id: int, status: str, reason: str | None = None) -> tuple[Order, str]:
        with self._lock:
            order = self.get(order_id)
            old = order.status
            if status not in TRANSITIONS[old]:
                raise OrderError("bad_transition", f"can't go from {old} to {status}",
                                 status=old)
            try:
                if status == "confirmed":  # the order's items leave the shelf
                    for i in order.items:
                        try:
                            self.catalog.move_stock(i["product_id"], i["size"], -i["qty"],
                                                    "order_confirmed", order.id)
                        except ValueError as e:
                            in_stock = self.catalog.get(i["product_id"]).stock.get(i["size"], 0)
                            raise OrderError("out_of_stock", str(e), product_id=i["product_id"],
                                             size=i["size"], requested=i["qty"], in_stock=in_stock,
                                             available=self.catalog.get(i["product_id"]).available_sizes()) from e
                elif old == "confirmed" and status == "cancelled":  # back on the shelf
                    for i in order.items:
                        self.catalog.move_stock(i["product_id"], i["size"], i["qty"],
                                                "order_cancelled", order.id)
                order.status = status
                if status == "cancelled":
                    order.cancel_reason = reason or "unspecified"
                return self._save(order), old
            except Exception:
                self._db.rollback()  # stock and status change together or not at all
                raise

    def schedule(self, order_id: int, day: date, today: date) -> Order:
        with self._lock:
            order = self.get(order_id)
            zone = self.catalog.zone(order.zone_id) or self._zone(order.area)
            earliest = today + timedelta(days=zone.days_min)
            latest = today + timedelta(days=zone.days_max + 5)
            if not earliest <= day <= latest:
                raise OrderError("date_out_of_window", "date outside the delivery window",
                                 earliest=earliest.isoformat(), latest=latest.isoformat())
            order.delivery_date = day.isoformat()
            return self._save(order)

    def add_risk_note(self, order_id: int, note: str) -> Order:
        with self._lock:
            order = self.get(order_id)
            order.risk_notes.append(note.strip()[:200])
            return self._save(order)

    def get(self, order_id: int) -> Order:
        row = self._db.execute("SELECT id, data FROM orders WHERE id=?", (order_id,)).fetchone()
        if row is None or row[1] is None:
            raise OrderError("unknown_order", f"no order {order_id}")
        return Order(**json.loads(row[1]))

    def all(self) -> list[Order]:
        rows = self._db.execute("SELECT data FROM orders WHERE data IS NOT NULL ORDER BY id")
        return [Order(**json.loads(r[0])) for r in rows.fetchall()]

    def by_phone(self, phone: str) -> list[Order]:
        p = norm_phone(phone) or phone
        return [o for o in self.all() if o.phone == p]

    def latest_for(self, conversation_id: str) -> Order | None:
        for o in reversed(self.all()):
            if o.conversation_id == conversation_id:
                return o
        return None

    def open_for(self, conversation_id: str) -> Order | None:
        for o in reversed(self.all()):
            if o.conversation_id == conversation_id and o.status in OPEN_STATUSES:
                return o
        return None


def summary_ar(order: Order, zone: Zone) -> str:
    lines = [f"طلب رقم {order.id}:"]
    for i in order.items:
        size = "" if i["size"] == "ONE" else f" مقاس {i['size']}"
        lines.append(f"- {i['qty']}× {i['name_ar']}{size} لون {i['color']} = "
                     f"{i['qty'] * i['unit_price']} جنيه")
    lines.append(f"الشحن ({zone.name_ar}): {order.delivery_fee} جنيه")
    lines.append(f"الإجمالي: {order.total} جنيه (الدفع عند الاستلام)")
    address = order.address
    if fold_text(order.area) not in fold_text(order.address):
        address = f"{order.address}، {order.area}"
    lines.append(f"العنوان: {address}")
    when = (f"يوم {order.delivery_date}" if order.delivery_date
            else f"خلال {zone.days_min}-{zone.days_max} أيام")
    lines.append(f"التوصيل: {when}")
    return "\n".join(lines)


def order_fingerprint(order: Order) -> str:
    """What the customer must have seen before saying yes: items, address and total (not the
    delivery date, which the customer may move without changing what they buy)."""
    return json.dumps([order.items, order.address, order.area, order.total],
                      ensure_ascii=False, sort_keys=True)
