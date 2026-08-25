"use client";

import type { ContributionCalendar } from "../lib/api";

export function ContributionGraph({ calendar }: { calendar: ContributionCalendar }) {
  // Render a CSS grid: 53 columns (weeks) × 7 rows (days)
  const getLevelColor = (level: number) => {
    switch (level) {
      case 1: return "#9be9a8";
      case 2: return "#40c463";
      case 3: return "#30a14e";
      case 4: return "#216e39";
      default: return "var(--line)";
    }
  };

  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  
  return (
    <div className="contributionGraph">
      <div className="sectionTitle">
        <span>Contributions</span>
        <small>{calendar.total} in the last year</small>
      </div>
      <div style={{ marginTop: "16px" }}>
        <div className="contributionMonths">
          <span />
          {/* Approximate months for demo purposes */}
          {months.map((m, i) => (
            <span key={m} style={{ gridColumn: `span ${i === 0 ? 4 : 4}` }}>{m}</span>
          ))}
        </div>
        <div className="contributionGrid">
          <div style={{ display: "grid", gridTemplateRows: "repeat(7, 1fr)", gap: "3px" }}>
            <span className="contributionDayLabel"></span>
            <span className="contributionDayLabel">Mon</span>
            <span className="contributionDayLabel"></span>
            <span className="contributionDayLabel">Wed</span>
            <span className="contributionDayLabel"></span>
            <span className="contributionDayLabel">Fri</span>
            <span className="contributionDayLabel"></span>
          </div>
          
          {calendar.weeks.map((week, i) => (
            <div key={i} style={{ display: "grid", gridTemplateRows: "repeat(7, 1fr)", gap: "3px" }}>
              {week.days.map((day, j) => (
                <div 
                  key={j} 
                  className="contributionCell" 
                  style={{ backgroundColor: getLevelColor(day.level) }}
                  title={`${day.date}: ${day.count} contributions`}
                />
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
