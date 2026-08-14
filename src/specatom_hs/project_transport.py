"""Minimal WSGI transports for Plain2MeTTa v2 project queries and commands."""

from __future__ import annotations

import json
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs, unquote

from .project_queries import ProjectQueryService
from .project_commands import ProjectCommandService
from .phase3_review import phase3_review_log_from_dict
from .projects import ArtifactKind


StartResponse = Callable[[str, list[tuple[str, str]]], Any]
MAX_COMMAND_BYTES = 1_048_576


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
        if resource == "review":
            self._query(query_string, ())
            return self._queries.phase3_review(project_id)
        if resource == "review-decisions":
            self._query(query_string, ())
            return self._queries.phase3_review_decisions(project_id)
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


class ProjectCommandApplication:
    """Expose only bounded JSON author/review commands without starting a server."""

    def __init__(self, commands: ProjectCommandService):
        self._commands = commands

    def __call__(self, environ: dict[str, Any], start_response: StartResponse) -> Iterable[bytes]:
        if environ.get("REQUEST_METHOD") != "POST":
            return self._respond(start_response, 405, {"error": "method_not_allowed"}, (("Allow", "POST"),))
        try:
            payload = self._read_json(environ)
            result = self._route(environ.get("PATH_INFO"), environ.get("QUERY_STRING", ""), payload)
        except FileExistsError:
            return self._respond(start_response, 409, {"error": "conflict"})
        except FileNotFoundError:
            return self._respond(start_response, 404, {"error": "not_found"})
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return self._respond(start_response, 400, {"error": "invalid_request", "detail": str(exc)})
        return self._respond(start_response, 201 if result["command"] == "create_project" else 200, result)

    def _route(self, raw_path: Any, query_string: Any, payload: Any) -> dict[str, Any]:
        if not isinstance(raw_path, str) or not isinstance(query_string, str):
            raise ValueError("request path and query must be text")
        if query_string:
            raise ValueError("command routes do not accept query parameters")
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")

        if raw_path == "/api/projects":
            self._exact_keys(payload, {"project_id", "name", "source"})
            project = self._commands.create_project(payload["project_id"], payload["name"], payload["source"])
            return {"command": "create_project", "project_id": project.project_id}

        review_parts = raw_path.split("/")
        if len(review_parts) == 4 and review_parts[:3] == ["", "api", "review"]:
            encoded_project_id = review_parts[3]
            if not encoded_project_id:
                raise KeyError("unknown route")
            project_id = unquote(encoded_project_id, errors="strict")
            if "/" in project_id or project_id != encoded_project_id:
                raise ValueError("project_id path segment must use canonical unescaped ASCII")
            review_log = phase3_review_log_from_dict(payload)
            project = self._commands.submit_phase3_review(project_id, review_log)
            artifact = project.current(ArtifactKind.REVIEW_LOG)
            return {
                "command": "submit_phase3_review",
                "project_id": project.project_id,
                "review_log_artifact_id": artifact.artifact_id,
                "review_log_content_hash": artifact.content_hash,
            }

        parts = raw_path.split("/")
        if len(parts) != 5 or parts[:2] != ["", "api"] or parts[2] != "projects":
            raise KeyError("unknown route")
        encoded_project_id, command = parts[3:]
        project_id = unquote(encoded_project_id, errors="strict")
        if "/" in project_id or project_id != encoded_project_id:
            raise ValueError("project_id path segment must use canonical unescaped ASCII")

        common = {"artifact_id", "content_hash"}
        if command == "annotations":
            self._exact_keys(payload, common | {"reviewer", "comment"}, {"target"})
            project = self._commands.add_annotation(project_id, **payload)
            return {"command": "add_annotation", "project_id": project.project_id,
                    "annotation_count": len(project.annotations)}
        if command == "decisions":
            self._exact_keys(payload, common | {"decision"}, {"reviewer", "rationale"})
            project = self._commands.submit_decision(project_id, **payload)
            return {"command": "submit_decision", "project_id": project.project_id,
                    "approval_count": len(project.approvals)}
        submission = {
            "elaborated-spec": self._commands.submit_elaborated_spec,
            "test-spec": self._commands.submit_test_spec,
        }.get(command)
        if submission is not None:
            self._exact_keys(payload, {"upstream_artifact_id", "upstream_content_hash", "content"})
            project = submission(project_id, **payload)
            artifact = project.current(
                ArtifactKind.ELABORATED_SPEC if command == "elaborated-spec" else ArtifactKind.TEST_SPEC
            )
            return {"command": f"submit_{command.replace('-', '_')}", "project_id": project.project_id,
                    "artifact_id": artifact.artifact_id, "content_hash": artifact.content_hash}
        raise KeyError("unknown route")

    @staticmethod
    def _read_json(environ: dict[str, Any]) -> Any:
        if environ.get("CONTENT_TYPE") != "application/json":
            raise ValueError("Content-Type must be application/json")
        if environ.get("HTTP_TRANSFER_ENCODING") is not None:
            raise ValueError("Transfer-Encoding is not accepted")
        raw_length = environ.get("CONTENT_LENGTH")
        if not isinstance(raw_length, str) or not raw_length.isascii() or not raw_length.isdigit():
            raise ValueError("Content-Length must be an explicit decimal byte count")
        if len(raw_length) > 1 and raw_length.startswith("0"):
            raise ValueError("Content-Length must use canonical decimal form")
        length = int(raw_length)
        if length <= 0 or length > MAX_COMMAND_BYTES:
            raise ValueError("request body length is outside the accepted bound")
        stream = environ.get("wsgi.input")
        if stream is None or not hasattr(stream, "read"):
            raise ValueError("request body stream is missing")
        body = stream.read(length)
        if not isinstance(body, bytes) or len(body) != length:
            raise ValueError("request body does not match Content-Length")
        try:
            text = body.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValueError("request body must be UTF-8") from exc

        def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in items:
                if key in result:
                    raise ValueError("duplicate JSON object key")
                result[key] = value
            return result

        def refuse_constant(value: str) -> Any:
            raise ValueError("non-finite JSON number")

        return json.loads(text, object_pairs_hook=pairs, parse_constant=refuse_constant)

    @staticmethod
    def _exact_keys(
        payload: dict[str, Any], required: set[str], optional: set[str] | None = None
    ) -> None:
        optional = optional or set()
        keys = set(payload)
        if not all(isinstance(key, str) for key in payload) or not required <= keys or keys - required - optional:
            raise ValueError("request body fields do not match the command schema")

    @staticmethod
    def _respond(
        start_response: StartResponse,
        status: int,
        payload: Any,
        extra_headers: tuple[tuple[str, str], ...] = (),
    ) -> tuple[bytes]:
        body = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        reason = {200: "OK", 201: "Created", 400: "Bad Request", 404: "Not Found",
                  405: "Method Not Allowed", 409: "Conflict"}[status]
        headers = [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body)))]
        headers.extend(extra_headers)
        start_response(f"{status} {reason}", headers)
        return (body,)
