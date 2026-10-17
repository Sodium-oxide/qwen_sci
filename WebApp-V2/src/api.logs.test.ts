import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";

afterEach(() => vi.unstubAllGlobals());

describe("persisted log events", () => {
  it("reads the finite event stream from its cursor without duplicating projected events", async () => {
    const event = { event_id: "8", event_type: "STAGE_STARTED", timestamp: "2026-10-17T00:00:00Z", payload: { stage: "survey" } };
    const payload = JSON.stringify(event);
    const fetcher = vi.fn().mockResolvedValue(new Response(
      `id: 8\nevent: STAGE_STARTED\ndata: ${payload}\n\nid: 8\nevent: run_event\ndata: ${payload}\n\n`,
      { headers: { "content-type": "text/event-stream" } },
    ));
    vi.stubGlobal("fetch", fetcher);
    const controller = new AbortController();
    await expect(api.logEvents("run-a", 7, controller.signal)).resolves.toEqual([event]);
    expect(fetcher).toHaveBeenCalledWith("/api/runs/run-a/events?follow=false&after=7", expect.objectContaining({ signal: controller.signal }));
  });
});
