import asyncio
import os
import re
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import httpx
import structlog

from .config import Settings, get_settings
from .database import RepositoryRecord
from .domain import CoverageModule, CoverageSummary, GenerateTestsRequest, JulesTestSession

logger = structlog.get_logger(__name__)

JULES_API_BASE_URL = "https://jules.googleapis.com/v1alpha"


class CoverageService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._active_session: JulesTestSession | None = None
        self._event_queues: list[asyncio.Queue[dict[str, str]]] = []
        self._coverage_cache: CoverageSummary | None = None

    @staticmethod
    def is_local_repository(owner: str, name: str) -> bool:
        full = f"{owner}/{name}".lower()
        return full in ("hazemhassine/github_maintainer", "hazemhassine/gitaudit")

    def get_repository_coverage_summary(
        self, repository: RepositoryRecord, coverage_xml_path: str | Path | None = None
    ) -> CoverageSummary:
        if not self.is_local_repository(repository.owner, repository.name):
            return CoverageSummary(
                status="unavailable",
                scope="remote",
                message=(
                    f"Local coverage evidence is not available for remote repository "
                    f"'{repository.owner}/{repository.name}'. Evidence collection requires "
                    f"local workspace execution or CI artifact reporting."
                ),
                coverage_percent=None,
                threshold_percent=80.0,
                passed_threshold=None,
                total_statements=0,
                total_missed=0,
                tests_passed=None,
                total_tests=None,
                execution_time_seconds=None,
                modules=[],
                jules_session=None,
            )
        return self.get_coverage_summary(coverage_xml_path=coverage_xml_path, scope="local")

    def get_coverage_summary(
        self, coverage_xml_path: str | Path | None = None, scope: str = "local"
    ) -> CoverageSummary:
        """Parses coverage.xml if present, or returns an honest unavailable/error state."""
        if coverage_xml_path is not None:
            xml_file = Path(coverage_xml_path)
            if not xml_file.is_file():
                return CoverageSummary(
                    status="unavailable",
                    scope=scope,
                    message=f"Coverage XML evidence not found at '{coverage_xml_path}'. Run pytest with coverage to produce coverage.xml.",
                    coverage_percent=None,
                    threshold_percent=80.0,
                    passed_threshold=None,
                    total_statements=0,
                    total_missed=0,
                    tests_passed=None,
                    total_tests=None,
                    execution_time_seconds=None,
                    modules=[],
                    jules_session=self._active_session,
                )
        else:
            candidates = [
                Path("coverage.xml"),
                Path("apps/api/coverage.xml"),
                Path(__file__).resolve().parents[4] / "coverage.xml",
                Path(__file__).resolve().parents[2] / "coverage.xml",
            ]
            xml_file = None
            for c in candidates:
                if c.is_file():
                    xml_file = c
                    break

            if xml_file is None:
                return CoverageSummary(
                    status="unavailable",
                    scope=scope,
                    message="Coverage XML evidence not found. Run pytest with coverage to produce coverage.xml.",
                    coverage_percent=None,
                    threshold_percent=80.0,
                    passed_threshold=None,
                    total_statements=0,
                    total_missed=0,
                    tests_passed=None,
                    total_tests=None,
                    execution_time_seconds=None,
                    modules=[],
                    jules_session=self._active_session,
                )

        try:
            tree = ET.parse(xml_file)
            root = tree.getroot()
            if root.tag != "coverage":
                raise ValueError(f"Root XML tag is '{root.tag}', expected 'coverage'")

            all_lines = root.findall(".//line")
            if not all_lines and not {"lines-valid", "lines-covered", "line-rate"} <= root.attrib.keys():
                raise ValueError("Coverage XML has no coverage evidence")

            if "lines-valid" in root.attrib:
                lines_valid = int(root.attrib["lines-valid"])
            else:
                lines_valid = len(all_lines)

            if "lines-covered" in root.attrib:
                lines_covered = int(root.attrib["lines-covered"])
            else:
                lines_covered = sum(1 for line in all_lines if int(line.attrib.get("hits", "0")) > 0)

            if lines_valid < 0 or lines_covered < 0 or lines_covered > lines_valid:
                raise ValueError(
                    f"Invalid statement counts: lines-valid={lines_valid}, lines-covered={lines_covered}"
                )

            lines_missed = lines_valid - lines_covered

            if "line-rate" in root.attrib:
                line_rate = float(root.attrib["line-rate"])
            elif lines_valid > 0:
                line_rate = lines_covered / lines_valid
            else:
                line_rate = 1.0

            if not (0.0 <= line_rate <= 1.0):
                raise ValueError(f"Invalid line-rate in root: {line_rate} (must be between 0.0 and 1.0)")

            coverage_pct = round(line_rate * 100, 2)

            modules: list[CoverageModule] = []
            for pkg in root.findall(".//package"):
                for cls in pkg.findall(".//class"):
                    filename = cls.attrib.get("filename", "")
                    cls_lines = cls.findall(".//line")

                    # Real coverage.py Cobertura class nodes lack lines-valid/covered attributes.
                    # Derive module counts from line nodes if class attributes are absent.
                    if "lines-valid" in cls.attrib and "lines-covered" in cls.attrib:
                        cls_valid = int(cls.attrib["lines-valid"])
                        cls_covered = int(cls.attrib["lines-covered"])
                        if cls_valid < 0 or cls_covered < 0 or cls_covered > cls_valid:
                            raise ValueError(
                                f"Invalid counts in class {cls.attrib.get('name')}: "
                                f"lines-valid={cls_valid}, lines-covered={cls_covered}"
                            )
                    else:
                        cls_valid = len(cls_lines)
                        cls_covered = sum(1 for line in cls_lines if int(line.attrib.get("hits", "0")) > 0)

                    cls_missed = cls_valid - cls_covered

                    if "line-rate" in cls.attrib:
                        cls_rate = float(cls.attrib["line-rate"])
                        if not (0.0 <= cls_rate <= 1.0):
                            raise ValueError(
                                f"Invalid line-rate in class {cls.attrib.get('name')}: {cls_rate}"
                            )
                        cls_pct = round(cls_rate * 100, 1)
                    elif cls_valid > 0:
                        cls_pct = round((cls_covered / cls_valid) * 100, 1)
                    else:
                        cls_pct = 100.0

                    uncovered = []
                    for line in cls_lines:
                        hits = line.attrib.get("hits")
                        num = line.attrib.get("number")
                        if hits == "0" and num:
                            uncovered.append(num)

                    mod_name = (
                        filename.replace("apps/api/src/maintainer_api/", "")
                        .replace("src/maintainer_api/", "")
                        .replace("maintainer_api/", "")
                    )
                    modules.append(
                        CoverageModule(
                            name=mod_name,
                            statements=cls_valid,
                            missed=cls_missed,
                            coverage_percent=cls_pct,
                            uncovered_lines=uncovered[:15],
                        )
                    )

            summary = CoverageSummary(
                status="available",
                scope=scope,
                message=None,
                coverage_percent=coverage_pct,
                threshold_percent=80.0,
                passed_threshold=coverage_pct >= 80.0,
                total_statements=lines_valid,
                total_missed=lines_missed,
                tests_passed=None,  # Not contained in coverage.xml; not fabricated
                total_tests=None,   # Not contained in coverage.xml; not fabricated
                execution_time_seconds=None,
                modules=sorted(modules, key=lambda m: m.coverage_percent),
                jules_session=self._active_session,
            )
            self._coverage_cache = summary
            return summary
        except (ET.ParseError, OSError, ValueError) as e:
            logger.warning("failed_to_parse_coverage_xml", error=str(e))
            return CoverageSummary(
                status="error",
                scope=scope,
                message=f"Failed to parse coverage XML: {e}",
                coverage_percent=None,
                threshold_percent=80.0,
                passed_threshold=None,
                total_statements=0,
                total_missed=0,
                tests_passed=None,
                total_tests=None,
                execution_time_seconds=None,
                modules=[],
                jules_session=self._active_session,
            )

    async def trigger_jules_test_generation(self, req: GenerateTestsRequest) -> JulesTestSession:
        untested_edge_cases = [
            "maintainer_api/curation.py: handle LLM prompt injection and malformed JSON responses",
            "maintainer_api/github.py: handle rate-limiting 403 and secondary rate limits gracefully",
            "maintainer_api/reproduction.py: test timeout cancellation when Docker command stalls",
            "maintainer_api/coordinator.py: test max_concurrent_scans semaphore backpressure",
        ]

        if req.dry_run:
            preview_id = f"preview-{uuid4().hex[:8]}"
            session = JulesTestSession(
                session_id=preview_id,
                status="preview",
                plan_status="[Preview] Simulated test generation (dry run)",
                untested_cases=untested_edge_cases,
                pull_request_url=None,
                logs=[
                    "Inspecting repository structure and pytest fixtures...",
                    f"Target coverage threshold: {req.target_coverage}%",
                    f"Focus module: {req.focus_module or 'all uncovered modules'}",
                    "Identified 4 critical untested branches in curation, github, and reproduction",
                    "Synthesized test plan preview (AUTO_CREATE_PR mode not executed in preview)",
                ],
            )
            self._active_session = session
            await self._broadcast_event("session_update", session.model_dump_json())
            return session

        api_key = os.environ.get("JULES_API_KEY")
        if not api_key:
            session = JulesTestSession(
                session_id="",
                status="unavailable",
                plan_status="Jules API key not configured (JULES_API_KEY missing)",
                untested_cases=untested_edge_cases,
                pull_request_url=None,
                logs=["Jules API key not configured. Set JULES_API_KEY to enable automated test generation."],
            )
            self._active_session = session
            await self._broadcast_event("session_update", session.model_dump_json())
            return session

        prompt = (
            f"Generate unit tests using pytest for uncovered code in GitAudit (apps/api/src/maintainer_api/). "
            f"Target coverage: {req.target_coverage}%. "
            f"Focus: {req.focus_module or 'curation.py, github.py, reproduction.py'}. "
            "Write tests in apps/api/tests/ following existing fixture conventions. Ensure make test passes with 0 errors."
        )
        payload = {
            "prompt": prompt,
            "sourceContext": {
                "source": "sources/github/HazemHassine/GitAudit",
                "githubRepoContext": {"startingBranch": "main"},
            },
            "automationMode": "AUTO_CREATE_PR",
            "requirePlanApproval": False,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(
                    f"{JULES_API_BASE_URL}/sessions",
                    headers={"X-Goog-Api-Key": api_key, "Content-Type": "application/json"},
                    json=payload,
                )
                if res.status_code in (200, 201):
                    try:
                        data = res.json()
                    except ValueError:
                        data = {}
                    real_session_id = data.get("name") if isinstance(data, dict) else None
                    if not isinstance(real_session_id, str) or not re.fullmatch(r"sessions/[A-Za-z0-9_-]+", real_session_id):
                        logger.error("jules_session_invalid_name", status_code=res.status_code)
                        session = JulesTestSession(
                            session_id="",
                            status="failed",
                            plan_status="Jules API returned response without valid session name",
                            untested_cases=untested_edge_cases,
                            pull_request_url=None,
                            logs=["Jules API response did not contain a valid session name."],
                        )
                        self._active_session = session
                        await self._broadcast_event("session_update", session.model_dump_json())
                        return session

                    session = JulesTestSession(
                        session_id=real_session_id,
                        status="running",
                        plan_status="Jules session created with AUTO_CREATE_PR",
                        untested_cases=untested_edge_cases,
                        pull_request_url=None,
                        logs=[f"Session created: {real_session_id}", "Waiting for plan generation..."],
                    )
                    self._active_session = session
                    await self._broadcast_event("session_update", session.model_dump_json())
                    return session
                else:
                    logger.error("jules_session_failed", status_code=res.status_code)
                    session = JulesTestSession(
                        session_id="",
                        status="failed",
                        plan_status=f"Jules session creation failed with HTTP {res.status_code}",
                        untested_cases=untested_edge_cases,
                        pull_request_url=None,
                        logs=[f"Error: Jules API request failed with HTTP {res.status_code}"],
                    )
                    self._active_session = session
                    await self._broadcast_event("session_update", session.model_dump_json())
                    return session
        except (httpx.HTTPError, OSError, RuntimeError) as e:
            logger.error("jules_invocation_error", error_type=type(e).__name__)
            session = JulesTestSession(
                session_id="",
                status="failed",
                plan_status="Jules service invocation failed",
                untested_cases=untested_edge_cases,
                pull_request_url=None,
                logs=["Error: An error occurred while communicating with Jules API."],
            )
            self._active_session = session
            await self._broadcast_event("session_update", session.model_dump_json())
            return session

    async def _broadcast_event(self, event_type: str, data: str) -> None:
        for q in self._event_queues:
            await q.put({"event": event_type, "data": data})

    def stream_events(self) -> AsyncIterator[str]:
        q: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        self._event_queues.append(q)

        async def generator():
            try:
                # Send initial snapshot
                summary = self.get_coverage_summary()
                yield f"event: coverage_snapshot\ndata: {summary.model_dump_json()}\n\n"
                while True:
                    event = await q.get()
                    yield f"event: {event['event']}\ndata: {event['data']}\n\n"
            finally:
                if q in self._event_queues:
                    self._event_queues.remove(q)

        return generator()
