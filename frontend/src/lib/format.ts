import { format, formatDistanceToNowStrict, isToday, isTomorrow, isYesterday, parseISO } from "date-fns";
import { de } from "date-fns/locale";

export const toDate = (v: string | Date) => (typeof v === "string" ? (v.length === 10 ? parseISO(v) : new Date(v)) : v);
export const fmt = (v: string | Date, f: string) => format(toDate(v), f, { locale: de });
export const time = (v: string | Date) => fmt(v, "HH:mm");
export const dateShort = (v: string | Date) => fmt(v, "d. MMM");
export const dateLong = (v: string | Date) => fmt(v, "EEEE, d. MMMM yyyy");
export const isoDate = (d: Date) => format(d, "yyyy-MM-dd");

export function relDay(v: string | Date) {
  const d = toDate(v);
  if (isToday(d)) return "Heute";
  if (isTomorrow(d)) return "Morgen";
  if (isYesterday(d)) return "Gestern";
  const diff = Math.round((d.getTime() - Date.now()) / 86400000);
  if (diff > 0 && diff < 7) return fmt(d, "EEEE");
  return fmt(d, "d. MMM");
}

export const ago = (v: string | Date) => formatDistanceToNowStrict(toDate(v), { locale: de, addSuffix: true });

export function minutes(m: number | null | undefined) {
  if (!m) return "–";
  const h = Math.floor(m / 60), r = m % 60;
  return h ? (r ? `${h} h ${r} min` : `${h} h`) : `${r} min`;
}

export const PRIORITY: Record<string, string> = { low: "Niedrig", normal: "Normal", high: "Hoch", critical: "Kritisch" };
export const TASK_STATUS: Record<string, string> = { open: "Offen", in_progress: "In Bearbeitung", waiting: "Wartet", done: "Erledigt", archived: "Archiviert" };
export const PROJECT_STATUS: Record<string, string> = { planned: "Geplant", active: "Aktiv", paused: "Pausiert", completed: "Abgeschlossen", archived: "Archiviert" };
export const MEMORY_CATEGORY: Record<string, string> = { project: "Projektinformation", decision: "Entscheidung", planning_rule: "Planungsregel", recurring: "Wiederkehrend", goal: "Langfristiges Ziel", note: "Notiz", preference: "Vorliebe" };
export const WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"];
