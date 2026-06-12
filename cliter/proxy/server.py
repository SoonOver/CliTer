"""Proxy HTTP server — pure asyncio, no extra deps.
OpenAI-compatible endpoint: /v1/chat/completions + /v1/models + /health
"""
import asyncio
import json
import time
import traceback
import urllib.parse
from cliter.utils.log import get_logger
from cliter.proxy import manager
from cliter.proxy.router import route, resolve_base_url
from cliter.proxy import strategy as strategy_engine
from cliter.proxy import pool as connection_pool
from cliter.proxy import tracker
from cliter.proxy import monitor

log = get_logger("proxy")

CRLF = b"\r\n"


class ProxyServer:
    """Async HTTP server for CliTer proxy. Zero extra deps."""

    def __init__(self, host: str = "127.0.0.1", port: int = 20129,
                 api_key: str = "cliter-proxy-key"):
        self.host = host
        self.port = port
        self.api_key = api_key
        self._server: asyncio.AbstractServer | None = None
        self._running = False

    # ── Public lifecycle ──────────────────────────────

    async def start(self):
        self._server = await asyncio.start_server(
            self._handle_client, self.host, self.port
        )
        self._running = True
        log.info(f"Proxy server listening on {self.host}:{self.port}")
        # Start background health + model sync
        asyncio.create_task(self._health_check_loop())
        asyncio.create_task(monitor.start())
        # Initial health check
        asyncio.create_task(monitor.run_health_check())

    async def stop(self):
        await monitor.stop()
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            log.info("Proxy server stopped")

    @property
    def running(self) -> bool:
        return self._running

    # ── Client handler ────────────────────────────────

    async def _handle_client(self, reader: asyncio.StreamReader,
                             writer: asyncio.StreamWriter):
        try:
            raw = await reader.readuntil(b"\r\n\r\n")
        except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
            writer.close()
            return

        try:
            decoded = raw.decode("utf-8", errors="replace")
            request_line, header_lines = decoded.split("\r\n", 1)
            parts = request_line.split(" ", 2)
            if len(parts) < 2:
                await self._send_error(writer, 400, "Bad Request")
                return
            method, path = parts[0], parts[1]

            # Parse headers
            headers = {}
            for line in header_lines.split("\r\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.lower().strip()] = v.strip()

            # Read body
            cl = int(headers.get("content-length", 0))
            body_raw = await reader.readexactly(cl) if cl > 0 else b""

            # Route
            if method == "POST" and path.rstrip("/") == "/v1/chat/completions":
                await self._handle_chat(writer, body_raw, headers)
            elif method == "GET" and path.rstrip("/") == "/v1/models":
                await self._handle_models(writer, headers)
            elif method == "GET" and path.rstrip("/") == "/health":
                await self._handle_health(writer)
            else:
                await self._send_error(writer, 404, f"Not Found: {method} {path}")
        except Exception as e:
            log.warning(f"Request error: {e}")
            try:
                await self._send_error(writer, 500, str(e))
            except Exception:
                pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    # ── Auth ──────────────────────────────────────────

    def _check_auth(self, headers: dict) -> bool:
        if not self.api_key:
            return True  # no auth required
        auth = headers.get("authorization", "")
        key_from_header = headers.get("x-api-key", "")
        if auth.startswith("Bearer "):
            return auth[7:] == self.api_key
        if key_from_header:
            return key_from_header == self.api_key
        return False

    # ── Chat completions handler ──────────────────────

    async def _handle_chat(self, writer: asyncio.StreamWriter,
                           body_raw: bytes, headers: dict):
        if not self._check_auth(headers):
            await self._send_error(writer, 401, "Unauthorized - invalid or missing proxy API key")
            return

        try:
            req = json.loads(body_raw)
        except json.JSONDecodeError as e:
            await self._send_error(writer, 400, f"Invalid JSON: {e}")
            return

        model_name = req.get("model", "")

        # ── Strategy-based model selection ──
        strat = await strategy_engine.get_active_strategy()
        selection = await strategy_engine.select_model(
            strategy=strat,
            user_input=str(req.get("messages", [{}])[-1].get("content", "")),
            preferred_model=model_name,
        )

        if "error" in selection:
            await self._send_error(writer, 503, selection["error"])
            return

        provider = selection["provider"]
        stripped_model = selection["model"]
        base = await resolve_base_url(provider)
        upstream_url = f"{base}/chat/completions"
        upstream_key = provider.get("api_key", "")
        connection_id = selection.get("connection_id", provider.get("id", ""))

        req["model"] = stripped_model

        # Tag request metadata for tracking
        req["_provider_id"] = provider.get("id", "")
        req["_connection_id"] = connection_id

        stream = req.get("stream", False)
        stream = False  # simplify: force non-stream for pool compatibility

        # ── Execute via connection pool with failover ──
        result = await connection_pool.execute_request(
            method="POST",
            upstream_url=upstream_url,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {upstream_key}"} if upstream_key else {"Content-Type": "application/json"},
            body=req,
            stream=stream,
            provider_id=provider.get("id", ""),
            connection_id=connection_id,
            model=stripped_model,
        )

        if "error" in result:
            await self._send_error(writer, result.get("status", 502), result["error"])
            return

        # ── Relay response ──
        response_data = result.get("response", {})
        resp_body = json.dumps(response_data).encode()
        status = result.get("status", 200)
        status_text = {200: "OK", 400: "Bad Request", 401: "Unauthorized",
                       403: "Forbidden", 404: "Not Found", 429: "Too Many Requests",
                       500: "Internal Server Error", 502: "Bad Gateway",
                       503: "Service Unavailable"}.get(status, "Unknown")

        writer.write(f"HTTP/1.1 {status} {status_text}\r\n".encode())
        writer.write(b"Content-Type: application/json\r\n")
        writer.write(f"Content-Length: {len(resp_body)}\r\n".encode())
        writer.write(b"Access-Control-Allow-Origin: *\r\n")
        writer.write(b"\r\n")
        writer.write(resp_body)
        await writer.drain()

    async def _proxy_sync(self, writer, url: str, api_key: str, body: dict):
        """Non-streaming: forward, wait, relay."""
        import httpx
        try:
            hdrs = {"Content-Type": "application/json"}
            if api_key:
                hdrs["Authorization"] = f"Bearer {api_key}"

            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(url, json=body, headers=hdrs)
                resp_data = await resp.aread()

            # Relay response
            status = resp.status_code
            status_text = {200: "OK", 400: "Bad Request", 401: "Unauthorized",
                           403: "Forbidden", 404: "Not Found", 429: "Too Many Requests",
                           500: "Internal Server Error", 502: "Bad Gateway",
                           503: "Service Unavailable"}.get(status, "Unknown")

            writer.write(f"HTTP/1.1 {status} {status_text}{CRLF.decode()}".encode())
            writer.write(f"Content-Type: application/json{CRLF.decode()}".encode())
            writer.write(f"Content-Length: {len(resp_data)}{CRLF.decode()}".encode())
            writer.write(f"Access-Control-Allow-Origin: *{CRLF.decode()}".encode())
            writer.write(CRLF)
            writer.write(resp_data)
            await writer.drain()
        except httpx.TimeoutException:
            await self._send_error(writer, 504, "Upstream timeout")
        except Exception as e:
            await self._send_error(writer, 502, f"Upstream error: {e}")

    async def _proxy_stream(self, writer, url: str, api_key: str, body: dict):
        """Streaming: SSE chunked transfer."""
        import httpx
        try:
            hdrs = {"Content-Type": "application/json"}
            if api_key:
                hdrs["Authorization"] = f"Bearer {api_key}"

            # Write headers first
            writer.write(
                b"HTTP/1.1 200 OK" + CRLF +
                b"Content-Type: text/event-stream" + CRLF +
                b"Cache-Control: no-cache" + CRLF +
                b"Connection: keep-alive" + CRLF +
                b"Access-Control-Allow-Origin: *" + CRLF +
                b"Transfer-Encoding: chunked" + CRLF +
                CRLF
            )
            await writer.drain()

            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream("POST", url, json=body, headers=hdrs) as up_resp:
                    async for chunk in up_resp.aiter_bytes():
                        if chunk:
                            # Write chunked encoding frame
                            chunk_size = f"{len(chunk):x}".encode() + CRLF
                            writer.write(chunk_size)
                            writer.write(chunk)
                            writer.write(CRLF)
                            await writer.drain()

            # Final chunk
            writer.write(b"0" + CRLF + CRLF)
            await writer.drain()
        except (httpx.TimeoutException, ConnectionResetError, BrokenPipeError) as e:
            log.warning(f"Stream error: {e}")
        except Exception as e:
            log.warning(f"Stream error: {e}")
            try:
                data = json.dumps({"error": str(e)}).encode()
                chunk_size = f"{len(data):x}".encode() + CRLF
                writer.write(chunk_size)
                writer.write(data)
                writer.write(CRLF)
                writer.write(b"0" + CRLF + CRLF)
                await writer.drain()
            except Exception:
                pass

    # ── Models endpoint ───────────────────────────────

    async def _handle_models(self, writer: asyncio.StreamWriter, headers: dict):
        if not self._check_auth(headers):
            await self._send_error(writer, 401, "Unauthorized")
            return

        models = await manager.get_all_models()
        # Format like OpenAI /v1/models response
        data = {
            "object": "list",
            "data": [
                {"id": m, "object": "model", "created": int(time.time()), "owned_by": "cliter-proxy"}
                for m in models
            ]
        }
        resp = json.dumps(data).encode()
        writer.write(
            b"HTTP/1.1 200 OK" + CRLF +
            b"Content-Type: application/json" + CRLF +
            f"Content-Length: {len(resp)}".encode() + CRLF +
            b"Access-Control-Allow-Origin: *" + CRLF +
            CRLF + resp
        )
        await writer.drain()

    # ── Health endpoint ───────────────────────────────

    async def _handle_health(self, writer: asyncio.StreamWriter):
        strat_info = await strategy_engine.get_strategy_info()
        mon_info = await monitor.get_monitor_status()
        data = json.dumps({
            "status": "ok",
            "providers": len(await manager.list_providers()),
            "strategy": strat_info["strategy"],
            "available": strat_info["available"],
            "budget": f"{strat_info['daily_used']}/{strat_info['daily_limit']}",
            "monitor": {
                "running": mon_info["running"],
                "active": mon_info["active"],
                "inactive": mon_info["inactive"],
                "rate_limited": mon_info["rate_limited"],
            },
        }).encode()
        writer.write(
            b"HTTP/1.1 200 OK" + CRLF +
            b"Content-Type: application/json" + CRLF +
            f"Content-Length: {len(data)}".encode() + CRLF +
            CRLF + data
        )
        await writer.drain()

    # ── Health check loop (background) ────────────────

    async def _health_check_loop(self):
        while self._running:
            await asyncio.sleep(60)
            # Could ping providers here
            pass

    # ── Helpers ───────────────────────────────────────

    async def _send_error(self, writer, status: int, message: str):
        data = json.dumps({"error": {"message": message, "type": "proxy_error"}}).encode()
        status_text = {400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
                       404: "Not Found", 429: "Too Many Requests", 500: "Internal Server Error",
                       502: "Bad Gateway", 503: "Service Unavailable", 504: "Gateway Timeout"}.get(status, "Error")
        try:
            writer.write(
                f"HTTP/1.1 {status} {status_text}\r\n".encode() +
                b"Content-Type: application/json\r\n" +
                f"Content-Length: {len(data)}\r\n".encode() +
                b"Access-Control-Allow-Origin: *\r\n" +
                b"\r\n" + data
            )
            await writer.drain()
        except Exception:
            pass
