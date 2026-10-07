"""Tool schemas and a dispatcher that never raises: errors go back to the model as data."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta

from moderator.agent.risk import score_order
from moderator.clock import Clock
from moderator.events import EventBus
from moderator.store.catalog import Catalog
from moderator.store.orders import OrderBook, OrderError, order_fingerprint, summary_ar
from moderator.text import clean_digits, fold_text, is_explicit_yes, to_number

CANCEL_REASONS = ["customer_declined", "unreachable", "duplicate", "out_of_stock", "other"]
_RELATIVE = {"النهارده": 0, "اليوم": 0, "بكره": 1, "بكرا": 1, "بعد بكره": 2,
             "today": 0, "tomorrow": 1}


@dataclass
class ToolContext:
    catalog: Catalog
    book: OrderBook
    bus: EventBus
    clock: Clock
    conversation_id: str
    last_agent_message: str = ""
    customer_message: str = ""
    handed_off: bool = False
    shown_fingerprint: str | None = None


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required}}}


_ITEM = {"type": "object", "properties": {
    "product_id": {"type": "string"},
    "size": {"type": "string", "description": "e.g. M, 32, ONE"},
    "color": {"type": "string", "description": "exactly one of the product's colors"},
    "qty": {"type": "integer"}}, "required": ["product_id", "size", "color", "qty"]}

TOOL_SCHEMAS = [
    _fn("search_products", "Search the shop catalog. Put the item type and any colour in the query, "
        "e.g. 'بنطلون أسود', 'black pants' or 'tshirt' (Arabic, Franco or English).",
        {"query": {"type": "string"},
         "category": {"type": "string", "enum": ["tops", "bottoms", "outerwear", "accessories"]},
         "max_price": {"type": "number"}}, ["query"]),
    _fn("get_product", "Price, colors, sizes in stock and size chart of one product.",
        {"product_id": {"type": "string"}}, ["product_id"]),
    _fn("recommend_size", "Recommend a size from the product's chart.",
        {"product_id": {"type": "string"}, "height_cm": {"type": "number"},
         "weight_kg": {"type": "number"},
         "fit_preference": {"type": "string", "enum": ["regular", "loose", "tight"]}},
        ["product_id", "height_cm", "weight_kg"]),
    _fn("quote_delivery", "Delivery fee and time for an Egyptian area or city.",
        {"area": {"type": "string"}}, ["area"]),
    _fn("create_order", "Create (or replace) this conversation's draft order. Returns summary_ar "
        "to send to the customer for confirmation.",
        {"customer_name": {"type": "string"}, "phone": {"type": "string"},
         "address": {"type": "string", "description": "street, building number, floor, landmark"},
         "area": {"type": "string"}, "items": {"type": "array", "items": _ITEM}},
        ["customer_name", "phone", "address", "area", "items"]),
    _fn("update_order", "Change an unconfirmed order. Returns the new summary_ar.",
        {"order_id": {"type": "integer"},
         "changes": {"type": "object", "properties": {
             "items": {"type": "array", "items": _ITEM}, "address": {"type": "string"},
             "area": {"type": "string"}, "phone": {"type": "string"},
             "customer_name": {"type": "string"}}}}, ["order_id", "changes"]),
    _fn("confirm_order", "Confirm an order. Only works right after you sent its summary_ar and "
        "the customer replied with a clear yes.",
        {"order_id": {"type": "integer"}}, ["order_id"]),
    _fn("cancel_order", "Cancel an order with a reason.",
        {"order_id": {"type": "integer"}, "reason": {"type": "string", "enum": CANCEL_REASONS}},
        ["order_id", "reason"]),
    _fn("schedule_delivery", "Set the delivery date (YYYY-MM-DD, or بكره/بعد بكره).",
        {"order_id": {"type": "integer"}, "date": {"type": "string"}}, ["order_id", "date"]),
    _fn("flag_risk", "Record a concern about an order (e.g. hesitation, odd answers).",
        {"order_id": {"type": "integer"}, "note": {"type": "string"}}, ["order_id", "note"]),
    _fn("handoff_to_human", "Hand the conversation to a human team member (complaints, refunds, "
        "abuse, anything you can't handle).",
        {"reason": {"type": "string"}}, ["reason"]),
]


class _BadArgs(Exception):
    pass


def _need(args: dict, key: str):
    if args.get(key) in (None, "", []):
        raise _BadArgs(f"missing '{key}'")
    return args[key]


def _int(value, key: str) -> int:
    n = to_number(value)
    if n is None or n != n.to_integral_value():
        raise _BadArgs(f"'{key}' must be a whole number")
    return int(n)


def _items(raw) -> list[dict]:
    if not isinstance(raw, list):
        raise _BadArgs("'items' must be a list")
    out = []
    for it in raw:
        if not isinstance(it, dict):
            raise _BadArgs("each item must be an object")
        out.append({**it, "qty": _int(it.get("qty", 1), "qty")})
    return out


def _order_of(ctx: ToolContext, args: dict):
    order = ctx.book.get(_int(_need(args, "order_id"), "order_id"))
    if order.conversation_id != ctx.conversation_id:
        raise OrderError("unknown_order", "no such order in this conversation")
    return order


def _status_event(ctx: ToolContext, order, old, reason=None) -> None:
    ctx.bus.publish("order_status", ctx.conversation_id, order_id=order.id, old=old,
                    new=order.status, reason=reason, total=order.total, source=order.source)
    publish_stock_moves(ctx.catalog, ctx.bus, ctx.conversation_id, order, old)


def publish_stock_moves(catalog, bus, conversation_id, order, old) -> None:
    """Announce the shop database's stock changes caused by this status change."""
    if order.status == "confirmed" and old != "confirmed":
        why = "order_confirmed"
    elif old == "confirmed" and order.status == "cancelled":
        why = "order_cancelled"
    else:
        return
    moves = [m for m in catalog.stock_movements(limit=100)
             if m["order_id"] == order.id and m["reason"] == why][:len(order.items)]
    for m in reversed(moves):
        bus.publish("stock", conversation_id, **m)


def _with_summary(ctx: ToolContext, order) -> dict:
    zone = ctx.catalog.zone(order.zone_id) or ctx.catalog.find_zone(order.area)
    return {"ok": True, "order_id": order.id, "status": order.status, "total": order.total,
            "summary_ar": summary_ar(order, zone),
            "risk": score_order(ctx.book, order).to_dict()}


def _pairs(ctx, p) -> list[dict]:
    return [{"id": q.id, "name": q.name_ar, "price": q.price}
            for q in (ctx.catalog.get(i) for i in p.pairs_with) if q is not None]


def _search_products(ctx, a):
    max_price = to_number(a["max_price"]) if a.get("max_price") not in (None, "") else None
    found = ctx.catalog.search(_need(a, "query"), a.get("category"),
                               int(max_price) if max_price is not None else None)
    return {"ok": True, "products": [{**p.to_dict(), "pairs_with": _pairs(ctx, p)} for p in found]}


def _get_product(ctx, a):
    p = ctx.catalog.get(_need(a, "product_id"))
    if p is None:
        return {"ok": False, "error": "unknown_product", "message": "no such product"}
    return {"ok": True, "product": {**p.to_dict(), "size_chart": ctx.catalog.charts[p.chart],
                                    "pairs_with": _pairs(ctx, p)}}


def _recommend_size(ctx, a):
    height = to_number(_need(a, "height_cm"))
    weight = to_number(_need(a, "weight_kg"))
    if height is None or weight is None:
        raise _BadArgs("height_cm and weight_kg must be numbers")
    height_cm = float(height) * (100 if height < 3 else 1)
    if ctx.catalog.get(_need(a, "product_id")) is None:
        return {"ok": False, "error": "unknown_product", "message": "no such product"}
    rec = ctx.catalog.recommend_size(a["product_id"], height_cm, float(weight),
                                     a.get("fit_preference"))
    return {"ok": True, **rec}


def _quote_delivery(ctx, a):
    zone = ctx.catalog.find_zone(_need(a, "area"))
    if zone is None:
        return {"ok": False, "error": "area_not_served", "message": "we don't deliver there",
                "served": [z.name_ar for z in ctx.catalog.zones]}
    return {"ok": True, "zone": zone.name_ar, "fee": zone.fee,
            "days_min": zone.days_min, "days_max": zone.days_max}


def _create_order(ctx, a):
    order = ctx.book.create(ctx.conversation_id, _need(a, "customer_name"), _need(a, "phone"),
                            _need(a, "address"), _need(a, "area"), _items(_need(a, "items")),
                            source="chat", now=ctx.clock.now())
    _status_event(ctx, order, None)
    return _with_summary(ctx, order)


def _update_order(ctx, a):
    order = _order_of(ctx, a)
    changes = dict(_need(a, "changes"))
    if "items" in changes:
        changes["items"] = _items(changes["items"])
    return _with_summary(ctx, ctx.book.update(order.id, changes))


def _confirm_order(ctx, a):
    order = _order_of(ctx, a)
    shown = ctx.shown_fingerprint == order_fingerprint(order)
    if not shown and str(order.total) not in clean_digits(ctx.last_agent_message).replace(",", ""):
        return {"ok": False, "error": "summary_not_sent",
                "message": "Send the customer this order's summary_ar (with the total) first, "
                           "then wait for their clear yes."}
    if not is_explicit_yes(ctx.customer_message, order_sizes={i["size"] for i in order.items}):
        return {"ok": False, "error": "no_explicit_yes",
                "message": "The customer has not given a clear, unconditional yes. Apply any "
                           "change they asked for, send the new summary, and ask again."}
    risk = score_order(ctx.book, order)
    if risk.level == "high":
        order, old = ctx.book.set_status(order.id, "needs_human")
        _status_event(ctx, order, old, "high_risk_review")
        return {"ok": True, "status": "needs_human", "risk": risk.to_dict(),
                "message": "The order is NOT confirmed: it is held for owner review. Do not write "
                           "'تم تأكيد' or say it is confirmed. Tell the customer the team will call "
                           "shortly to finish the order, and suggest paying the delivery fee "
                           "upfront by InstaPay to speed it up."}
    order, old = ctx.book.set_status(order.id, "confirmed")
    _status_event(ctx, order, old)
    return {"ok": True, "status": "confirmed", "order_id": order.id, "risk": risk.to_dict()}


def _cancel_order(ctx, a):
    order = _order_of(ctx, a)
    reason = _need(a, "reason")
    if reason not in CANCEL_REASONS:
        raise _BadArgs(f"reason must be one of {CANCEL_REASONS}")
    order, old = ctx.book.set_status(order.id, "cancelled", reason)
    _status_event(ctx, order, old, reason)
    return {"ok": True, "status": "cancelled"}


def _schedule_delivery(ctx, a):
    order = _order_of(ctx, a)
    raw = clean_digits(str(_need(a, "date"))).strip()
    offset = _RELATIVE.get(fold_text(raw))
    try:
        day = (ctx.clock.today() + timedelta(days=offset) if offset is not None
               else date.fromisoformat(raw[:10]))
    except ValueError as e:
        raise _BadArgs("date must be YYYY-MM-DD") from e
    return _with_summary(ctx, ctx.book.schedule(order.id, day, ctx.clock.today()))


def _flag_risk(ctx, a):
    order = _order_of(ctx, a)
    order = ctx.book.add_risk_note(order.id, str(_need(a, "note")))
    return {"ok": True, "risk": score_order(ctx.book, order).to_dict()}


def _handoff(ctx, a):
    reason = str(a.get("reason") or "unspecified")
    ctx.handed_off = True
    order = ctx.book.open_for(ctx.conversation_id)
    if order is not None:
        order, old = ctx.book.set_status(order.id, "needs_human")
        _status_event(ctx, order, old, "handoff")
    ctx.bus.publish("handoff", ctx.conversation_id, reason=reason)
    return {"ok": True, "message": "A team member will take over. Tell the customer politely "
                                   "that someone from the team will reply shortly."}


_HANDLERS = {
    "search_products": _search_products, "get_product": _get_product,
    "recommend_size": _recommend_size, "quote_delivery": _quote_delivery,
    "create_order": _create_order, "update_order": _update_order,
    "confirm_order": _confirm_order, "cancel_order": _cancel_order,
    "schedule_delivery": _schedule_delivery, "flag_risk": _flag_risk,
    "handoff_to_human": _handoff,
}


def run_tool(name: str, arguments: str | dict, ctx: ToolContext) -> dict:
    handler = _HANDLERS.get(name)
    args = {}
    if handler is None:
        result = {"ok": False, "error": "unknown_tool", "message": f"no tool '{name}'"}
    else:
        try:
            args = json.loads(arguments or "{}") if isinstance(arguments, str) else dict(arguments)
            if not isinstance(args, dict):
                raise _BadArgs("arguments must be a JSON object")
            result = handler(ctx, args)
        except json.JSONDecodeError:
            result = {"ok": False, "error": "bad_arguments", "message": "arguments are not JSON"}
        except _BadArgs as e:
            result = {"ok": False, "error": "bad_arguments", "message": str(e)}
        except OrderError as e:
            result = e.to_dict()
        except (KeyError, TypeError, ValueError) as e:
            result = {"ok": False, "error": "bad_arguments", "message": str(e)}
    ctx.bus.publish("tool_call", ctx.conversation_id, name=name, ok=result.get("ok", False),
                    error=result.get("error"), db=db_note(ctx, name, args, result))
    return result


def _in_stock(stock: dict) -> str:
    sizes = [f"{size} {n}" for size, n in stock.items() if n > 0]
    return "in stock: " + ", ".join(sizes) if sizes else "sold out"


def iso(text: str) -> str:
    """Wrap a name in Unicode isolates, so an Arabic name inside an English line keeps its place."""
    return chr(0x2068) + text + chr(0x2069)


def db_note(ctx: ToolContext, name: str, args, result: dict) -> dict | None:
    """One line for the chat on what a tool read from or wrote to the shop database."""
    if not result.get("ok") or not isinstance(args, dict):
        return None
    if name == "search_products":
        query = iso(str(args.get("query", "")))
        found = result["products"]
        if not found:
            return {"kind": "read", "text": f"search “{query}”: nothing found"}
        shown = "; ".join(f"{iso(p['name'])} {p['price']} EGP" for p in found[:2])
        more = f" +{len(found) - 2} more" if len(found) > 2 else ""
        return {"kind": "read", "text": f"search “{query}” → {shown}{more}"}
    if name == "get_product":
        p = result["product"]
        return {"kind": "read", "text": f"{iso(p['name'])} · {p['price']} EGP · {_in_stock(p['stock_by_size'])}"}
    if name == "recommend_size":
        p = ctx.catalog.get(args.get("product_id", ""))
        label = iso(p.name_ar) if p else "size chart"
        if result.get("size") is None:
            return {"kind": "read", "text": f"{label} · no size chart · {_in_stock(p.stock if p else {})}"}
        state = "in stock" if result.get("in_stock") else "sold out"
        return {"kind": "read", "text": f"{label} · size chart → {result['size']} ({state})"}
    if name == "quote_delivery":
        return {"kind": "read", "text": f"delivery to {iso(result['zone'])}: {result['fee']} EGP, "
                                        f"{result['days_min']}–{result['days_max']} days"}
    if name in ("create_order", "update_order"):
        return {"kind": "write", "text": f"order #{result['order_id']} saved · {result['status']} · "
                                         f"total {result['total']} EGP"}
    return None
