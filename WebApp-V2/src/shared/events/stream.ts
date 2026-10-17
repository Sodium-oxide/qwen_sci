import { createParser } from "eventsource-parser";

export type Connection = "connecting" | "connected" | "reconnecting" | "polling" | "closed";
export interface DurableEvent {event_id: string; event_type: string; timestamp: string; payload: Record<string, unknown>}

export function readCursor(key: string) {
  try {return sessionStorage.getItem(`qwensci:event:${key}`) || "0";} catch {return "0";}
}

function writeCursor(key: string, cursor: string) {
  try {sessionStorage.setItem(`qwensci:event:${key}`, cursor);} catch {return;}
}

function pause(duration: number, signal: AbortSignal) {
  return new Promise<void>((resolve) => {
    const finish = () => {clearTimeout(timer); signal.removeEventListener("abort", finish); resolve();};
    const timer = setTimeout(finish, duration);
    signal.addEventListener("abort", finish, {once: true});
    if (signal.aborted) finish();
  });
}

export async function streamEvents(options: {
  url: string; key: string; signal: AbortSignal;
  onEvent: (event: DurableEvent) => void; onConnection: (connection: Connection) => void;
  fetcher?: typeof fetch;
}) {
  const {signal, key, onConnection, onEvent} = options;
  let cursor = readCursor(key);
  let failures = 0;
  while (!signal.aborted) {
    onConnection(failures ? failures >= 2 ? "polling" : "reconnecting" : "connecting");
    try {
      const url = `${options.url}${options.url.includes("?") ? "&" : "?"}after=${cursor}`;
      const response = await (options.fetcher || fetch)(url, {signal, credentials: "same-origin", headers: {Accept: "text/event-stream", "Last-Event-ID": cursor}});
      if (!response.ok || !response.body || !response.headers.get("content-type")?.includes("text/event-stream")) throw new Error("Event stream unavailable");
      onConnection("connected");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      const parser = createParser({onEvent(message) {
        if (message.event === "keepalive") return;
        if (!message.id || !/^\d+$/.test(message.id) || BigInt(message.id) <= BigInt(cursor)) return;
        let value: Record<string, unknown>;
        try {value = JSON.parse(message.data) as Record<string, unknown>;} catch {return;}
        if (typeof value !== "object" || value === null) return;
        cursor = message.id;
        failures = 0;
        writeCursor(key, cursor);
        onEvent({event_id: cursor, event_type: String(value.event_type || message.event || "EVENT"),
          timestamp: typeof value.timestamp === "string" ? value.timestamp : "",
          payload: typeof value.payload === "object" && value.payload !== null ? value.payload as Record<string, unknown> : value});
      }});
      try {
        while (!signal.aborted) {
          const chunk = await reader.read();
          if (chunk.done) break;
          parser.feed(decoder.decode(chunk.value, {stream: true}));
        }
      } finally {await reader.cancel().catch(() => undefined); reader.releaseLock();}
      if (!signal.aborted) throw new Error("Event stream ended");
    } catch {
      if (signal.aborted) break;
      failures += 1;
      onConnection(failures >= 2 ? "polling" : "reconnecting");
      await pause(Math.min(30_000, 1000 * 2 ** Math.min(failures, 5)) + Math.random() * 250, signal);
    }
  }
}
