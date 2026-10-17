import { useEffect, useRef, useState } from "react";
import { streamEvents, type Connection, type DurableEvent } from "./stream";

export function useResourceEvents(key: string | undefined, url: string | undefined, onSnapshot: () => void, enabled = true) {
  const [connection, setConnection] = useState<Connection>("closed");
  const [events, setEvents] = useState<DurableEvent[]>([]);
  const callback = useRef(onSnapshot);
  callback.current = onSnapshot;
  useEffect(() => {
    setEvents([]);
    if (!key || !url || !enabled) {setConnection("closed"); return;}
    const controller = new AbortController();
    let refreshTimer: ReturnType<typeof setTimeout> | undefined;
    const poll = setInterval(() => callback.current(), 15_000);
    void streamEvents({url, key, signal: controller.signal, onConnection: setConnection, onEvent(event) {
      setEvents(current => [...current, event].slice(-300));
      if (!refreshTimer) refreshTimer = setTimeout(() => {refreshTimer = undefined; callback.current();}, 250);
    }});
    return () => {controller.abort(); clearInterval(poll); clearTimeout(refreshTimer);};
  }, [key, url, enabled]);
  return {connection, events};
}
