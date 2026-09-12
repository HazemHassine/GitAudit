import asyncio
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator
from pathlib import Path

import structlog

from .config import Settings, get_settings
from .database import RepositoryRecord
from .domain import (
    CoverageModule,
    CoverageSummary,
    CreateJulesSessionRequest,
    GenerateTestsRequest,
    JulesAuditArea,
    JulesAuditSession,
    JulesTestSession,
)
from .jules import JulesAuditService

logger = structlog.get_logger(__name__)

class CoverageService:
    def __init__(
        self,
        settings: Settings | None = None,
        jules_service: JulesAuditService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.jules_service = jules_service or JulesAuditService(self.settings)
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
        focus = req.focus_module or "all uncovered modules"
        audit_session = await self.jules_service.create_session(
            CreateJulesSessionRequest(
                audit_area=JulesAuditArea.COVERAGE,
                focus=f"{focus}; target coverage: {req.target_coverage}%",
                dry_run=req.dry_run,
                idempotency_key=req.idempotency_key,
            )
        )
        session = self._to_coverage_session(audit_session)
        self._active_session = session
        await self._broadcast_event("session_update", session.model_dump_json())
        return session

    def _to_coverage_session(self, session: JulesAuditSession) -> JulesTestSession:
        status = "running" if session.status.value in {"in_progress", "queued"} else session.status.value
        return JulesTestSession(
            session_id="" if session.status.value in {"failed", "unavailable"} else session.session_id,
            status=status,
            plan_status=session.plan_status,
            untested_cases=self.jules_service.review_targets("coverage"),
            pull_request_url=session.pull_request_url,
            logs=[f"Error: {entry}" for entry in session.activity]
            if session.status.value == "failed"
            else session.activity,
        )

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
