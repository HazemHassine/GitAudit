from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from maintainer_api.activity import ActivityService
from maintainer_api.database import Base, RepositoryRecord
from maintainer_api.domain import MonitoringState
from maintainer_api.github import GitHubError


class MockGitHubForActivity:
    def __init__(self) -> None:
        self.raise_calendar_error = False
        self.raise_events_error = False
        self.raise_repo_error = False

    async def contribution_calendar(self, login: str):
        if self.raise_calendar_error:
            raise GitHubError("Calendar error")
        return {
            "data": {
                "user": {
                    "contributionsCollection": {
                        "contributionCalendar": {
                            "totalContributions": 42,
                            "weeks": [
                                {
                                    "contributionDays": [
                                        {"date": "2026-08-01", "contributionCount": 0},
                                        {"date": "2026-08-02", "contributionCount": 1},
                                        {"date": "2026-08-03", "contributionCount": 4},
                                        {"date": "2026-08-04", "contributionCount": 7},
                                        {"date": "2026-08-05", "contributionCount": 12},
                                    ]
                                }
                            ],
                        }
                    }
                }
            }
        }

    async def user_events(self, login: str):
        if self.raise_events_error:
            raise GitHubError("Events error")
        return [
            {"id": "1", "type": "PushEvent", "repo": {"name": "org/repo1"}, "payload": {"size": 2}},
            {"id": "2", "type": "PushEvent", "repo": {"name": "org/repo1"}, "payload": {"size": 1}},
            {"id": "3", "type": "PullRequestEvent", "repo": {"name": "org/repo1"}, "payload": {"action": "opened", "number": 10}},
            {"id": "4", "type": "IssuesEvent", "repo": {"name": "org/repo2"}, "payload": {"action": "closed", "issue": {"number": 5}}},
            {"id": "5", "type": "CreateEvent", "repo": {"name": "org/repo2"}, "payload": {"ref_type": "branch"}},
            {"id": "6", "type": "ReleaseEvent", "repo": {"name": "org/repo1"}, "payload": {"release": {"tag_name": "v1.0.0"}}},
            {"id": "7", "type": "WatchEvent", "repo": {"name": "org/repo1"}, "payload": {}},
            {"id": "8", "type": "ForkEvent", "repo": {"name": "org/repo1"}, "payload": {}},
            {"id": "9", "type": "MemberEvent", "repo": {"name": "org/repo1"}, "payload": {}},
        ]

    async def commit_activity(self, owner: str, name: str):
        if self.raise_repo_error:
            raise GitHubError("Commit activity error")
        return [
            {"week": 1756000000, "total": 5, "days": [1, 2, 0, 1, 1, 0, 0]},
            {"week": 1756604800, "total": 3, "days": [0, 0, 1, 0, 2, 0, 0]},
        ]

    async def punch_card(self, owner: str, name: str):
        if self.raise_repo_error:
            raise GitHubError("Punch card error")
        return [
            [0, 10, 2],
            [1, 14, 5],
        ]

    async def recent_commits(self, owner: str, name: str, branch: str):
        if self.raise_repo_error:
            raise GitHubError("Recent commits error")
        return [
            {
                "sha": "abc1234",
                "commit": {
                    "message": "Initial commit",
                    "author": {"name": "Alice", "date": "2026-08-20T10:00:00Z"},
                },
                "author": {"avatar_url": "https://avatars.example.com/alice"},
                "html_url": "https://github.com/org/repo1/commit/abc1234",
            }
        ]


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def test_dashboard_stats(session_factory: async_sessionmaker[AsyncSession]) -> None:
    service = ActivityService(MockGitHubForActivity())
    async with session_factory() as session:
        # Initially empty
        stats = await service.dashboard_stats(session)
        assert stats.total_repositories == 0
        assert stats.public_count == 0
        assert stats.private_count == 0

        # Add repositories
        repo1 = RepositoryRecord(
            id=uuid4(),
            github_id=1,
            owner="acme",
            name="repo1",
            default_branch="main",
            primary_language="Python",
            private=False,
            html_url="https://github.com/acme/repo1",
            stars=15,
            monitoring_state=MonitoringState.ACTIVE.value,
            latest_health={"repository_status": "healthy", "overall_score": 90, "score_version": "v1"},
        )
        repo2 = RepositoryRecord(
            id=uuid4(),
            github_id=2,
            owner="acme",
            name="repo2",
            default_branch="main",
            primary_language="TypeScript",
            private=True,
            html_url="https://github.com/acme/repo2",
            stars=5,
            monitoring_state=MonitoringState.ACTIVE.value,
            latest_health={"repository_status": "attention", "overall_score": 60, "score_version": "v1"},
        )
        repo_excluded = RepositoryRecord(
            id=uuid4(),
            github_id=3,
            owner="acme",
            name="excluded",
            default_branch="main",
            primary_language="Python",
            private=False,
            html_url="https://github.com/acme/excluded",
            stars=100,
            monitoring_state=MonitoringState.EXCLUDED.value,
        )
        session.add_all([repo1, repo2, repo_excluded])
        await session.commit()

        stats = await service.dashboard_stats(session)
        assert stats.total_repositories == 2
        assert stats.public_count == 1
        assert stats.private_count == 1
        assert stats.total_stars == 20
        assert stats.languages == {"Python": 1, "TypeScript": 1}
        assert stats.health_distribution == {"healthy": 1, "attention": 1}


def test_is_stale() -> None:
    service = ActivityService(MockGitHubForActivity(), stale_minutes=30)
    assert service._is_stale(None) is True

    fresh = datetime.now(UTC) - timedelta(minutes=10)
    assert service._is_stale(fresh) is False

    stale = datetime.now(UTC) - timedelta(minutes=45)
    assert service._is_stale(stale) is True

    naive_fresh = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5)
    assert service._is_stale(naive_fresh) is False


def test_parse_event_summary() -> None:
    service = ActivityService(MockGitHubForActivity())
    assert service._parse_event_summary({"type": "PushEvent", "repo": {"name": "r"}, "payload": {"size": 1}}) == "Pushed 1 commit to r"
    assert service._parse_event_summary({"type": "PushEvent", "repo": {"name": "r"}, "payload": {"size": 3}}) == "Pushed 3 commits to r"
    assert service._parse_event_summary({"type": "PullRequestEvent", "repo": {"name": "r"}, "payload": {"action": "opened", "number": 12}}) == "Opened PR #12 in r"
    assert service._parse_event_summary({"type": "IssuesEvent", "repo": {"name": "r"}, "payload": {"action": "closed", "issue": {"number": 7}}}) == "Closed issue #7 in r"
    assert service._parse_event_summary({"type": "CreateEvent", "repo": {"name": "r"}, "payload": {"ref_type": "tag"}}) == "Created tag in r"
    assert service._parse_event_summary({"type": "ReleaseEvent", "repo": {"name": "r"}, "payload": {"release": {"tag_name": "v2.0"}}}) == "Published release v2.0 in r"
    assert service._parse_event_summary({"type": "WatchEvent", "repo": {"name": "r"}}) == "Starred r"
    assert service._parse_event_summary({"type": "ForkEvent", "repo": {"name": "r"}}) == "Forked r"
    assert service._parse_event_summary({"type": "OtherEvent", "repo": {"name": "r"}}) == "Activity in r"


async def test_dashboard_activity_and_caching(session_factory: async_sessionmaker[AsyncSession]) -> None:
    github = MockGitHubForActivity()
    service = ActivityService(github, stale_minutes=60)

    async with session_factory() as session:
        repo = RepositoryRecord(
            id=uuid4(),
            github_id=1,
            owner="acme",
            name="widgets",
            default_branch="main",
            html_url="https://github.com/acme/widgets",
            monitoring_state=MonitoringState.ACTIVE.value,
        )
        session.add(repo)
        await session.commit()

        # First fetch - populate from GitHub
        activity = await service.dashboard_activity(session, "acme")
        assert activity.contribution_calendar.total == 42
        assert len(activity.contribution_calendar.weeks) == 1
        assert len(activity.events) == 9
        assert len(activity.weekly_commits) == 2
        assert len(activity.punch_card) == 2
        assert len(activity.recent_commits) == 1
        assert activity.recent_commits[0].author == "Alice"

        # Verify caching (does not re-query if not stale)
        github.raise_calendar_error = True
        github.raise_events_error = True
        cached_activity = await service.dashboard_activity(session, "acme")
        assert cached_activity.contribution_calendar.total == 42

        # Force refresh
        refreshed = await service.refresh_all(session, "acme")
        assert refreshed is not None


async def test_dashboard_activity_fallback_calendar(session_factory: async_sessionmaker[AsyncSession]) -> None:
    github = MockGitHubForActivity()
    async def empty_calendar(login: str):
        return {"data": {"user": {"contributionsCollection": {"contributionCalendar": {"totalContributions": 0, "weeks": []}}}}}
    github.contribution_calendar = empty_calendar
    service = ActivityService(github, stale_minutes=60)

    async with session_factory() as session:
        repo = RepositoryRecord(
            id=uuid4(),
            github_id=1,
            owner="acme",
            name="tools",
            default_branch="main",
            html_url="https://github.com/acme/tools",
            monitoring_state=MonitoringState.ACTIVE.value,
        )
        session.add(repo)
        await session.commit()

        activity = await service.dashboard_activity(session, "acme", force=True)
        # Should generate fallback calendar from weekly_commits
        assert len(activity.contribution_calendar.weeks) == 2
        assert activity.contribution_calendar.total == 8


async def test_repository_activity_error_handling(session_factory: async_sessionmaker[AsyncSession]) -> None:
    github = MockGitHubForActivity()
    github.raise_repo_error = True
    service = ActivityService(github)

    async with session_factory() as session:
        repo = RepositoryRecord(
            id=uuid4(),
            github_id=1,
            owner="acme",
            name="failing_repo",
            default_branch="main",
            html_url="https://github.com/acme/failing_repo",
            monitoring_state=MonitoringState.ACTIVE.value,
        )
        session.add(repo)
        await session.commit()

        act = await service.repository_activity(session, repo)
        assert act["weekly_commits"] == []
        assert act["punch_card"] == []
        assert act["recent_commits"] == []
