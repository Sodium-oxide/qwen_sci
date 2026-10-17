import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, request } from "./http";

afterEach(() => vi.restoreAllMocks());

describe("request error contract", () => {
  it("normalizes the backend error envelope and request id", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({error: {
      code: "MODEL_CALL_OUTCOME_UNKNOWN", message: "provider state is unknown", retryable: false, request_id: "req-42",
    }}), {status: 502, headers: {"content-type": "application/json"}})));
    await expect(request("/api/jobs/job-1")).rejects.toMatchObject({
      name: "ApiError", status: 502, code: "MODEL_CALL_OUTCOME_UNKNOWN", requestId: "req-42", retryable: false,
    } satisfies Partial<ApiError>);
  });

  it("does not retry or parse an empty 204 response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, {status: 204})));
    await expect(request<void>("/api/files/file-1", {method: "DELETE"})).resolves.toBeUndefined();
  });
});
