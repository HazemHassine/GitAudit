"use client";

import type { Repository } from "../lib/api";
import { repositoryDisplayStatus } from "../lib/api";

export type FilterState = {
  search: string;
  visibility: "all" | "public" | "private";
  language: string | null;
  status: string | null;
};

export function RepoFilters({
  repositories,
  filters,
  onChange,
}: {
  repositories: Repository[];
  filters: FilterState;
  onChange: (filters: FilterState) => void;
}) {
  const languages = Array.from(new Set(repositories.map(r => r.primary_language).filter(Boolean))) as string[];
  
  return (
    <div className="filterBar">
      <input 
        type="text" 
        placeholder="Find a repository..." 
        value={filters.search} 
        onChange={e => onChange({ ...filters, search: e.target.value })}
      />
      
      <div className="filterPills">
        <button 
          className={`filterPill ${filters.visibility === "all" ? "active" : ""}`}
          onClick={() => onChange({ ...filters, visibility: "all" })}
        >
          All
        </button>
        <button 
          className={`filterPill ${filters.visibility === "public" ? "active" : ""}`}
          onClick={() => onChange({ ...filters, visibility: "public" })}
        >
          Public
        </button>
        <button 
          className={`filterPill ${filters.visibility === "private" ? "active" : ""}`}
          onClick={() => onChange({ ...filters, visibility: "private" })}
        >
          Private
        </button>
      </div>

      <select 
        value={filters.language || ""} 
        onChange={e => onChange({ ...filters, language: e.target.value || null })}
      >
        <option value="">Language</option>
        {languages.map(lang => (
          <option key={lang} value={lang}>{lang}</option>
        ))}
      </select>

      <select 
        value={filters.status || ""} 
        onChange={e => onChange({ ...filters, status: e.target.value || null })}
      >
        <option value="">Status</option>
        <option value="healthy">Healthy</option>
        <option value="attention">Attention</option>
        <option value="degraded">Degraded</option>
        <option value="unscanned">Unscanned</option>
      </select>
    </div>
  );
}

export function applyFilters(repositories: Repository[], filters: FilterState): Repository[] {
  return repositories.filter((repo) => {
    if (filters.search && !`${repo.owner}/${repo.name}`.toLowerCase().includes(filters.search.toLowerCase())) return false;
    if (filters.visibility === "public" && repo.private) return false;
    if (filters.visibility === "private" && !repo.private) return false;
    if (filters.language && repo.primary_language !== filters.language) return false;
    if (filters.status) {
      if (repositoryDisplayStatus(repo) !== filters.status) return false;
    }
    return true;
  });
}
