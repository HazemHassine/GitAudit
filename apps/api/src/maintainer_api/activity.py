from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import ProfileActivityRecord, RepositoryActivityRecord, RepositoryRecord
from .domain import (
    CommitWeek,
    ContributionCalendar,
    ContributionDay,
    ContributionWeek,
    DashboardActivity,
    DashboardStats,
    GitHubEvent,
    HealthReport,
    MonitoringState,
    PunchCardEntry,
    RecentCommit,
)
from .github import GitHubError, GitHubReader


class ActivityService:
    def __init__(self, github: GitHubReader, stale_minutes: int = 60) -> None:
        self._github = github
        self._stale_minutes = stale_minutes

    def _is_stale(self, fetched_at: datetime | None) -> bool:
        if not fetched_at:
            return True
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=UTC)
        return fetched_at < datetime.now(UTC) - timedelta(minutes=self._stale_minutes)

    async def dashboard_stats(self, session: AsyncSession) -> DashboardStats:
        """Compute aggregate stats from persisted repository data."""
        active_repos = (
            await session.scalars(
                select(RepositoryRecord).where(
                    RepositoryRecord.monitoring_state == MonitoringState.ACTIVE.value
                )
            )
        ).all()
        
        stats = DashboardStats(total_repositories=len(active_repos))
        
        for repo in active_repos:
            if repo.private:
                stats.private_count += 1
            else:
                stats.public_count += 1
                
            stats.total_stars += repo.stars
            
            if repo.primary_language:
                stats.languages[repo.primary_language] = stats.languages.get(repo.primary_language, 0) + 1
                
            if repo.latest_health and isinstance(repo.latest_health, dict):
                repo_status = repo.latest_health.get("repository_status")
                if repo_status:
                    stats.health_distribution[repo_status] = stats.health_distribution.get(repo_status, 0) + 1
                    
        return stats

    def _parse_event_summary(self, event: dict) -> str:
        event_type = event.get("type", "")
        repo_name = event.get("repo", {}).get("name", "repo")
        payload = event.get("payload", {})
        
        if event_type == "PushEvent":
            size = payload.get("size", 1)
            return f"Pushed {size} commit{'s' if size != 1 else ''} to {repo_name}"
        elif event_type == "PullRequestEvent":
            action = payload.get("action", "opened").capitalize()
            num = payload.get("number", "")
            return f"{action} PR #{num} in {repo_name}"
        elif event_type == "IssuesEvent":
            action = payload.get("action", "opened").capitalize()
            num = payload.get("issue", {}).get("number", "")
            return f"{action} issue #{num} in {repo_name}"
        elif event_type == "CreateEvent":
            ref_type = payload.get("ref_type", "branch/tag")
            return f"Created {ref_type} in {repo_name}"
        elif event_type == "ReleaseEvent":
            version = payload.get("release", {}).get("tag_name", "vX")
            return f"Published release {version} in {repo_name}"
        elif event_type == "WatchEvent":
            return f"Starred {repo_name}"
        elif event_type == "ForkEvent":
            return f"Forked {repo_name}"
        return f"Activity in {repo_name}"

    async def _fetch_profile_activity(self, session: AsyncSession, login: str, force: bool = False) -> ProfileActivityRecord:
        record = await session.scalar(select(ProfileActivityRecord).where(ProfileActivityRecord.login == login))
        
        if record and not self._is_stale(record.fetched_at) and not force:
            return record
            
        if not record:
            record = ProfileActivityRecord(login=login)
            session.add(record)
            
        try:
            calendar_data = await self._github.contribution_calendar(login)
            user_data = calendar_data.get("data", {}).get("user", {})
            contrib_coll = user_data.get("contributionsCollection", {})
            calendar = contrib_coll.get("contributionCalendar", {})
            record.contribution_calendar = calendar
        except GitHubError:
            if not record.contribution_calendar:
                record.contribution_calendar = {"totalContributions": 0, "weeks": []}
                
        try:
            events_data = await self._github.user_events(login)
            record.events = events_data
        except GitHubError:
            if record.events is None:
                record.events = []
                
        record.fetched_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(record)
        return record

    async def repository_activity(self, session: AsyncSession, repository: RepositoryRecord, force: bool = False) -> dict:
        record = await session.scalar(
            select(RepositoryActivityRecord).where(RepositoryActivityRecord.repository_id == repository.id)
        )
        
        if record and not self._is_stale(record.fetched_at) and not force:
            return {
                "weekly_commits": record.weekly_commits,
                "punch_card": record.punch_card,
                "recent_commits": record.recent_commits
            }
            
        if not record:
            record = RepositoryActivityRecord(repository_id=repository.id)
            session.add(record)
            
        try:
            record.weekly_commits = await self._github.commit_activity(repository.owner, repository.name)
            record.punch_card = await self._github.punch_card(repository.owner, repository.name)
            record.recent_commits = await self._github.recent_commits(repository.owner, repository.name, repository.default_branch)
        except GitHubError:
            # Keep existing if failed, or set to empty lists
            if record.weekly_commits is None:
                record.weekly_commits = []
            if record.punch_card is None:
                record.punch_card = []
            if record.recent_commits is None:
                record.recent_commits = []
                
        record.fetched_at = datetime.now(UTC)
        await session.commit()
        
        return {
            "weekly_commits": record.weekly_commits,
            "punch_card": record.punch_card,
            "recent_commits": record.recent_commits
        }

    async def dashboard_activity(self, session: AsyncSession, login: str, force: bool = False) -> DashboardActivity:
        profile_record = await self._fetch_profile_activity(session, login, force)
        
        active_repos = (
            await session.scalars(
                select(RepositoryRecord).where(
                    RepositoryRecord.monitoring_state == MonitoringState.ACTIVE.value
                )
            )
        ).all()
        
        repo_activities = []
        for repo in active_repos:
            act = await self.repository_activity(session, repo, force)
            repo_activities.append((repo, act))
            
        # Parse contribution calendar
        calendar = ContributionCalendar()
        cal_data = profile_record.contribution_calendar or {}
        calendar.total = cal_data.get("totalContributions", 0)
        
        for week_data in cal_data.get("weeks", []):
            days = []
            for day_data in week_data.get("contributionDays", []):
                count = day_data.get("contributionCount", 0)
                # Map count to 0-4 intensity level
                if count == 0:
                    level = 0
                elif count <= 2:
                    level = 1
                elif count <= 5:
                    level = 2
                elif count <= 9:
                    level = 3
                else:
                    level = 4
                days.append(ContributionDay(
                    date=day_data.get("date", ""),
                    count=count,
                    level=level,
                ))
            calendar.weeks.append(ContributionWeek(days=days))

        # Parse events
        events = []
        for event in (profile_record.events or [])[:50]:
            events.append(GitHubEvent(
                id=str(event.get("id", "")),
                type=event.get("type", "Event"),
                repo=event.get("repo", {}).get("name", ""),
                created_at=event.get("created_at", ""),
                summary=self._parse_event_summary(event)
            ))
            
        # Aggregate weekly commits
        weekly_map = {}
        for _, act in repo_activities:
            for week in act.get("weekly_commits") or []:
                w = week.get("week")
                if w not in weekly_map:
                    weekly_map[w] = {"week": w, "total": 0, "days": [0]*7}
                weekly_map[w]["total"] += week.get("total", 0)
                for i, d in enumerate(week.get("days", [0]*7)):
                    weekly_map[w]["days"][i] += d
                    
        weekly_commits = [CommitWeek(**w) for w in sorted(weekly_map.values(), key=lambda x: x["week"])]

        # Fallback: if GraphQL calendar is empty (e.g. App auth mode), generate calendar from weekly_commits
        if not calendar.weeks and weekly_commits:
            total_contribs = 0
            for w in weekly_commits:
                days = []
                # week is unix timestamp (seconds since epoch)
                week_dt = datetime.fromtimestamp(w.week, tz=UTC)
                for i, count in enumerate(w.days):
                    day_dt = week_dt + timedelta(days=i)
                    total_contribs += count
                    if count == 0:
                        level = 0
                    elif count <= 2:
                        level = 1
                    elif count <= 5:
                        level = 2
                    elif count <= 9:
                        level = 3
                    else:
                        level = 4
                    days.append(ContributionDay(
                        date=day_dt.strftime("%Y-%m-%d"),
                        count=count,
                        level=level,
                    ))
                calendar.weeks.append(ContributionWeek(days=days))
            calendar.total = total_contribs

        
        # Aggregate punch card
        punch_map = defaultdict(int)
        for _, act in repo_activities:
            for entry in act.get("punch_card") or []:
                if len(entry) == 3:
                    day, hour, count = entry
                    punch_map[(day, hour)] += count
                    
        punch_card = [PunchCardEntry(day=d, hour=h, commits=c) for (d, h), c in punch_map.items()]
        
        # Aggregate recent commits
        all_recent_commits = []
        for repo, act in repo_activities:
            for commit_item in act.get("recent_commits") or []:
                commit = commit_item.get("commit", {})
                author = commit_item.get("author", {}) or {}
                all_recent_commits.append(RecentCommit(
                    sha=commit_item.get("sha", ""),
                    message=commit.get("message", ""),
                    author=commit.get("author", {}).get("name", "Unknown"),
                    avatar_url=author.get("avatar_url"),
                    authored_at=commit.get("author", {}).get("date", ""),
                    repository=f"{repo.owner}/{repo.name}",
                    url=commit_item.get("html_url", "")
                ))
                
        all_recent_commits.sort(key=lambda x: x.authored_at, reverse=True)
        recent_commits = all_recent_commits[:50]
        
        fetched_at = profile_record.fetched_at.isoformat() if profile_record.fetched_at else None
        
        return DashboardActivity(
            contribution_calendar=calendar,
            weekly_commits=weekly_commits,
            punch_card=punch_card,
            recent_commits=recent_commits,
            events=events,
            fetched_at=fetched_at
        )

    async def refresh_all(self, session: AsyncSession, login: str) -> DashboardActivity:
        return await self.dashboard_activity(session, login, force=True)
