"use client";

import type { GitHubEvent } from "../lib/api";
import { relativeTime } from "../lib/api";

export function ActivityFeed({ events }: { events: GitHubEvent[] }) {
  const getEventColor = (type: string) => {
    switch (type) {
      case "PushEvent": return "var(--mint)";
      case "PullRequestEvent": return "#a371f7";
      case "IssuesEvent": return "var(--orange)";
      case "CreateEvent": return "var(--acid)";
      case "ReleaseEvent": return "#f78166";
      default: return "var(--muted)";
    }
  };

  return (
    <div className="activityPanel">
      <div className="sectionTitle">
        <span>Recent Activity</span>
      </div>
      <div className="activityList trace">
        <ol>
          {events.map((event) => (
            <li key={event.id}>
              <i style={{ backgroundColor: getEventColor(event.type) }} />
              <div>
                <b>{event.summary}</b>
                <small>{event.repo}</small>
              </div>
              <time>{relativeTime(event.created_at)}</time>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
