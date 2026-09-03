import { useEffect, useRef, useState } from "react";

import { parseRunEvent } from "../api";
import type { ResearchRun, RunEvent } from "../types";

const EVENT_TYPES = [
  "RUN_INITIALIZED", "MATERIALS_REGISTERED", "MATERIAL_REMOVED", "STAGE_STARTED", "STAGE_COMPLETED",
  "STAGE_FAILED", "STAGE_RECOVERED", "STAGE_RECOVERY_RETRY", "RUN_COMPLETED", "RUN_PARTIAL",
  "RUN_CANCELLATION_REQUESTED", "RUN_CANCELLED", "RUN_RESUMED",
  "QUANTITATIVE_IDEA_SIDECAR_PUBLISHED", "QUANTITATIVE_ACTION_STARTED", "QUANTITATIVE_ACTION_COMPLETED",
  "QUANTITATIVE_ACTION_FAILED",
];

export function useRunEvents(run: ResearchRun | null, onSnapshotNeeded: () => void) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [connection, setConnection] = useState("等待选择运行");
  const refreshTimer = useRef<number | null>(null);

  useEffect(() => {
    if (!run?.event_url) {
      setEvents([]);
      setConnection("等待选择运行");
      return undefined;
    }
    setEvents([]);
    setConnection("已连接");
    const source = new EventSource(run.event_url);
    const receive = (message: MessageEvent<string>) => {
      const event = parseRunEvent(message);
      if (!event) return;
      setEvents((previous) => previous.some((item) => item.event_id === event.event_id) ? previous : [...previous, event]);
      if (refreshTimer.current === null) {
        refreshTimer.current = window.setTimeout(() => {
          refreshTimer.current = null;
          onSnapshotNeeded();
        }, 250);
      }
    };
    source.addEventListener("run_event", receive as EventListener);
    EVENT_TYPES.forEach((eventType) => source.addEventListener(eventType, receive as EventListener));
    source.addEventListener("keepalive", () => setConnection("实时更新中"));
    source.onerror = () => setConnection(source.readyState === EventSource.CLOSED ? "事件连接已关闭" : "正在重连");
    return () => {
      if (refreshTimer.current !== null) window.clearTimeout(refreshTimer.current);
      refreshTimer.current = null;
      source.removeEventListener("run_event", receive as EventListener);
      EVENT_TYPES.forEach((eventType) => source.removeEventListener(eventType, receive as EventListener));
      source.close();
    };
  }, [run?.run_id, run?.event_url, onSnapshotNeeded]);

  return { events, connection };
}
