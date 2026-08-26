"use client";

import { ScatterChart, Scatter, XAxis, YAxis, ZAxis, Tooltip, ResponsiveContainer } from "recharts";
import type { PunchCardEntry } from "../lib/api";
import type { TooltipProps } from "recharts";

const days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const formatHour = (hour: number) => {
  if (hour === 0) return "12a";
  if (hour < 12) return `${hour}a`;
  if (hour === 12) return "12p";
  return `${hour - 12}p`;
};

interface CustomTooltipProps extends TooltipProps<number, number> {
  active?: boolean;
  payload?: Array<{ payload: PunchCardEntry }>;
}
const CustomTooltip = ({ active, payload }: CustomTooltipProps) => {
  if (active && payload && payload.length) {
    const data = payload[0].payload;
    return (
      <div style={{ background: "var(--ink)", color: "white", padding: "8px 12px", font: "10px DM Mono", textTransform: "uppercase" }}>
        {days[data.day]} {formatHour(data.hour)}: {data.commits} commit{data.commits !== 1 ? "s" : ""}
      </div>
    );
  }
  return null;
};

export function PunchCard({ data }: { data: PunchCardEntry[] }) {
  // Only plot points where commits > 0
  const activeData = data.filter((d) => d.commits > 0);
  return (
    <div className="chartPanel">
      <div className="sectionTitle" style={{ marginBottom: "16px" }}>
        <span>Punch Card</span>
        <small>Commits by hour & day</small>
      </div>

      {activeData.length === 0 ? (
        <div className="panelEmpty" style={{ height: "200px", display: "flex", flexDirection: "column", justifyContent: "center" }}>
          <b>No time-of-day data yet</b>
          <span>GitHub generates punch card stats on demand. Click &quot;Refresh activity&quot; to update.</span>
        </div>
      ) : (
        <div style={{ width: "100%", height: "250px" }}>
          <ResponsiveContainer>
            <ScatterChart margin={{ top: 10, right: 10, bottom: 0, left: -20 }}>
              <XAxis 
                dataKey="hour" 
                type="number" 
                domain={[0, 23]} 
                tickFormatter={formatHour} 
                ticks={[0, 3, 6, 9, 12, 15, 18, 21]}
                axisLine={false}
                tickLine={false}
              />
              <YAxis 
                dataKey="day" 
                type="number" 
                domain={[0, 6]} 
                tickFormatter={(tick) => days[tick]} 
                ticks={[0, 1, 2, 3, 4, 5, 6]}
                axisLine={false}
                tickLine={false}
                reversed
              />
              <ZAxis 
                dataKey="commits" 
                type="number" 
                range={[40, 400]} 
                name="commits" 
              />
              <Tooltip content={<CustomTooltip />} cursor={{ strokeDasharray: '3 3' }} />
              <Scatter 
                data={activeData} 
                fill="#40c463" 
                fillOpacity={0.75}
              />
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
