import asyncio
import unittest

from fastapi import Request
from fastapi.responses import StreamingResponse

from app.main import TraceIdMiddleware


class TraceIdMiddlewareTest(unittest.IsolatedAsyncioTestCase):
    async def test_sse_response_is_returned_without_consuming_body(self):
        release_body = asyncio.Event()

        async def body():
            await release_body.wait()
            yield b"event: assistant_delta\ndata: {}\n\n"

        response = StreamingResponse(body(), media_type="text/event-stream")
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/v1/command/websochat/sessions/1/messages/stream",
                "query_string": b"",
                "headers": [],
            }
        )
        middleware = TraceIdMiddleware(app=lambda scope, receive, send: None)

        async def call_next(_request):
            return response

        result = await asyncio.wait_for(
            middleware.dispatch(request, call_next),
            timeout=0.1,
        )

        self.assertIs(result, response)
        self.assertTrue(result.headers.get("trace_id"))
        release_body.set()
        await result.body_iterator.aclose()


if __name__ == "__main__":
    unittest.main()
