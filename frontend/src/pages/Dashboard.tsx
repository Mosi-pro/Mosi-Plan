import { useQuery } from "@tanstack/react-query";
import { ArrowUp, ArrowDown, CalendarDays, CheckSquare, FolderKanban, MapPin, Settings2, MessageSquareText } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useCreate } from "@/components/dialogs";
import { TaskRow } from "@/components/task-row";
import { MicButton } from "@/components/voice";
import { Button, Dialog, Empty, ErrorNote, Panel, Progress, Skeleton, Switch } from "@/components/ui";
import { api } from "@/lib/api";
import { dateLong, relDay, time, toDate } from "@/lib/format";
import type { CalEvent, Overview } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useSaveSettings, useSettings } from "@/hooks/queries";

const WIDGET_LABEL: Record<string, string> = {
  summary: "Zusammenfassung", today_events: "Tagesleiste", today_tasks: "Heute fällig", overdue: "Überfällig",
  deadlines: "Deadlines", projects: "Aktive Projekte", upcoming: "Nächste Termine",
};

/* Tagesleiste: Termine des Tages auf einer Zeitachse mit Jetzt-Markierung */
function DayStrip({ events }: { events: CalEvent[] }) {
  const { editEvent, newEvent } = useCreate();
  const [now, setNow] = useState(new Date());
  useEffect(() => { const t = setInterval(() => setNow(new Date()), 60000); return () => clearInterval(t); }, []);
  const timed = events.filter((e) => !e.all_day);
  const allDay = events.filter((e) => e.all_day);
  const startH = Math.min(7, ...timed.map((e) => toDate(e.start).getHours()));
  const endH = Math.max(21, ...timed.map((e) => { const d = toDate(e.end); return d.getHours() + (d.getMinutes() ? 1 : 0); }));
  const span = (endH - startH) * 60;
  const pos = (d: Date) => ((d.getHours() - startH) * 60 + d.getMinutes()) / span * 100;
  const day0 = new Date(now); day0.setHours(0, 0, 0, 0);
  // Überlappende Termine auf Spuren verteilen
  const lanes: Date[] = [];
  const placed = timed.map((e) => {
    const s = toDate(e.start) < day0 ? day0 : toDate(e.start);
    const en = toDate(e.end);
    let lane = lanes.findIndex((l) => l <= s);
    if (lane < 0) { lane = lanes.length; lanes.push(en); } else lanes[lane] = en;
    return { e, s, en, lane };
  });
  const laneCount = Math.max(1, lanes.length);
  const hours = Array.from({ length: endH - startH + 1 }, (_, i) => startH + i);
  return (
    <div>
      {allDay.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-3">
          {allDay.map((e) => (
            <button key={e.id} onClick={() => editEvent(e)} className="h-6 px-2 rounded-sm text-xs font-medium bg-raised border border-line text-ink-2 hover:text-ink">
              Ganztägig: {e.title}
            </button>
          ))}
        </div>
      )}
      <div className="relative" style={{ height: 30 + laneCount * 38 }}>
        {hours.map((h, i) => (
          <div key={h} className="absolute top-0 bottom-0 border-l border-line" style={{ left: `${(i * 60 / span) * 100}%` }}>
            {h % 2 === (startH % 2) && <span className="absolute -top-0.5 left-1.5 text-2xs text-ink-3 tnum">{String(h).padStart(2, "0")}</span>}
          </div>
        ))}
        <button aria-label="Termin anlegen" className="absolute inset-x-0 top-5 bottom-0" onClick={(ev) => {
          const r = (ev.currentTarget as HTMLElement).getBoundingClientRect();
          const mins = Math.round(((ev.clientX - r.left) / r.width * span) / 30) * 30;
          const s = new Date(day0); s.setHours(startH, mins, 0, 0);
          newEvent({ start: s });
        }} />
        {placed.map(({ e, s, en, lane }) => {
          const left = Math.max(0, pos(s));
          const width = Math.max(1.2, Math.min(100, pos(en)) - left);
          const past = en < now;
          return (
            <button key={e.id} onClick={() => editEvent(e)} title={`${time(e.start)}–${time(e.end)} ${e.title}`}
              className={cn("absolute h-8 rounded-sm px-2 text-left overflow-hidden border-l-2 transition-colors", past ? "bg-surface text-ink-3" : "bg-raised text-ink hover:bg-line")}
              style={{ left: `${left}%`, width: `${width}%`, top: 22 + lane * 38, borderLeftColor: e.color ?? (e.source === "google" ? "#4C8DF6" : "rgb(var(--accent))") }}>
              <div className="text-xs font-medium truncate leading-4 mt-[3px]">{e.title}</div>
              <div className="text-2xs text-ink-3 tnum leading-3">{time(e.start)}</div>
            </button>
          );
        })}
        {now.getHours() >= startH && now.getHours() < endH && (
          <div className="absolute top-4 bottom-0 w-px bg-danger pointer-events-none" style={{ left: `${pos(now)}%` }}>
            <span className="absolute -top-1 -left-[3px] h-[7px] w-[7px] rounded-full bg-danger" />
          </div>
        )}
      </div>
    </div>
  );
}

function CustomizeDialog({ open, onOpenChange, widgets }: { open: boolean; onOpenChange: (o: boolean) => void; widgets: { id: string; visible: boolean }[] }) {
  const save = useSaveSettings("dashboard");
  const [w, setW] = useState(widgets);
  useEffect(() => { if (open) setW(widgets); }, [open, widgets]);
  const move = (i: number, d: number) => setW((s) => { const n = [...s]; const [x] = n.splice(i, 1); n.splice(i + d, 0, x); return n; });
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Übersicht anpassen" description="Bereiche ein- und ausblenden und die Reihenfolge festlegen." size="sm"
      footer={<><Button variant="ghost" onClick={() => onOpenChange(false)}>Abbrechen</Button><Button variant="primary" loading={save.isPending} onClick={() => save.mutate({ widgets: w }, { onSuccess: () => onOpenChange(false) })}>Speichern</Button></>}>
      <div className="divide-y divide-line">
        {w.map((x, i) => (
          <div key={x.id} className="flex items-center gap-2">
            <div className="flex flex-col">
              <button aria-label="Nach oben" disabled={i === 0} onClick={() => move(i, -1)} className="text-ink-3 hover:text-ink disabled:opacity-30"><ArrowUp className="h-3.5 w-3.5" /></button>
              <button aria-label="Nach unten" disabled={i === w.length - 1} onClick={() => move(i, 1)} className="text-ink-3 hover:text-ink disabled:opacity-30"><ArrowDown className="h-3.5 w-3.5" /></button>
            </div>
            <div className="flex-1"><Switch checked={x.visible} label={WIDGET_LABEL[x.id] ?? x.id} onChange={(v) => setW((s) => s.map((y) => (y.id === x.id ? { ...y, visible: v } : y)))} /></div>
          </div>
        ))}
      </div>
    </Dialog>
  );
}

export default function Dashboard() {
  const ov = useQuery({ queryKey: ["overview"], queryFn: () => api.get<Overview>("/api/overview"), refetchInterval: 5 * 60_000 });
  const settings = useSettings();
  const create = useCreate();
  const nav = useNavigate();
  const [customize, setCustomize] = useState(false);
  const widgets: { id: string; visible: boolean }[] = settings.data?.dashboard?.widgets ?? [];
  const visible = (id: string) => widgets.length === 0 || widgets.find((w) => w.id === id)?.visible !== false;
  const order = (id: string) => { const i = widgets.findIndex((w) => w.id === id); return i < 0 ? 99 : i; };
  const d = ov.data;

  if (ov.isError) return <ErrorNote error={ov.error} />;

  const blocks: Record<string, React.ReactNode> = d ? {
    today_tasks: (
      <Panel title="Heute fällig" action={<Button variant="ghost" size="sm" onClick={() => create.newTask({ due_date: d.date })}>Hinzufügen</Button>} bodyClassName="divide-y divide-line/70">
        {d.tasks_today.length ? d.tasks_today.map((t) => <TaskRow key={t.id} task={t} />) : <Empty icon={CheckSquare} title="Für heute ist nichts fällig" text="Plane eine Aufgabe für heute oder arbeite an einem Projekt weiter." />}
      </Panel>
    ),
    overdue: d.overdue.length > 0 && (
      <Panel title={<span className="text-danger">Überfällig</span>} action={<span className="text-sm text-ink-3 tnum">{d.overdue.length}</span>} bodyClassName="divide-y divide-line/70">
        {d.overdue.slice(0, 8).map((t) => <TaskRow key={t.id} task={t} />)}
        {d.overdue.length > 8 && <Link to="/aufgaben?filter=ueberfaellig" className="block px-4 py-2.5 text-sm text-accent-ink hover:underline">Alle {d.overdue.length} anzeigen</Link>}
      </Panel>
    ),
    projects: (
      <Panel title="Aktive Projekte" action={<Link to="/projekte" className="text-sm text-ink-3 hover:text-ink">Alle</Link>}>
        {d.active_projects.length ? (
          <div className="divide-y divide-line/70">
            {d.active_projects.slice(0, 6).map((p) => (
              <Link key={p.id} to={`/projekte/${p.id}`} className="grid grid-cols-[1fr_auto] sm:grid-cols-[minmax(0,1fr)_160px_90px] items-center gap-x-6 gap-y-1.5 px-4 py-3 hover:bg-raised/60">
                <div className="flex items-center gap-2.5 min-w-0"><span className="h-2.5 w-2.5 rounded-[3px] shrink-0" style={{ background: p.color }} /><span className="truncate text-base text-ink">{p.name}</span></div>
                <div className="flex items-center gap-2 col-span-2 sm:col-span-1 order-last sm:order-none"><Progress value={p.progress} /><span className="text-xs text-ink-3 tnum w-10 text-right whitespace-nowrap">{p.progress} %</span></div>
                <div className="text-sm text-ink-3 text-right tnum">{p.task_open} offen</div>
              </Link>
            ))}
          </div>
        ) : <Empty icon={FolderKanban} title="Keine aktiven Projekte" action={<Button size="sm" onClick={() => create.newProject()}>Projekt anlegen</Button>} />}
      </Panel>
    ),
    upcoming: (
      <Panel title="Nächste Termine" action={<Link to="/kalender" className="text-sm text-ink-3 hover:text-ink">Kalender</Link>}>
        {d.upcoming_events.length ? (
          <ul className="divide-y divide-line/70">
            {d.upcoming_events.map((e) => (
              <li key={e.id}>
                <button onClick={() => create.editEvent(e)} className="w-full flex gap-3 px-4 py-2.5 text-left hover:bg-raised/60">
                  <div className="w-[68px] shrink-0 text-sm tnum"><div className="text-ink-2">{relDay(e.start)}</div><div className="text-ink-3">{e.all_day ? "ganztägig" : time(e.start)}</div></div>
                  <div className="min-w-0"><div className="text-base text-ink truncate">{e.title}</div>{e.location && <div className="text-sm text-ink-3 truncate flex items-center gap-1"><MapPin className="h-3 w-3" />{e.location}</div>}</div>
                </button>
              </li>
            ))}
          </ul>
        ) : <Empty icon={CalendarDays} title="Keine Termine in den nächsten 7 Tagen" />}
      </Panel>
    ),
    deadlines: (
      <Panel title="Deadlines">
        {d.deadlines.length ? (
          <ul className="divide-y divide-line/70">
            {d.deadlines.map((x) => (
              <li key={`${x.type}${x.id}`}>
                <Link to={x.type === "project" ? `/projekte/${x.id}` : `/aufgaben?aufgabe=${x.id}`} className="flex items-center gap-3 px-4 py-2.5 hover:bg-raised/60">
                  <span className="w-[68px] text-sm text-ink-2 tnum shrink-0">{relDay(x.date)}</span>
                  <span className="min-w-0 flex-1"><span className="block text-base text-ink truncate">{x.title}</span><span className="block text-sm text-ink-3 truncate">{x.type === "project" ? "Projektdeadline" : x.project_name ?? "Aufgabe"}</span></span>
                </Link>
              </li>
            ))}
          </ul>
        ) : <Empty title="Keine anstehenden Deadlines" text="In den nächsten zwei Wochen ist nichts Kritisches fällig." />}
      </Panel>
    ),
  } : {};

  const main = ["overdue", "today_tasks", "projects"].filter((k) => visible(k)).sort((a, b) => order(a) - order(b));
  const side = ["upcoming", "deadlines"].filter((k) => visible(k)).sort((a, b) => order(a) - order(b));

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="text-sm text-ink-3">{d ? dateLong(d.date) : <Skeleton className="h-4 w-48" />}</div>
          <h1 className="mt-1 text-2xl font-semibold text-ink">{d ? d.headline : <Skeleton className="h-8 w-64" />}</h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="md:hidden"><MicButton /></div>
          <Button variant="secondary" size="md" onClick={() => nav("/assistent")}><MessageSquareText className="h-4 w-4" />Assistent</Button>
          <Button variant="ghost" size="icon" aria-label="Übersicht anpassen" onClick={() => setCustomize(true)}><Settings2 className="h-4 w-4" /></Button>
        </div>
      </div>

      {visible("summary") && (
        <section className="mt-6 rounded-md border border-line bg-surface px-5 py-4">
          <div className="text-xs font-medium text-ink-3 mb-1.5">Tageslage</div>
          {d ? <p className="text-md text-ink leading-relaxed max-w-[75ch]">{d.summary}</p> : <Skeleton className="h-6 w-full" />}
          <div className="mt-4 flex flex-wrap gap-1.5 border-t border-line pt-3">
            <Button variant="ghost" size="sm" onClick={() => create.newTask()}><CheckSquare className="h-4 w-4" />Aufgabe</Button>
            <Button variant="ghost" size="sm" onClick={() => create.newEvent()}><CalendarDays className="h-4 w-4" />Termin</Button>
            <Button variant="ghost" size="sm" onClick={() => create.newProject()}><FolderKanban className="h-4 w-4" />Projekt</Button>
          </div>
        </section>
      )}

      {visible("today_events") && (
        <section className="mt-8">
          <div className="flex items-baseline justify-between mb-3">
            <h2 className="text-sm font-semibold">Heute</h2>
            <span className="text-sm text-ink-3">{d ? (d.events_today.length === 1 ? "1 Termin" : `${d.events_today.length} Termine`) : ""}</span>
          </div>
          <div className="rounded-md border border-line bg-surface px-4 pt-4 pb-3 overflow-x-auto">
            <div className="min-w-[560px]">{d ? <DayStrip events={d.events_today} /> : <Skeleton className="h-16 w-full" />}</div>
          </div>
        </section>
      )}

      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-6 min-w-0">{d ? main.map((k) => <div key={k}>{blocks[k]}</div>) : <Skeleton className="h-64 w-full" />}</div>
        <div className="space-y-6">{d ? side.map((k) => <div key={k}>{blocks[k]}</div>) : <Skeleton className="h-64 w-full" />}</div>
      </div>
      <CustomizeDialog open={customize} onOpenChange={setCustomize} widgets={widgets} />
    </div>
  );
}
