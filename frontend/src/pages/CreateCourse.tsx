import { useState, useEffect, useRef } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import {
  ArrowLeft, Play, Save, Clock, Square, Trash2, Gamepad2,
  ChevronLeft, ChevronRight
} from 'lucide-react';
import { toast } from '@/hooks/use-toast';
import { useEventStream } from '@/hooks/useEventStream';

interface RecordedMove {
  id: string;
  robotId: number;
  startT: number;
  endT: number | null;
  entries: any[];
}

interface RobotTimeline {
  robotId: number;
  moves: RecordedMove[];
}

type ControllerId = 1 | 2;

const ROBOTS = Array.from({ length: 10 }, (_, i) => i + 1);

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


// mm:ss (or h:mm:ss) formatter
const fmt = (secs: number) => {
  const s = Math.max(0, Math.floor(secs));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  return h > 0 ? `${h}:${String(m).padStart(2,'0')}:${String(ss).padStart(2,'0')}`
               : `${m}:${String(ss).padStart(2,'0')}`;
};


export default function CreateCourse() {
  const navigate = useNavigate();
  const { courseId: routeCourseId } = useParams();
  const editCourseId = routeCourseId || null;

  // Duration field is MINUTES in UI
  const [durationMinUI, setDurationMinUI] = useState(30);
  const [durationStr, setDurationStr] = useState(String(30));

  const [courseName, setCourseName] = useState('');
  const [robotTimelines, setRobotTimelines] = useState<RobotTimeline[]>(
    ROBOTS.map(id => ({ robotId: id, moves: [] }))
  );

  // NEW: allow multiple robots recording at once
  const [recordingRobots, setRecordingRobots] = useState<Set<number>>(new Set());

  // NEW: per-robot controller assignment (null | 1 | 2)
  const [robotControllers, setRobotControllers] = useState<Record<number, ControllerId | null>>(
    Object.fromEntries(ROBOTS.map(id => [id, null])) as Record<number, ControllerId | null>
  );

  const [currentTimeSec, setCurrentTimeSec] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [selectedMove, setSelectedMove] = useState<string | null>(null);
  // near your other state
  const [playingMoveId, setPlayingMoveId] = useState<string | null>(null);
  const [loadingMoveId, setLoadingMoveId] = useState<string | null>(null);

const clamp = (v: number, min: number, max: number) => Math.max(min, Math.min(max, v));
const stepBy = (delta: number) => {
  if (sampling) return; // ignore while server drives time
  setCurrentTimeSec(prev => clamp(prev + delta, 0, durationSec));
};

const stepLeftOnce  = () => stepBy(-1);
const stepRightOnce = () => stepBy(+1);

const leftHold  = useHoldRepeat(stepLeftOnce,  { initialDelay: 300, repeatInterval: 85, accelerate: true });
const rightHold = useHoldRepeat(stepRightOnce, { initialDelay: 300, repeatInterval: 85, accelerate: true });


const playMove = async (move: RecordedMove) => {
  if (!editCourseId || move.endT == null) return; // don't play incomplete
  setLoadingMoveId(move.id);
  try {
    const res = await fetch(`/api/move/run/${editCourseId}/${move.id}`, { method: 'POST' });
    if (!res.ok) throw new Error('run move failed');
    setPlayingMoveId(move.id);
    toast({ title: 'Redare mișcare', description: `Robot ${move.robotId} ${fmt(move.startT)}–${fmt(move.endT)}` });
  } catch (e) {
    console.error(e);
    toast({ title: 'Eroare', description: 'Nu s-a putut reda mișcarea', variant: 'destructive' });
  } finally {
    setLoadingMoveId(null);
  }
};

const stopMove = async (move: RecordedMove) => {
  if (!editCourseId) return;
  setLoadingMoveId(move.id);
  try {
    await fetch(`/api/move/stop/${editCourseId}/${move.id}`, { method: 'POST' });
    setPlayingMoveId(null);
  } catch (e) {
    console.error(e);
  } finally {
    setLoadingMoveId(null);
  }
};


  // 🔌 Stream ({ play, course })
  const stream = useEventStream<any>('/stream');

  // Use duration from stream if present (assumed MINUTES to match your UI), else local UI value
  const durationMin = (() => {
    const n = parseInt(durationStr, 10);
    return !Number.isNaN(n) && n > 0 && n <= 60 ? n : durationMinUI;
  })();
  const durationSec = Math.max(1, durationMin) * 60;

  // ===== Server-driven timer (seconds) =====
  const sampling = !!stream?.course?.sampling;
  const courseTime = Number(stream?.course?.course_time ?? 0);

  const [displayTime, setDisplayTime] = useState(0);
  const baseRef = useRef<{ t: number; ts: number; sampling: boolean }>({
    t: 0, ts: performance.now(), sampling: false
  });

  const buildTimelines = (moves: RecordedMove[]): RobotTimeline[] =>
    ROBOTS.map(id => ({ robotId: id, moves: moves.filter(m => m.robotId === id) 
  }));
  
function useHoldRepeat(
  action: () => void,
  opts: { initialDelay?: number; repeatInterval?: number; accelerate?: boolean; minInterval?: number } = {}
) {
  const { initialDelay = 300, repeatInterval = 80, accelerate = true, minInterval = 35 } = opts;

  const timerRef = useRef<number | null>(null);
  const repeatRef = useRef<number | null>(null);
  const intervalRef = useRef<number>(repeatInterval);
  const activeRef = useRef(false);

  const stop = () => {
    activeRef.current = false;
    if (timerRef.current !== null) { window.clearTimeout(timerRef.current); timerRef.current = null; }
    if (repeatRef.current !== null) { window.clearTimeout(repeatRef.current); repeatRef.current = null; }
    intervalRef.current = repeatInterval;
  };

  useEffect(() => () => stop(), []); // cleanup on unmount

  const loop = () => {
    if (!activeRef.current) return;
    action();
    if (accelerate) intervalRef.current = Math.max(minInterval, Math.floor(intervalRef.current * 0.92));
    repeatRef.current = window.setTimeout(loop, intervalRef.current);
  };

  const start = () => {
    if (activeRef.current) return;
    activeRef.current = true;
    action(); // immediate tap = one step
    timerRef.current = window.setTimeout(loop, initialDelay);
  };

  return { start, stop };
}

useEffect(() => {
  const onKey = (e: KeyboardEvent) => {
    if (sampling) return;
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault();
      stepBy((e.key === 'ArrowLeft' ? -1 : 1) * (e.shiftKey ? 5 : 1));
    }
  };
  window.addEventListener('keydown', onKey);
  return () => window.removeEventListener('keydown', onKey);
}, [sampling, durationSec]);
  // baseline from SSE
  useEffect(() => {
    if (!stream?.course) return;
    baseRef.current = { t: courseTime, ts: performance.now(), sampling };
    setDisplayTime(courseTime);
  }, [courseTime, sampling, stream?.course]);

  // Smooth animation between SSE ticks
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const { t, ts, sampling } = baseRef.current;
      setDisplayTime(sampling ? t + (performance.now() - ts) / 1000 : t);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  // While recording, follow server time; when paused, use scrubber
  const effectiveNowSec = sampling ? displayTime : currentTimeSec;

  // ===== Seed per-controller selection from SSE (if available) =====
  useEffect(() => {
    const controllers = stream?.play?.controllers;
    if (!controllers) return;

    // Build a fresh map: which robot is selected by C1/C2?
    const next: Record<number, ControllerId | null> =
      Object.fromEntries(ROBOTS.map(id => [id, null])) as Record<number, ControllerId | null>;

    const c1Sel = controllers['1']?.selected_robot;
    if (typeof c1Sel === 'number' && ROBOTS.includes(c1Sel)) next[c1Sel] = 1;

    const c2Sel = controllers['2']?.selected_robot;
    if (typeof c2Sel === 'number' && ROBOTS.includes(c2Sel)) next[c2Sel] = 2;

    setRobotControllers(next);
  }, [stream?.play?.controllers]);

 // ===== Load course for editing (prime backend + hydrate UI) =====
  useEffect(() => {
    if (!editCourseId) return;
    (async () => {
      try {
        // prime server: sets current_course + loads moves into memory
        const res = await fetch(`/api/course/edit/${editCourseId}/begin`, { method: 'POST' });
        if (!res.ok) throw new Error('begin-edit failed');
        const c = await res.json();
 
        setCourseName(c.name || '');
        const dm = Number(c.duration ?? durationMinUI);
        if (!Number.isNaN(dm) && dm > 0) {
          setDurationMinUI(dm);
          setDurationStr(String(dm));
        }
        const moves: RecordedMove[] = Array.isArray(c.moves) ? c.moves : [];
        // rebuild timelines from moves we just loaded
        setRobotTimelines(ROBOTS.map(id => ({
          robotId: id,
          moves: moves.filter(m => m.robotId === id),
        })));
      } catch (e) {
        console.error('Failed to begin edit:', e);
      }
    })();
  }, [editCourseId]);

  // ===== Controller assignment actions (exclusive per controller) =====
  const assignController = async (robotId: number, controller: ControllerId) => {
    try {
      // Backend: set controller → robot mapping
      const res = await fetch('/select_robot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ controller, robot: robotId }),
      });
      if (!res.ok) throw new Error('select_robot failed');

      // UI: exclusivity — the same controller can't be on two robots at once
      setRobotControllers(prev => {
        const next: Record<number, ControllerId | null> = { ...prev };
        for (const r of ROBOTS) {
          if (next[r] === controller) next[r] = null;
        }
        next[robotId] = controller;
        return next;
      });
    } catch (e) {
      console.error(e);
      toast({ title: "Eroare", description: "Nu s-a putut selecta controlerul", variant: "destructive" });
    }
  };

  // ===== Recording controls (now per-robot) =====
  const startRecording = async (robotId: number) => {
    if (!robotControllers[robotId]) {
      toast({ title: "Alege controlerul", description: "Selectați C1 sau C2 pentru robotul acesta", variant: "destructive" });
      return;
    }
    if (recordingRobots.has(robotId)) return; // already recording this robot

    try {
      const response = await fetch('/api/robot/start-recording', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ robotId, startTime: Math.max(0, Math.floor(effectiveNowSec)) })
      });
      if (!response.ok) throw new Error();
      const moveData = await response.json();

      setRecordingRobots(prev => {
        const s = new Set(prev);
        s.add(robotId);
        return s;
      });

      const newMove: RecordedMove = {
        id: moveData.id,
        robotId: moveData.robotId,
        startT: typeof moveData.startT === 'number' ? moveData.startT : Math.floor(effectiveNowSec),
        endT: null,
        entries: Array.isArray(moveData.entries) ? moveData.entries : []
      };
      setRobotTimelines(prev =>
        prev.map(tl => tl.robotId === robotId ? { ...tl, moves: [...tl.moves, newMove] } : tl)
      );

      toast({ title: "Înregistrare pornită", description: `Robot ${robotId} la ${fmt(effectiveNowSec)}` });
    } catch (e) {
      console.error(e);
      toast({ title: "Eroare", description: "Înregistrarea nu a putut porni", variant: "destructive" });
    }
  };

  const stopRecording = async (robotId: number) => {
    if (!recordingRobots.has(robotId)) return;

    try {
      const response = await fetch('/api/robot/stop-recording', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ robotId })
      });
      if (!response.ok) throw new Error();
      await response.json();

      setRecordingRobots(prev => {
        const s = new Set(prev);
        s.delete(robotId);
        return s;
      });

      setRobotTimelines(prev =>
        prev.map(tl =>
          tl.robotId === robotId
            ? { ...tl, moves: tl.moves.map(m => m.endT == null ? { ...m, endT: Math.max(0, Math.floor(effectiveNowSec)) } : m) }
            : tl
        )
      );

      toast({ title: "Înregistrare oprită", description: `Robot ${robotId}` });
    } catch (e) {
      console.error(e);
    }
  };

  const deleteMove = async (moveId: string) => {
    try {
      const response = await fetch(`/api/moves/${moveId}`, { method: 'DELETE' });
      if (!response.ok) throw new Error();
      setRobotTimelines(prev => prev.map(tl => ({ ...tl, moves: tl.moves.filter(m => m.id !== moveId) })));
      setSelectedMove(null);
      toast({ title: "Mișcare ștearsă", description: "Mișcarea a fost ștearsă cu succes" });
    } catch (e) {
      console.error('Failed to delete move:', e);
    }
  };

  const playFromTime = (time: number) => {
    setCurrentTimeSec(time);
    setIsPlaying(true);
    // TODO: implement actual playback
  };

  const handleSaveCourse = async () => {
    if (!courseName.trim()) {
      toast({ title: "Error", description: "Please enter a course name", variant: "destructive" });
      return;
    }
    try {
      // Save duration in MINUTES (as per your UI field)
      const response = await fetch('/api/course/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: courseName, duration: durationMin })
      });
      if (!response.ok) throw new Error();
      toast({ title: "Traseu salvat", description: `Traseu "${courseName}" salvat` });
      navigate('/');
    } catch (e) {
      console.error('Failed to save course:', e);
      toast({ title: "Eroare", description: "Eroare: traseul nu s-a putut salva", variant: "destructive" });
    }
  };

  // Positions/widths use SECONDS for precision; markers show MINUTES
  const getMoveLeft = (start: number) => `${(start / durationSec) * 100}%`;
  const getMoveWidth = (start: number, end: number | null) => {
    const now = end == null ? effectiveNowSec : end;
    return `${Math.max(0, ((now - start) / durationSec) * 100)}%`;
  };

  return (
    <div className="min-h-screen bg-background p-6">
      <div className="max-w-7xl mx-auto space-y-8">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-4">
            <Button variant="outline" size="sm" onClick={() => navigate('/')} className="flex items-center space-x-2">
              <ArrowLeft className="h-4 w-4" />
              <span>Înapoi</span>
            </Button>
            <h1 className="text-3xl font-bold">{editCourseId ? 'Editați Traseu' : 'Creați traseu'}</h1>
          </div>
          <Button onClick={handleSaveCourse} className="flex items-center space-x-2">
            <Save className="h-4 w-4" />
            <span>Save Course</span>
          </Button>
        </div>

        {/* Settings / Timer / Info */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <Card>
            <CardHeader><CardTitle>Setări traseu</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <div>
                <Label htmlFor="courseName">Course Name</Label>
                <Input id="courseName" value={courseName} onChange={e => setCourseName(e.target.value)} placeholder="Numele traseului" />
              </div>
              <div>
                <Label htmlFor="duration">Durata (minutes)</Label>
                <Input
                  id="duration"
                  type="number"
                  value={durationStr}
                  onChange={e => setDurationStr(e.target.value)}
                  onBlur={() => {
                    const num = parseInt(durationStr, 10);
                    const clamped = isNaN(num) || num < 1 ? durationMinUI : Math.min(num, 120);
                    setDurationMinUI(clamped);
                    setDurationStr(String(clamped));
                  }}
                  min="1"
                  max="120"
                />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center space-x-2">
                <Clock className="h-5 w-5" />
                <span>Timeline Control</span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                <div className="text-center">
                  <div className="text-2xl font-mono mb-2">{fmt(effectiveNowSec)}</div>
                  <div className="flex items-center justify-center space-x-2">
                    {recordingRobots.size > 0 && (
                      <Badge variant="destructive" className="animate-pulse">
                        Înregistrează: {Array.from(recordingRobots).join(', ')}
                      </Badge>
                    )}
                    {isPlaying && <Badge variant="secondary">Playing</Badge>}
                    {sampling && <Badge className="bg-green-100 text-green-700">REC</Badge>}
                  </div>
                </div>
              </div>
		<div className="flex space-x-2">
		  {/* jump left (press & hold) */}
		  <Button
		    size="sm"
		    variant="outline"
		    disabled={sampling}
		    className="flex-1 select-none"
		    onPointerDown={leftHold.start}
		    onPointerUp={leftHold.stop}
		    onPointerLeave={leftHold.stop}
		    onPointerCancel={leftHold.stop}
		    aria-label="Move left 1s"
		    title="Move left 1s (Shift+← = 5s)"
		  >
		    <ChevronLeft className="h-3 w-3 mr-1" />
		    -1s
		  </Button>

		  {/* jump right (press & hold) */}
		  <Button
		    size="sm"
		    variant="outline"
		    disabled={sampling}
		    className="flex-1 select-none"
		    onPointerDown={rightHold.start}
		    onPointerUp={rightHold.stop}
		    onPointerLeave={rightHold.stop}
		    onPointerCancel={rightHold.stop}
		    aria-label="Move right 1s"
		    title="Move right 1s (Shift+→ = 5s)"
		  >
		    +1s
		    <ChevronRight className="h-3 w-3 ml-1" />
		  </Button>
		</div>

            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Info Traseu</CardTitle></CardHeader>
            <CardContent>
              <div className="space-y-2">
                <div className="flex justify-between"><span className="text-muted-foreground">Durata totală:</span><span>{durationMin} minute</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Mișcări înregistrate:</span><span>{robotTimelines.reduce((a,t)=>a+t.moves.length,0)}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Înregistrează:</span><span>{recordingRobots.size ? `Robots ${Array.from(recordingRobots).join(', ')}` : 'None'}</span></div>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Timeline Editor */}
        <Card>
          <CardHeader><CardTitle>Timeline editor</CardTitle></CardHeader>
          <CardContent>
            {/* Scrubber (seconds precision), but labels/minutes */}
            <div className="mb-6">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-muted-foreground">Timeline</span>
                <span className="text-sm text-muted-foreground">{fmt(durationSec)}</span>
              </div>
              <div className="relative">
                <input
                  type="range"
                  min={0}
                  max={durationSec}
                  step={1}
                  value={currentTimeSec}
                  onChange={(e) => setCurrentTimeSec(Number(e.target.value))}
                  disabled={sampling}
                  className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer"
                />
                <div className="absolute top-0 left-0 h-2 bg-primary rounded-lg pointer-events-none" style={{ width: `${(currentTimeSec / durationSec) * 100 }%` }} />
              </div>
              <div className="flex justify-between text-xs text-muted-foreground mt-1">
                <span>0:00</span><span>{fmt(durationSec)}</span>
              </div>
            </div>

            {/* Robot Timelines */}
            <div className="space-y-4">
              {ROBOTS.map(robotId => {
                const timeline = robotTimelines.find(t => t.robotId === robotId);
                const isRecording = recordingRobots.has(robotId);
                const assigned = robotControllers[robotId]; // 1 | 2 | null

                return (
                  <div key={robotId} className="space-y-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center space-x-3">
                        <h3 className="font-medium min-w-[80px]">
			  {NICKNAMES[robotId] ?? `Robot ${robotId}`}
			</h3>
                        <div className="flex space-x-2">
                          {/* C1 / C2 selector (exclusive) */}
                          <Button
                            size="default"
                            variant={assigned === 1 ? "default" : "outline"}
                            onClick={() => assignController(robotId, 1)}
                            disabled={isRecording}
                            className="flex items-center space-x-1"
                          >
                            <Gamepad2 className="h-4 w-4" />
                            <span>C1</span>
                          </Button>
                          <Button
                            size="default"
                            variant={assigned === 2 ? "default" : "outline"}
                            onClick={() => assignController(robotId, 2)}
                            disabled={isRecording}
                            className="flex items-center space-x-1"
                          >
                            <Gamepad2 className="h-4 w-4" />
                            <span>C2</span>
                          </Button>

                          {/* Record / Stop for THIS robot */}
                          {!isRecording ? (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => startRecording(robotId)}
                              className="flex items-center space-x-1"
                            >
                              <Play className="h-3 w-3" />
                              <span>Record</span>
                            </Button>
                          ) : (
                            <Button
                              size="sm"
                              variant="destructive"
                              onClick={() => stopRecording(robotId)}
                              className="flex items-center space-x-1"
                            >
                              <Square className="h-3 w-3" />
                              <span>Stop</span>
                            </Button>
                          )}
                        </div>
                      </div>
                      <span className="text-sm text-muted-foreground">{timeline?.moves.length || 0} moves</span>
                    </div>

                    {/* Track with minute markers */}
                    <div className="relative h-12 bg-muted/30 rounded border">
                      {/* minute markers */}
                      <div className="absolute inset-0 flex">
                        {Array.from({ length: Math.max(1, durationMin) + 1 }, (_, i) => (
                          <div key={i} className="flex-1 border-r border-border/20 relative" style={{ minWidth: '20px' }}>
                            {i % 5 === 0 && (
                              <div className="absolute bottom-0 text-xs text-muted-foreground transform -translate-x-1/2">{i}</div>
                            )}
                          </div>
                        ))}
                      </div>

                      {/* Current time cursor (seconds-based but scaled to minutes width) */}
                      <div className="absolute top-0 bottom-0 w-0.5 bg-primary z-20" style={{ left: `${(effectiveNowSec / durationSec) * 100}%` }} />

                      {/* Recorded moves (seconds-based widths) */}
                      {timeline?.moves.map(move => (
                        <div
                          key={move.id}
                          className={`absolute top-1 bottom-1 rounded cursor-pointer transition-all z-10 ${
                            selectedMove === move.id
                              ? 'bg-primary border-2 border-primary'
                              : move.endT === null ? 'bg-red-500/70 animate-pulse' : 'bg-secondary/60 hover:bg-secondary/80'
                          }`}
                          style={{
                            left: getMoveLeft(move.startT),
                            width: getMoveWidth(move.startT, move.endT),
                            minWidth: '4px'
                          }}
                          onClick={() => setSelectedMove(move.id)}
                        >
                          <div className="h-full flex items-center justify-center text-xs text-white font-medium">
                            {move.endT === null ? 'REC' : `${fmt(move.startT)}-${fmt(move.endT)}`}
                          </div>
                          {selectedMove === move.id && move.endT !== null && (
                            <div className="absolute -top-8 left-1/2 transform -translate-x-1/2 flex space-x-1">
			      <Button
			        size="sm"
			        variant={playingMoveId === move.id ? "secondary" : "default"}
			        className="h-6 w-6 p-0"
			        disabled={loadingMoveId === move.id || sampling || recordingRobots.size > 0}
			        onClick={(e) => {
			          e.stopPropagation();
			          if (playingMoveId === move.id) stopMove(move);
			          else playMove(move);
			        }}
			        >
			        {playingMoveId === move.id ? <Square className="h-3 w-3" /> : <Play className="h-3 w-3" />}
			      </Button>
                              <Button
                                size="sm"
                                variant="destructive"
                                className="h-6 w-6 p-0"
                                onClick={(e) => { e.stopPropagation(); deleteMove(move.id); }}
                              >
                                <Trash2 className="h-3 w-3" />
                              </Button>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
