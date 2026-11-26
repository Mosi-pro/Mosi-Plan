/** Erstellen/Bearbeiten von Aufgaben, Projekten und Terminen – global über useCreate() erreichbar. */
import { useMutation, useQuery } from "@tanstack/react-query";
import { addHours, format } from "date-fns";
import { AlertTriangle, Trash2 } from "lucide-react";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import { time } from "@/lib/format";
import type { CalEvent, Priority, Project, Task } from "@/lib/types";
import { useCategories, useInvalidate, useProjects } from "@/hooks/queries";
import { Button, ConfirmDialog, Dialog, ErrorNote, Field, Input, Select, Switch, Textarea } from "./ui";
import { useToast } from "./toast";

const PRIORITIES: { v: Priority; l: string }[] = [
  { v: "low", l: "Niedrig" }, { v: "normal", l: "Normal" }, { v: "high", l: "Hoch" }, { v: "critical", l: "Kritisch" },
];
const COLORS = ["#5B8DEF", "#4FB78B", "#D9A441", "#E5645E", "#A07CE8", "#4CB3C9", "#C9739B", "#8C96A8"];

/* ===================================================================== Aufgabe */
export function TaskDialog({ open, onOpenChange, task, defaults }: { open: boolean; onOpenChange: (o: boolean) => void; task?: Task | null; defaults?: Partial<Task> }) {
  const projects = useProjects("open");
  const inv = useInvalidate();
  const toast = useToast();
  const [f, setF] = useState<Partial<Task>>({});
  const [confirmDel, setConfirmDel] = useState(false);
  useEffect(() => {
    if (open) setF(task ? { ...task } : { title: "", description: "", priority: "normal", status: "open", project_id: null, due_date: null, estimated_minutes: null, ...defaults });
  }, [open, task, defaults]);
  const save = useMutation({
    mutationFn: () => {
      const body = { title: f.title?.trim(), description: f.description ?? "", priority: f.priority, status: f.status, project_id: f.project_id || null,
        parent_id: f.parent_id ?? null, due_date: f.due_date || null, estimated_minutes: f.estimated_minutes || null, actual_minutes: f.actual_minutes || null };
      return task ? api.patch(`/api/tasks/${task.id}`, body) : api.post("/api/tasks", body);
    },
    onSuccess: () => { inv(); toast.ok(task ? "Aufgabe gespeichert" : "Aufgabe erstellt"); onOpenChange(false); },
  });
  const del = useMutation({
    mutationFn: () => api.del(`/api/tasks/${task!.id}`),
    onSuccess: () => { inv(); toast.ok("Aufgabe gelöscht"); setConfirmDel(false); onOpenChange(false); },
    onError: toast.error,
  });
  const set = (k: keyof Task) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setF((s) => ({ ...s, [k]: e.target.value }));
  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange} title={task ? "Aufgabe bearbeiten" : f.parent_id ? "Neue Unteraufgabe" : "Neue Aufgabe"}
        footer={<>
          {task && <Button variant="ghost" className="mr-auto text-danger" onClick={() => setConfirmDel(true)}><Trash2 className="h-4 w-4" />Löschen</Button>}
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Abbrechen</Button>
          <Button variant="primary" loading={save.isPending} disabled={!f.title?.trim()} onClick={() => save.mutate()}>{task ? "Speichern" : "Aufgabe erstellen"}</Button>
        </>}>
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (f.title?.trim()) save.mutate(); }}>
          <Field label="Titel"><Input autoFocus value={f.title ?? ""} onChange={set("title")} placeholder="Was ist zu tun?" maxLength={300} /></Field>
          <Field label="Beschreibung"><Textarea value={f.description ?? ""} onChange={set("description")} rows={3} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Projekt">
              <Select value={f.project_id ?? ""} onChange={(e) => setF((s) => ({ ...s, project_id: e.target.value ? Number(e.target.value) : null }))}>
                <option value="">Kein Projekt</option>
                {projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </Select>
            </Field>
            <Field label="Priorität">
              <Select value={f.priority} onChange={set("priority")}>{PRIORITIES.map((p) => <option key={p.v} value={p.v}>{p.l}</option>)}</Select>
            </Field>
            <Field label="Fällig am"><Input type="date" value={f.due_date ?? ""} onChange={set("due_date")} /></Field>
            <Field label="Status">
              <Select value={f.status} onChange={set("status")}>
                <option value="open">Offen</option><option value="in_progress">In Bearbeitung</option><option value="waiting">Wartet</option><option value="done">Erledigt</option><option value="archived">Archiviert</option>
              </Select>
            </Field>
            <Field label="Geschätzte Dauer (Min.)"><Input type="number" min={0} step={15} value={f.estimated_minutes ?? ""} onChange={(e) => setF((s) => ({ ...s, estimated_minutes: e.target.value ? Number(e.target.value) : null }))} /></Field>
            <Field label="Tatsächliche Dauer (Min.)" hint="Optional"><Input type="number" min={0} step={15} value={f.actual_minutes ?? ""} onChange={(e) => setF((s) => ({ ...s, actual_minutes: e.target.value ? Number(e.target.value) : null }))} /></Field>
          </div>
          <ErrorNote error={save.error} />
          <button type="submit" hidden />
        </form>
      </Dialog>
      <ConfirmDialog open={confirmDel} onOpenChange={setConfirmDel} title="Aufgabe löschen?" text={`„${task?.title}“ und alle Unteraufgaben werden endgültig gelöscht.`} confirmLabel="Endgültig löschen" loading={del.isPending} onConfirm={() => del.mutate()} />
    </>
  );
}

/* ===================================================================== Projekt */
export function ProjectDialog({ open, onOpenChange, project, presetName }: { open: boolean; onOpenChange: (o: boolean) => void; project?: Project | null; presetName?: string }) {
  const inv = useInvalidate();
  const toast = useToast();
  const [f, setF] = useState<Partial<Project>>({});
  const [cats, setCats] = useState("");
  useEffect(() => {
    if (!open) return;
    const base = project ?? { name: presetName ?? "", description: "", goal: "", status: "active", priority: "normal", start_date: null, deadline: null, color: COLORS[0], categories: [], notes: "" };
    setF({ ...base } as Partial<Project>);
    setCats((base.categories ?? []).join(", "));
  }, [open, project, presetName]);
  const save = useMutation({
    mutationFn: () => {
      const body = { name: f.name?.trim(), description: f.description, goal: f.goal, status: f.status, priority: f.priority, start_date: f.start_date || null,
        deadline: f.deadline || null, color: f.color, categories: cats.split(",").map((c) => c.trim()).filter(Boolean), notes: f.notes ?? "" };
      return project ? api.patch<Project>(`/api/projects/${project.id}`, body) : api.post<Project>("/api/projects", body);
    },
    onSuccess: () => { inv(); toast.ok(project ? "Projekt gespeichert" : "Projekt erstellt"); onOpenChange(false); },
  });
  const set = (k: keyof Project) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setF((s) => ({ ...s, [k]: e.target.value }));
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={project ? "Projekt bearbeiten" : "Neues Projekt"}
      footer={<>
        <Button variant="ghost" onClick={() => onOpenChange(false)}>Abbrechen</Button>
        <Button variant="primary" loading={save.isPending} disabled={!f.name?.trim()} onClick={() => save.mutate()}>{project ? "Speichern" : "Projekt erstellen"}</Button>
      </>}>
      <div className="space-y-4">
        <Field label="Name"><Input autoFocus value={f.name ?? ""} onChange={set("name")} maxLength={200} /></Field>
        <Field label="Ziel" hint="Woran erkennst du, dass das Projekt erfolgreich ist?"><Textarea rows={2} value={f.goal ?? ""} onChange={set("goal")} /></Field>
        <Field label="Beschreibung"><Textarea rows={3} value={f.description ?? ""} onChange={set("description")} /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Status">
            <Select value={f.status} onChange={set("status")}>
              <option value="planned">Geplant</option><option value="active">Aktiv</option><option value="paused">Pausiert</option><option value="completed">Abgeschlossen</option><option value="archived">Archiviert</option>
            </Select>
          </Field>
          <Field label="Priorität"><Select value={f.priority} onChange={set("priority")}>{PRIORITIES.map((p) => <option key={p.v} value={p.v}>{p.l}</option>)}</Select></Field>
          <Field label="Start"><Input type="date" value={f.start_date ?? ""} onChange={set("start_date")} /></Field>
          <Field label="Deadline"><Input type="date" value={f.deadline ?? ""} onChange={set("deadline")} /></Field>
        </div>
        <Field label="Kategorien" hint="Durch Komma getrennt"><Input value={cats} onChange={(e) => setCats(e.target.value)} placeholder="z. B. Verein, Website" /></Field>
        <div>
          <div className="text-sm font-medium text-ink-2 mb-1.5">Farbe</div>
          <div className="flex gap-2">
            {COLORS.map((c) => (
              <button key={c} type="button" aria-label={`Farbe ${c}`} onClick={() => setF((s) => ({ ...s, color: c }))}
                className="h-6 w-6 rounded-full ring-offset-2 ring-offset-surface transition" style={{ background: c, boxShadow: f.color === c ? `0 0 0 2px rgb(var(--surface)), 0 0 0 4px ${c}` : undefined }} />
            ))}
          </div>
        </div>
        <ErrorNote error={save.error} />
      </div>
    </Dialog>
  );
}

/* ===================================================================== Termin */
const toLocalInput = (d: Date) => format(d, "yyyy-MM-dd'T'HH:mm");
const RRULES = [
  { v: "", l: "Keine Wiederholung" }, { v: "FREQ=DAILY", l: "Täglich" }, { v: "FREQ=WEEKLY", l: "Wöchentlich" },
  { v: "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", l: "Werktags" }, { v: "FREQ=WEEKLY;INTERVAL=2", l: "Alle zwei Wochen" }, { v: "FREQ=MONTHLY", l: "Monatlich" }, { v: "FREQ=YEARLY", l: "Jährlich" },
];

export function EventDialog({ open, onOpenChange, event, defaults }: { open: boolean; onOpenChange: (o: boolean) => void; event?: CalEvent | null; defaults?: { start?: Date; end?: Date; allDay?: boolean } }) {
  const inv = useInvalidate();
  const toast = useToast();
  const cats = useCategories();
  const projects = useProjects("open");
  const google = useQuery({ queryKey: ["google-status"], queryFn: () => api.get<any>("/api/google/status"), enabled: open });
  const [f, setF] = useState({ title: "", notes: "", location: "", start: "", end: "", all_day: false, start_date: "", end_date: "", rrule: "", category_id: "", project_id: "", reminder: "15", target: "internal", google_calendar_id: "" });
  const [conflicts, setConflicts] = useState<CalEvent[]>([]);
  const [confirmDel, setConfirmDel] = useState<null | "one" | "all">(null);

  useEffect(() => {
    if (!open) return;
    setConflicts([]);
    if (event) {
      setF({
        title: event.title, notes: event.notes, location: event.location, start: toLocalInput(new Date(event.start)), end: toLocalInput(new Date(event.end)),
        all_day: event.all_day, start_date: event.start_date ?? event.start.slice(0, 10), end_date: event.end_date ?? event.start.slice(0, 10), rrule: event.rrule ?? "",
        category_id: event.category_id ? String(event.category_id) : "", project_id: event.project_id ? String(event.project_id) : "",
        reminder: event.reminders[0] !== undefined ? String(event.reminders[0]) : "", target: event.source, google_calendar_id: event.google_calendar_id ?? "",
      });
    } else {
      const s = defaults?.start ?? new Date(Math.ceil(Date.now() / 1800000) * 1800000);
      const e = defaults?.end ?? addHours(s, 1);
      setF({ title: "", notes: "", location: "", start: toLocalInput(s), end: toLocalInput(e), all_day: !!defaults?.allDay, start_date: format(s, "yyyy-MM-dd"), end_date: format(s, "yyyy-MM-dd"), rrule: "", category_id: "", project_id: "", reminder: "15", target: "internal", google_calendar_id: "" });
    }
  }, [open, event, defaults]);

  const isGoogle = f.target === "google";
  const save = useMutation({
    mutationFn: async () => {
      const body: Record<string, unknown> = {
        title: f.title.trim(), notes: f.notes, location: f.location, all_day: f.all_day,
        project_id: f.project_id ? Number(f.project_id) : null, reminders: f.reminder ? [Number(f.reminder)] : [],
      };
      if (f.all_day) { body.start_date = f.start_date; body.end_date = f.end_date || f.start_date; }
      else { body.start = new Date(f.start).toISOString(); body.end = new Date(f.end).toISOString(); }
      if (!isGoogle) { body.rrule = f.rrule || null; body.category_id = f.category_id ? Number(f.category_id) : null; }
      if (event) {
        if (event.source === "google") { delete body.reminders; }
        return api.patch<{ id: number; conflicts: CalEvent[] }>(`/api/events/${event.event_id}`, body);
      }
      body.target = f.target;
      if (isGoogle && f.google_calendar_id) body.google_calendar_id = f.google_calendar_id;
      return api.post<{ id: number; conflicts: CalEvent[] }>("/api/events", body);
    },
    onSuccess: (r) => {
      inv();
      if (r.conflicts?.length) { setConflicts(r.conflicts); toast.info(`Gespeichert – überschneidet sich mit „${r.conflicts[0].title}“.`); }
      else toast.ok(event ? "Termin gespeichert" : "Termin erstellt");
      onOpenChange(false);
    },
  });
  const del = useMutation({
    mutationFn: (mode: "one" | "all") => api.del(`/api/events/${event!.event_id}${mode === "one" && event!.occurrence ? `?occurrence=${encodeURIComponent(event!.occurrence)}` : ""}`),
    onSuccess: () => { inv(); toast.ok("Termin gelöscht"); setConfirmDel(null); onOpenChange(false); },
    onError: toast.error,
  });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setF((s) => ({ ...s, [k]: e.target.value }));
  const writable = (google.data?.calendars ?? []).filter((c: any) => c.selected && ["owner", "writer"].includes(c.access_role));
  const readOnly = event && !event.editable;
  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange} title={event ? (readOnly ? "Termin" : "Termin bearbeiten") : "Neuer Termin"}
        description={event ? (event.source === "google" ? "Aus Google Calendar" : event.origin === "weekly_plan" ? "Aus dem Wochenplan (MOSI-Kalender)" : "MOSI-Kalender") : undefined}
        footer={<>
          {event && event.editable && <Button variant="ghost" className="mr-auto text-danger" onClick={() => setConfirmDel(event.recurring && event.occurrence ? "one" : "all")}><Trash2 className="h-4 w-4" />Löschen</Button>}
          <Button variant="ghost" onClick={() => onOpenChange(false)}>{readOnly ? "Schließen" : "Abbrechen"}</Button>
          {!readOnly && <Button variant="primary" loading={save.isPending} disabled={!f.title.trim()} onClick={() => save.mutate()}>{event ? "Speichern" : "Termin erstellen"}</Button>}
        </>}>
        <fieldset disabled={!!readOnly} className="space-y-4">
          <Field label="Titel"><Input autoFocus value={f.title} onChange={set("title")} maxLength={300} /></Field>
          {!event && (
            <Field label="Kalender" hint={isGoogle ? "Wird direkt in Google Calendar eingetragen." : "Nur in MOSI PLAN, unabhängig von Google."}>
              <Select value={isGoogle ? `g:${f.google_calendar_id}` : "internal"} onChange={(e) => {
                const v = e.target.value;
                setF((s) => ({ ...s, target: v === "internal" ? "internal" : "google", google_calendar_id: v.startsWith("g:") ? v.slice(2) : "" }));
              }}>
                <option value="internal">MOSI-Kalender</option>
                {writable.map((c: any) => <option key={c.google_id} value={`g:${c.google_id}`}>Google: {c.summary}</option>)}
              </Select>
            </Field>
          )}
          <Switch checked={f.all_day} onChange={(v) => setF((s) => ({ ...s, all_day: v }))} label="Ganztägig" />
          {f.all_day ? (
            <div className="grid grid-cols-2 gap-3">
              <Field label="Von"><Input type="date" value={f.start_date} onChange={set("start_date")} /></Field>
              <Field label="Bis"><Input type="date" value={f.end_date} onChange={set("end_date")} /></Field>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              <Field label="Beginn"><Input type="datetime-local" value={f.start} onChange={(e) => {
                const ns = e.target.value; const dur = new Date(f.end).getTime() - new Date(f.start).getTime();
                setF((s) => ({ ...s, start: ns, end: dur > 0 && ns ? toLocalInput(new Date(new Date(ns).getTime() + dur)) : s.end }));
              }} /></Field>
              <Field label="Ende"><Input type="datetime-local" value={f.end} onChange={set("end")} /></Field>
            </div>
          )}
          <Field label="Ort"><Input value={f.location} onChange={set("location")} /></Field>
          {!isGoogle && (
            <div className="grid grid-cols-2 gap-3">
              <Field label="Wiederholung" hint={event?.recurring ? "Änderungen gelten für die gesamte Serie." : undefined}>
                <Select value={RRULES.some((r) => r.v === f.rrule) ? f.rrule : "custom"} onChange={set("rrule")}>
                  {RRULES.map((r) => <option key={r.v} value={r.v}>{r.l}</option>)}
                  {!RRULES.some((r) => r.v === f.rrule) && <option value="custom" disabled>Benutzerdefiniert ({f.rrule})</option>}
                </Select>
              </Field>
              <Field label="Kategorie">
                <Select value={f.category_id} onChange={set("category_id")}>
                  <option value="">Keine</option>
                  {cats.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </Select>
              </Field>
            </div>
          )}
          <div className="grid grid-cols-2 gap-3">
            <Field label="Projekt">
              <Select value={f.project_id} onChange={set("project_id")}>
                <option value="">Kein Projekt</option>
                {projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </Select>
            </Field>
            {!isGoogle && (
              <Field label="Erinnerung">
                <Select value={f.reminder} onChange={set("reminder")}>
                  <option value="">Keine</option><option value="0">Zum Beginn</option><option value="5">5 Minuten vorher</option><option value="15">15 Minuten vorher</option>
                  <option value="30">30 Minuten vorher</option><option value="60">1 Stunde vorher</option><option value="1440">1 Tag vorher</option>
                </Select>
              </Field>
            )}
          </div>
          <Field label="Notizen"><Textarea rows={3} value={f.notes} onChange={set("notes")} /></Field>
          {conflicts.length > 0 && (
            <div className="flex gap-2 text-sm text-warn"><AlertTriangle className="h-4 w-4 mt-0.5" />Überschneidung mit {conflicts.map((c) => `„${c.title}“ (${time(c.start)})`).join(", ")}</div>
          )}
          <ErrorNote error={save.error} />
        </fieldset>
      </Dialog>
      <Dialog open={!!confirmDel} onOpenChange={(o) => !o && setConfirmDel(null)} title="Termin löschen?" size="sm"
        footer={<>
          <Button variant="ghost" onClick={() => setConfirmDel(null)}>Abbrechen</Button>
          {event?.recurring && event.occurrence && <Button variant="secondary" loading={del.isPending && del.variables === "one"} onClick={() => del.mutate("one")}>Nur diesen Termin</Button>}
          <Button variant="danger" loading={del.isPending && del.variables === "all"} onClick={() => del.mutate("all")}>{event?.recurring && event.occurrence ? "Ganze Serie" : "Löschen"}</Button>
        </>}>
        <p className="text-base text-ink-2">„{event?.title}“ wird {event?.source === "google" ? "auch in Google Calendar " : ""}gelöscht.</p>
      </Dialog>
    </>
  );
}

/* ===================================================================== Globaler Zugriff */
interface CreateCtx {
  newTask: (d?: Partial<Task>) => void;
  editTask: (t: Task) => void;
  newProject: (name?: string) => void;
  editProject: (p: Project) => void;
  newEvent: (d?: { start?: Date; end?: Date; allDay?: boolean }) => void;
  editEvent: (e: CalEvent) => void;
}
const Ctx = createContext<CreateCtx>(null as unknown as CreateCtx);
export const useCreate = () => useContext(Ctx);

export function CreateProvider({ children }: { children: ReactNode }) {
  const [task, setTask] = useState<{ open: boolean; task?: Task | null; defaults?: Partial<Task> }>({ open: false });
  const [project, setProject] = useState<{ open: boolean; project?: Project | null; name?: string }>({ open: false });
  const [ev, setEv] = useState<{ open: boolean; event?: CalEvent | null; defaults?: { start?: Date; end?: Date; allDay?: boolean } }>({ open: false });
  return (
    <Ctx.Provider value={{
      newTask: (d) => setTask({ open: true, task: null, defaults: d }),
      editTask: (t) => setTask({ open: true, task: t }),
      newProject: (name) => setProject({ open: true, project: null, name }),
      editProject: (p) => setProject({ open: true, project: p }),
      newEvent: (d) => setEv({ open: true, event: null, defaults: d }),
      editEvent: (e) => setEv({ open: true, event: e }),
    }}>
      {children}
      <TaskDialog open={task.open} onOpenChange={(o) => setTask((s) => ({ ...s, open: o }))} task={task.task} defaults={task.defaults} />
      <ProjectDialog open={project.open} onOpenChange={(o) => setProject((s) => ({ ...s, open: o }))} project={project.project} presetName={project.name} />
      <EventDialog open={ev.open} onOpenChange={(o) => setEv((s) => ({ ...s, open: o }))} event={ev.event} defaults={ev.defaults} />
    </Ctx.Provider>
  );
}
