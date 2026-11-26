/**
 * Sprachassistent: Aufnahme -> Transkription -> Agent -> Ergebnis -> Sprachausgabe.
 * Zustände: idle, recording, transcribing, thinking, acting, speaking, done, error.
 */
import { useQueryClient } from "@tanstack/react-query";
import { Check, Loader2, MessageSquare, Mic, RotateCcw, Square, Volume2, VolumeX, X } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { ensureConversation, streamChat } from "@/lib/chat";
import { browserSttAvailable, openMic, speak, startBrowserStt, startServerStt, stopSpeaking, VoiceError, type SttSession, type VoiceSettings } from "@/lib/speech";
import type { PendingAction } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useSettings, useInvalidate } from "@/hooks/queries";
import { Markdown } from "./markdown";
import { PendingActionCard } from "./pending-action";
import { Button } from "./ui";

export type VoiceState = "idle" | "recording" | "transcribing" | "thinking" | "acting" | "speaking" | "done" | "error";

interface VoiceCtx {
  state: VoiceState;
  open: boolean;
  transcript: string;
  reply: string;
  actionLabel: string;
  pending: PendingAction[];
  error: string | null;
  conversationId: number | null;
  level: React.MutableRefObject<number[]>;
  muted: boolean;
  toggle: () => void;
  start: () => void;
  stop: () => void;
  close: () => void;
  setMuted: (m: boolean) => void;
}
const Ctx = createContext<VoiceCtx>(null as unknown as VoiceCtx);
export const useVoice = () => useContext(Ctx);

const DEFAULTS: VoiceSettings = { stt_enabled: true, stt_provider: "browser", tts_enabled: true, tts_provider: "browser", tts_voice_name: "", tts_rate: 1, auto_speak: true };

export function VoiceProvider({ children }: { children: ReactNode }) {
  const settings = useSettings();
  const vs: VoiceSettings = { ...DEFAULTS, ...(settings.data?.voice ?? {}) } as VoiceSettings;
  const [state, setState] = useState<VoiceState>("idle");
  const [open, setOpen] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [reply, setReply] = useState("");
  const [actionLabel, setActionLabel] = useState("");
  const [pending, setPending] = useState<PendingAction[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [muted, setMuted] = useState(false);
  const level = useRef<number[]>(new Array(48).fill(0));
  const session = useRef<SttSession | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const audioCtx = useRef<AudioContext | null>(null);
  const raf = useRef<number>(0);
  const runId = useRef(0);
  const qc = useQueryClient();
  const invalidate = useInvalidate();

  const releaseMic = useCallback(() => {
    cancelAnimationFrame(raf.current);
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    audioCtx.current?.close().catch(() => {});
    audioCtx.current = null;
    level.current = level.current.map(() => 0);
  }, []);

  const fail = useCallback((msg: string) => {
    session.current?.cancel();
    session.current = null;
    releaseMic();
    setError(msg);
    setState("error");
  }, [releaseMic]);

  const start = useCallback(async () => {
    if (!vs.stt_enabled) { setOpen(true); fail("Die Spracheingabe ist in den Einstellungen deaktiviert."); return; }
    stopSpeaking();
    const id = ++runId.current;
    setOpen(true);
    setError(null); setTranscript(""); setReply(""); setPending([]); setActionLabel("");
    try {
      if (vs.stt_provider === "browser" && !browserSttAvailable())
        throw new VoiceError("Dieser Browser bietet keine eingebaute Spracherkennung (z. B. Firefox). Nutze Chrome, Edge oder Safari – oder richte unter Einstellungen → Sprache einen Server-Dienst ein.");
      const s = await openMic();
      if (id !== runId.current) { s.getTracks().forEach((t) => t.stop()); return; }
      stream.current = s;
      // Wellenform
      const ctx = new AudioContext();
      audioCtx.current = ctx;
      const src = ctx.createMediaStreamSource(s);
      const an = ctx.createAnalyser();
      an.fftSize = 512;
      src.connect(an);
      const buf = new Uint8Array(an.fftSize);
      const tick = () => {
        an.getByteTimeDomainData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; sum += v * v; }
        const rms = Math.min(1, Math.sqrt(sum / buf.length) * 3.2);
        level.current = [...level.current.slice(1), rms];
        raf.current = requestAnimationFrame(tick);
      };
      tick();
      session.current = vs.stt_provider === "server" ? startServerStt(s) : startBrowserStt(setTranscript, fail);
      setState("recording");
    } catch (e) {
      fail(e instanceof Error ? e.message : String(e));
    }
  }, [vs.stt_enabled, vs.stt_provider, fail]);

  const stop = useCallback(async () => {
    const sess = session.current;
    if (!sess) return;
    const id = runId.current;
    session.current = null;
    setState("transcribing");
    let text = "";
    try {
      text = (await sess.stop()).trim();
    } catch (e) {
      return fail(e instanceof Error ? e.message : String(e));
    } finally {
      releaseMic();
    }
    if (id !== runId.current) return;
    if (!text) return fail("Es wurde keine Sprache erkannt. Bitte noch einmal deutlich sprechen.");
    setTranscript(text);
    setState("thinking");
    try {
      const cid = await ensureConversation();
      setConversationId(cid);
      let acc = "";
      const done = await streamChat(cid, text, true, (ev) => {
        if (id !== runId.current) return;
        if (ev.type === "tool") { setState("acting"); setActionLabel(ev.label); }
        if (ev.type === "status" && ev.state === "thinking") setState((s) => (s === "acting" ? s : "thinking"));
        if (ev.type === "delta") { acc += ev.text; setReply(acc); }
      });
      if (id !== runId.current) return;
      qc.invalidateQueries({ queryKey: ["conversation", cid] });
      qc.invalidateQueries({ queryKey: ["conversations"] });
      invalidate();
      if (done.error) return fail(done.error);
      setReply(done.content);
      setPending(done.pending_actions);
      if (vs.tts_enabled && vs.auto_speak && !muted) {
        setState("speaking");
        try { await speak(done.content, vs); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
      }
      if (id === runId.current) setState("done");
    } catch (e) {
      fail(e instanceof Error ? e.message : String(e));
    }
  }, [fail, releaseMic, qc, invalidate, vs, muted]);

  const close = useCallback(() => {
    runId.current++;
    session.current?.cancel();
    session.current = null;
    releaseMic();
    stopSpeaking();
    setOpen(false);
    setState("idle");
  }, [releaseMic]);

  const toggle = useCallback(() => {
    if (state === "recording") stop();
    else if (state === "speaking") { stopSpeaking(); setState("done"); }
    else if (["idle", "done", "error"].includes(state)) start();
  }, [state, start, stop]);

  useEffect(() => () => { session.current?.cancel(); releaseMic(); }, [releaseMic]);

  return (
    <Ctx.Provider value={{ state, open, transcript, reply, actionLabel, pending, error, conversationId, level, muted, toggle, start, stop, close, setMuted }}>
      {children}
      <VoiceSheet />
    </Ctx.Provider>
  );
}

/* --------------------------------------------------------------------- Wellenform */
function Waveform({ active }: { active: boolean }) {
  const { level } = useVoice();
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    let id = 0;
    const draw = () => {
      const c = ref.current;
      if (!c) return;
      const dpr = window.devicePixelRatio || 1;
      const w = c.clientWidth, h = c.clientHeight;
      if (c.width !== w * dpr) { c.width = w * dpr; c.height = h * dpr; }
      const g = c.getContext("2d")!;
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.clearRect(0, 0, w, h);
      const bars = level.current;
      const gap = 3, bw = (w - gap * (bars.length - 1)) / bars.length;
      bars.forEach((v, i) => {
        const bh = Math.max(2, v * h * 0.95);
        g.fillStyle = active ? `rgba(91,141,239,${0.35 + v * 0.65})` : "rgba(107,116,132,0.5)";
        g.beginPath();
        g.roundRect(i * (bw + gap), (h - bh) / 2, bw, bh, bw / 2);
        g.fill();
      });
      id = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(id);
  }, [active, level]);
  return <canvas ref={ref} className="h-12 w-full" aria-hidden />;
}

/* --------------------------------------------------------------------- Statusfolge */
const STEPS: { key: VoiceState[]; label: string }[] = [
  { key: ["recording"], label: "Aufnahme" },
  { key: ["transcribing"], label: "Verarbeitung" },
  { key: ["thinking"], label: "Denken" },
  { key: ["acting"], label: "Aktion" },
  { key: ["speaking"], label: "Antwort" },
  { key: ["done"], label: "Fertig" },
];
const ORDER: VoiceState[] = ["recording", "transcribing", "thinking", "acting", "speaking", "done"];

function StatusSteps({ state }: { state: VoiceState }) {
  const cur = ORDER.indexOf(state);
  return (
    <ol className="flex items-center gap-1.5 text-xs" aria-label="Status">
      {STEPS.map((s, i) => {
        const active = s.key.includes(state);
        const past = cur > i || state === "done";
        return (
          <li key={s.label} className={cn("flex items-center gap-1.5", active ? "text-ink" : past ? "text-ink-2" : "text-ink-3/60")}>
            {i > 0 && <span className={cn("h-px w-3", past || active ? "bg-ink-3" : "bg-line-strong")} />}
            {active && state !== "done" ? <Loader2 className="h-3 w-3 animate-spin text-accent" /> : past ? <Check className="h-3 w-3" /> : null}
            <span className={active ? "font-medium" : undefined}>{s.label}</span>
          </li>
        );
      })}
    </ol>
  );
}

const HEADLINE: Record<VoiceState, string> = {
  idle: "", recording: "Aufnahme läuft", transcribing: "Sprache wird erkannt", thinking: "Anfrage wird verarbeitet",
  acting: "Aktion wird ausgeführt", speaking: "Antwort wird vorgelesen", done: "Abgeschlossen", error: "Fehler",
};

function VoiceSheet() {
  const v = useVoice();
  const nav = useNavigate();
  if (!v.open) return null;
  const busy = ["transcribing", "thinking", "acting"].includes(v.state);
  return (
    <div className="fixed inset-0 z-[55] flex items-end md:items-center justify-center p-0 md:p-6" role="dialog" aria-modal="true" aria-label="Sprachassistent">
      <div className="absolute inset-0 bg-black/55 backdrop-blur-[2px] animate-fade-in" onClick={v.state === "recording" ? undefined : v.close} />
      <div className="relative w-full md:max-w-[620px] max-h-[86vh] overflow-y-auto rounded-t-lg md:rounded-lg bg-surface shadow-pop animate-pop-in safe-bottom">
        <div className="flex items-center justify-between px-5 pt-4">
          <StatusSteps state={v.state} />
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="icon-sm" aria-label={v.muted ? "Sprachausgabe einschalten" : "Sprachausgabe stummschalten"} onClick={() => { v.setMuted(!v.muted); if (!v.muted) stopSpeaking(); }}>
              {v.muted ? <VolumeX className="h-4 w-4" /> : <Volume2 className="h-4 w-4" />}
            </Button>
            <Button variant="ghost" size="icon-sm" aria-label="Schließen" onClick={v.close}><X className="h-4 w-4" /></Button>
          </div>
        </div>

        <div className="px-5 pt-5 pb-5">
          <div className="text-lg font-semibold text-ink">{HEADLINE[v.state]}</div>
          {v.state === "acting" && v.actionLabel && <div className="text-sm text-accent-ink mt-0.5">{v.actionLabel}</div>}

          {(v.state === "recording" || v.state === "transcribing") && (
            <div className="mt-4"><Waveform active={v.state === "recording"} /></div>
          )}

          {v.transcript && (
            <div className="mt-4">
              <div className="text-xs text-ink-3 mb-1">Erkannt</div>
              <p className={cn("text-md text-ink leading-relaxed", v.state === "recording" && "text-ink-2")}>„{v.transcript}“</p>
            </div>
          )}

          {v.reply && (
            <div className="mt-5 border-t border-line pt-4 text-base text-ink-2">
              <div className="text-xs text-ink-3 mb-1.5">Antwort</div>
              <Markdown text={v.reply} />
            </div>
          )}
          {v.pending.map((a) => <PendingActionCard key={a.id} action={a} />)}

          {v.error && <p role="alert" className="mt-4 text-base text-danger">{v.error}</p>}

          <div className="mt-6 flex items-center justify-between gap-3">
            {v.conversationId && !busy && v.state !== "recording" ? (
              <Button variant="ghost" size="sm" onClick={() => { v.close(); nav(`/assistent?c=${v.conversationId}`); }}>
                <MessageSquare className="h-4 w-4" /> Im Chat öffnen
              </Button>
            ) : <span />}
            {v.state === "recording" && (
              <Button variant="primary" size="lg" onClick={v.stop}><Square className="h-4 w-4 fill-current" /> Aufnahme beenden</Button>
            )}
            {v.state === "speaking" && (
              <Button variant="secondary" onClick={() => { stopSpeaking(); }}><VolumeX className="h-4 w-4" /> Vorlesen stoppen</Button>
            )}
            {(v.state === "done" || v.state === "error") && (
              <Button variant="primary" onClick={v.start}>{v.state === "error" ? <RotateCcw className="h-4 w-4" /> : <Mic className="h-4 w-4" />}{v.state === "error" ? "Erneut versuchen" : "Neue Spracheingabe"}</Button>
            )}
            {busy && <span className="text-sm text-ink-3">Wird bearbeitet</span>}
          </div>
        </div>
      </div>
    </div>
  );
}

/** Mikrofonbutton – überall gleich, mit aktivem Aufnahmestatus. */
export function MicButton({ className, size = "md", label = true }: { className?: string; size?: "md" | "lg"; label?: boolean }) {
  const v = useVoice();
  const rec = v.state === "recording";
  return (
    <button
      onClick={v.toggle}
      aria-label={rec ? "Aufnahme beenden" : "Sprachaufnahme starten"}
      aria-pressed={rec}
      className={cn(
        "relative inline-flex items-center justify-center gap-2 rounded-full font-medium transition-colors",
        size === "lg" ? "h-14 w-14" : label ? "h-9 px-3.5" : "h-9 w-9",
        rec ? "bg-danger text-white" : size === "lg" ? "bg-accent text-white hover:bg-accent/90" : "bg-raised text-ink border border-line-strong hover:border-ink-3/60",
        className,
      )}
    >
      {rec && <span className="absolute inset-0 rounded-full ring-4 ring-danger/30 animate-pulse" aria-hidden />}
      {rec ? <Square className={size === "lg" ? "h-5 w-5 fill-current" : "h-3.5 w-3.5 fill-current"} /> : <Mic className={size === "lg" ? "h-6 w-6" : "h-4 w-4 text-accent"} />}
      {label && size !== "lg" && <span className="text-sm">{rec ? "Aufnahme beenden" : "Spracheingabe"}</span>}
    </button>
  );
}
