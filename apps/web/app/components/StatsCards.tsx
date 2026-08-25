"use client";

import type { DashboardStats } from "../lib/api";

export function StatsCards({ stats }: { stats: DashboardStats }) {
  return (
    <div className="statsRow">
      <div className="statCard">
        <div className="statLabel">Total Repositories</div>
        <div className="statValue">{stats.total_repositories}</div>
      </div>
      <div className="statCard">
        <div className="statLabel">Public</div>
        <div className="statValue">{stats.public_count}</div>
      </div>
      <div className="statCard">
        <div className="statLabel">Private</div>
        <div className="statValue">{stats.private_count}</div>
      </div>
      <div className="statCard" style={{ borderBottom: "3px solid var(--mint)" }}>
        <div className="statLabel">Total Stars</div>
        <div className="statValue">{stats.total_stars}</div>
      </div>
    </div>
  );
}
