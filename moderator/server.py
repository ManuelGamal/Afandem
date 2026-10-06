"""FastAPI app: a sandbox per browser session, live dashboard updates over SSE.

    uv run uvicorn --factory moderator.server:create_app --port 8000
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import queue
import secrets
import threading
from collections import OrderedDict
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from moderator.demo_scripts import DEMO_SCRIPTS
from moderator.bench.report import load_assumptions
from moderator.providers.client import ProviderError
from moderator.providers.config import build_provider
from moderator.roi import ASSUMPTIONS, load_bench, shop_roi
from moderator.session import Session
from moderator.store.orders import OrderError
from moderator.whatsapp import WhatsAppBridge, WhatsAppSender, verify_signature, whatsapp_configured

WEB = Path(__file__).with_name("web")
MAX_CHARS = 1000
MAX_SESSIONS = 200


class ChatIn(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=64, pattern=r"^[\w-]+$")
    text: str = Field(max_length=MAX_CHARS)


class CheckoutIn(BaseModel):
    preset: int | None = Field(default=None, ge=0, le=99)


class AdvanceIn(BaseModel):
    hours: float = Field(gt=0, le=24)


class StockIn(BaseModel):
    product_id: str = Field(min_length=1, max_length=16)
    size: str = Field(min_length=1, max_length=8)
    stock: int = Field(ge=0, le=10000)


def versioned_index() -> str:
    """index.html with ?v=<content hash> on its assets, so a new deploy is never served stale."""
    html = (WEB / "index.html").read_text(encoding="utf-8")
    for name in ("app.js", "style.css"):
        digest = hashlib.sha256((WEB / name).read_bytes()).hexdigest()[:10]
        html = html.replace(f"/static/{name}\"", f"/static/{name}?v={digest}\"")
    return html


def sse(event) -> str:
    return f"data: {json.dumps(event.to_dict(), ensure_ascii=False)}\n\n"


def create_app(provider_factory=None, mode: str | None = None, whatsapp_sender=None) -> FastAPI:
    mode = mode or os.environ.get("MODERATOR_MODE", "live")
    max_messages = int(os.environ.get("MODERATOR_MAX_MESSAGES", "60"))
    failed_cost = float(os.environ.get("MODERATOR_FAILED_DELIVERY_COST", "120"))
    notice = None
    try:
        provider = provider_factory() if provider_factory else build_provider(mode)
    except ProviderError as e:
        mode, notice = "replay", str(e)
        provider = build_provider("replay")

    app = FastAPI(title="Afandem — AI sales assistant")
    app.state.mode = mode
    sessions: OrderedDict[str, Session] = OrderedDict()
    registry = threading.Lock()

    def session_for(request: Request, response: Response) -> Session:
        sid = request.cookies.get("sid")
        with registry:
            if not sid or sid not in sessions:
                sid = secrets.token_urlsafe(16)
                sessions[sid] = Session(provider)
                response.set_cookie("sid", sid, httponly=True, samesite="lax")
                while len(sessions) > MAX_SESSIONS:
                    sessions.popitem(last=False)
            sessions.move_to_end(sid)
            return sessions[sid]

    bridge = None
    if whatsapp_configured():
        sender = whatsapp_sender or WhatsAppSender(os.environ["WHATSAPP_TOKEN"],
                                                   os.environ["WHATSAPP_PHONE_ID"])
        bridge = WhatsAppBridge(Session(provider), sender)

    def view_session(request: Request, response: Response) -> Session:
        if request.query_params.get("view") == "whatsapp" and bridge is not None:
            return bridge.session
        return session_for(request, response)

    @app.get("/webhook/whatsapp")
    def whatsapp_verify(request: Request):
        if bridge is None:
            raise HTTPException(404, "WhatsApp is not configured")
        q = request.query_params
        if q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == os.environ["WHATSAPP_VERIFY_TOKEN"]:
            return PlainTextResponse(q.get("hub.challenge", ""))
        raise HTTPException(403, "bad verify token")

    @app.post("/webhook/whatsapp")
    async def whatsapp_receive(request: Request, background: BackgroundTasks):
        if bridge is None:
            raise HTTPException(404, "WhatsApp is not configured")
        body = await request.body()
        if not verify_signature(os.environ["WHATSAPP_APP_SECRET"], body,
                                request.headers.get("X-Hub-Signature-256")):
            raise HTTPException(403, "bad signature")
        background.add_task(bridge.handle, json.loads(body))
        return {"ok": True}

    def spend(s: Session) -> None:
        if s.message_count >= max_messages:
            raise HTTPException(429, "Message limit for this demo session reached. Press reset.")
        s.message_count += 1

    @app.get("/")
    def index():
        return HTMLResponse(versioned_index())

    app.mount("/static", StaticFiles(directory=WEB), name="static")

    @app.middleware("http")
    async def revalidate_page(request: Request, call_next):
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"  # always fetch the latest deploy
        return response

    assumptions = load_assumptions(ASSUMPTIONS)
    bench = load_bench()
    base = {k: assumptions[k]["base"] for k in ("cod_orders_per_day", "dms_per_day",
            "moderator_salary_egp_month", "refusal_rate_without_confirmation", "average_order_egp")}

    @app.get("/api/roi")
    def roi(orders: float = Query(base["cod_orders_per_day"], ge=1, le=5000),
            dms: float = Query(base["dms_per_day"], ge=0, le=20000),
            salary: float = Query(base["moderator_salary_egp_month"], ge=500, le=200000),
            refusal: float = Query(base["refusal_rate_without_confirmation"], ge=0, le=0.9),
            aov: float = Query(base["average_order_egp"], ge=20, le=100000)):
        return shop_roi({"cod_orders_per_day": orders, "dms_per_day": dms,
                         "moderator_salary_egp_month": salary,
                         "refusal_rate_without_confirmation": refusal, "average_order_egp": aov},
                        assumptions, bench) | {"defaults": base}

    @app.get("/api/inventory")
    def inventory(request: Request, response: Response):
        s = view_session(request, response)
        with s.lock:
            return {"rows": s.catalog.inventory(), "movements": s.catalog.stock_movements(20)}

    @app.post("/api/inventory")
    def set_stock(body: StockIn, request: Request, response: Response):
        s = view_session(request, response)
        with s.lock:
            try:
                row = s.catalog.set_stock(body.product_id, body.size, body.stock)
            except KeyError as e:
                raise HTTPException(404, f"no such product size: {e}") from e
            if row["stock"] != row["previous"]:
                s.bus.publish("stock", None, product_id=row["product_id"], size=row["size"],
                              delta=row["stock"] - row["previous"], stock_after=row["stock"],
                              reason="owner_update", order_id=None)
            return row

    @app.get("/api/info")
    def info():
        return {"mode": app.state.mode, "notice": notice, "max_messages": max_messages,
                "demo_scripts": DEMO_SCRIPTS}

    @app.get("/api/state")
    def state(request: Request, response: Response):
        s = view_session(request, response)
        with s.lock:
            return s.state(failed_cost) | {"messages_left": max_messages - s.message_count}

    @app.post("/api/chat")
    def chat(body: ChatIn, request: Request, response: Response):
        text = body.text.strip()
        if not text:
            raise HTTPException(422, "empty message")
        s = session_for(request, response)
        with s.lock:
            spend(s)
            return {"replies": s.chat(body.conversation_id, text)}

    @app.post("/api/checkout")
    def checkout(body: CheckoutIn, request: Request, response: Response):
        s = session_for(request, response)
        with s.lock:
            spend(s)
            conv_id, order_id, replies = s.checkout(body.preset)
            return {"conversation_id": conv_id, "order_id": order_id, "replies": replies}

    @app.post("/api/advance")
    def advance(body: AdvanceIn, request: Request, response: Response):
        s = session_for(request, response)
        with s.lock:
            spend(s)
            return {"reminders": s.advance(body.hours)}

    @app.post("/api/orders/{order_id}/ship")
    def ship(order_id: int, request: Request, response: Response):
        s = session_for(request, response)
        with s.lock:
            try:
                s.ship(order_id)
            except OrderError as e:
                raise HTTPException(409, e.message) from e
            return {"ok": True}

    @app.post("/api/reset")
    def reset(request: Request, response: Response):
        session_for(request, response)
        sid = request.cookies.get("sid")
        with registry:
            if sid in sessions:
                sessions[sid] = Session(provider)
        return {"ok": True}

    @app.get("/api/events")
    async def events(request: Request):
        s = (bridge.session if request.query_params.get("view") == "whatsapp" and bridge
             else sessions.get(request.cookies.get("sid", "")))
        if s is None:
            raise HTTPException(404, "no session; load /api/state first")

        async def stream():
            q = s.bus.subscribe()
            try:
                while not await request.is_disconnected():
                    try:
                        event = await asyncio.to_thread(q.get, True, 15)
                    except queue.Empty:
                        yield ": keepalive\n\n"
                        continue
                    yield sse(event)
            finally:
                s.bus.unsubscribe(q)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    return app
