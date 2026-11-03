import { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Gamepad2, Settings, Power } from 'lucide-react';
import { useEventStream } from '@/hooks/useEventStream';

// ------------------------------
// Nicknames (id -> nickname)
// Only display logic is changed. All endpoints & payloads stay the same.
// ------------------------------
const NICKNAMES: Record<number, string> = {
  1: 'AMIS',
  2: 'OGLINDA',
  3: 'FOTOLIU',
  4: 'SCANNER',
  5: 'ASPIRATOR',
  6: 'JUCARIE 1',
  7: 'JUCARIE 2',
  8: 'BRAT',
  9: 'BROSELE',
  10: 'LUMINI',
};

const labelForId = (id: number): string => {
  const nn = NICKNAMES[id];
  return nn ? nn : `Robot ${id}`;
};

const idFromLabel = (label: string): number | null => {
  // Accept labels like "Robot 1" or just the nickname
  const m = label.match(/^Robot\s+(\d+)/i);
  if (m) {
    const id = Number(m[1]);
    return Number.isFinite(id) ? id : null;
  }
  // Allow selecting by pure nickname
  const lower = label.toLowerCase().trim();
  for (const [k, v] of Object.entries(NICKNAMES)) {
    if (v.toLowerCase() === lower) return Number(k);
  }
  return null;
};

const NONE_LABEL = 'Fără robot'; // “None / Stand-by” in RO

// Render labels for 15 robots, with nicknames only if defined
const ROBOT_IDS = Array.from({ length: 15 }, (_, i) => i + 1);
const ROBOT_LABELS = ROBOT_IDS.map(labelForId);


// ------------------------------
// Types
// ------------------------------
type ControllerId = 1 | 2;

type StreamController = {
  selected_robot?: number | string | null;
  axes?: number[];
  buttons?: (number | boolean)[];
  enabled?: boolean;
  disabled?: boolean;
  last_update?: number | null;
};

type StreamPlay = {
  mode?: string;
  controllers?: Record<'1' | '2', StreamController>;
  telemetry?: Record<string, any>;
};

interface Controller {
  id: ControllerId;
  enabled: boolean; // power toggle (client-side)
  disabled: boolean; // “disable commands” toggle (client-side)
  selected_robot: string; // label like "Robot 1 - erou"
  axes: number[];
  buttons: (number | boolean)[];
}

export default function GamepadController() {
  const [isConnected, setIsConnected] = useState(false);

  // Local UI state for two controllers; toggles are client-only for now.
  const [controllers, setControllers] = useState<Controller[]>([
    { id: 1, enabled: true, disabled: false, selected_robot: labelForId(1), axes: [], buttons: [] },
    { id: 2, enabled: true, disabled: false, selected_robot: labelForId(2), axes: [], buttons: [] },
  ]);

  const stream = useEventStream<{ play?: StreamPlay }>('/stream');

  // Helper: map stream selected_robot (number/string) to display label with nickname
  const toLabel = (
    sel: number | string | null | undefined,
    prev: string
  ): string => {
    if (sel === null || sel === undefined || (sel as any) === '') return NONE_LABEL;
    if (typeof sel === 'number') return labelForId(Math.max(1, Math.min(ROBOT_IDS.length, sel)));
    if (typeof sel === 'string') {
      const id = idFromLabel(sel);
      return id ? labelForId(id) : sel; // keep server-provided string if it doesn't match our pattern
    }
    return prev;
  };

  // Pull data from SSE → update axes/buttons/selected robot for each controller.
  useEffect(() => {
    const play = stream?.play;
    if (!play || !play.controllers) return;

    setIsConnected(true);

    setControllers(prev => {
      const byId = (id: ControllerId) => prev.find(c => c.id === id)!;
      const c1Prev = byId(1);
      const c2Prev = byId(2);

      const s1 = play.controllers['1'] || {};
      const s2 = play.controllers['2'] || {};

      const c1: Controller = {
        ...c1Prev,
        // keep local toggles (enabled/disabled) as UI-only
        selected_robot: toLabel(s1.selected_robot, c1Prev.selected_robot),
        axes: Array.isArray(s1.axes) ? (s1.axes as number[]) : c1Prev.axes,
        buttons: Array.isArray(s1.buttons) ? s1.buttons : c1Prev.buttons,
      };

      const c2: Controller = {
        ...c2Prev,
        selected_robot: toLabel(s2.selected_robot, c2Prev.selected_robot),
        axes: Array.isArray(s2.axes) ? (s2.axes as number[]) : c2Prev.axes,
        buttons: Array.isArray(s2.buttons) ? s2.buttons : c2Prev.buttons,
      };

      return [c1, c2];
    });
  }, [stream]);

  // UI-only toggles
  const toggleController = (controllerId: ControllerId) => {
    setControllers(prev => prev.map(c => (c.id === controllerId ? { ...c, enabled: !c.enabled } : c)));
  };
  const toggleDisable = (controllerId: ControllerId) => {
    setControllers(prev => prev.map(c => (c.id === controllerId ? { ...c, disabled: !c.disabled } : c)));
  };

  const selectNone = async (controllerId: ControllerId) => {
    try {
      const res = await fetch('/select_robot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ controller: controllerId, robot: null }),
      });
      if (res.ok) {
        setControllers(prev => prev.map(c => (c.id === controllerId ? { ...c, selected_robot: NONE_LABEL } : c)));
      } else {
        console.error('Failed to clear selection');
      }
    } catch (err) {
      console.error('Failed to clear selection:', err);
    }
  };

  // Robot selection → keep first endpoint logic, include controller for the new model
  const selectRobot = async (controllerId: ControllerId, robotLabel: string) => {
    const robotId = idFromLabel(robotLabel);
    if (!robotId) return;

    try {
      const res = await fetch('/select_robot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // new model: include controller; old backends may ignore it
        body: JSON.stringify({ controller: controllerId, robot: robotId }),
      });

      if (res.status === 409) {
        const msg = await res.json().catch(() => ({}));
        console.warn(msg?.error || 'Robot already taken by the other controller.');
        return; // do not update local state
      }
      if (res.ok) {
        setControllers(prev => prev.map(c => (c.id === controllerId ? { ...c, selected_robot: labelForId(robotId) } : c)));
      } else {
        console.error('Invalid robot selection');
      }
    } catch (err) {
      console.error('Failed to select robot:', err);
    }
  };

  return (
    <div className="min-h-screen bg-background p-6 ">
      <div className="max-w-7xl mx-auto space-y-8">
        {/* Header */}
        <div className="text-center space-y-4">
          <div className="flex items-center justify-center space-x-3">
            <Gamepad2 className="h-8 w-8 text-gaming-primary" />
            <h1 className="text-4xl font-bold bg-gradient-to-r from-gaming-primary to-gaming-secondary bg-clip-text text-transparent">
              Panou Control pentru Roboti
            </h1>
          </div>
          <div className="flex items-center justify-center space-x-2">
            <div className={`h-3 w-3 rounded-full ${isConnected ? 'bg-gaming-success animate-pulse' : 'bg-destructive'}`} />
            <span className="text-sm text-muted-foreground">
              {isConnected ? 'Connected' : 'Disconnected'}
            </span>
          </div>
        </div>

        {/* Two controller columns */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {controllers.map(controller => (
            <div key={controller.id} className="space-y-6">
              {/* Controller header with toggles */}
              <Card className={`border-2 ${controller.enabled ? 'border-gaming-primary' : 'border-border/50'}`}>
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <CardTitle className="flex items-center space-x-2">
                      <Gamepad2 className="h-5 w-5" />
                      <span>Controller {controller.id}</span>
                      <Badge variant="secondary" className="ml-2">
                        {controller.selected_robot}
                      </Badge>
                    </CardTitle>
                    <div className="flex items-center space-x-4">
                      {controller.id === 1 && (
                        <div className="flex items-center space-x-2">
                          <span className="text-sm">Dezactivează comenzi</span>
                          <Switch checked={controller.disabled} onCheckedChange={() => toggleDisable(controller.id)} />
                        </div>
                      )}
                      <div className="flex items-center space-x-2">
                        <Power className="h-4 w-4" />
                        <Switch checked={controller.enabled} onCheckedChange={() => toggleController(controller.id)} />
                      </div>
                    </div>
                  </div>
                </CardHeader>
              </Card>

              {/* Robot selection */}
              {controller.enabled && (
                <Card className={controller.disabled ? 'opacity-50' : ''}>
                  <CardHeader>
                    <CardTitle className="flex items-center space-x-2">
                      <Settings className="h-5 w-5 text-gaming-secondary" />
                      <span>Selectare Robot</span>
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                      {/* NONE button */}
                      <Button
                        key={`${controller.id}-none`}
                        variant={controller.selected_robot === NONE_LABEL ? 'default' : 'outline'}
                        size="sm"
                        onClick={() => selectNone(controller.id)}
                        disabled={controller.disabled}
                        className={`transition-all duration-200 ${
                          controller.selected_robot === NONE_LABEL
                            ? 'bg-gaming-primary hover:bg-gaming-primary/90 text-background shadow-[0_0_20px_hsl(var(--gaming-primary)/0.4)]'
                            : 'border-border hover:border-gaming-primary/50 hover:bg-gaming-primary/10'
                        }`}
                      >
                        {NONE_LABEL}
                      </Button>

                      {ROBOT_LABELS.map(robotLabel => {
                        const otherId = controllers.find(c => c.id !== controller.id)?.selected_robot ?? NONE_LABEL;
                        const isTakenByOther = (() => {
                          const a = idFromLabel(otherId);
                          const b = idFromLabel(robotLabel);
                          return a !== null && b !== null && a === b;
                        })();
                        return (
                          <Button
                            key={`${controller.id}-${robotLabel}`}
                            variant={controller.selected_robot === robotLabel ? 'default' : 'outline'}
                            size="sm"
                            onClick={() => selectRobot(controller.id, robotLabel)}
                            disabled={controller.disabled || isTakenByOther}
                            className={`transition-all duration-200 ${
                              controller.selected_robot === robotLabel
                                ? 'bg-gaming-primary hover:bg-gaming-primary/90 text-background shadow-[0_0_20px_hsl(var(--gaming-primary)/0.4)]'
                                : 'border-border hover:border-gaming-primary/50 hover:bg-gaming-primary/10'
                            }`}
                            title={isTakenByOther ? 'Ales de celălalt controller' : undefined}
                          >
                            {robotLabel}
                          </Button>
                        );
                      })}
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* Selected Robot */}
              {controller.enabled && (
                <Card className={controller.disabled ? 'opacity-50' : ''}>
                  <CardContent className="py-4">
                    <div className="text-center">
                      <div className="text-xl font-bold text-gaming-primary">
                        Robot activ: {controller.selected_robot}
                      </div>
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* Axes */}
              {controller.enabled && (
                <Card>
                  <CardHeader>
                    <CardTitle>Axe Analog</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-3 max-h-64 overflow-y-auto">
                      {controller.axes.length === 0 ? (
                        <div className="text-center text-muted-foreground py-4">Fără date de axe</div>
                      ) : (
                        controller.axes.map((value, index) => (
                          <div key={index} className="flex items-center space-x-3">
                            <span className="text-sm font-medium w-16">Axa {index}:</span>
                            <div className="flex-1 bg-muted rounded-full h-2">
                              <div className="h-2 bg-gaming-primary rounded-full transition-all duration-75" style={{ width: `${Math.abs(value) * 100}%` }} />
                            </div>
                            <span className="text-sm font-mono w-16 text-right">{Number(value).toFixed(3)}</span>
                          </div>
                        ))
                      )}
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* Buttons */}
              {controller.enabled && (
                <Card>
                  <CardHeader>
                    <CardTitle>Butoane Digitale</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-2 max-h-64 overflow-y-auto">
                      {controller.buttons.length === 0 ? (
                        <div className="text-center text-muted-foreground py-4">Fără date de butoane</div>
                      ) : (
                        <div className="grid grid-cols-2 gap-2">
                          {controller.buttons.map((pressed, index) => {
                            const on = !!pressed;
                            return (
                              <div
                                key={index}
                                className={`flex items-center justify-between p-2 rounded-md border transition-all duration-75 ${
                                  on
                                    ? 'bg-gaming-secondary/20 border-gaming-secondary text-gaming-secondary'
                                    : 'bg-muted/50 border-border text-muted-foreground'
                                }`}
                              >
                                <span className="text-sm font-medium">Btn {index}</span>
                                <div className={`h-3 w-3 rounded-full transition-all duration-75 ${on ? 'bg-gaming-secondary' : 'bg-muted-foreground/30'}`} />
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  </CardContent>
                </Card>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
