import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Gamepad2, Radio } from 'lucide-react';
import { useEventStream } from '@/hooks/useEventStream';
import { toast } from '@/hooks/use-toast';
import { NONE_LABEL, ROBOT_IDS, robotLabel } from '@/lib/robots';

type ControllerId = 1 | 2;

type StreamController = {
  selected_robot?: number | null;
  axes?: number[];
  buttons?: (number | boolean)[];
};

type Telemetry = Record<string, unknown> & { _last_seen_ms?: number };

type StreamPayload = {
  play?: {
    controllers?: Partial<Record<'1' | '2', StreamController>>;
    telemetry?: Record<string, Telemetry>;
  };
};

const TELEMETRY_STALE_MS = 1500;
const AXIS_NAMES = ['X', 'Y'];

// Robots stop streaming after a recording ends, so "stale" means "no recent packets", not "offline".
function useTelemetryFreshness(telemetry: Record<string, Telemetry> | undefined) {
  const lastChange = useRef<Record<string, { seen?: number; at: number }>>({});
  const [, tick] = useState(0);

  useEffect(() => {
    const now = performance.now();
    for (const [rid, pkt] of Object.entries(telemetry ?? {})) {
      const prev = lastChange.current[rid];
      if (!prev || prev.seen !== pkt._last_seen_ms) lastChange.current[rid] = { seen: pkt._last_seen_ms, at: now };
    }
  }, [telemetry]);

  useEffect(() => {
    const id = setInterval(() => tick(n => n + 1), 500);
    return () => clearInterval(id);
  }, []);

  return (rid: number) => {
    const entry = lastChange.current[String(rid)];
    return !!entry && performance.now() - entry.at < TELEMETRY_STALE_MS;
  };
}

async function postSelection(controller: ControllerId, robot: number | null) {
  try {
    const res = await fetch('/select_robot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ controller, robot }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      toast({ title: 'Selecție respinsă', description: body?.error ?? `HTTP ${res.status}`, variant: 'destructive' });
    }
  } catch {
    toast({ title: 'Eroare de rețea', description: 'Serverul nu răspunde', variant: 'destructive' });
  }
}

function AxisBar({ name, value }: { name: string; value: number }) {
  const pct = Math.min(1, Math.abs(value)) * 50;
  return (
    <div className="flex items-center gap-3">
      <span className="w-6 text-xs font-medium text-muted-foreground">{name}</span>
      <div className="relative h-2 flex-1 rounded-full bg-muted">
        <div className="absolute inset-y-0 left-1/2 w-px bg-border" />
        <div
          className="absolute inset-y-0 rounded-full bg-gaming-primary transition-all duration-75"
          style={value >= 0 ? { left: '50%', width: `${pct}%` } : { right: '50%', width: `${pct}%` }}
        />
      </div>
      <span className="w-14 text-right font-mono text-xs tabular-nums">{value.toFixed(2)}</span>
    </div>
  );
}

function TelemetryReadout({ pkt, fresh }: { pkt?: Telemetry; fresh: boolean }) {
  const fields: [string, string][] = [
    ['A', 'Enc. stânga'],
    ['B', 'Enc. dreapta'],
    ['g', 'Unghi (°)'],
    ['L', 'PWM st.'],
    ['R', 'PWM dr.'],
  ];
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-sm">
        <span className={`h-2.5 w-2.5 rounded-full ${fresh ? 'bg-gaming-success animate-pulse' : 'bg-muted-foreground/40'}`} />
        <span className="text-muted-foreground">{fresh ? 'Telemetrie activă' : 'Fără telemetrie recentă'}</span>
      </div>
      {pkt && (
        <dl className="grid grid-cols-3 gap-2 sm:grid-cols-5">
          {fields.filter(([k]) => k in pkt).map(([k, label]) => (
            <div key={k} className="rounded-md border border-border/60 bg-muted/30 px-2 py-1.5">
              <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</dt>
              <dd className="font-mono text-sm tabular-nums">
                {typeof pkt[k] === 'number' ? Number(pkt[k]).toFixed(k === 'g' ? 1 : 0) : String(pkt[k])}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

export default function GamepadController() {
  const stream = useEventStream<StreamPayload>('/stream');
  const play = stream?.play;
  const isFresh = useTelemetryFreshness(play?.telemetry);

  const selected = (id: ControllerId): number | null => {
    const sel = play?.controllers?.[String(id) as '1' | '2']?.selected_robot;
    return typeof sel === 'number' ? sel : null;
  };

  return (
    <div className="bg-background p-6">
      <div className="mx-auto max-w-7xl space-y-8">
        <div className="flex flex-col items-center gap-3 text-center">
          <div className="flex items-center gap-3">
            <Gamepad2 className="h-8 w-8 text-gaming-primary" />
            <h1 className="bg-gradient-to-r from-gaming-primary to-gaming-secondary bg-clip-text text-3xl font-bold text-transparent sm:text-4xl">
              Panou control roboți
            </h1>
          </div>
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <span className={`h-3 w-3 rounded-full ${play ? 'bg-gaming-success animate-pulse' : 'bg-destructive'}`} />
            {play ? 'Conectat la server' : 'Se conectează…'}
          </div>
        </div>

        <div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
          {([1, 2] as ControllerId[]).map(cid => {
            const ctrl = play?.controllers?.[String(cid) as '1' | '2'];
            const rid = selected(cid);
            const other = selected(cid === 1 ? 2 : 1);
            const axes = (ctrl?.axes ?? []).slice(0, 2);
            const buttons = ctrl?.buttons ?? [];

            return (
              <Card key={cid} className={`border-2 ${rid !== null ? 'border-gaming-primary/70' : 'border-border/50'}`}>
                <CardHeader className="pb-4">
                  <CardTitle className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-2">
                      <Gamepad2 className="h-5 w-5" />
                      Controller {cid}
                    </span>
                    <Badge variant={rid !== null ? 'default' : 'secondary'} className="text-sm">
                      {rid !== null ? robotLabel(rid) : NONE_LABEL}
                    </Badge>
                  </CardTitle>
                </CardHeader>

                <CardContent className="space-y-6">
                  <section className="space-y-2">
                    <h3 className="text-sm font-medium text-muted-foreground">Selectare robot</h3>
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                      <Button
                        size="sm"
                        variant={rid === null ? 'default' : 'outline'}
                        onClick={() => postSelection(cid, null)}
                      >
                        {NONE_LABEL}
                      </Button>
                      {ROBOT_IDS.map(id => (
                        <Button
                          key={id}
                          size="sm"
                          variant={rid === id ? 'default' : 'outline'}
                          onClick={() => postSelection(cid, id)}
                          title={other === id ? 'Folosit de celălalt controller; selectarea îl preia' : undefined}
                          className={`relative ${rid === id ? 'shadow-[0_0_16px_hsl(var(--gaming-primary)/0.4)]' : ''}`}
                        >
                          {robotLabel(id)}
                          {isFresh(id) && <Radio className="absolute right-1.5 top-1.5 h-3 w-3 text-gaming-success" />}
                          {other === id && <span className="ml-1 text-[10px] text-muted-foreground">C{cid === 1 ? 2 : 1}</span>}
                        </Button>
                      ))}
                    </div>
                  </section>

                  {rid !== null && (
                    <section className="space-y-2">
                      <h3 className="text-sm font-medium text-muted-foreground">Telemetrie {robotLabel(rid)}</h3>
                      <TelemetryReadout pkt={play?.telemetry?.[String(rid)]} fresh={isFresh(rid)} />
                    </section>
                  )}

                  <section className="space-y-2">
                    <h3 className="text-sm font-medium text-muted-foreground">Joystick stânga</h3>
                    {axes.length === 0 ? (
                      <p className="text-sm text-muted-foreground">Fără date de la controller</p>
                    ) : (
                      axes.map((v, i) => <AxisBar key={i} name={AXIS_NAMES[i] ?? String(i)} value={Number(v)} />)
                    )}
                  </section>

                  {buttons.length > 0 && (
                    <section className="space-y-2">
                      <h3 className="text-sm font-medium text-muted-foreground">Butoane</h3>
                      <div className="flex flex-wrap gap-1.5">
                        {buttons.map((pressed, i) => (
                          <span
                            key={i}
                            className={`min-w-8 rounded-md border px-2 py-1 text-center font-mono text-xs transition-colors duration-75 ${
                              pressed
                                ? 'border-gaming-secondary bg-gaming-secondary/20 text-gaming-secondary'
                                : 'border-border bg-muted/40 text-muted-foreground'
                            }`}
                          >
                            {i}
                          </span>
                        ))}
                      </div>
                    </section>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>
    </div>
  );
}
