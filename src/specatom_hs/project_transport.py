"""Minimal read-only WSGI transport for Plain2MeTTa v2 project queries."""

from __future__ import annotations

import json
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs, unquote

from .project_queries import ProjectQueryService


StartResponse = Callable[[str, list[tuple[str, str]]], Any]


class ReadOnlyProjectApplication:
    """Expose query-service results over exact GET routes without starting a server."""

    def __init__(self, queries: ProjectQueryService):
        self._queries = queries

    def __call__(self, environ: dict[str, Any], start_response: StartResponse) -> Iterable[bytes]:
        method = environ.get("REQUEST_METHOD")
        if method != "GET":
            return self._respond(start_response, 405, {"error": "method_not_allowed"}, (("Allow", "GET"),))

        try:
            payload = self._route(environ.get("PATH_INFO"), environ.get("QUERY_STRING", ""))
        except FileNotFoundError:
            return self._respond(start_response, 404, {"error": "not_found"})
        except KeyError:
            return self._respond(start_response, 404, {"error": "not_found"})
        except ValueError as exc:
            return self._respond(start_response, 400, {"error": "invalid_request", "detail": str(exc)})
        return self._respond(start_response, 200, payload)

    def _route(self, raw_path: Any, query_string: Any) -> Any:
        if not isinstance(raw_path, str) or not isinstance(query_string, str):
            raise ValueError("request path and query must be text")
        if raw_path == "/api/projects":
            self._query(query_string, ())
            return {"projects": self._queries.list_projects()}

        parts = raw_path.split("/")
        if len(parts) != 4 or parts[:2] != ["", "api"] or not parts[2] or not parts[3]:
            raise KeyError("unknown route")
        resource, encoded_project_id = parts[2:]
        project_id = unquote(encoded_project_id, errors="strict")
        if "/" in project_id or project_id != encoded_project_id:
            # Canonical paths avoid alternate identities and encoded-separator routing.
            raise ValueError("project_id path segment must use canonical unescaped ASCII")

        if resource == "projects":
            self._query(query_string, ())
            return self._queries.status(project_id)
        if resource == "versions":
            self._query(query_string, ())
            return {"project_id": project_id, "versions": self._queries.version_history(project_id)}
        if resource == "trace":
            query = self._query(query_string, ("spec_id",))
            return self._queries.trace(project_id, query.get("spec_id"))
        raise KeyError("unknown route")

    @staticmethod
    def _query(query_string: str, allowed: tuple[str, ...]) -> dict[str, str]:
        if not query_string:
            return {}
        parsed = parse_qs(query_string, keep_blank_values=True, strict_parsing=True)
        unknown = set(parsed) - set(allowed)
        if unknown:
            raise ValueError("unknown query parameter")
        if any(len(values) != 1 for values in parsed.values()):
            raise ValueError("query parameters must occur at most once")
        return {key: values[0] for key, values in parsed.items()}

    @staticmethod
    def _respond(
        start_response: StartResponse,
        status: int,
        payload: Any,
        extra_headers: tuple[tuple[str, str], ...] = (),
    ) -> tuple[bytes]:
        body = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        reason = {200: "OK", 400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed"}[status]
        headers = [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body)))]
        headers.extend(extra_headers)
        start_response(f"{status} {reason}", headers)
        return (body,)
