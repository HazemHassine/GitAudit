"use client";

import { useEffect, useState, use } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  API_URL,
  ReproductionRun,
  ReproductionPhase,
  ReproductionEvent,
  request,
} from "../../../../lib/api";
import ReproductionTerminal from "../../../../components/ReproductionTerminal";
import { Navigation } from "../../../../components/Navigation";

const PHASES: { id: ReproductionPhase; label: string }[] = [
  { id: "queued", label: "Queued" },
  { id: "fetching_logs", label: "Fetching Logs" },
  { id: "preparing_workspace", label: "Preparing Workspace" },
  { id: "detecting_stack", label: "Stack Detection" },
  { id: "executing_sandbox", label: "Sandbox Execution" },
  { id: "completed", label: "Verdict" },
];

export default function ReproductionRunPage({
  params,
}: {
  params: Promise<{ repositoryId: string; reproductionId: string }>;
}) {
  const router = useRouter();
  const resolvedParams = use(params);
  const [run, setRun] = useState<ReproductionRun | null>(null);
  const [events, setEvents] = useState<ReproductionEvent[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let eventSource: EventSource | null = null;
    let pollInterval: NodeJS.Timeout | null = null;

    const fetchRun = async () => {
      try {
        const data = await request<ReproductionRun>(
          `/api/v1/reproductions/${resolvedParams.reproductionId}`
        );
        setRun(data);
        setEvents(data.events || []);

        if (data.status === "running") {
          startEventSource();
        }
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Failed to fetch reproduction run");
      }
    };

    const startEventSource = () => {
      eventSource = new EventSource(
        `${API_URL}/api/v1/reproductions/${resolvedParams.reproductionId}/stream`
      );

      eventSource.onmessage = (e) => {
        try {
          const newEvent = JSON.parse(e.data) as ReproductionEvent;
          setEvents((prev) => [...prev, newEvent]);
          setRun((prevRun: ReproductionRun | null) => {
            if (!prevRun) return prevRun;
            return {
              ...prevRun,
              current_phase: newEvent.phase,
            };
          });
          
          if (
            newEvent.phase === "completed" ||
            newEvent.phase === "failed" ||
            newEvent.phase === "cancelled"
          ) {
            eventSource?.close();
            // Refresh run to get final state
            setTimeout(fetchRun, 1000);
          }
        } catch (err) {
          console.error("Error parsing SSE data", err);
        }
      };

      eventSource.onerror = () => {
        console.error("SSE connection error. Falling back to polling.");
        eventSource?.close();
        // Fallback to polling every 3 seconds
        pollInterval = setInterval(fetchRun, 3000);
      };
    };

    fetchRun();

    return () => {
      if (eventSource) eventSource.close();
      if (pollInterval) clearInterval(pollInterval);
    };
  }, [resolvedParams.reproductionId]);

  const handleCancel = async () => {
    try {
      await request(`/api/v1/reproductions/${resolvedParams.reproductionId}/cancel`, {
        method: "POST",
      });
      // Will be updated via SSE or next poll
    } catch (e: unknown) {
      alert("Failed to cancel: " + (e instanceof Error ? e.message : String(e)));
    }
  };

  const handleRerun = async () => {
    if (!run) return;
    try {
      const newRun = await request<ReproductionRun>(`/api/v1/reproductions`, {
        method: "POST",
        body: JSON.stringify({
          commit_sha: run.commit_sha,
          workflow_run_id: run.workflow_run_id,
          job_id: run.job_id,
        }),
      });
      router.push(
        `/repositories/${resolvedParams.repositoryId}/reproductions/${newRun.id}`
      );
    } catch (e: unknown) {
      alert("Failed to re-run: " + (e instanceof Error ? e.message : String(e)));
    }
  };

  if (error) {
    return (
      <div className="shell">
        <Navigation active="repositories" />
        <main className="workspace">
          <div className="errorBanner">
            <b>Error</b>
            <span>{error}</span>
          </div>
        </main>
      </div>
    );
  }

  if (!run) {
    return (
      <div className="shell">
        <Navigation active="repositories" />
        <main className="workspace">
          <p>Loading reproduction run...</p>
        </main>
      </div>
    );
  }

  const isRunActive = run.status === "running";
  
  // Phase logic
  let activePhaseIndex = PHASES.findIndex((p) => p.id === run.current_phase);
  if (run.current_phase === "failed" || run.current_phase === "cancelled") {
    activePhaseIndex = PHASES.length - 1; // Verdict
  }

  return (
    <div className="shell">
      <Navigation active="repositories" />
      <main className="workspace">
        <header>
          <div>
            <div className="eyebrow">
              <Link href={`/repositories/${resolvedParams.repositoryId}`}>
                BACK TO REPOSITORY
              </Link>
            </div>
            <h1>
              COMMAND CENTER / {run.commit_sha.substring(0, 7)}
            </h1>
          </div>
          <div className="reportActions">
            <Link
              href={`/repositories/${resolvedParams.repositoryId}`}
              className="quietButton"
            >
              Back to Repository
            </Link>
            {!isRunActive && (
              <button onClick={handleRerun}>Re-run Reproduction</button>
            )}
          </div>
        </header>

        <div className="phaseTimeline">
          {PHASES.map((phase, idx) => {
            const isCompleted =
              idx < activePhaseIndex ||
              (idx === activePhaseIndex && !isRunActive && run.current_phase === "completed");
            const isActive = idx === activePhaseIndex && isRunActive;
            const isFailed =
              idx === activePhaseIndex &&
              (run.current_phase === "failed" || run.current_phase === "cancelled");

            return (
              <div
                key={phase.id}
                className={`phaseStep ${
                  isActive
                    ? "active"
                    : isCompleted
                    ? "completed"
                    : isFailed
                    ? "failed"
                    : ""
                }`}
              >
                <div className="stepIndicator">
                  <div className="circle" />
                  <b>Step {idx + 1}</b>
                </div>
                <small>{phase.label}</small>
              </div>
            );
          })}
        </div>

        <ReproductionTerminal
          events={events}
          command={run.command}
          detectedStack={run.detected_stack}
          exitCode={run.exit_code}
          isRunActive={isRunActive}
          onCancel={handleCancel}
        />
      </main>
    </div>
  );
}
