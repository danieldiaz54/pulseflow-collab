"""Main entrypoint for the PulseFlow Collab Incident Command & Multi-Node Sync Server."""

from __future__ import annotations

from src.interfaces.http.server import create_http_server, main

__all__ = ["create_http_server", "main"]

if __name__ == "__main__":
    main()
