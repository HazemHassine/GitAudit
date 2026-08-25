"use client";

import { ScatterChart, Scatter, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import type { PunchCardEntry } from "../lib/api";

export function PunchCard({ data }: { data: PunchCardEntry[] }) {
  const days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  
  const formatHour = (hour: number) => {
    if (hour === 0) return "12a";
    if (hour < 12) return `${hour}a`;
    if (hour === 12) return "12p";
    return `${hour - 12}p`;
  };

  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload;
      return (
        <div style={{ background: "var(--ink)", color: "white", padding: "8px 12px", font: "10px DM Mono", textTransform: "uppercase" }}>
          {days[data.day]} {formatHour(data.hour)}: {data.commits} commits
        </div>
      );
    }
    return null;
  };

  return (
    <div className="chartPanel">
      <div className="sectionTitle" style={{ marginBottom: "16px" }}>
        <span>Punch Card</span>
        <small>Commits by hour & day</small>
      </div>
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
            <Tooltip content={<CustomTooltip />} cursor={{ strokeDasharray: '3 3' }} />
            <Scatter 
              data={data} 
              fill="var(--mint)" 
              fillOpacity={0.6}
            />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
