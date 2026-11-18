"""Multi-threaded HTTP + SSE server for PulseFlow Collab.

Built on Python 3.12's `ThreadingHTTPServer` and `BaseHTTPRequestHandler` with
strict DTO contracts, 64 KB payload limits, security headers, and semantic mapping
of domain exceptions (`400`, `404`, `409`, `422`, `500`) without leaking stack traces.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from src.application.services import PulseFlowApplicationService
from src.domain.collaboration import RealtimeEnvelope
from src.domain.exceptions import (
    IncidentNotFoundError,
    InvalidIncidentError,
    InvalidStateTransitionError,
    OptimisticConcurrencyError,
)

MAX_JSON_BODY_BYTES: int = 64 * 1024  # 64 KB strict payload ceiling

_INCIDENT_ID_ROUTE = re.compile(r"^/api/v1/incidents/([^/]+)$")
_INCIDENT_COMMENTS_ROUTE = re.compile(r"^/api/v1/incidents/([^/]+)/comments$")
_REPO_ROOT = Path(__file__).resolve().parents[3]
_UI_INDEX_PATH = _REPO_ROOT / "ui" / "index.html"


class PulseFlowHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer bound to a PulseFlowApplicationService instance."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        RequestHandlerClass: type[BaseHTTPRequestHandler],
        service: PulseFlowApplicationService,
    ) -> None:
        super().__init__(server_address, RequestHandlerClass)
        self.service: PulseFlowApplicationService = service


class PulseFlowRequestHandler(BaseHTTPRequestHandler):
    """HTTP + SSE request handler implementing the PulseFlow Collab REST API."""

    protocol_version = "HTTP/1.1"

    @property
    def app_service(self) -> PulseFlowApplicationService:
        server = self.server
        if isinstance(server, PulseFlowHTTPServer):
            return server.service
        raise RuntimeError("Server is not a PulseFlowHTTPServer.")

    def log_message(self, format: str, *args: Any) -> None:
        """Silence noisy access logs during automated test runs unless PULSEFLOW_HTTP_LOG=1."""
        if os.environ.get("PULSEFLOW_HTTP_LOG") == "1":
            super().log_message(format, *args)

    def _send_security_and_cors_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization, X-Actor, X-Gateway-Node",
        )

    def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self._send_security_and_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status_code: int, html_bytes: bytes) -> None:
        self.send_response(status_code)
        self._send_security_and_cors_headers()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html_bytes)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(html_bytes)

    def _send_error_json(
        self,
        status_code: int,
        code: str,
        message: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        error_obj: dict[str, Any] = {
            "code": code,
            "message": message,
        }
        if extra:
            error_obj.update(extra)
        self._send_json(status_code, {"error": error_obj})

    def _read_json_body(self) -> dict[str, Any]:
        transfer_encoding = self.headers.get("Transfer-Encoding", "")
        if "chunked" in transfer_encoding.lower():
            raise InvalidIncidentError("Chunked transfer encoding is not supported.")

        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise InvalidIncidentError("Missing Content-Length header.")
        try:
            content_length = int(raw_length)
        except ValueError as exc:
            raise InvalidIncidentError("Invalid Content-Length header.") from exc

        if content_length < 0:
            raise InvalidIncidentError("Negative Content-Length is invalid.")
        if content_length > MAX_JSON_BODY_BYTES:
            raise InvalidIncidentError(
                f"Request body exceeds maximum size of {MAX_JSON_BODY_BYTES} bytes (64 KB)."
            )
        if content_length == 0:
            raise InvalidIncidentError("Request body cannot be empty.")

        raw_bytes = self.rfile.read(content_length)
        try:
            decoded = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InvalidIncidentError("Request body must be valid UTF-8.") from exc

        try:
            parsed = json.loads(decoded)
        except json.JSONDecodeError as exc:
            raise InvalidIncidentError("Malformed JSON in request body.") from exc

        if not isinstance(parsed, dict):
            raise InvalidIncidentError("JSON payload root must be an object.")
        return parsed

    def _handle_domain_exception(self, exc: Exception) -> None:
        if isinstance(exc, OptimisticConcurrencyError):
            self._send_error_json(
                409,
                exc.code,
                str(exc),
                extra={
                    "incident_id": exc.incident_id,
                    "expected_version": exc.expected_version,
                    "actual_version": exc.actual_version,
                },
            )
        elif isinstance(exc, InvalidStateTransitionError):
            self._send_error_json(
                422,
                "ERR-422-INVALID-TRANSITION",
                str(exc),
            )
        elif isinstance(exc, IncidentNotFoundError):
            self._send_error_json(
                404,
                "ERR-404-INCIDENT-NOT-FOUND",
                str(exc),
            )
        elif isinstance(exc, InvalidIncidentError):
            self._send_error_json(
                400,
                "ERR-400-BAD-REQUEST",
                str(exc),
            )
        else:
            self._send_error_json(
                500,
                "ERR-500-INTERNAL",
                "An unexpected internal server error occurred.",
            )

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_security_and_cors_headers()
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path.rstrip("/") or "/"
        query = parse_qs(parsed_url.query)

        try:
            if path in ("/", "/ui", "/ui/index.html"):
                self._serve_ui()
                return

            if path == "/api/v1/health":
                self._send_json(200, self.app_service.get_health())
                return

            if path == "/api/v1/incidents":
                incidents = self.app_service.list_incidents()
                self._send_json(200, {"incidents": incidents, "total": len(incidents)})
                return

            incident_match = _INCIDENT_ID_ROUTE.match(path)
            if incident_match:
                incident_id = incident_match.group(1)
                detail = self.app_service.get_incident_detail(incident_id)
                self._send_json(200, detail)
                return

            if path == "/api/v1/presence":
                incident_filter = query.get("incident_id", [None])[0]
                sessions = self.app_service.list_presence(incident_id=incident_filter)
                self._send_json(200, {"presence": sessions, "total": len(sessions)})
                return

            if path == "/api/v1/events/backplane":
                limit_str = query.get("limit", ["50"])[0]
                try:
                    limit = int(limit_str)
                except ValueError as exc:
                    raise InvalidIncidentError("Query parameter 'limit' must be an integer.") from exc
                self._send_json(200, self.app_service.list_backplane_events(limit=limit))
                return

            if path == "/api/v1/events/stream":
                self._serve_sse_stream(query)
                return

            if path == "/api/v1/audit/ledger":
                incident_filter = query.get("incident_id", [None])[0]
                limit_str = query.get("limit", ["100"])[0]
                try:
                    limit = int(limit_str)
                except ValueError as exc:
                    raise InvalidIncidentError("Query parameter 'limit' must be an integer.") from exc
                entries = self.app_service.list_audit_ledger(
                    incident_id=incident_filter,
                    limit=limit,
                )
                self._send_json(
                    200,
                    {
                        "entries": entries,
                        "ledger": entries,
                        "total": len(entries),
                    },
                )
                return

            self._send_error_json(
                404,
                "ERR-404-NOT-FOUND",
                f"Route '{path}' was not found.",
            )
        except Exception as exc:
            self._handle_domain_exception(exc)

    def do_POST(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path.rstrip("/") or "/"

        try:
            if path == "/api/v1/incidents":
                payload = self._read_json_body()
                result = self.app_service.create_incident(payload)
                self._send_json(201, result)
                return

            comments_match = _INCIDENT_COMMENTS_ROUTE.match(path)
            if comments_match:
                incident_id = comments_match.group(1)
                payload = self._read_json_body()
                result = self.app_service.add_comment(incident_id, payload)
                self._send_json(201, result)
                return

            if path == "/api/v1/presence":
                payload = self._read_json_body()
                session = self.app_service.upsert_presence(payload)
                self._send_json(200, {"presence": session})
                return

            self._send_error_json(
                404,
                "ERR-404-NOT-FOUND",
                f"Route '{path}' was not found.",
            )
        except Exception as exc:
            self._handle_domain_exception(exc)

    def do_PATCH(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path.rstrip("/") or "/"

        try:
            incident_match = _INCIDENT_ID_ROUTE.match(path)
            if incident_match:
                incident_id = incident_match.group(1)
                payload = self._read_json_body()
                result = self.app_service.update_incident(incident_id, payload)
                self._send_json(200, result)
                return

            self._send_error_json(
                404,
                "ERR-404-NOT-FOUND",
                f"Route '{path}' was not found.",
            )
        except Exception as exc:
            self._handle_domain_exception(exc)

    def _serve_ui(self) -> None:
        if _UI_INDEX_PATH.exists():
            html_bytes = _UI_INDEX_PATH.read_bytes()
            self._send_html(200, html_bytes)
            return

        fallback = (
            "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<title>PulseFlow Collab — Incident Command War-Room</title></head>"
            "<body><h1>PulseFlow Collab API Server Ready</h1></body></html>"
        ).encode("utf-8")
        self._send_html(200, fallback)

    def _serve_sse_stream(self, query: dict[str, list[str]]) -> None:
        """Stream backplane events over Server-Sent Events (SSE)."""
        node_id = query.get("node", ["ws-gateway-01"])[0]
        follow = query.get("follow", ["0"])[0] == "1"

        backplane_snapshot = self.app_service.list_backplane_events(limit=25)
        frames: list[str] = []

        connected_data = json.dumps(
            {
                "status": "connected",
                "gateway_node": node_id,
                "nodes": backplane_snapshot["nodes"],
            },
            ensure_ascii=False,
        )
        frames.append(f"event: connected\ndata: {connected_data}\n\n")

        for env in backplane_snapshot["events"]:
            data_str = json.dumps(env, ensure_ascii=False)
            frames.append(
                f"id: {env['event_id']}\nevent: {env['event_type']}\ndata: {data_str}\n\n"
            )

        payload_bytes = "".join(frames).encode("utf-8")

        self.send_response(200)
        self._send_security_and_cors_headers()
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        if not follow:
            self.send_header("Content-Length", str(len(payload_bytes)))
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload_bytes)
        self.wfile.flush()

        if follow:
            event_queue: queue.Queue[RealtimeEnvelope] = queue.Queue()
            self.app_service.backplane.subscribe(node_id, event_queue.put)
            try:
                env = event_queue.get(timeout=5.0)
                serialized = self.app_service._serialize_envelope(env)
                frame = (
                    f"id: {serialized['event_id']}\n"
                    f"event: {serialized['event_type']}\n"
                    f"data: {json.dumps(serialized, ensure_ascii=False)}\n\n"
                ).encode("utf-8")
                self.wfile.write(frame)
                self.wfile.flush()
            except (queue.Empty, OSError):
                pass


def create_http_server(
    host: str = "127.0.0.1",
    port: int = 8095,
    service: PulseFlowApplicationService | None = None,
) -> PulseFlowHTTPServer:
    """Create and configure a multi-threaded PulseFlow HTTP + SSE server."""
    resolved_service = service or PulseFlowApplicationService(
        db_path=os.environ.get("PULSEFLOW_SQLITE_PATH", ":memory:"),
        auto_seed=True,
    )
    return PulseFlowHTTPServer((host, port), PulseFlowRequestHandler, resolved_service)


def main() -> None:
    host = os.environ.get("PULSEFLOW_HOST", "0.0.0.0")
    port = int(os.environ.get("PULSEFLOW_PORT", "8095"))
    server = create_http_server(host=host, port=port)
    bound_host, bound_port = server.server_address
    print(
        f"[PulseFlow Collab] Incident Command & Multi-Node Sync Engine listening on "
        f"http://{bound_host}:{bound_port}"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
