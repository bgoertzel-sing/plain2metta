"""Bounded Stage-9 API over immutable semantic project artifacts."""

from __future__ import annotations

import io
import json
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import parse_qs, unquote

from .project_repository import FilesystemProjectRepository, validate_project_id
from .projects import ApprovalDecision, ArtifactKind, ArtifactRef, ArtifactState
from .semantic_artifacts import validate_semantic_artifact
from .validation_plan import PlanReview, submit_plan_review, validate_plan_review_chain

MAX_SEMANTIC_REQUEST_BYTES = 128_000
SEMANTIC_KINDS = {
    ArtifactKind.SEMANTIC_CONTRACT, ArtifactKind.VALIDATION_OBLIGATION,
    ArtifactKind.VALIDATION_PLAN, ArtifactKind.VALIDATION_PLAN_REVIEW,
    ArtifactKind.INPUT_GENERATOR, ArtifactKind.VALIDATION_ORACLE,
    ArtifactKind.RUNTIME_EVIDENCE, ArtifactKind.COUNTEREXAMPLE,
    ArtifactKind.VALIDATION_VERDICT,
}


def _ref(ref: ArtifactRef) -> dict[str, str]:
    return {"artifact_id": ref.artifact_id, "content_hash": ref.content_hash}


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


class SemanticValidationService:
    """Atomic command and metadata query seam; providers/runners are injected."""

    def __init__(self, repository: FilesystemProjectRepository, *, plan_author=None, executor=None):
        self.repository = repository
        self.plan_author = plan_author
        self.executor = executor

    def plan(self, project_id: str) -> dict[str, Any]:
        project = self.repository.get(validate_project_id(project_id))
        validate_plan_review_chain(project)
        plan = project.current(ArtifactKind.VALIDATION_PLAN)
        review = project.current(ArtifactKind.VALIDATION_PLAN_REVIEW)
        return {"project_id": project_id, "plan": self._metadata(plan), "review": self._metadata(review)}

    def synthesize_plan(self, project_id: str) -> dict[str, Any]:
        if self.plan_author is None:
            raise LookupError("validation-plan author is not configured")
        before = self.repository.get(validate_project_id(project_id))
        after = self.plan_author.synthesize(before)
        self.repository.save(after)
        return self.plan(project_id)

    def review_plan(self, project_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        fields = {"plan", "decision", "reviewer", "rationale", "timestamp", "edited_plan_payload"}
        if set(payload) != fields:
            raise ValueError("plan review has unknown or missing fields")
        plan = payload["plan"]
        if not isinstance(plan, Mapping) or set(plan) != {"artifact_id", "content_hash"}:
            raise ValueError("plan reference is malformed")
        try:
            decision = ApprovalDecision(payload["decision"])
        except (TypeError, ValueError) as exc:
            raise ValueError("plan decision is invalid") from exc
        project = self.repository.get(validate_project_id(project_id))
        updated = submit_plan_review(project, PlanReview(
            ArtifactRef(plan["artifact_id"], plan["content_hash"]), decision,
            payload["reviewer"], payload["rationale"], payload["timestamp"],
            payload["edited_plan_payload"],
        ))
        self.repository.save(updated)
        return self.plan(project_id)

    def execute(self, project_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        if self.executor is None:
            raise LookupError("semantic executor is not configured")
        if set(payload) != {"obligation", "implementation"}:
            raise ValueError("semantic execution request has unknown or missing fields")
        before = self.repository.get(validate_project_id(project_id))
        after = self.executor.execute_once(before, payload["obligation"], payload["implementation"])
        self.repository.save(after)
        return self.results(project_id)

    def results(self, project_id: str) -> dict[str, Any]:
        project = self.repository.get(validate_project_id(project_id))
        validate_plan_review_chain(project)
        artifacts = [self._metadata(a) for a in project.artifacts
                     if a.state is ArtifactState.CURRENT and a.kind in SEMANTIC_KINDS]
        return {"project_id": project_id, "artifacts": artifacts,
                "grade_legend": {f"G{i}": label for i, label in enumerate(
                    ("structured", "contracted", "executed", "oracle-tested", "property-tested", "formally-checked", "operationally-observed"))}}

    def trace(self, project_id: str, obligation_id: str) -> dict[str, Any]:
        project = self.repository.get(validate_project_id(project_id))
        validate_plan_review_chain(project)
        matches = []
        for artifact in project.artifacts:
            if artifact.state is not ArtifactState.CURRENT or artifact.kind is not ArtifactKind.VALIDATION_OBLIGATION:
                continue
            document = json.loads(artifact.content); validate_semantic_artifact(document)
            if document["payload"]["obligation_id"] == obligation_id:
                matches.append(artifact)
        if len(matches) != 1:
            raise KeyError("obligation not found or ambiguous")
        wanted = {matches[0].ref}; changed = True
        while changed:
            changed = False
            for artifact in project.artifacts:
                if artifact.state is ArtifactState.CURRENT and artifact.kind in SEMANTIC_KINDS and any(ref in wanted for ref in artifact.upstream):
                    if artifact.ref not in wanted: wanted.add(artifact.ref); changed = True
        nodes = [self._metadata(a) for a in project.artifacts if a.ref in wanted]
        edges = [{"from": _ref(upstream), "to": _ref(a.ref)} for a in project.artifacts if a.ref in wanted for upstream in a.upstream if upstream in wanted]
        return {"project_id": project_id, "obligation": obligation_id, "nodes": nodes, "edges": edges}

    def artifact_body(self, project_id: str, artifact_id: str, digest: str) -> dict[str, Any]:
        project = self.repository.get(validate_project_id(project_id))
        artifact = project.artifact(artifact_id)
        if artifact.kind not in SEMANTIC_KINDS or artifact.state is not ArtifactState.CURRENT or artifact.content_hash != digest:
            raise KeyError("artifact is stale or hash-mismatched")
        return {**self._metadata(artifact), "content": artifact.content}

    @staticmethod
    def _metadata(artifact):
        if artifact is None: return None
        item = {"artifact_id": artifact.artifact_id, "content_hash": artifact.content_hash,
                "kind": artifact.kind.value, "version": artifact.version, "state": artifact.state.value,
                "upstream": [_ref(x) for x in artifact.upstream]}
        if artifact.kind in SEMANTIC_KINDS and artifact.kind is not ArtifactKind.VALIDATION_PLAN_REVIEW:
            document = json.loads(artifact.content); validate_semantic_artifact(document)
            item["semantic_id"] = document["artifact_id"]
            if artifact.kind is ArtifactKind.VALIDATION_VERDICT:
                item["verdict"] = document["payload"]
        return item


class SemanticValidationApplication:
    """Exact WSGI routes with bounded duplicate-safe JSON and injected authorization."""

    def __init__(self, service: SemanticValidationService, authorize: Callable[[Mapping[str, Any]], bool]):
        self.service, self.authorize = service, authorize

    def __call__(self, environ, start_response) -> Iterable[bytes]:
        try:
            method = environ.get("REQUEST_METHOD"); resource, project_id = self._path(environ.get("PATH_INFO"))
            query = self._query(environ.get("QUERY_STRING", ""))
            if method == "GET":
                if resource == "validation-plan" and not query: result = self.service.plan(project_id)
                elif resource == "semantic-results":
                    if query:
                        if set(query) != {"artifact", "hash"}: raise ValueError("invalid artifact download query")
                        self._authorized(environ); result = self.service.artifact_body(project_id, query["artifact"], query["hash"])
                    else: result = self.service.results(project_id)
                elif resource == "semantic-trace" and set(query) == {"obligation"}: result = self.service.trace(project_id, query["obligation"])
                else: raise KeyError("unknown route")
            elif method == "POST":
                self._authorized(environ); payload = self._body(environ)
                if resource == "validation-plan" and not payload: result = self.service.synthesize_plan(project_id)
                elif resource == "validation-plan-review": result = self.service.review_plan(project_id, payload)
                elif resource == "semantic-test": result = self.service.execute(project_id, payload)
                else: raise KeyError("unknown route")
            else: return self._respond(start_response, 405, {"error":"method_not_allowed"})
            return self._respond(start_response, 200, result)
        except PermissionError as exc: return self._respond(start_response, 403, {"error":"forbidden", "detail":str(exc)})
        except FileNotFoundError: return self._respond(start_response, 404, {"error":"not_found"})
        except KeyError as exc: return self._respond(start_response, 404, {"error":"not_found", "detail":str(exc)})
        except LookupError as exc: return self._respond(start_response, 503, {"error":"unavailable", "detail":str(exc)})
        except (ValueError, TypeError, json.JSONDecodeError) as exc: return self._respond(start_response, 400, {"error":"invalid_request", "detail":str(exc)})

    def _authorized(self, environ):
        if not self.authorize(environ): raise PermissionError("authorization required")

    @staticmethod
    def _path(path):
        if not isinstance(path, str): raise ValueError("path must be text")
        parts = path.split("/")
        if len(parts) != 4 or parts[:2] != ["", "api"] or parts[2] not in {"validation-plan","validation-plan-review","semantic-test","semantic-results","semantic-trace"}:
            raise KeyError("unknown route")
        project_id = unquote(parts[3], errors="strict")
        if project_id != parts[3] or "/" in project_id: raise ValueError("project_id path is non-canonical")
        return parts[2], validate_project_id(project_id)

    @staticmethod
    def _query(raw):
        if not raw: return {}
        parsed = parse_qs(raw, keep_blank_values=True, strict_parsing=True)
        if any(len(v) != 1 for v in parsed.values()): raise ValueError("duplicate query parameter")
        return {k:v[0] for k,v in parsed.items()}

    @staticmethod
    def _body(environ):
        raw_length = environ.get("CONTENT_LENGTH", "")
        try: length = int(raw_length)
        except (TypeError, ValueError): raise ValueError("valid Content-Length required")
        if length < 0 or length > MAX_SEMANTIC_REQUEST_BYTES: raise ValueError("request exceeds bounded size")
        raw = environ.get("wsgi.input", io.BytesIO()).read(length + 1)
        if len(raw) != length: raise ValueError("request body length mismatch")
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
        if not isinstance(value, dict): raise ValueError("request body must be an object")
        return value

    @staticmethod
    def _respond(start_response, status, payload):
        body=(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",",":"))+"\n").encode()
        reason={200:"OK",400:"Bad Request",403:"Forbidden",404:"Not Found",405:"Method Not Allowed",503:"Service Unavailable"}[status]
        start_response(f"{status} {reason}", [("Content-Type","application/json; charset=utf-8"),("Content-Length",str(len(body)))])
        return (body,)
