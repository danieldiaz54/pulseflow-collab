"""End-to-End HTTP REST, Server-Sent Events (SSE), and Multi-Node Pub/Sub integration tests.

Covers:
1. Starting `create_http_server("127.0.0.1", 0)` in a daemon thread.
2. `GET /` (200 HTML Workbench), `GET /api/v1/health` (200), `GET /api/v1/incidents` (200 with 5 incidents).
3. `POST /api/v1/incidents` (`201 Created` on valid payload, `400 Bad Request` on invalid payload).
4. `PATCH /api/v1/incidents/INC-2026-101`:
   - Valid update (`expected_version: 1`) -> `200 OK` (`version: 2`, `incident.updated` broadcast to `ws-gateway-01` and `ws-gateway-02`).
   - Stale concurrent update (`expected_version: 1`) -> `409 Conflict` (`error.code == "ERR-409-OPTIMISTIC-LOCK"`, `expected_version == 1`, `actual_version == 2`, and `incident.conflict_rejected` recorded in `/api/v1/events/backplane`).
   - Invalid state transition -> `422 Unprocessable Entity` with zero stack traces.
   - Non-existent incident -> `404 Not Found`.
5. `POST /api/v1/incidents/INC-2026-101/comments` (`201 Created`), `GET /api/v1/audit/ledger` (`200 OK`), and `GET /api/v1/events/stream` (`200 OK`, `text/event-stream`).
"""

from __future__ import annotations

import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from src.application.services import PulseFlowApplicationService
from src.interfaces.http.server import create_http_server


class TestHttpSseAndMultiNodeBackplaneIntegration(unittest.TestCase):
    """End-to-end integration test suite against a live ThreadingHTTPServer."""

    def setUp(self) -> None:
        self.service = PulseFlowApplicationService(db_path=":memory:", auto_seed=True)
        self.server = create_http_server(host="127.0.0.1", port=0, service=self.service)
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.service.repository.close()
        self.server_thread.join(timeout=3.0)

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> tuple[int, dict[str, str], dict[str, object]]:
        url = f"{self.base_url}{path}"
        headers = {"Accept": "application/json"}
        body_bytes: bytes | None = None
        if payload is not None:
            body_bytes = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"

        req = Request(url, data=body_bytes, headers=headers, method=method)
        try:
            with urlopen(req, timeout=5.0) as resp:
                raw = resp.read().decode("utf-8")
                hdrs = {k.lower(): v for k, v in resp.headers.items()}
                return resp.status, hdrs, json.loads(raw)
        except HTTPError as err:
            raw = err.read().decode("utf-8")
            hdrs = {k.lower(): v for k, v in err.headers.items()}
            return err.code, hdrs, json.loads(raw)

    def test_get_workbench_ui_health_and_seeded_incidents(self) -> None:
        # 1. GET / -> 200 HTML Workbench
        with urlopen(f"{self.base_url}/", timeout=5.0) as ui_resp:
            html = ui_resp.read().decode("utf-8")
            self.assertEqual(ui_resp.status, 200)
            self.assertIn("text/html", ui_resp.headers.get("Content-Type", ""))
            self.assertIn("PulseFlow", html)

        # 2. GET /api/v1/health -> 200 OK
        status, headers, health = self._request_json("GET", "/api/v1/health")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["incident_count"], 5)
        self.assertEqual(health["gateway_nodes"], ["ws-gateway-01", "ws-gateway-02"])

        # 3. GET /api/v1/incidents -> 200 OK with 5 incidents
        status, _, incidents_body = self._request_json("GET", "/api/v1/incidents")
        self.assertEqual(status, 200)
        self.assertEqual(incidents_body["total"], 5)
        incidents = incidents_body["incidents"]
        self.assertIsInstance(incidents, list)
        self.assertEqual(len(incidents), 5)  # type: ignore[arg-type]

    def test_post_create_incident_201_and_400_validation(self) -> None:
        valid_payload = {
            "incident_id": "INC-2026-106",
            "title": "Envoy Ingress TLS Handshake Latency",
            "service_name": "edge-envoy-proxy",
            "severity": "SEV2",
            "status": "OPEN",
            "commander": "sre.daniela",
            "summary": "Elevated TLS handshake time in eu-central-1 ingress tier.",
            "actor": "sre.daniela",
            "gateway_node": "ws-gateway-01",
        }
        status, _, created = self._request_json("POST", "/api/v1/incidents", valid_payload)
        self.assertEqual(status, 201)
        self.assertEqual(created["incident"]["incident_id"], "INC-2026-106")  # type: ignore[index]
        self.assertEqual(created["incident"]["version"], 1)  # type: ignore[index]
        self.assertEqual(created["audit"]["action"], "INCIDENT_CREATED")  # type: ignore[index]
        self.assertEqual(created["event"]["event_type"], "incident.created")  # type: ignore[index]

        # Invalid payload (empty title & invalid severity) -> 400 Bad Request
        invalid_payload = {
            "title": "   ",
            "service_name": "edge-envoy-proxy",
            "severity": "SEV9",
            "commander": "sre.daniela",
            "summary": "Missing title.",
        }
        err_status, _, err_body = self._request_json("POST", "/api/v1/incidents", invalid_payload)
        self.assertEqual(err_status, 400)
        self.assertEqual(err_body["error"]["code"], "ERR-400-BAD-REQUEST")  # type: ignore[index]
        self.assertNotIn("Traceback", json.dumps(err_body))

    def test_patch_incident_occ_200_conflict_409_transition_422_and_not_found_404(self) -> None:
        # 1. Valid PATCH update (expected_version: 1 -> version: 2)
        patch_v2 = {
            "expected_version": 1,
            "actor": "sre.valeria",
            "gateway_node": "ws-gateway-01",
            "status": "MITIGATED",
            "summary": "Pub/Sub shard buffer limits tuned; p99 fan-out stabilized at 24ms.",
        }
        status, _, body_v2 = self._request_json(
            "PATCH",
            "/api/v1/incidents/INC-2026-101",
            patch_v2,
        )
        self.assertEqual(status, 200)
        self.assertEqual(body_v2["incident"]["version"], 2)  # type: ignore[index]
        self.assertEqual(body_v2["incident"]["status"], "MITIGATED")  # type: ignore[index]
        self.assertEqual(body_v2["event"]["event_type"], "incident.updated")  # type: ignore[index]

        # Verify fan-out to both ws-gateway-01 and ws-gateway-02
        _, _, backplane = self._request_json("GET", "/api/v1/events/backplane")
        counts = backplane["node_delivery_counts"]  # type: ignore[index]
        self.assertGreaterEqual(counts["ws-gateway-01"], 2)  # type: ignore[index]
        self.assertEqual(counts["ws-gateway-01"], counts["ws-gateway-02"])  # type: ignore[index]

        # 2. Stale concurrent PATCH update (expected_version: 1 when actual is 2) -> 409 Conflict
        stale_patch = {
            "expected_version": 1,
            "actor": "netops.carlos",
            "gateway_node": "ws-gateway-02",
            "status": "RESOLVED",
            "summary": "Concurrent attempt with stale expected_version=1.",
        }
        status_409, _, body_409 = self._request_json(
            "PATCH",
            "/api/v1/incidents/INC-2026-101",
            stale_patch,
        )
        self.assertEqual(status_409, 409)
        err_409 = body_409["error"]  # type: ignore[index]
        self.assertEqual(err_409["code"], "ERR-409-OPTIMISTIC-LOCK")  # type: ignore[index]
        self.assertEqual(err_409["incident_id"], "INC-2026-101")  # type: ignore[index]
        self.assertEqual(err_409["expected_version"], 1)  # type: ignore[index]
        self.assertEqual(err_409["actual_version"], 2)  # type: ignore[index]
        self.assertNotIn("Traceback", json.dumps(body_409))

        # Verify incident.conflict_rejected was broadcast on backplane
        _, _, backplane_after_409 = self._request_json("GET", "/api/v1/events/backplane")
        event_types = [e["event_type"] for e in backplane_after_409["events"]]  # type: ignore[index]
        self.assertIn("incident.conflict_rejected", event_types)

        # 3. Invalid state transition (MITIGATED -> OPEN is disallowed) -> 422 Unprocessable Entity
        invalid_transition_patch = {
            "expected_version": 2,
            "actor": "sre.valeria",
            "gateway_node": "ws-gateway-01",
            "status": "OPEN",
        }
        status_422, _, body_422 = self._request_json(
            "PATCH",
            "/api/v1/incidents/INC-2026-101",
            invalid_transition_patch,
        )
        self.assertEqual(status_422, 422)
        self.assertEqual(body_422["error"]["code"], "ERR-422-INVALID-TRANSITION")  # type: ignore[index]
        self.assertNotIn("Traceback", json.dumps(body_422))

        # 4. Non-existent incident -> 404 Not Found
        status_404, _, body_404 = self._request_json(
            "PATCH",
            "/api/v1/incidents/INC-DOES-NOT-EXIST",
            {
                "expected_version": 1,
                "actor": "sre.valeria",
                "summary": "No such incident.",
            },
        )
        self.assertEqual(status_404, 404)
        self.assertEqual(body_404["error"]["code"], "ERR-404-INCIDENT-NOT-FOUND")  # type: ignore[index]

    def test_comments_audit_ledger_and_sse_event_stream(self) -> None:
        # 1. POST /api/v1/incidents/INC-2026-101/comments -> 201 Created
        comment_payload = {
            "author": "netops.carlos",
            "body": "Confirmed zero packet drops across ws-gateway-01 and ws-gateway-02.",
            "gateway_node": "ws-gateway-02",
        }
        status, _, comment_res = self._request_json(
            "POST",
            "/api/v1/incidents/INC-2026-101/comments",
            comment_payload,
        )
        self.assertEqual(status, 201)
        self.assertEqual(comment_res["comment"]["author"], "netops.carlos")  # type: ignore[index]
        self.assertEqual(comment_res["audit"]["action"], "COMMENT_ADDED")  # type: ignore[index]
        self.assertEqual(comment_res["event"]["event_type"], "comment.added")  # type: ignore[index]

        # 2. GET /api/v1/audit/ledger?incident_id=INC-2026-101 -> 200 OK
        status_audit, _, audit_res = self._request_json(
            "GET",
            "/api/v1/audit/ledger?incident_id=INC-2026-101",
        )
        self.assertEqual(status_audit, 200)
        self.assertGreaterEqual(audit_res["total"], 4)  # type: ignore[arg-type]

        # 3. GET /api/v1/events/stream -> 200 OK (text/event-stream)
        with urlopen(f"{self.base_url}/api/v1/events/stream?node=ws-gateway-02", timeout=5.0) as sse_resp:
            sse_body = sse_resp.read().decode("utf-8")
            self.assertEqual(sse_resp.status, 200)
            self.assertIn("text/event-stream", sse_resp.headers.get("Content-Type", ""))
            self.assertIn("event: connected", sse_body)
            self.assertIn("event: comment.added", sse_body)


if __name__ == "__main__":
    unittest.main()
