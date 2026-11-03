import { useEffect, useRef, useState } from "react";

export function useEventStream<T = any>(url: string = "/stream") {
  const [data, setData] = useState<T | null>(null);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const es = new EventSource(url);
    es.onmessage = (e) => { try { setData(JSON.parse(e.data)); } catch {} };
    es.onerror = () => {}; // browser retries automatically
    esRef.current = es;
    return () => { es.close(); };
  }, [url]);

  return data;
}
