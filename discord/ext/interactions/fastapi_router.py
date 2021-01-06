"""
This section of the module has a function that returns an APIRouter for starlette/fastapi.

It has no use outside of that.
"""
from json import loads

try:
    from fastapi import APIRouter, Request, FastAPI
    from fastapi.responses import JSONResponse
except ImportError:
    fastapi = None
    raise ImportError("FastAPI must be installed to be able to install the router.")

try:
    from nacl import VerifyKey
except ImportError:
    raise ImportError("PyNaCl must be installed to be able to install the router.")

__ROUTER__ = APIRouter()


class Router:
    def __init__(self, bot, public_key):
        self.bot = bot
        self.public_key = public_key
        self._route_added = False

    @staticmethod
    def verify_key(headers, body: bytes, *, key):
        signature = headers.get("X-Signature-Ed25519")
        timestamp = headers.get("X-Signature-Timestamp")

        message = timestamp.encode() + body
        body = body.decode("utf-8", "replace")
        try:
            vk = VerifyKey(bytes.fromhex(key))
            vk.verify(message, bytes.fromhex(signature))
            return True
        except Exception as e:
            pass
        return False

    def route(self, request: Request):
        body = await request.body()
        if not self.verify_key(request.headers, body, key=self.public_key):
            return JSONResponse({}, 401)
        json = loads(body)
        if json["type"] == 1:
            return JSONResponse({"type": 1})
        from .models import Interaction

        # noinspection PyUnresolvedReferences,PyTypeChecker
        BOT.dispatch("ext_interaction", Interaction.from_request(BOT, json))
        return JSONResponse({}, 202)

    def mount(self, app: FastAPI, *, prefix: str = "", path: str = "/"):
        if not self._route_added:
            self._route_added = True
            __ROUTER__.add_route(path, self.route, methods=["POST"])
        app.include_router(__ROUTER__, prefix=prefix)
