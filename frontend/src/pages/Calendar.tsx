import { useMutation, useQuery } from "@tanstack/react-query";
import { addDays, addMonths, endOfMonth, isSameDay, isSameMonth, startOfDay, startOfMonth, startOfWeek } from "date-fns";
import { ChevronLeft, ChevronRight, Filter, Plus, Repeat } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import * as RPopover from "@radix-ui/react-popover";
import { useCreate } from "@/components/dialogs";
import { useToast } from "@/components/toast";
import { Button, Empty, Segmented, Spinner } from "@/components/ui";
import { api, qs } from "@/lib/api";
import { fmt, isoDate, time, toDate } from "@/lib/format";
import type { CalEvent } from "@/lib/types";
import { cn, saveStorage, storage } from "@/lib/utils";
import { useCategories, useInvalidate } from "@/hooks/queries";

type View = "day" | "week" | "month" | "list";
const HOUR = 48;

function range(view: View, d: Date): [Date, Date] {
  if (view === "day") return [startOfDay(d), addDays(startOfDay(d), 1)];
  if (view === "week") { const s = startOfWeek(d, { weekStartsOn: 1 }); return [s, addDays(s, 7)]; }
  if (view === "month") { const s = startOfWeek(startOfMonth(d), { weekStartsOn: 1 }); return [s, addDays(s, 42)]; }
  return [startOfDay(d), addDays(startOfDay(d), 60)];
}
const color = (e: CalEvent) => e.color ?? (e.source === "google" ? "#4C8DF6" : "#5B8DEF");

/** Überlappende Termine nebeneinander anordnen */
function layout(evs: CalEvent[]) {
  const sorted = [...evs].sort((a, b) => a.start.localeCompare(b.start));
  const out: { e: CalEvent; col: number; cols: number }[] = [];
  let cluster: { e: CalEvent; col: number; cols: number }[] = [];
  let clusterEnd = "";
  const flush = () => { const n = Math.max(...cluster.map((c) => c.col)) + 1; cluster.forEach((c) => (c.cols = n)); out.push(...cluster); cluster = []; };
  for (const e of sorted) {
    if (cluster.length && e.start >= clusterEnd) flush();
    const used = new Set(cluster.filter((c) => c.e.end > e.start).map((c) => c.col));
    let col = 0; while (used.has(col)) col++;
    cluster.push({ e, col, cols: 1 });
    clusterEnd = clusterEnd > e.end && cluster.length > 1 ? clusterEnd : e.end;
  }
  if (cluster.length) flush();
  return out;
}

function TimeGrid({ days, events, onMove }: { days: Date[]; events: CalEvent[]; onMove: (e: CalEvent, start: Date, end: Date) => void }) {
  const { newEvent, editEvent } = useCreate();
  const scroller = useRef<HTMLDivElement>(null);
  const cols = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<{ id: string; dx: number; dy: number; resize: boolean } | null>(null);
  const [now, setNow] = useState(new Date());
  useEffect(() => { scroller.current?.scrollTo({ top: HOUR * 7 }); const t = setInterval(() => setNow(new Date()), 60000); return () => clearInterval(t); }, []);
  const allDay = events.filter((e) => e.all_day);

  const startDrag = (ev: React.PointerEvent, e: CalEvent, resize: boolean) => {
    if (!e.editable || (e.recurring && e.source === "internal")) { editEvent(e); return; }
    ev.preventDefault(); ev.stopPropagation();
    const x0 = ev.clientX, y0 = ev.clientY;
    const colW = (cols.current?.clientWidth ?? 700) / days.length;
    let st = { dx: 0, dy: 0 };
    const move = (m: PointerEvent) => { st = { dx: days.length > 1 && !resize ? Math.round((m.clientX - x0) / colW) : 0, dy: Math.round((m.clientY - y0) / HOUR * 4) * 15 }; setDrag({ id: e.id, ...st, resize }); };
    const up = () => {
      window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up);
      setDrag(null);
      if (!st.dx && !st.dy) return editEvent(e);
      const s = toDate(e.start), en = toDate(e.end);
      if (resize) { const ne = new Date(en.getTime() + st.dy * 60000); if (ne > s) onMove(e, s, ne); return; }
      const shift = st.dx * 86400000 + st.dy * 60000;
      onMove(e, new Date(s.getTime() + shift), new Date(en.getTime() + shift));
    };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
  };

  return (
    <div className="rounded-md border border-line bg-surface overflow-hidden">
      <div className="grid border-b border-line" style={{ gridTemplateColumns: `52px repeat(${days.length}, minmax(0,1fr))` }}>
        <div />
        {days.map((d) => (
          <div key={d.toISOString()} className="px-2 py-2 border-l border-line">
            <div className={cn("text-xs", isSameDay(d, now) ? "text-accent-ink" : "text-ink-3")}>{fmt(d, "EEE")}</div>
            <div className={cn("text-lg font-semibold tnum", isSameDay(d, now) ? "text-accent-ink" : "text-ink")}>{fmt(d, "d")}</div>
            {allDay.filter((e) => toDate(e.start_date!) <= d && d <= toDate(e.end_date!)).map((e) => (
              <button key={e.id} onClick={() => editEvent(e)} className="mt-1 w-full truncate rounded-sm px-1.5 text-left text-xs h-5 text-ink" style={{ background: color(e) + "33" }}>{e.title}</button>
            ))}
          </div>
        ))}
      </div>
      <div ref={scroller} className="relative overflow-y-auto h-[calc(100dvh-260px)] min-h-[420px]">
        <div className="grid relative" style={{ gridTemplateColumns: `52px repeat(${days.length}, minmax(0,1fr))`, height: HOUR * 24 }}>
          <div>{Array.from({ length: 24 }, (_, h) => <div key={h} className="text-2xs text-ink-3 tnum text-right pr-2 -translate-y-1.5" style={{ height: HOUR }}>{h ? `${String(h).padStart(2, "0")}:00` : ""}</div>)}</div>
          <div ref={cols} className="contents">
            {days.map((d) => {
              const dayEvs = events.filter((e) => !e.all_day && toDate(e.start) < addDays(d, 1) && toDate(e.end) > d);
              return (
                <div key={d.toISOString()} className="relative border-l border-line"
                  onClick={(ev) => {
                    const r = (ev.currentTarget as HTMLElement).getBoundingClientRect();
                    const mins = Math.floor((ev.clientY - r.top) / HOUR * 2) * 30;
                    const s = new Date(d); s.setMinutes(mins); newEvent({ start: s });
                  }}>
                  {Array.from({ length: 24 }, (_, h) => <div key={h} className="border-b border-line/60" style={{ height: HOUR }} />)}
                  {isSameDay(d, now) && <div className="absolute inset-x-0 h-px bg-danger z-10 pointer-events-none" style={{ top: (now.getHours() * 60 + now.getMinutes()) / 60 * HOUR }} />}
                  {layout(dayEvs).map(({ e, col, cols: n }) => {
                    const s = toDate(e.start) < d ? d : toDate(e.start);
                    const en = toDate(e.end) > addDays(d, 1) ? addDays(d, 1) : toDate(e.end);
                    const top = (s.getHours() * 60 + s.getMinutes()) / 60 * HOUR;
                    const h = Math.max(20, (en.getTime() - s.getTime()) / 3600000 * HOUR);
                    const dg = drag?.id === e.id ? drag : null;
                    return (
                      <div key={e.id} onPointerDown={(ev) => startDrag(ev, e, false)} onClick={(ev) => ev.stopPropagation()}
                        className={cn("absolute rounded-sm px-1.5 py-0.5 overflow-hidden text-left select-none border-l-2 cursor-pointer touch-none", dg && "z-20 shadow-pop opacity-90")}
                        style={{ top: top + (dg && !dg.resize ? dg.dy / 60 * HOUR : 0), height: h + (dg?.resize ? dg.dy / 60 * HOUR : 0), left: `calc(${(col / n) * 100}% + 2px)`, width: `calc(${100 / n}% - 4px)`,
                          transform: dg ? `translateX(${dg.dx * 100}%)` : undefined, background: color(e) + "26", borderLeftColor: color(e) }}>
                        <div className="text-xs font-medium text-ink truncate flex items-center gap-1">{e.recurring && <Repeat className="h-3 w-3 shrink-0 text-ink-3" />}{e.title}</div>
                        {h > 30 && <div className="text-2xs text-ink-2 tnum">{time(e.start)}–{time(e.end)}</div>}
                        {e.editable && !e.recurring && <div onPointerDown={(ev) => startDrag(ev, e, true)} className="absolute bottom-0 inset-x-0 h-1.5 cursor-ns-resize" />}
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

function MonthGrid({ anchor, events, onDay }: { anchor: Date; events: CalEvent[]; onDay: (d: Date) => void }) {
  const { editEvent } = useCreate();
  const start = startOfWeek(startOfMonth(anchor), { weekStartsOn: 1 });
  const days = Array.from({ length: 42 }, (_, i) => addDays(start, i)).filter((d, i) => i < 35 || d <= endOfMonth(anchor) || i % 7 !== 0 || isSameMonth(d, anchor));
  return (
    <div className="rounded-md border border-line bg-surface overflow-hidden">
      <div className="grid grid-cols-7 border-b border-line">{["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"].map((d) => <div key={d} className="px-2 py-1.5 text-xs text-ink-3">{d}</div>)}</div>
      <div className="grid grid-cols-7">
        {days.map((d) => {
          const evs = events.filter((e) => toDate(e.start) < addDays(d, 1) && toDate(e.end) > d);
          return (
            <div key={d.toISOString()} className={cn("min-h-[92px] border-b border-r border-line/70 p-1 cursor-pointer hover:bg-raised/40", !isSameMonth(d, anchor) && "bg-canvas/40")} onClick={() => onDay(d)}>
              <div className={cn("text-xs tnum mb-0.5 px-1", isSameDay(d, new Date()) ? "text-accent-ink font-semibold" : isSameMonth(d, anchor) ? "text-ink-2" : "text-ink-3")}>{fmt(d, "d")}</div>
              {evs.slice(0, 3).map((e) => (
                <button key={e.id} onClick={(ev) => { ev.stopPropagation(); editEvent(e); }} className="w-full flex items-center gap-1 truncate rounded-sm px-1 text-left text-2xs h-[18px] text-ink hover:bg-raised">
                  <span className="h-1.5 w-1.5 rounded-full shrink-0" style={{ background: color(e) }} />{!e.all_day && <span className="text-ink-3 tnum">{time(e.start)}</span>}<span className="truncate">{e.title}</span>
                </button>
              ))}
              {evs.length > 3 && <div className="text-2xs text-ink-3 px-1">+{evs.length - 3} weitere</div>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function CalendarPage() {
  const [params, setParams] = useSearchParams();
  const mobile = typeof window !== "undefined" && window.innerWidth < 768;
  const [view, setView] = useState<View>(storage("mosi.calView", mobile ? "day" : "week"));
  const anchor = params.get("datum") ? toDate(params.get("datum")!) : new Date();
  const setAnchor = (d: Date) => setParams({ datum: isoDate(d) });
  const [hidden, setHidden] = useState<string[]>(storage("mosi.calHidden", []));
  const [from, to] = range(view, anchor);
  const cats = useCategories();
  const google = useQuery({ queryKey: ["google-status"], queryFn: () => api.get<any>("/api/google/status") });
  const evs = useQuery({ queryKey: ["events", from.toISOString(), to.toISOString()], queryFn: () => api.get<CalEvent[]>(`/api/events?${qs({ start: from.toISOString(), end: to.toISOString() })}`), placeholderData: (p) => p });
  const create = useCreate();
  const toast = useToast();
  const inv = useInvalidate();
  useEffect(() => saveStorage("mosi.calView", view), [view]);
  useEffect(() => saveStorage("mosi.calHidden", hidden), [hidden]);

  const move = useMutation({
    mutationFn: ({ e, s, en }: { e: CalEvent; s: Date; en: Date }) => api.patch<{ conflicts: CalEvent[] }>(`/api/events/${e.event_id}`, { start: s.toISOString(), end: en.toISOString() }),
    onSuccess: (r) => { inv(); r.conflicts?.length ? toast.info(`Verschoben – überschneidet sich mit „${r.conflicts[0].title}“.`) : toast.ok("Termin verschoben"); },
    onError: (e) => { inv(); toast.error(e); },
  });

  const filtered = useMemo(() => (evs.data ?? []).filter((e) => {
    const key = e.source === "google" ? `g:${e.google_calendar_id}` : "internal";
    return !hidden.includes(key) && !(e.category_id && hidden.includes(`c:${e.category_id}`));
  }), [evs.data, hidden]);

  const step = (dir: number) => setAnchor(view === "day" ? addDays(anchor, dir) : view === "week" ? addDays(anchor, 7 * dir) : view === "month" ? addMonths(anchor, dir) : addDays(anchor, 30 * dir));
  const title = view === "day" ? fmt(anchor, "EEEE, d. MMMM yyyy") : view === "week" ? `KW ${fmt(from, "I")} · ${fmt(from, "d. MMM")} – ${fmt(addDays(to, -1), "d. MMM yyyy")}` : view === "month" ? fmt(anchor, "MMMM yyyy") : "Ab " + fmt(from, "d. MMMM");
  const sources = [{ key: "internal", label: "MOSI-Kalender", color: "#5B8DEF" }, ...((google.data?.calendars ?? []).filter((c: any) => c.selected).map((c: any) => ({ key: `g:${c.google_id}`, label: `Google: ${c.summary}`, color: c.color })))];
  const toggle = (k: string) => setHidden((h) => (h.includes(k) ? h.filter((x) => x !== k) : [...h, k]));

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <h1 className="text-xl font-semibold mr-auto min-w-0 truncate">{title}</h1>
        <Button variant="secondary" size="sm" onClick={() => setAnchor(new Date())}>Heute</Button>
        <Button variant="ghost" size="icon-sm" aria-label="Zurück" onClick={() => step(-1)}><ChevronLeft className="h-4 w-4" /></Button>
        <Button variant="ghost" size="icon-sm" aria-label="Weiter" onClick={() => step(1)}><ChevronRight className="h-4 w-4" /></Button>
        <Segmented value={view} onChange={setView} options={[{ value: "day", label: "Tag" }, { value: "week", label: "Woche" }, { value: "month", label: "Monat" }, { value: "list", label: "Liste" }]} />
        <RPopover.Root>
          <RPopover.Trigger asChild><Button variant="ghost" size="sm"><Filter className="h-4 w-4" />Filter{hidden.length > 0 && <span className="text-accent-ink">({hidden.length})</span>}</Button></RPopover.Trigger>
          <RPopover.Portal><RPopover.Content align="end" sideOffset={6} className="z-50 w-64 rounded-md bg-raised p-2 shadow-pop">
            <div className="px-2 py-1 text-xs text-ink-3">Kalender</div>
            {sources.map((s) => <FilterRow key={s.key} label={s.label} color={s.color} on={!hidden.includes(s.key)} onClick={() => toggle(s.key)} />)}
            {(cats.data?.length ?? 0) > 0 && <div className="px-2 pt-2 pb-1 text-xs text-ink-3">Kategorien</div>}
            {cats.data?.map((c) => <FilterRow key={c.id} label={c.name} color={c.color} on={!hidden.includes(`c:${c.id}`)} onClick={() => toggle(`c:${c.id}`)} />)}
          </RPopover.Content></RPopover.Portal>
        </RPopover.Root>
        <Button variant="primary" size="sm" onClick={() => create.newEvent()}><Plus className="h-4 w-4" />Termin</Button>
      </div>
      {evs.isLoading ? <div className="py-20 grid place-items-center"><Spinner /></div> :
        view === "month" ? <MonthGrid anchor={anchor} events={filtered} onDay={(d) => { setView("day"); setAnchor(d); }} /> :
        view === "list" ? <ListView events={filtered} /> :
        <TimeGrid days={view === "day" ? [startOfDay(anchor)] : Array.from({ length: 7 }, (_, i) => addDays(from, i))} events={filtered} onMove={(e, s, en) => move.mutate({ e, s, en })} />}
      <p className="mt-3 text-sm text-ink-3">Klick auf eine freie Zeit erstellt einen Termin. Termine lassen sich per Ziehen verschieben und am unteren Rand in der Länge ändern. Google-Termine sind blau markiert.</p>
    </div>
  );
}

function FilterRow({ label, color, on, onClick }: { label: string; color: string; on: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} className="w-full flex items-center gap-2 h-8 px-2 rounded-sm text-sm text-ink hover:bg-surface">
      <span className="h-3 w-3 rounded-sm border" style={{ background: on ? color : "transparent", borderColor: color }} /><span className="truncate">{label}</span>
    </button>
  );
}

function ListView({ events }: { events: CalEvent[] }) {
  const { editEvent } = useCreate();
  if (!events.length) return <Empty title="Keine Termine in den nächsten 60 Tagen" />;
  const groups = events.reduce<Record<string, CalEvent[]>>((g, e) => { const k = isoDate(toDate(e.start)); (g[k] ??= []).push(e); return g; }, {});
  return (
    <div className="rounded-md border border-line bg-surface divide-y divide-line">
      {Object.entries(groups).map(([d, list]) => (
        <div key={d} className="flex flex-col sm:flex-row">
          <div className="sm:w-44 shrink-0 px-4 pt-3 sm:py-3 text-sm text-ink-2">{fmt(d, "EEEE, d. MMM")}</div>
          <div className="flex-1 py-1.5">
            {list.map((e) => (
              <button key={e.id} onClick={() => editEvent(e)} className="w-full flex items-center gap-3 px-4 py-1.5 text-left hover:bg-raised/60">
                <span className="h-2 w-2 rounded-full shrink-0" style={{ background: color(e) }} />
                <span className="w-24 text-sm text-ink-3 tnum shrink-0">{e.all_day ? "ganztägig" : `${time(e.start)}–${time(e.end)}`}</span>
                <span className="text-base text-ink truncate">{e.title}</span>
                <span className="ml-auto text-xs text-ink-3 shrink-0">{e.source === "google" ? "Google" : "MOSI"}</span>
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
