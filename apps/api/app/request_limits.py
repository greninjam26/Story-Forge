"""ASGI request-size guards applied before multipart parsing."""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


REFERENCE_PHOTO_FILE_BYTES = 10 * 1024 * 1024
REFERENCE_PHOTO_MULTIPART_OVERHEAD_BYTES = 64 * 1024
REFERENCE_PHOTO_REQUEST_BYTES = (
    REFERENCE_PHOTO_FILE_BYTES + REFERENCE_PHOTO_MULTIPART_OVERHEAD_BYTES
)


class _RequestTooLarge(Exception):
    pass


class ReferencePhotoUploadLimitMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    @staticmethod
    def _applies(scope: Scope) -> bool:
        parts = scope.get("path", "").split("/")
        return (
            scope.get("type") == "http"
            and scope.get("method") == "PUT"
            and len(parts) == 6
            and parts[1] == "parents"
            and bool(parts[2])
            and parts[3] == "children"
            and bool(parts[4])
            and parts[5] == "reference-photo"
        )

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            {"detail": "Reference photo must be 10 MB or smaller."},
            status_code=413,
        )
        await response(scope, receive, send)

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if not self._applies(scope):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                if int(content_length) > REFERENCE_PHOTO_REQUEST_BYTES:
                    await self._reject(scope, receive, send)
                    return
            except ValueError:
                pass

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > REFERENCE_PHOTO_REQUEST_BYTES:
                raise _RequestTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _RequestTooLarge:
            await self._reject(scope, receive, send)
