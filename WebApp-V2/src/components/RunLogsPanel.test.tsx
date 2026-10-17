import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../api";
import type { ResearchRun, RunLogChunk, RunLogSource } from "../types";
import { RunLogsPanel } from "./RunLogsPanel";

vi.mock("../api", () => ({ api: { logs: vi.fn(), logChunk: vi.fn(), logEvents: vi.fn() } }));

const source: RunLogSource = {
  log_id: "survey:attempt-001/console.log", label: "Survey console", stage: "survey", attempt: 1, format: "text", size_bytes: 10,
};
const run = { run_id: "run-a", status: "RUNNING", stages: { survey: { status: "RUNNING", attempt: 1 } } } as unknown as ResearchRun;
const chunk = (offset: number, content: string, logId = source.log_id): RunLogChunk => ({
  log_id: logId, format: "text", offset, next_offset: offset + content.length, has_more: false, content,
});

beforeEach(() => {
  vi.useFakeTimers();
  vi.mocked(api.logs).mockResolvedValue([source]);
  vi.mocked(api.logChunk).mockImplementation(async (_runId, logId, offset = 0) => chunk(offset, offset === 0 ? "initial\n" : "", logId));
  vi.mocked(api.logEvents).mockResolvedValue([]);
});

afterEach(() => { cleanup(); vi.useRealTimers(); vi.resetAllMocks(); });

async function mount(currentRun = run) {
  let rendered: ReturnType<typeof render>;
  await act(async () => { rendered = render(<RunLogsPanel run={currentRun} />); });
  return rendered!;
}

describe("run log synchronization", () => {
  it("polls new content without depending on automatic scrolling or duplicating records", async () => {
    vi.mocked(api.logChunk).mockImplementation(async (_runId, logId, offset = 0) =>
      chunk(offset, offset === 0 ? "initial\n" : offset === 8 ? "next\n" : "", logId));
    await mount();
    fireEvent.click(screen.getByRole("checkbox", { name: "滚动到最新内容" }));
    await act(async () => { await vi.advanceTimersByTimeAsync(4_100); });
    expect(screen.getByLabelText("运行日志内容").textContent).toBe("initial\nnext\n");
    expect(vi.mocked(api.logChunk).mock.calls.map((call) => call[2])).toEqual([0, 8, 13]);
  });

  it("shows persisted system events before the first stage log appears, then follows the stage", async () => {
    vi.mocked(api.logs).mockResolvedValueOnce([]).mockResolvedValue([source]);
    vi.mocked(api.logEvents).mockResolvedValue([{
      event_id: "1", event_type: "STAGE_STARTED", timestamp: "2026-10-17T00:00:00Z", payload: { stage: "survey" },
    }]);
    await mount();
    expect(screen.getByLabelText("运行日志内容").textContent).toContain("STAGE_STARTED");
    await act(async () => { await vi.advanceTimersByTimeAsync(2_100); });
    expect((screen.getByRole("combobox") as HTMLSelectElement).value).toBe(source.log_id);
    expect(screen.getByLabelText("运行日志内容").textContent).toBe("initial\n");
  });

  it("ignores a delayed response belonging to the previously selected research run", async () => {
    let completeOldRequest: (value: RunLogChunk) => void = () => undefined;
    vi.mocked(api.logChunk).mockImplementationOnce(() => new Promise((resolve) => { completeOldRequest = resolve; }));
    const rendered = await mount();
    await act(async () => { rendered.rerender(<RunLogsPanel run={{ ...run, run_id: "run-b" }} />); });
    expect(screen.getByLabelText("运行日志内容").textContent).toBe("initial\n");
    await act(async () => { completeOldRequest(chunk(0, "wrong research\n")); });
    expect(screen.getByLabelText("运行日志内容").textContent).toBe("initial\n");
  });

  it("retries a network failure from the last confirmed cursor and keeps existing content", async () => {
    vi.mocked(api.logChunk)
      .mockResolvedValueOnce(chunk(0, "initial\n"))
      .mockRejectedValueOnce(new Error("temporary network failure"))
      .mockResolvedValueOnce(chunk(8, "recovered\n"));
    await mount();
    await act(async () => { await vi.advanceTimersByTimeAsync(2_100); });
    expect(screen.getByRole("status").textContent).toContain("temporary network failure");
    expect(screen.getByLabelText("运行日志内容").textContent).toBe("initial\n");
    await act(async () => { await vi.advanceTimersByTimeAsync(2_000); });
    expect(screen.getByLabelText("运行日志内容").textContent).toBe("initial\nrecovered\n");
    expect(vi.mocked(api.logChunk).mock.calls[2][2]).toBe(8);
  });

  it("replaces the visible content when the server reports a truncated log", async () => {
    vi.mocked(api.logChunk).mockResolvedValueOnce(chunk(0, "initial\n")).mockResolvedValueOnce(chunk(0, "reset\n"));
    await mount();
    await act(async () => { await vi.advanceTimersByTimeAsync(2_100); });
    expect(screen.getByLabelText("运行日志内容").textContent).toBe("reset\n");
  });
});
