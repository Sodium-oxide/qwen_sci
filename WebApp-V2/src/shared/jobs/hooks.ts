import { useQuery, useQueryClient } from "@tanstack/react-query";
import { client } from "../api";
import { useResourceEvents } from "../events/useResourceEvents";

export function useJob(jobId: string) {
  const queryClient = useQueryClient();
  const job = useQuery({queryKey: ["job", jobId], queryFn: ({signal}) => client.job(jobId, signal), enabled: Boolean(jobId)});
  const live = job.data && ["QUEUED", "RUNNING", "WAITING_FOR_REVIEW", "CANCEL_REQUESTED"].includes(job.data.status);
  const events = useResourceEvents(`job:${jobId}`, `/api/jobs/${encodeURIComponent(jobId)}/events`, () => {
    void queryClient.invalidateQueries({queryKey: ["job", jobId]});
    void queryClient.invalidateQueries({queryKey: ["jobs"]});
    void queryClient.invalidateQueries({queryKey: ["review", jobId]});
    void queryClient.invalidateQueries({queryKey: ["artifacts", jobId]});
    void queryClient.invalidateQueries({queryKey: ["result", jobId]});
  }, Boolean(live));
  return {...job, ...events};
}

export const useCapabilities = () => useQuery({queryKey: ["capabilities"], queryFn: ({signal}) => client.capabilities(signal), staleTime: 60_000});
export const usePreferences = () => useQuery({queryKey: ["preferences"], queryFn: ({signal}) => client.preferences(signal), staleTime: 30_000});
