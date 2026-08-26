"use client";

import { useEffect, useRef } from "react";
import { ReproductionEvent } from "../lib/api";

type ReproductionTerminalProps = {
  events: ReproductionEvent[];
  command: string | null;
  detectedStack: string | null;
  exitCode: number | null;
  onCancel?: () => void;
  isRunActive: boolean;
};

export default function ReproductionTerminal({
  events,
  command,
  detectedStack,
  exitCode,
  onCancel,
  isRunActive,
}: ReproductionTerminalProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events]);

  return (
    <div className="reproTerminal">
      <div className="reproTerminalHead">
        <div className="command" title={command || "No command executed yet"}>
          {command || "Waiting for execution..."}
        </div>
        <div className="controls">
          {detectedStack && (
            <span className="stackBadge">{detectedStack}</span>
          )}
          {exitCode !== null && (
            <span
              className={`exitCodeBadge ${exitCode === 0 ? "success" : "failure"}`}
            >
              Exit {exitCode}
            </span>
          )}
          {isRunActive && onCancel && (
            <button
              onClick={onCancel}
              style={{
                background: "transparent",
                border: "1px solid var(--orange)",
                color: "var(--orange)",
                cursor: "pointer",
                padding: "4px 8px",
                font: "500 9px DM Mono",
                textTransform: "uppercase",
              }}
            >
              Cancel Run
            </button>
          )}
        </div>
      </div>
      <div className="reproTerminalBody" ref={scrollRef}>
        {events.length === 0 ? (
          <p className="level-info">Initializing workspace...</p>
        ) : (
          events.map((ev, i) => (
            <p key={i} className={`level-${ev.level}`}>
              {ev.message}
            </p>
          ))
        )}
      </div>
    </div>
  );
}
