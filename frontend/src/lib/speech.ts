/**
 * Austauschbare Sprachverarbeitung.
 * STT: "browser" (Web Speech API) oder "server" (MediaRecorder -> /api/voice/transcribe -> OpenAI-kompatibler Dienst)
 * TTS: "browser" (speechSynthesis, männliche deutsche Stimme) oder "server" (/api/voice/speak)
 */
import { api, ApiError } from "./api";

export interface VoiceSettings {
  stt_enabled: boolean; stt_provider: "browser" | "server"; tts_enabled: boolean; tts_provider: "browser" | "server";
  tts_voice_name: string; tts_rate: number; auto_speak: boolean;
}

export class VoiceError extends Error {}

export function micSupportError(): string | null {
  if (!window.isSecureContext) return "Das Mikrofon funktioniert nur über HTTPS (oder localhost). Bitte MOSI PLAN über die HTTPS-Adresse öffnen.";
  if (!navigator.mediaDevices?.getUserMedia) return "Dieser Browser unterstützt keinen Mikrofonzugriff.";
  return null;
}

export async function openMic(): Promise<MediaStream> {
  const err = micSupportError();
  if (err) throw new VoiceError(err);
  try {
    return await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
  } catch (e) {
    const name = (e as DOMException).name;
    if (name === "NotAllowedError" || name === "SecurityError") throw new VoiceError("Der Mikrofonzugriff wurde verweigert. Bitte in den Browser-Einstellungen für diese Seite erlauben.");
    if (name === "NotFoundError") throw new VoiceError("Es wurde kein Mikrofon gefunden.");
    throw new VoiceError("Das Mikrofon konnte nicht gestartet werden.");
  }
}

/* -------------------------------------------------------------- STT */
export interface SttSession { stop: () => Promise<string>; cancel: () => void }

type SR = { lang: string; continuous: boolean; interimResults: boolean; start(): void; stop(): void; abort(): void;
  onresult: ((e: any) => void) | null; onerror: ((e: any) => void) | null; onend: (() => void) | null };

export const browserSttAvailable = () => !!((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition);

export function startBrowserStt(onInterim: (text: string) => void, onFatal: (msg: string) => void): SttSession {
  const Ctor = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
  if (!Ctor) throw new VoiceError("Dieser Browser bietet keine eingebaute Spracherkennung. In den Einstellungen kann ein serverseitiger Dienst gewählt werden.");
  const rec: SR = new Ctor();
  rec.lang = "de-DE";
  rec.continuous = true;
  rec.interimResults = true;
  let finalText = "";
  let interim = "";
  let ended = false;
  let resolveEnd: (() => void) | null = null;
  let stopping = false;
  rec.onresult = (e: any) => {
    interim = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const r = e.results[i];
      if (r.isFinal) finalText += r[0].transcript + " ";
      else interim += r[0].transcript;
    }
    onInterim((finalText + interim).trim());
  };
  rec.onerror = (e: any) => {
    const map: Record<string, string> = {
      "not-allowed": "Der Mikrofonzugriff wurde verweigert.",
      "service-not-allowed": "Die Spracherkennung des Browsers ist nicht erlaubt.",
      network: "Die Spracherkennung des Browsers ist nicht erreichbar (Internetverbindung nötig).",
      "audio-capture": "Kein Mikrofon verfügbar.",
      "language-not-supported": "Deutsch wird von der Spracherkennung dieses Browsers nicht unterstützt.",
    };
    if (e.error !== "no-speech" && e.error !== "aborted") onFatal(map[e.error] ?? `Spracherkennung fehlgeschlagen (${e.error}).`);
  };
  rec.onend = () => {
    // Manche Browser beenden nach Sprechpausen – automatisch fortsetzen, solange nicht gestoppt.
    if (!stopping) { try { rec.start(); return; } catch { /* beendet */ } }
    ended = true;
    resolveEnd?.();
  };
  rec.start();
  return {
    stop: () => new Promise<string>((resolve) => {
      stopping = true;
      const finish = () => resolve((finalText + interim).trim());
      if (ended) return finish();
      resolveEnd = finish;
      rec.stop();
      setTimeout(finish, 1800);
    }),
    cancel: () => { stopping = true; try { rec.abort(); } catch { /* */ } },
  };
}

export function startServerStt(stream: MediaStream): SttSession {
  const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"].find((m) => (window as any).MediaRecorder?.isTypeSupported?.(m));
  if (!(window as any).MediaRecorder) throw new VoiceError("Dieser Browser kann keine Audioaufnahmen erstellen.");
  const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
  const chunks: Blob[] = [];
  rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  rec.start(250);
  const started = Date.now();
  return {
    stop: () => new Promise<string>((resolve, reject) => {
      rec.onstop = async () => {
        if (Date.now() - started < 500) return resolve("");
        const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
        const fd = new FormData();
        fd.append("file", blob, "aufnahme.webm");
        try {
          const r = await api.post<{ text: string }>("/api/voice/transcribe", fd);
          resolve(r.text);
        } catch (e) {
          reject(e instanceof ApiError ? new VoiceError(e.message) : e);
        }
      };
      rec.stop();
    }),
    cancel: () => { rec.onstop = null; try { rec.stop(); } catch { /* */ } },
  };
}

/* -------------------------------------------------------------- TTS */
const MALE_HINTS = ["conrad", "killian", "florian", "markus", "yannick", "stefan", "hans", "bernd", "jonas", "ralf", "christoph", "kasper", "male", "männlich", "mann"];
const FEMALE_HINTS = ["katja", "anna", "petra", "helena", "hedda", "marlene", "vicki", "amala", "louisa", "seraphina", "tanja", "female", "weiblich", "frau"];

export function germanVoices(): SpeechSynthesisVoice[] {
  if (!("speechSynthesis" in window)) return [];
  return speechSynthesis.getVoices().filter((v) => v.lang.toLowerCase().startsWith("de"));
}

export function isLikelyMale(v: SpeechSynthesisVoice) {
  const n = v.name.toLowerCase();
  return MALE_HINTS.some((h) => n.includes(h)) && !FEMALE_HINTS.some((h) => n.includes(h));
}

export function pickVoice(preferred: string): SpeechSynthesisVoice | null {
  const voices = germanVoices();
  if (!voices.length) return null;
  const exact = voices.find((v) => v.name === preferred);
  if (exact) return exact;
  const male = voices.filter(isLikelyMale);
  const natural = (l: SpeechSynthesisVoice[]) => l.find((v) => /natural|online|neural|premium|enhanced/i.test(v.name)) ?? l[0];
  return natural(male) ?? natural(voices) ?? null;
}

/** Entfernt Markdown für die Sprachausgabe. */
export const speakable = (t: string) =>
  t.replace(/```[\s\S]*?```/g, "").replace(/[*_`#>]/g, "").replace(/\[(.*?)\]\(.*?\)/g, "$1").replace(/^\s*[-•]\s+/gm, "").replace(/\n{2,}/g, ". ").trim();

let currentAudio: HTMLAudioElement | null = null;

export async function speak(text: string, s: VoiceSettings): Promise<void> {
  stopSpeaking();
  const clean = speakable(text);
  if (!clean) return;
  if (s.tts_provider === "server") {
    const res = await api.raw("POST", "/api/voice/speak", { text: clean.slice(0, 4000) });
    const url = URL.createObjectURL(await res.blob());
    await new Promise<void>((resolve, reject) => {
      const a = new Audio(url);
      currentAudio = a;
      a.onended = () => { URL.revokeObjectURL(url); resolve(); };
      a.onerror = () => reject(new VoiceError("Die Sprachausgabe konnte nicht abgespielt werden."));
      a.play().catch(() => reject(new VoiceError("Die Wiedergabe wurde vom Browser blockiert.")));
    });
    return;
  }
  if (!("speechSynthesis" in window)) throw new VoiceError("Dieser Browser unterstützt keine Sprachausgabe.");
  await new Promise<void>((resolve) => {
    // Lange Texte in Sätze teilen (Chrome bricht lange Äußerungen sonst ab)
    const parts = clean.match(/[^.!?]+[.!?]*/g) ?? [clean];
    const voice = pickVoice(s.tts_voice_name);
    parts.forEach((p, i) => {
      const u = new SpeechSynthesisUtterance(p.trim());
      u.lang = "de-DE";
      if (voice) u.voice = voice;
      u.rate = s.tts_rate || 1;
      u.pitch = 0.95;
      if (i === parts.length - 1) { u.onend = () => resolve(); u.onerror = () => resolve(); }
      speechSynthesis.speak(u);
    });
  });
}

export function stopSpeaking() {
  if ("speechSynthesis" in window) speechSynthesis.cancel();
  if (currentAudio) { currentAudio.pause(); currentAudio = null; }
}
