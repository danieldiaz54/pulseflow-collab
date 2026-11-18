"""RFC 6455 WebSocket + REST Gateway built on aiohttp.web for PulseFlow Collab.

Bridges full-duplex WebSocket sessions (`/ws?node=ws-gateway-01&operator=sre-daniela`)
to the `MultiNodePubSubBackplane` replica ring while maintaining strict semantic error
contracts and zero stack-trace leakage.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from src.application.services import PulseFlowApplicationService
from src.domain.collaboration import RealtimeEnvelope
from src.domain.exceptions import (
    IncidentNotFoundError,
    InvalidIncidentError,
    InvalidStateTransitionError,
    OptimisticConcurrencyError,
)


def _map_domain_error(exc: Exception) -> tuple[int, dict[str, Any]]:
    if isinstance(exc, OptimisticConcurrencyError):
        return 409, {
            "error": {
                "code": exc.code,
                "message": str(exc),
                "incident_id": exc.incident_id,
                "expected_version": exc.expected_version,
                "actual_version": exc.actual_version,
            }
        }
    if isinstance(exc, InvalidStateTransitionError):
        return 422, {
            "error": {
                "code": "ERR-422-INVALID-TRANSITION",
                "message": str(exc),
            }
        }
    if isinstance(exc, IncidentNotFoundError):
        return 404, {
            "error": {
                "code": "ERR-404-INCIDENT-NOT-FOUND",
                "message": str(exc),
            }
        }
    if isinstance(exc, InvalidIncidentError):
        return 400, {
            "error": {
                "code": "ERR-400-BAD-REQUEST",
                "message": str(exc),
            }
        }
    return 500, {
        "error": {
            "code": "ERR-500-INTERNAL",
            "message": "An unexpected internal server error occurred.",
        }
    }


def create_aiohttp_ws_app(
    service: PulseFlowApplicationService | None = None,
) -> Any:
    """Create an aiohttp.web.Application exposing full-duplex `/ws` and `/api/v1/*` routes."""
    from aiohttp import WSMsgType, web

    resolved_service = service or PulseFlowApplicationService(auto_seed=True)
    app = web.Application(client_max_size=64 * 1024)
    app["pulseflow_service"] = resolved_service

    active_ws_by_node: dict[str, set[web.WebSocketResponse]] = {
        node: set() for node in resolved_service.backplane.list_nodes()
    }

    def _schedule_fanout(node_id: str, envelope: RealtimeEnvelope) -> None:
        sockets = list(active_ws_by_node.get(node_id, set()))
        if not sockets:
            return
        packet = {
            "type": "realtime.envelope",
            "gateway_node": node_id,
            "envelope": resolved_service._serialize_envelope(envelope),
        }
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        for ws in sockets:
            if not ws.closed:
                loop.create_task(ws.send_json(packet))

    for node_id in resolved_service.backplane.list_nodes():
        active_ws_by_node.setdefault(node_id, set())
        resolved_service.backplane.subscribe(
            node_id,
            lambda env, n=node_id: _schedule_fanout(n, env),
        )

    async def ws_handler(request: web.Request) -> web.WebSocketResponse:
        node = request.query.get("node", "ws-gateway-01").strip() or "ws-gateway-01"
        operator = request.query.get("operator", "sre.daniela").strip() or "sre.daniela"
        incident_id = request.query.get("incident_id", "INC-2026-101").strip() or "INC-2026-101"

        ws = web.WebSocketResponse(heartbeat=30.0)
        await ws.prepare(request)

        if node not in active_ws_by_node:
            active_ws_by_node[node] = set()
            resolved_service.backplane.subscribe(
                node,
                lambda env, n=node: _schedule_fanout(n, env),
            )
        active_ws_by_node[node].add(ws)

        presence = resolved_service.upsert_presence(
            {
                "operator_id": operator,
                "gateway_node": node,
                "active_incident_id": incident_id,
                "observed_version": 1,
            }
        )

        await ws.send_json(
            {
                "type": "ws.connected",
                "gateway_node": node,
                "operator_id": operator,
                "presence": presence,
                "nodes": resolved_service.backplane.list_nodes(),
            }
        )

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        if not isinstance(data, dict):
                            raise InvalidIncidentError("WebSocket message must be a JSON object.")
                    except (ValueError, InvalidIncidentError) as exc:
                        _, err_body = _map_domain_error(
                            InvalidIncidentError(str(exc))
                        )
                        await ws.send_json({"type": "ws.error", "status": 400, **err_body})
                        continue

                    action = str(data.get("action", "")).strip()
                    try:
                        if action == "ping":
                            await ws.send_json({"type": "pong", "gateway_node": node})
                        elif action == "incident.patch":
                            target_id = str(data.get("incident_id", incident_id))
                            patch_payload = dict(data.get("payload") or data)
                            patch_payload.setdefault("actor", operator)
                            patch_payload.setdefault("gateway_node", node)
                            result = resolved_service.update_incident(target_id, patch_payload)
                            await ws.send_json({"type": "incident.patched", "status": 200, "data": result})
                        elif action == "comment.add":
                            target_id = str(data.get("incident_id", incident_id))
                            comment_payload = dict(data.get("payload") or data)
                            comment_payload.setdefault("author", operator)
                            comment_payload.setdefault("gateway_node", node)
                            result = resolved_service.add_comment(target_id, comment_payload)
                            await ws.send_json({"type": "comment.added", "status": 201, "data": result})
                        elif action == "presence.update":
                            presence_payload = dict(data.get("payload") or data)
                            presence_payload.setdefault("operator_id", operator)
                            presence_payload.setdefault("gateway_node", node)
                            updated_presence = resolved_service.upsert_presence(presence_payload)
                            await ws.send_json(
                                {"type": "presence.updated", "status": 200, "presence": updated_presence}
                            )
                        else:
                            raise InvalidIncidentError(f"Unsupported WebSocket action '{action}'.")
                    except Exception as exc:
                        status_code, err_body = _map_domain_error(exc)
                        await ws.send_json({"type": "ws.error", "status": status_code, **err_body})
                elif msg.type == WSMsgType.ERROR:
                    break
        finally:
            active_ws_by_node.get(node, set()).discard(ws)

        return ws

    async def health_handler(_request: web.Request) -> web.Response:
        return web.json_response(resolved_service.get_health(), status=200)

    async def list_incidents_handler(_request: web.Request) -> web.Response:
        items = resolved_service.list_incidents()
        return web.json_response({"incidents": items, "total": len(items)}, status=200)

    async def patch_incident_handler(request: web.Request) -> web.Response:
        inc_id = request.match_info["incident_id"]
        try:
            payload = await request.json()
            result = resolved_service.update_incident(inc_id, payload)
            return web.json_response(result, status=200)
        except json.JSONDecodeError:
            status_code, err_body = _map_domain_error(
                InvalidIncidentError("Malformed JSON in request body.")
            )
            return web.json_response(err_body, status=status_code)
        except Exception as exc:
            status_code, err_body = _map_domain_error(exc)
            return web.json_response(err_body, status=status_code)

    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/api/v1/health", health_handler)
    app.router.add_get("/api/v1/incidents", list_incidents_handler)
    app.router.add_patch("/api/v1/incidents/{incident_id}", patch_incident_handler)

    return app
