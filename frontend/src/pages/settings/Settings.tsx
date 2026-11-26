import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, ExternalLink, RefreshCw, XCircle } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useParams, useSearchParams } from "react-router-dom";
import { useToast } from "@/components/toast";
import { Badge, Button, ErrorNote, Field, Input, Panel, Select, Skeleton, Switch, Textarea } from "@/components/ui";
import { useAuth } from "@/hooks/auth";
import { useSaveSettings, useSettings } from "@/hooks/queries";
import { api } from "@/lib/api";
import { ago, WEEKDAYS } from "@/lib/format";
import { germanVoices, isLikelyMale, speak, type VoiceSettings } from "@/lib/speech";
import type { User } from "@/lib/types";
import { cn } from "@/lib/utils";

const SECTIONS = [
  ["profil", "Profil"], ["ki", "KI"], ["sprache", "Sprache"], ["kalender", "Kalender"], ["planung", "Planungsregeln"],
  ["benachrichtigungen", "Benachrichtigungen"], ["sicherheit", "Sicherheit"], ["system", "System"],
] as const;

function Row({ title, desc, children }: { title: string; desc?: string; children: ReactNode }) {
  return (
    <div className="grid gap-3 md:grid-cols-[240px_minmax(0,1fr)] py-5 border-b border-line last:border-0">
      <div><h3 className="text-base font-medium text-ink">{title}</h3>{desc && <p className="text-sm text-ink-3 mt-0.5">{desc}</p>}</div>
      <div className="space-y-4 max-w-xl">{children}</div>
    </div>
  );
}

/** Lokaler Formularzustand für einen Einstellungsbereich */
function useSection(name: string) {
  const s = useSettings();
  const save = useSaveSettings(name);
  const [f, setF] = useState<Record<string, any>>({});
  useEffect(() => { if (s.data?.[name]) setF(s.data[name]); }, [s.data, name]);
  const set = (k: string, v: unknown) => setF((x) => ({ ...x, [k]: v }));
  return { f, set, save, loading: s.isLoading };
}

function Profile() {
  const { user, setUser } = useAuth();
  const toast = useToast();
  const [f, setF] = useState({ display_name: user?.display_name ?? "", timezone: user?.timezone ?? "Europe/Berlin", language: user?.language ?? "de" });
  const dash = useSection("dashboard");
  const save = useMutation({ mutationFn: () => api.patch<User>("/api/auth/profile", f), onSuccess: (u) => { setUser(u); toast.ok("Profil gespeichert"); }, onError: toast.error });
  const upload = async (file: File) => {
    const fd = new FormData(); fd.append("file", file);
    try { setUser(await api.post<User>("/api/auth/avatar", fd)); toast.ok("Profilbild aktualisiert"); } catch (e) { toast.error(e); }
  };
  const zones = (Intl as any).supportedValuesOf?.("timeZone") ?? ["Europe/Berlin"];
  return (
    <>
      <Row title="Profil" desc="Name und Zeitzone für Begrüßung, Kalender und Planung.">
        <Field label="Anzeigename"><Input value={f.display_name} onChange={(e) => setF({ ...f, display_name: e.target.value })} /></Field>
        <Field label="Zeitzone"><Select value={f.timezone} onChange={(e) => setF({ ...f, timezone: e.target.value })}>{zones.map((z: string) => <option key={z}>{z}</option>)}</Select></Field>
        <Field label="Sprache" hint="Weitere Sprachen sind vorbereitet."><Select value={f.language} onChange={(e) => setF({ ...f, language: e.target.value })}><option value="de">Deutsch</option></Select></Field>
        <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>Profil speichern</Button>
      </Row>
      <Row title="Begrüßung" desc="Wie dich MOSI auf der Übersicht anspricht.">
        <Field label="Name in der Begrüßung"><Input value={dash.f.greeting_name ?? ""} placeholder={user?.display_name} onChange={(e) => dash.set("greeting_name", e.target.value)} /></Field>
        <Button loading={dash.save.isPending} onClick={() => dash.save.mutate({ greeting_name: dash.f.greeting_name })}>Speichern</Button>
      </Row>
      <Row title="Profilbild" desc="PNG, JPEG oder WebP, höchstens 2 MB.">
        <div className="flex items-center gap-4">
          <div className="h-14 w-14 rounded-full overflow-hidden bg-raised border border-line-strong">{user?.has_avatar && <img src={`/api/auth/avatar?${Date.now()}`} alt="" className="h-full w-full object-cover" />}</div>
          <label className="inline-flex"><input type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} /><span className="cursor-pointer inline-flex h-9 items-center rounded border border-line-strong bg-raised px-3.5 text-base font-medium">Bild wählen</span></label>
          {user?.has_avatar && <Button variant="ghost" onClick={async () => setUser(await api.del<User>("/api/auth/avatar"))}>Entfernen</Button>}
        </div>
      </Row>
    </>
  );
}

const PRESETS = [
  { name: "Google Gemini (kostenloses Kontingent)", url: "https://generativelanguage.googleapis.com/v1beta/openai" },
  { name: "Groq (kostenloses Kontingent)", url: "https://api.groq.com/openai/v1" },
  { name: "OpenRouter", url: "https://openrouter.ai/api/v1" },
  { name: "Lokal: Ollama auf diesem Server", url: "http://ollama:11434/v1" },
];

function AI() {
  const { f, set, save } = useSection("ai");
  const [key, setKey] = useState("");
  const status = useQuery({ queryKey: ["assistant-status"], queryFn: () => api.get<any>("/api/assistant/status") });
  const test = useMutation({ mutationFn: () => api.post<{ backend: string; answer: string }>("/api/settings/ai/test") });
  const qc = useQueryClient();
  const auto = useMutation({
    mutationFn: () => api.post<{ ok: boolean; model?: string; fallbacks: string[]; tested: { model: string; ok: boolean; status: number }[] }>("/api/settings/ai/autoselect"),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["settings"] }); qc.invalidateQueries({ queryKey: ["assistant-status"] }); },
  });
  const models = useQuery({ queryKey: ["ai-models"], queryFn: () => api.get<{ models: string[] }>("/api/settings/ai/models"), enabled: false, retry: false });
  const payload = () => ({ mode: f.mode, fallback_direct: f.fallback_direct, direct_base_url: f.direct_base_url, direct_model: f.direct_model,
    fallback_models: f.fallback_models ?? [], memory_enabled: f.memory_enabled, ...(key ? { direct_api_key: key } : {}) });
  return (
    <>
      <Row title="Status">
        <div className="flex flex-wrap gap-2">
          {status.data?.mode === "hermes" || status.data?.hermes_ok ? (
            <Badge tone={status.data?.hermes_ok ? "ok" : "danger"}>{status.data?.hermes_ok ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}Hermes: {status.data?.hermes_message ?? "…"}</Badge>
          ) : <Badge>Hermes: nicht verwendet</Badge>}
          <Badge tone={status.data?.direct_configured ? "ok" : "neutral"}>Direkter Anbieter: {status.data?.direct_configured ? "konfiguriert" : "nicht konfiguriert"}</Badge>
        </div>
        {status.data && !status.data.available && <p className="text-sm text-warn">{status.data.reason}</p>}
        <div className="flex items-center gap-3"><Button loading={test.isPending} onClick={() => test.mutate()}>Verbindung testen</Button>{test.data && <span className="text-sm text-ok">Antwort über {test.data.backend}: „{test.data.answer}“</span>}</div>
        <ErrorNote error={test.error} />
      </Row>
      <Row title="KI-Modus" desc="Hermes Agent ist die Agentenebene. Das Sprachmodell von Hermes wird in data/hermes/config.yaml bzw. per install.sh festgelegt.">
        <Field label="Modus"><Select value={f.mode} onChange={(e) => set("mode", e.target.value)}><option value="hermes">Hermes Agent</option><option value="direct">Direkter Anbieter (ohne Hermes)</option><option value="off">KI deaktiviert</option></Select></Field>
        <Switch checked={!!f.fallback_direct} onChange={(v) => set("fallback_direct", v)} label="Fallback nutzen" description="Wenn Hermes nicht erreichbar ist, den direkten Anbieter verwenden." />
      </Row>
      <Row title="KI-Anbieter" desc="Beliebige OpenAI-kompatible Schnittstelle. Vorlage wählen, API-Schlüssel eintragen, speichern – dann „Passendes Modell automatisch finden“.">
        <Field label="Vorlage">
          <Select value={PRESETS.find((p) => p.url === f.direct_base_url)?.url ?? ""} onChange={(e) => e.target.value && set("direct_base_url", e.target.value)}>
            <option value="">Eigene Adresse</option>
            {PRESETS.map((p) => <option key={p.url} value={p.url}>{p.name}</option>)}
          </Select>
        </Field>
        <Field label="Basis-URL"><Input value={f.direct_base_url ?? ""} onChange={(e) => set("direct_base_url", e.target.value)} /></Field>
        <Field label="API-Schlüssel" hint={f.has_direct_api_key ? "Ein Schlüssel ist hinterlegt (verschlüsselt). Leer lassen, um ihn zu behalten." : "Wird verschlüsselt gespeichert und nie im Browser angezeigt."}><Input type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} /></Field>
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" loading={save.isPending} onClick={() => save.mutate(payload(), { onSuccess: () => setKey("") })}>Speichern</Button>
          <Button loading={auto.isPending} onClick={async () => { await save.mutateAsync(payload()); setKey(""); auto.mutate(); }}>Passendes Modell automatisch finden</Button>
        </div>
        {auto.data && (auto.data.ok
          ? <p className="text-sm text-ok">Eingestellt: {auto.data.model}{auto.data.fallbacks.length ? ` (Ausweichmodelle: ${auto.data.fallbacks.join(", ")})` : ""}. {auto.data.tested.length} Modell(e) getestet.</p>
          : <p className="text-sm text-danger">Keines von {auto.data.tested.length} getesteten Modellen hat geantwortet ({auto.data.tested.map((t) => `${t.model}: ${t.status || "keine Verbindung"}`).join(", ")}). Meist ist das kostenlose Kontingent gerade überlastet – später erneut versuchen oder einen anderen Anbieter wählen.</p>)}
        <ErrorNote error={auto.error} />
        <Field label="Modell" hint="Wird bei der automatischen Suche ausgefüllt.">
          <div className="flex gap-2">
            {models.data?.models.length ? (
              <Select value={f.direct_model ?? ""} onChange={(e) => set("direct_model", e.target.value)}>
                {!models.data.models.includes(f.direct_model) && <option value={f.direct_model}>{f.direct_model || "– bitte wählen –"}</option>}
                {models.data.models.map((m: string) => <option key={m} value={m}>{m}</option>)}
              </Select>
            ) : <Input value={f.direct_model ?? ""} onChange={(e) => set("direct_model", e.target.value)} placeholder="Modellname" />}
            <Button variant="secondary" loading={models.isFetching} onClick={() => models.refetch()}>Liste laden</Button>
          </div>
        </Field>
        <ErrorNote error={models.error} />
        <Field label="Ausweichmodelle" hint="Durch Komma getrennt. Werden automatisch genutzt, wenn das Hauptmodell überlastet ist oder das Limit erreicht hat.">
          <Input value={(f.fallback_models ?? []).join(", ")} onChange={(e) => set("fallback_models", e.target.value.split(",").map((x: string) => x.trim()).filter(Boolean))} />
        </Field>
      </Row>
      <Row title="Gedächtnis">
        <Switch checked={!!f.memory_enabled} onChange={(v) => set("memory_enabled", v)} label="Gedächtnis verwenden" description="MOSI darf gespeicherte Einträge lesen und auf Wunsch neue speichern." />
      </Row>
      <div className="pt-4"><Button variant="primary" loading={save.isPending} onClick={() => save.mutate(payload(), { onSuccess: () => setKey("") })}>Speichern</Button></div>
    </>
  );
}

function Voice() {
  const { f, set, save } = useSection("voice");
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [sttKey, setSttKey] = useState(""), [ttsKey, setTtsKey] = useState("");
  const toast = useToast();
  useEffect(() => { const load = () => setVoices(germanVoices()); load(); if ("speechSynthesis" in window) speechSynthesis.onvoiceschanged = load; }, []);
  return (
    <>
      <Row title="Spracheingabe" desc="Browser: kostenlos, nutzt die Spracherkennung von Chrome/Edge/Safari (Audio wird dabei vom Browser-Hersteller verarbeitet). Server: eigener oder externer OpenAI-kompatibler Whisper-Dienst.">
        <Switch checked={!!f.stt_enabled} onChange={(v) => set("stt_enabled", v)} label="Spracheingabe aktivieren" />
        <Field label="Erkennung"><Select value={f.stt_provider} onChange={(e) => set("stt_provider", e.target.value)}><option value="browser">Browser (Web Speech API)</option><option value="server">Server (OpenAI-kompatibel)</option></Select></Field>
        {f.stt_provider === "server" && <>
          <Field label="Basis-URL" hint="Endpunkt …/audio/transcriptions wird angehängt."><Input value={f.stt_base_url ?? ""} onChange={(e) => set("stt_base_url", e.target.value)} /></Field>
          <Field label="Modell"><Input value={f.stt_model ?? ""} onChange={(e) => set("stt_model", e.target.value)} /></Field>
          <Field label="API-Schlüssel" hint={f.has_stt_api_key ? "Hinterlegt." : undefined}><Input type="password" value={sttKey} onChange={(e) => setSttKey(e.target.value)} /></Field>
        </>}
      </Row>
      <Row title="Sprachausgabe" desc="Bevorzugt eine ruhige, männliche deutsche Stimme.">
        <Switch checked={!!f.tts_enabled} onChange={(v) => set("tts_enabled", v)} label="Sprachausgabe aktivieren" />
        <Switch checked={!!f.auto_speak} onChange={(v) => set("auto_speak", v)} label="Antworten nach Spracheingabe automatisch vorlesen" />
        <Field label="Ausgabe"><Select value={f.tts_provider} onChange={(e) => set("tts_provider", e.target.value)}><option value="browser">Browser-Stimme</option><option value="server">Server (OpenAI-kompatibel)</option></Select></Field>
        {f.tts_provider === "browser" ? (
          <Field label="Stimme" hint={voices.length ? "Männliche Stimmen sind markiert. Auf Windows/Edge klingen die „Online (Natural)“-Stimmen am natürlichsten." : "Dieser Browser bietet keine deutschen Stimmen an."}>
            <Select value={f.tts_voice_name ?? ""} onChange={(e) => set("tts_voice_name", e.target.value)}>
              <option value="">Automatisch (männlich, deutsch)</option>
              {voices.map((v) => <option key={v.name} value={v.name}>{v.name}{isLikelyMale(v) ? " (männlich)" : ""}</option>)}
            </Select>
          </Field>
        ) : <>
          <Field label="Basis-URL" hint="Endpunkt …/audio/speech wird angehängt."><Input value={f.tts_base_url ?? ""} onChange={(e) => set("tts_base_url", e.target.value)} /></Field>
          <div className="grid grid-cols-2 gap-3"><Field label="Modell"><Input value={f.tts_model ?? ""} onChange={(e) => set("tts_model", e.target.value)} /></Field><Field label="Stimme"><Input value={f.tts_voice ?? ""} onChange={(e) => set("tts_voice", e.target.value)} /></Field></div>
          <Field label="API-Schlüssel" hint={f.has_tts_api_key ? "Hinterlegt." : undefined}><Input type="password" value={ttsKey} onChange={(e) => setTtsKey(e.target.value)} /></Field>
        </>}
        <Field label={`Sprechgeschwindigkeit: ${Number(f.tts_rate ?? 1).toFixed(2)}`}><input type="range" min={0.5} max={2} step={0.05} value={f.tts_rate ?? 1} onChange={(e) => set("tts_rate", Number(e.target.value))} className="w-full accent-[rgb(var(--accent))]" /></Field>
        <Button onClick={() => speak("Hallo, ich bin MOSI. Ich helfe dir, deine Woche zu planen.", f as VoiceSettings).catch(toast.error)}>Stimme testen</Button>
      </Row>
      <div className="pt-4"><Button variant="primary" loading={save.isPending} onClick={() => { const { has_stt_api_key, has_tts_api_key, ...rest } = f; void has_stt_api_key; void has_tts_api_key; save.mutate({ ...rest, ...(sttKey ? { stt_api_key: sttKey } : {}), ...(ttsKey ? { tts_api_key: ttsKey } : {}) }); }}>Speichern</Button></div>
    </>
  );
}

function CalendarSettings() {
  const qc = useQueryClient();
  const toast = useToast();
  const [params] = useSearchParams();
  const { f, set, save } = useSection("calendar");
  const g = useQuery({ queryKey: ["google-status"], queryFn: () => api.get<any>("/api/google/status") });
  const [cred, setCred] = useState({ client_id: "", client_secret: "" });
  useEffect(() => { if (g.data) setCred((c) => ({ ...c, client_id: g.data.client_id })); }, [g.data]);
  useEffect(() => { const s = params.get("google"); if (s === "verbunden") toast.ok("Google Calendar verbunden"); if (s === "fehler") toast.error(params.get("grund") ?? "Verbindung fehlgeschlagen"); }, []); // eslint-disable-line
  const refresh = () => { qc.invalidateQueries({ queryKey: ["google-status"] }); qc.invalidateQueries({ queryKey: ["events"] }); };
  const saveCred = useMutation({ mutationFn: () => api.put("/api/google/credentials", cred), onSuccess: () => { refresh(); toast.ok("Zugangsdaten gespeichert"); setCred((c) => ({ ...c, client_secret: "" })); }, onError: toast.error });
  const connect = useMutation({ mutationFn: () => api.get<{ url: string }>("/api/google/auth-url"), onSuccess: (r) => { window.location.href = r.url; }, onError: toast.error });
  const sync = useMutation({ mutationFn: () => api.post<any>("/api/google/sync"), onSuccess: (r) => { refresh(); toast.ok(`Synchronisiert: ${r.upserted} aktualisiert, ${r.removed} entfernt`); }, onError: (e) => { refresh(); toast.error(e); } });
  const disconnect = useMutation({ mutationFn: () => api.post("/api/google/disconnect"), onSuccess: () => { refresh(); toast.ok("Google getrennt"); } });
  const select = useMutation({ mutationFn: (sel: string[]) => api.put("/api/google/calendars", { selected: sel }), onSuccess: () => { refresh(); sync.mutate(); } });
  const d = g.data;
  return (
    <>
      <Row title="Google Calendar" desc="OAuth-Client in der Google Cloud Console anlegen (Anleitung: docs/GOOGLE_CALENDAR.md) und hier eintragen.">
        {d && <>
          <div className="flex flex-wrap gap-2">
            <Badge tone={d.connected ? "ok" : "neutral"}>{d.connected ? `Verbunden${d.email ? ` als ${d.email}` : ""}` : "Nicht verbunden"}</Badge>
            {d.last_sync_at && <Badge>Letzte Synchronisation {ago(d.last_sync_at)}</Badge>}
          </div>
          {d.last_error && <p className="text-sm text-danger">{d.last_error}</p>}
          <Field label="Weiterleitungs-URI (in Google eintragen)"><Input readOnly value={d.redirect_uri} onFocus={(e) => e.target.select()} /></Field>
          <Field label="Client-ID"><Input value={cred.client_id} onChange={(e) => setCred({ ...cred, client_id: e.target.value })} placeholder="….apps.googleusercontent.com" /></Field>
          <Field label="Client-Secret" hint={d.has_client_secret ? "Hinterlegt (verschlüsselt). Leer lassen, um es zu behalten." : undefined}><Input type="password" value={cred.client_secret} onChange={(e) => setCred({ ...cred, client_secret: e.target.value })} /></Field>
          <div className="flex flex-wrap gap-2">
            <Button loading={saveCred.isPending} onClick={() => saveCred.mutate()}>Zugangsdaten speichern</Button>
            {d.configured && !d.connected && <Button variant="primary" loading={connect.isPending} onClick={() => connect.mutate()}><ExternalLink className="h-4 w-4" />Mit Google verbinden</Button>}
            {d.connected && <><Button variant="primary" loading={sync.isPending} onClick={() => sync.mutate()}><RefreshCw className="h-4 w-4" />Jetzt synchronisieren</Button><Button variant="danger" onClick={() => disconnect.mutate()}>Trennen</Button></>}
          </div>
          {d.calendars.length > 0 && (
            <div className="rounded border border-line divide-y divide-line">
              {d.calendars.map((c: any) => (
                <label key={c.google_id} className="flex items-center gap-3 px-3 py-2.5 cursor-pointer">
                  <input type="checkbox" checked={c.selected} className="accent-[rgb(var(--accent))]" onChange={(e) => select.mutate(d.calendars.filter((x: any) => (x.google_id === c.google_id ? e.target.checked : x.selected)).map((x: any) => x.google_id))} />
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: c.color }} />
                  <span className="text-sm text-ink flex-1 truncate">{c.summary}</span>
                  <span className="text-xs text-ink-3">{["owner", "writer"].includes(c.access_role) ? "Lesen & Schreiben" : "Nur lesen"}</span>
                </label>
              ))}
            </div>
          )}
        </>}
      </Row>
      <Row title="Synchronisation & Standards" desc="Google ist für Google-Termine führend. MOSI schreibt nur nach Google, wenn du es ausdrücklich auswählst.">
        <Field label="Synchronisationsintervall (Minuten)"><Input type="number" min={5} max={120} value={f.google_sync_minutes ?? 10} onChange={(e) => set("google_sync_minutes", Number(e.target.value))} /></Field>
        <Field label="Google-Kalender für neue Einträge"><Select value={f.google_write_calendar_id ?? ""} onChange={(e) => set("google_write_calendar_id", e.target.value)}><option value="">Hauptkalender</option>{d?.calendars.filter((c: any) => ["owner", "writer"].includes(c.access_role)).map((c: any) => <option key={c.google_id} value={c.google_id}>{c.summary}</option>)}</Select></Field>
        <Field label="Standard-Erinnerung"><Select value={String(f.default_reminders?.[0] ?? "")} onChange={(e) => set("default_reminders", e.target.value ? [Number(e.target.value)] : [])}><option value="">Keine</option><option value="5">5 Minuten</option><option value="15">15 Minuten</option><option value="30">30 Minuten</option><option value="60">1 Stunde</option></Select></Field>
        <Button variant="primary" loading={save.isPending} onClick={() => save.mutate(f)}>Speichern</Button>
      </Row>
      <Categories />
    </>
  );
}

function Categories() {
  const qc = useQueryClient();
  const toast = useToast();
  const cats = useQuery({ queryKey: ["categories"], queryFn: () => api.get<{ id: number; name: string; color: string }[]>("/api/categories") });
  const [n, setN] = useState({ name: "", color: "#4FB78B" });
  const add = useMutation({ mutationFn: () => api.post("/api/categories", n), onSuccess: () => { qc.invalidateQueries({ queryKey: ["categories"] }); setN({ ...n, name: "" }); }, onError: toast.error });
  const del = useMutation({ mutationFn: (id: number) => api.del(`/api/categories/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ["categories"] }) });
  return (
    <Row title="Kategorien (MOSI-Kalender)" desc="Eigene Kategorien mit Farbe für interne Termine.">
      <div className="space-y-1.5">{cats.data?.map((c) => <div key={c.id} className="flex items-center gap-3 text-sm"><span className="h-3 w-3 rounded-sm" style={{ background: c.color }} /><span className="flex-1">{c.name}</span><Button variant="ghost" size="sm" onClick={() => del.mutate(c.id)}>Entfernen</Button></div>)}</div>
      <div className="flex gap-2"><input type="color" value={n.color} onChange={(e) => setN({ ...n, color: e.target.value.toUpperCase() })} className="h-9 w-10 rounded bg-transparent" aria-label="Farbe" /><Input value={n.name} onChange={(e) => setN({ ...n, name: e.target.value })} placeholder="Neue Kategorie" /><Button disabled={!n.name.trim()} onClick={() => add.mutate()}>Hinzufügen</Button></div>
    </Row>
  );
}

function Planning() {
  const { f, set, save } = useSection("planner");
  const days: number[] = f.work_days ?? [];
  return (
    <>
      <Row title="Automatischer Wochenplan">
        <Switch checked={!!f.enabled} onChange={(v) => set("enabled", v)} label="Wöchentlich automatisch erstellen" />
        <div className="grid grid-cols-2 gap-3">
          <Field label="Tag"><Select value={f.weekday ?? 6} onChange={(e) => set("weekday", Number(e.target.value))}>{WEEKDAYS.map((w, i) => <option key={i} value={i}>{w}</option>)}</Select></Field>
          <Field label="Uhrzeit"><Input type="time" value={f.time ?? "18:00"} onChange={(e) => set("time", e.target.value)} /></Field>
        </div>
      </Row>
      <Row title="Arbeitszeiten" desc="Nur innerhalb dieser Zeiten plant MOSI Aufgaben. Andere Zeiten gelten als nicht verfügbar.">
        <div className="flex flex-wrap gap-1.5">{WEEKDAYS.map((w, i) => (
          <button key={i} onClick={() => set("work_days", days.includes(i) ? days.filter((x) => x !== i) : [...days, i].sort())}
            className={cn("h-8 px-3 rounded border text-sm", days.includes(i) ? "border-accent/50 bg-accent/15 text-ink" : "border-line text-ink-3")}>{w.slice(0, 2)}</button>
        ))}</div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Beginn"><Input type="time" value={f.work_start ?? ""} onChange={(e) => set("work_start", e.target.value)} /></Field>
          <Field label="Ende"><Input type="time" value={f.work_end ?? ""} onChange={(e) => set("work_end", e.target.value)} /></Field>
          <Field label="Pause von"><Input type="time" value={f.lunch_start ?? ""} onChange={(e) => set("lunch_start", e.target.value)} /></Field>
          <Field label="Pause bis"><Input type="time" value={f.lunch_end ?? ""} onChange={(e) => set("lunch_end", e.target.value)} /></Field>
        </div>
      </Row>
      <Row title="Regeln">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Puffer um Termine (Min.)"><Input type="number" value={f.buffer_minutes ?? 15} onChange={(e) => set("buffer_minutes", Number(e.target.value))} /></Field>
          <Field label="Max. Fokuszeit pro Tag (Min.)"><Input type="number" value={f.max_focus_minutes_per_day ?? 300} onChange={(e) => set("max_focus_minutes_per_day", Number(e.target.value))} /></Field>
          <Field label="Max. Blocklänge (Min.)"><Input type="number" value={f.max_block_minutes ?? 120} onChange={(e) => set("max_block_minutes", Number(e.target.value))} /></Field>
          <Field label="Standard-Schätzung (Min.)"><Input type="number" value={f.default_task_minutes ?? 60} onChange={(e) => set("default_task_minutes", Number(e.target.value))} /></Field>
        </div>
        <Field label="Persönliche Planungsregeln" hint="Freitext, den MOSI bei jeder Planung berücksichtigt."><Textarea rows={4} value={f.rules_text ?? ""} onChange={(e) => set("rules_text", e.target.value)} placeholder="z. B. Kreative Arbeit lieber vormittags. Mittwochs Vereinstraining ab 18 Uhr." /></Field>
      </Row>
      <div className="pt-4"><Button variant="primary" loading={save.isPending} onClick={() => save.mutate(f)}>Speichern</Button></div>
    </>
  );
}

function Notifications() {
  const { f, set, save } = useSection("notifications");
  const toast = useToast();
  const [hook, setHook] = useState("");
  const [perm, setPerm] = useState(typeof Notification !== "undefined" ? Notification.permission : "denied");
  const test = useMutation({ mutationFn: (channel: string) => api.post("/api/notifications/test", { channel }), onSuccess: () => toast.ok("Testbenachrichtigung gesendet"), onError: toast.error });
  const enablePush = async () => {
    try {
      if (!window.isSecureContext || !("serviceWorker" in navigator) || !("PushManager" in window)) throw new Error("Push benötigt HTTPS und einen unterstützten Browser (auf iOS: App zum Home-Bildschirm hinzufügen).");
      const p = await Notification.requestPermission(); setPerm(p);
      if (p !== "granted") throw new Error("Benachrichtigungen wurden nicht erlaubt.");
      const reg = await navigator.serviceWorker.ready;
      const { public_key } = await api.get<{ public_key: string }>("/api/push/vapid-key");
      const key = Uint8Array.from(atob(public_key.replace(/-/g, "+").replace(/_/g, "/") + "==".slice(0, (4 - (public_key.length % 4)) % 4)), (c) => c.charCodeAt(0));
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
      await api.post("/api/push/subscribe", { ...sub.toJSON(), user_agent: navigator.userAgent.slice(0, 250) });
      set("push", true); await save.mutateAsync({ push: true });
    } catch (e) { toast.error(e); }
  };
  const types: Record<string, boolean> = f.types ?? {};
  const LABEL: Record<string, string> = { event_upcoming: "Anstehende Termine", task_overdue: "Überfällige Aufgaben", project_deadline: "Projektdeadlines", weekly_plan: "Neuer Wochenplan", ai_hint: "Wichtige KI-Hinweise", sync_error: "Synchronisations- und Systemfehler" };
  return (
    <>
      <Row title="Kanäle">
        <Switch checked={!!f.browser} onChange={(v) => { set("browser", v); if (v && typeof Notification !== "undefined") Notification.requestPermission().then(setPerm); }} label="Browser-Benachrichtigungen" description={perm === "granted" ? "Erlaubt." : perm === "denied" ? "Im Browser blockiert." : "Noch nicht erlaubt."} />
        <div className="flex items-center justify-between gap-4"><div><div className="text-base">Push (PWA)</div><div className="text-sm text-ink-3">Auch bei geschlossener App. Benötigt HTTPS.</div></div>{f.push ? <div className="flex gap-2"><Button size="sm" onClick={() => test.mutate("push")}>Testen</Button><Button size="sm" variant="ghost" onClick={() => save.mutate({ push: false })}>Aus</Button></div> : <Button size="sm" onClick={enablePush}>Auf diesem Gerät aktivieren</Button>}</div>
        <Switch checked={!!f.discord} onChange={(v) => set("discord", v)} label="Discord" description="Über einen Webhook in einen Kanal deines Servers." />
        {f.discord && <Field label="Discord-Webhook-URL" hint={f.has_discord_webhook ? "Hinterlegt." : "Servereinstellungen → Integrationen → Webhooks"}><Input type="password" value={hook} onChange={(e) => setHook(e.target.value)} /></Field>}
        {f.has_discord_webhook && <Button size="sm" onClick={() => test.mutate("discord")}>Discord testen</Button>}
      </Row>
      <Row title="Meldungen">
        {Object.keys(LABEL).map((k) => <Switch key={k} checked={types[k] !== false} onChange={(v) => set("types", { ...types, [k]: v })} label={LABEL[k]} />)}
      </Row>
      <Row title="Zeiten">
        <Field label="Erinnerung vor Terminen (Min.)" hint="Gilt für Termine ohne eigene Erinnerung."><Input type="number" value={f.event_reminder_minutes ?? 15} onChange={(e) => set("event_reminder_minutes", Number(e.target.value))} /></Field>
        <Field label="Tägliche Zusammenfassung überfälliger Aufgaben um"><Input type="time" value={f.daily_digest_time ?? "07:30"} onChange={(e) => set("daily_digest_time", e.target.value)} /></Field>
        <Field label="Deadline-Hinweis (Tage vorher)"><Input type="number" value={f.deadline_days_before ?? 2} onChange={(e) => set("deadline_days_before", Number(e.target.value))} /></Field>
      </Row>
      <div className="pt-4"><Button variant="primary" loading={save.isPending} onClick={() => { const { has_discord_webhook, ...rest } = f; void has_discord_webhook; save.mutate({ ...rest, ...(hook ? { discord_webhook: hook } : {}) }, { onSuccess: () => setHook("") }); }}>Speichern</Button></div>
    </>
  );
}

function Security() {
  const toast = useToast();
  const qc = useQueryClient();
  const [pw, setPw] = useState({ current_password: "", new_password: "", repeat: "" });
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: () => api.get<any[]>("/api/auth/sessions") });
  const backups = useQuery({ queryKey: ["backups"], queryFn: () => api.get<any[]>("/api/system/backups") });
  const change = useMutation({ mutationFn: () => api.post("/api/auth/password", { current_password: pw.current_password, new_password: pw.new_password }), onSuccess: () => { toast.ok("Passwort geändert. Andere Sitzungen wurden beendet."); setPw({ current_password: "", new_password: "", repeat: "" }); qc.invalidateQueries({ queryKey: ["sessions"] }); } });
  const backup = useMutation({ mutationFn: () => api.post<{ name: string }>("/api/system/backups"), onSuccess: (r) => { toast.ok(`Backup erstellt: ${r.name}`); qc.invalidateQueries({ queryKey: ["backups"] }); }, onError: toast.error });
  const mismatch = pw.repeat && pw.repeat !== pw.new_password;
  return (
    <>
      <Row title="Passwort ändern" desc="Mindestens 10 Zeichen mit Groß-/Kleinbuchstaben und Ziffer.">
        <Field label="Aktuelles Passwort"><Input type="password" autoComplete="current-password" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} /></Field>
        <Field label="Neues Passwort"><Input type="password" autoComplete="new-password" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} /></Field>
        <Field label="Wiederholen" error={mismatch ? "Passwörter stimmen nicht überein." : undefined}><Input type="password" autoComplete="new-password" value={pw.repeat} onChange={(e) => setPw({ ...pw, repeat: e.target.value })} /></Field>
        <ErrorNote error={change.error} />
        <Button variant="primary" disabled={!pw.current_password || !pw.new_password || !!mismatch} loading={change.isPending} onClick={() => change.mutate()}>Passwort ändern</Button>
      </Row>
      <Row title="Sitzungen">
        <div className="rounded border border-line divide-y divide-line">{sessions.data?.map((s) => (
          <div key={s.id} className="flex items-center gap-3 px-3 py-2.5 text-sm"><div className="flex-1 min-w-0"><div className="truncate text-ink">{s.user_agent || "Unbekanntes Gerät"}</div><div className="text-xs text-ink-3">{s.ip}, zuletzt aktiv {ago(s.last_seen_at)}</div></div>
            {s.current ? <Badge tone="accent">Diese Sitzung</Badge> : <Button size="sm" variant="ghost" onClick={async () => { await api.del(`/api/auth/sessions/${s.id}`); qc.invalidateQueries({ queryKey: ["sessions"] }); }}>Beenden</Button>}</div>
        ))}</div>
      </Row>
      <Row title="Backup & Export" desc="Automatisches Datenbank-Backup täglich um 02:30 Uhr (14 Stück). Vollständige Sicherung inkl. Konfiguration: scripts/backup.sh auf dem Server.">
        <div className="flex flex-wrap gap-2"><Button loading={backup.isPending} onClick={() => backup.mutate()}>Backup jetzt erstellen</Button><a href="/api/system/export" className="inline-flex items-center gap-2 h-9 px-3.5 rounded border border-line-strong bg-raised text-base font-medium"><Download className="h-4 w-4" />Daten exportieren (JSON)</a></div>
        {backups.data && backups.data.length > 0 && <ul className="text-sm text-ink-3 space-y-1">{backups.data.slice(0, 5).map((b) => <li key={b.name} className="tnum">{b.name} ({Math.round(b.size / 1024)} KB)</li>)}</ul>}
      </Row>
    </>
  );
}

function System() {
  const s = useQuery({ queryKey: ["system"], queryFn: () => api.get<any>("/api/system/status"), refetchInterval: 30000 });
  if (!s.data) return <Skeleton className="h-64" />;
  const d = s.data;
  const gb = (b: number) => (b / 1024 ** 3).toFixed(2) + " GB";
  return (
    <>
      <Row title="Dienste">
        <div className="space-y-2 text-sm">
          <div className="flex justify-between"><span>Version</span><span className="tnum">{d.version}</span></div>
          <div className="flex justify-between"><span>Datenbank</span><Badge tone={d.database.ok ? "ok" : "danger"}>{d.database.ok ? `PostgreSQL ${d.database.version}` : "Fehler"}</Badge></div>
          <div className="flex justify-between"><span>Hermes Agent</span><Badge tone={d.hermes.ok ? "ok" : "danger"}>{d.hermes.message}</Badge></div>
          <div className="flex justify-between"><span>HTTPS</span><Badge tone={d.secure_context_hint ? "ok" : "warn"}>{d.secure_context_hint ? "aktiv" : "nicht konfiguriert – Mikrofon/PWA eingeschränkt"}</Badge></div>
        </div>
      </Row>
      <Row title="Speicher" desc={`Grenze ${gb(d.storage.limit)}; Warnung ab 80 % und 90 %.`}>
        <div className={cn("text-md font-medium", d.storage.level !== "ok" && "text-warn")}>{gb(d.storage.used)} belegt ({d.storage.percent} %)</div>
        <ul className="text-sm text-ink-3 space-y-1">{Object.entries(d.storage.parts).map(([k, v]) => <li key={k} className="flex justify-between"><span>{({ database: "Datenbank", uploads: "Uploads", backups: "Backups", hermes: "Hermes", logs: "Logs" } as any)[k] ?? k}</span><span className="tnum">{gb(v as number)}</span></li>)}</ul>
        {d.storage.disk && <p className="text-sm text-ink-3">Datenträger: {gb(d.storage.disk.free)} frei von {gb(d.storage.disk.total)}</p>}
      </Row>
      <Row title="Hintergrundjobs">
        <ul className="text-sm space-y-1.5">{Object.entries(d.jobs).map(([k, v]: [string, any]) => <li key={k} className="flex justify-between gap-3"><span>{k}</span><span className={cn("text-right", v.ok ? "text-ink-3" : "text-danger")}>{v.info || (v.ok ? "ok" : "Fehler")}, {ago(v.last_run)}</span></li>)}</ul>
      </Row>
      <Row title="Daten"><ul className="text-sm text-ink-3 space-y-1">{Object.entries(d.counts).map(([k, v]) => <li key={k} className="flex justify-between"><span>{({ projects: "Projekte", tasks: "Aufgaben", events: "Termine", memory: "Gedächtniseinträge", weekly_plans: "Wochenpläne", conversations: "Gespräche" } as any)[k]}</span><span className="tnum">{String(v)}</span></li>)}</ul></Row>
    </>
  );
}

export default function Settings() {
  const { section = "profil" } = useParams();
  const view: Record<string, ReactNode> = { profil: <Profile />, ki: <AI />, sprache: <Voice />, kalender: <CalendarSettings />, planung: <Planning />, benachrichtigungen: <Notifications />, sicherheit: <Security />, system: <System /> };
  return (
    <div>
      <h1 className="text-2xl font-semibold mb-6">Einstellungen</h1>
      <div className="grid gap-8 md:grid-cols-[180px_minmax(0,1fr)]">
        <nav className="flex md:flex-col gap-0.5 overflow-x-auto -mx-4 px-4 md:mx-0 md:px-0" aria-label="Einstellungsbereiche">
          {SECTIONS.map(([k, l]) => <NavLink key={k} to={`/einstellungen/${k}`} className={({ isActive }) => cn("shrink-0 h-8 px-2.5 rounded text-sm flex items-center", isActive ? "bg-raised text-ink" : "text-ink-2 hover:text-ink hover:bg-surface")}>{l}</NavLink>)}
        </nav>
        <Panel className="px-5">{view[section] ?? <Profile />}</Panel>
      </div>
    </div>
  );
}
