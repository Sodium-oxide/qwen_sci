import type { ResearchRun } from "../types";
import { useResourceEvents } from "../shared/events/useResourceEvents";

export function useRunEvents(run: ResearchRun | null, onSnapshotNeeded: () => void) {
  return useResourceEvents(run ? `run:${run.run_id}` : undefined, run?.event_url, onSnapshotNeeded);
}
