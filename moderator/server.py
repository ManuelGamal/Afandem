"""FastAPI app: a sandbox per browser session, live dashboard updates over SSE.

    uv run uvicorn --factory moderator.server:create_app --port 8000
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import secrets
import threading
from collections import OrderedDict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from moderator.demo_scripts import DEMO_SCRIPTS
from moderator.providers.client import ProviderError
from moderator.providers.config import build_provider
from moderator.session import Session
from moderator.store.orders import OrderError

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


def sse(event) -> str:
    return f"data: {json.dumps(event.to_dict(), ensure_ascii=False)}\n\n"


def create_app(provider_factory=None, mode: str | None = None) -> FastAPI:
    mode = mode or os.environ.get("MODERATOR_MODE", "live")
    max_messages = int(os.environ.get("MODERATOR_MAX_MESSAGES", "60"))
    failed_cost = float(os.environ.get("MODERATOR_FAILED_DELIVERY_COST", "120"))
    notice = None
    try:
        provider = provider_factory() if provider_factory else build_provider(mode)
    except ProviderError as e:
        mode, notice = "replay", str(e)
        provider = build_provider("replay")

    app = FastAPI(title="Wasla Wear AI moderator")
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

    def spend(s: Session) -> None:
        if s.message_count >= max_messages:
            raise HTTPException(429, "Message limit for this demo session reached. Press reset.")
        s.message_count += 1

    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html")

    app.mount("/static", StaticFiles(directory=WEB), name="static")

    @app.get("/api/info")
    def info():
        return {"mode": app.state.mode, "notice": notice, "max_messages": max_messages,
                "demo_scripts": DEMO_SCRIPTS}

    @app.get("/api/state")
    def state(request: Request, response: Response):
        s = session_for(request, response)
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
        s = sessions.get(request.cookies.get("sid", ""))
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
