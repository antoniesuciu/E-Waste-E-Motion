import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useEventStream } from "@/hooks/useEventStream";

export default function Live() {
  const snapshot = useEventStream<any>("/stream");
  if (!snapshot) return <div className="p-6">Connecting…</div>;
  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold mb-3">play_state</h1>
      <pre className="text-xs bg-black/5 p-3 rounded max-h-[70vh] overflow-auto">
        {JSON.stringify(snapshot, null, 2)}
      </pre>
    </div>
  );
}
