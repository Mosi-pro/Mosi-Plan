import * as RPopover from "@radix-ui/react-popover";
import * as RDialog from "@radix-ui/react-dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Command } from "cmdk";
import {
  Bell, BookMarked, CalendarDays, CalendarRange, CheckSquare, FolderKanban, LayoutGrid, LogOut, Menu as MenuIcon, MessageSquare, Mic, Plus, Search,
  Settings, MessageSquareText, User as UserIcon,
} from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { ago, relDay, time } from "@/lib/format";
import type { NotificationItem, Project } from "@/lib/types";
import { cn, storage, saveStorage } from "@/lib/utils";
import { useAuth } from "@/hooks/auth";
import { useProjects, useSettings } from "@/hooks/queries";
import { useCreate } from "./dialogs";
import { MicButton, useVoice } from "./voice";
import { Button, Kbd, Menu, MenuContent, MenuItem, MenuSeparator, MenuTrigger, Tip } from "./ui";

const NAV = [
  { to: "/", label: "Übersicht", icon: LayoutGrid, end: true },
  { to: "/assistent", label: "Assistent", icon: MessageSquare },
  { to: "/kalender", label: "Kalender", icon: CalendarDays },
  { to: "/aufgaben", label: "Aufgaben", icon: CheckSquare },
  { to: "/projekte", label: "Projekte", icon: FolderKanban },
  { to: "/wochenplan", label: "Wochenplan", icon: CalendarRange },
  { to: "/gedaechtnis", label: "Gedächtnis", icon: BookMarked },
];

export function Logo({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <svg viewBox="0 0 32 32" className="h-7 w-7" aria-hidden>
        <rect width="32" height="32" rx="10" fill="rgba(255,255,255,0.14)" />
        <rect x="8" y="9" width="16" height="2.6" rx="1.3" fill="#5B8DEF" />
        <rect x="8" y="14.7" width="11" height="2.6" rx="1.3" fill="#E8EBF0" />
        <rect x="8" y="20.4" width="7" height="2.6" rx="1.3" fill="#6B7484" />
      </svg>
      <span className="text-[15px] font-semibold tracking-[-0.01em] text-ink">MOSI PLAN</span>
    </div>
  );
}

/* --------------------------------------------------------------------- Benachrichtigungen */
function Notifications() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const settings = useSettings();
  const lastSeen = useRef<number>(storage("mosi.lastNotification", 0));
  const q = useQuery({ queryKey: ["notifications"], queryFn: () => api.get<{ unread: number; items: NotificationItem[] }>("/api/notifications"), refetchInterval: 60000 });

  // Browser-Benachrichtigungen für neue Einträge (wenn erlaubt und aktiviert)
  useEffect(() => {
    const items = q.data?.items ?? [];
    if (!items.length) return;
    const maxId = Math.max(...items.map((i) => i.id));
    if (lastSeen.current && settings.data?.notifications?.browser && "Notification" in window && Notification.permission === "granted" && document.visibilityState !== "visible") {
      items.filter((i) => i.id > lastSeen.current && !i.read).slice(0, 3).forEach((i) => {
        navigator.serviceWorker?.getRegistration().then((reg) => {
          if (reg) reg.showNotification(i.title, { body: i.body, tag: `mosi-${i.id}`, icon: "/icons/icon-192.png", data: { link: i.link } });
          else new Notification(i.title, { body: i.body });
        });
      });
    }
    lastSeen.current = maxId;
    saveStorage("mosi.lastNotification", maxId);
  }, [q.data, settings.data]);

  const readAll = async () => { await api.post("/api/notifications/read-all"); qc.invalidateQueries({ queryKey: ["notifications"] }); };
  const unread = q.data?.unread ?? 0;
  return (
    <RPopover.Root>
      <RPopover.Trigger asChild>
        <Button variant="secondary" size="icon" aria-label={`Benachrichtigungen${unread ? ` (${unread} ungelesen)` : ""}`} className="relative">
          <Bell className="h-4 w-4" />
          {unread > 0 && <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-accent ring-2 ring-canvas" />}
        </Button>
      </RPopover.Trigger>
      <RPopover.Portal>
        <RPopover.Content align="end" sideOffset={10} className="z-50 w-[min(380px,calc(100vw-24px))] rounded-md shadow-pop glass-pop animate-pop-in">
          <div className="flex items-center justify-between px-4 h-11 border-b border-line">
            <span className="text-sm font-semibold">Benachrichtigungen</span>
            {unread > 0 && <button className="text-sm text-accent-ink hover:underline" onClick={readAll}>Alle gelesen</button>}
          </div>
          <div className="max-h-[420px] overflow-y-auto">
            {(q.data?.items ?? []).length === 0 && <p className="px-4 py-8 text-center text-sm text-ink-3">Keine Benachrichtigungen.</p>}
            {q.data?.items.slice(0, 30).map((n) => (
              <RPopover.Close asChild key={n.id}>
                <button className="w-full text-left flex gap-3 px-4 py-3 border-b border-line/60 last:border-0 hover:bg-surface"
                  onClick={async () => { await api.post(`/api/notifications/${n.id}/read`); qc.invalidateQueries({ queryKey: ["notifications"] }); if (n.link) nav(n.link); }}>
                  <span className={cn("mt-1.5 h-1.5 w-1.5 rounded-full shrink-0", n.read ? "bg-transparent" : n.type === "sync_error" ? "bg-danger" : "bg-accent")} />
                  <span className="min-w-0">
                    <span className="block text-sm text-ink">{n.title}</span>
                    {n.body && <span className="block text-sm text-ink-3 line-clamp-2">{n.body}</span>}
                    <span className="block text-xs text-ink-3 mt-0.5">{ago(n.created_at)}</span>
                  </span>
                </button>
              </RPopover.Close>
            ))}
          </div>
        </RPopover.Content>
      </RPopover.Portal>
    </RPopover.Root>
  );
}

/* --------------------------------------------------------------------- Befehlsleiste */
interface SearchRes { projects: { id: number; name: string; color: string; status: string }[]; tasks: { id: number; title: string; status: string; due_date: string | null }[]; events: { id: string; title: string; start: string; all_day: boolean; date: string; source: string }[]; memory: { id: number; content: string }[] }

export function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const nav = useNavigate();
  const create = useCreate();
  const voice = useVoice();
  const [q, setQ] = useState("");
  const [deb, setDeb] = useState("");
  useEffect(() => { const t = setTimeout(() => setDeb(q.trim()), 140); return () => clearTimeout(t); }, [q]);
  useEffect(() => { if (!open) setQ(""); }, [open]);
  const res = useQuery({ queryKey: ["search", deb], queryFn: () => api.get<SearchRes>(`/api/search?q=${encodeURIComponent(deb)}`), enabled: open && deb.length >= 2, placeholderData: (p) => p });
  const run = (fn: () => void) => { onOpenChange(false); setTimeout(fn, 0); };
  const item = "flex items-center gap-3 h-9 px-3 rounded text-sm text-ink-2 cursor-pointer data-[selected=true]:bg-surface data-[selected=true]:text-ink";
  const group = "px-1.5 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:pt-3 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:text-ink-3";
  const data = deb.length >= 2 ? res.data : undefined;
  return (
    <RDialog.Root open={open} onOpenChange={onOpenChange}>
      <RDialog.Portal>
        <RDialog.Overlay className="fixed inset-0 z-50 bg-black/45 backdrop-blur-sm animate-fade-in" />
        <RDialog.Content className="fixed z-50 left-1/2 top-[10vh] -translate-x-1/2 w-[min(640px,calc(100vw-24px))] rounded-lg shadow-pop glass-pop animate-pop-in overflow-hidden">
          <RDialog.Title className="sr-only">Suche und Befehle</RDialog.Title>
          <RDialog.Description className="sr-only">Projekte, Aufgaben und Termine suchen oder Aktionen ausführen</RDialog.Description>
          <Command shouldFilter={!data} loop>
            <div className="flex items-center gap-3 px-4 border-b border-line">
              <Search className="h-4 w-4 text-ink-3" />
              <Command.Input value={q} onValueChange={setQ} autoFocus placeholder="Suchen, Befehl eingeben oder Assistenten fragen …" className="h-12 flex-1 bg-transparent text-md text-ink placeholder:text-ink-3 outline-none" />
              <Kbd>Esc</Kbd>
            </div>
            <Command.List className="max-h-[min(440px,60vh)] overflow-y-auto pb-2">
              <Command.Empty className="px-4 py-6 text-sm text-ink-3">Keine Treffer.</Command.Empty>
              {q.trim().length > 2 && (
                <Command.Group heading="Assistent" className={group} forceMount>
                  <Command.Item value={`__ask ${q}`} forceMount className={item} onSelect={() => run(() => nav(`/assistent?q=${encodeURIComponent(q.trim())}`))}>
                    <MessageSquareText className="h-4 w-4 text-accent" /><span className="truncate">„{q.trim()}“</span>
                  </Command.Item>
                </Command.Group>
              )}
              {data && data.projects.length > 0 && (
                <Command.Group heading="Projekte" className={group}>
                  {data.projects.map((p) => (
                    <Command.Item key={p.id} value={`p${p.id} ${p.name}`} className={item} onSelect={() => run(() => nav(`/projekte/${p.id}`))}>
                      <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: p.color }} />{p.name}
                    </Command.Item>
                  ))}
                </Command.Group>
              )}
              {data && data.tasks.length > 0 && (
                <Command.Group heading="Aufgaben" className={group}>
                  {data.tasks.map((t) => (
                    <Command.Item key={t.id} value={`t${t.id} ${t.title}`} className={item} onSelect={() => run(() => nav(`/aufgaben?aufgabe=${t.id}`))}>
                      <CheckSquare className="h-4 w-4 text-ink-3" /><span className={cn("truncate", t.status === "done" && "line-through text-ink-3")}>{t.title}</span>
                      {t.due_date && <span className="ml-auto text-xs text-ink-3">{relDay(t.due_date)}</span>}
                    </Command.Item>
                  ))}
                </Command.Group>
              )}
              {data && data.events.length > 0 && (
                <Command.Group heading="Termine" className={group}>
                  {data.events.map((e) => (
                    <Command.Item key={e.id} value={`e${e.id} ${e.title}`} className={item} onSelect={() => run(() => nav(`/kalender?datum=${e.date}`))}>
                      <CalendarDays className="h-4 w-4 text-ink-3" /><span className="truncate">{e.title}</span>
                      <span className="ml-auto text-xs text-ink-3 tnum">{relDay(e.start)}{!e.all_day && `, ${time(e.start)}`}</span>
                    </Command.Item>
                  ))}
                </Command.Group>
              )}
              <Command.Group heading="Aktionen" className={group}>
                <Command.Item className={item} onSelect={() => run(() => create.newTask())}><Plus className="h-4 w-4 text-ink-3" />Neue Aufgabe</Command.Item>
                <Command.Item className={item} onSelect={() => run(() => create.newEvent())}><CalendarDays className="h-4 w-4 text-ink-3" />Neuer Termin</Command.Item>
                <Command.Item className={item} onSelect={() => run(() => create.newProject())}><FolderKanban className="h-4 w-4 text-ink-3" />Neues Projekt</Command.Item>
                <Command.Item className={item} onSelect={() => run(() => voice.start())}><Mic className="h-4 w-4 text-ink-3" />Sprachaufnahme starten</Command.Item>
                <Command.Item className={item} onSelect={() => run(() => nav("/wochenplan"))}><CalendarRange className="h-4 w-4 text-ink-3" />Wochenplan öffnen</Command.Item>
              </Command.Group>
              <Command.Group heading="Navigation" className={group}>
                {[...NAV, { to: "/einstellungen", label: "Einstellungen", icon: Settings }].map((n) => (
                  <Command.Item key={n.to} value={`Gehe zu ${n.label}`} className={item} onSelect={() => run(() => nav(n.to))}><n.icon className="h-4 w-4 text-ink-3" />{n.label}</Command.Item>
                ))}
              </Command.Group>
            </Command.List>
          </Command>
        </RDialog.Content>
      </RDialog.Portal>
    </RDialog.Root>
  );
}

/* --------------------------------------------------------------------- Kopfzeile (schwebende Glasleiste) */
function Topbar({ onSearch, onMenu }: { onSearch: () => void; onMenu: () => void }) {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const create = useCreate();
  return (
    <header className="sticky top-0 z-30 px-3 md:px-6 pt-3 md:pt-4">
      <div className="mx-auto max-w-[1360px] flex items-center gap-2">
        <button onClick={onMenu} className="lg:hidden" aria-label="Menü öffnen"><Logo /></button>
        <div className="hidden lg:flex"><Logo /></div>
        {/* Hauptnavigation als Pille */}
        <nav aria-label="Hauptnavigation" className="hidden lg:flex mx-auto glass rounded-full border border-white/[0.12] p-1.5 gap-1">
          {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.end} aria-label={n.label} title={n.label}
                className={({ isActive }) => cn("flex items-center gap-2 h-10 rounded-full transition-colors", isActive ? "bg-white text-[#16130f] px-4" : "w-10 justify-center text-ink-2 hover:text-ink hover:bg-white/10")}>
                {({ isActive }) => (<><n.icon className="h-[18px] w-[18px]" />{isActive && <span className="text-sm font-medium">{n.label}</span>}</>)}
              </NavLink>
          ))}
        </nav>
        <div className="ml-auto lg:ml-0 flex items-center gap-1.5">
          <Button variant="secondary" size="icon" aria-label="Suchen (Strg+K)" onClick={onSearch}><Search className="h-4 w-4" /></Button>
          <Menu>
            <MenuTrigger asChild><Button variant="secondary" size="icon" aria-label="Neu erstellen" className="hidden md:inline-flex"><Plus className="h-4 w-4" /></Button></MenuTrigger>
            <MenuContent>
              <MenuItem icon={CheckSquare} onSelect={() => create.newTask()}>Neue Aufgabe</MenuItem>
              <MenuItem icon={CalendarDays} onSelect={() => create.newEvent()}>Neuer Termin</MenuItem>
              <MenuItem icon={FolderKanban} onSelect={() => create.newProject()}>Neues Projekt</MenuItem>
            </MenuContent>
          </Menu>
          <Notifications />
          <div className="hidden md:block"><MicButton label={false} className="h-10 w-10" /></div>
          <Menu>
            <MenuTrigger asChild>
              <button className="h-10 w-10 rounded-full overflow-hidden bg-white/10 border border-white/[0.14] grid place-items-center text-sm font-semibold text-ink" aria-label="Profil">
                {user?.has_avatar ? <img src="/api/auth/avatar" alt="" className="h-full w-full object-cover" /> : (user?.display_name || user?.username || "?").slice(0, 1).toUpperCase()}
              </button>
            </MenuTrigger>
            <MenuContent>
              <div className="px-3 py-2"><div className="text-sm text-ink">{user?.display_name || user?.username}</div><div className="text-xs text-ink-3">@{user?.username}</div></div>
              <MenuSeparator />
              <MenuItem icon={UserIcon} onSelect={() => nav("/einstellungen/profil")}>Profil</MenuItem>
              <MenuItem icon={Settings} onSelect={() => nav("/einstellungen")}>Einstellungen</MenuItem>
              <MenuSeparator />
              <MenuItem icon={LogOut} onSelect={logout}>Abmelden</MenuItem>
            </MenuContent>
          </Menu>
        </div>
      </div>
    </header>
  );
}

/* --------------------------------------------------------------------- Mobiles Dock (schwebend) */
function MobileNav({ onMore }: { onMore: () => void }) {
  const item = (to: string, label: string, Icon: React.ComponentType<{ className?: string }>, end = false) => (
    <NavLink to={to} end={end} aria-label={label} className={({ isActive }) => cn("flex flex-1 flex-col items-center justify-center gap-0.5 h-12 rounded-full text-[10px] font-medium transition-colors", isActive ? "bg-white text-[#16130f]" : "text-ink-2")}>
      <Icon className="h-5 w-5" /><span>{label}</span>
    </NavLink>
  );
  return (
    <nav className="lg:hidden fixed bottom-0 inset-x-0 z-40 px-3 pb-3 safe-bottom" aria-label="Mobile Navigation">
      <div className="glass glass-pop mx-auto max-w-md flex items-center gap-1 rounded-full border border-white/[0.14] p-1.5 shadow-pop">
        {item("/", "Heute", LayoutGrid, true)}
        {item("/kalender", "Kalender", CalendarDays)}
        <div className="flex items-center justify-center px-1"><MicButton size="lg" className="h-14 w-14" /></div>
        {item("/aufgaben", "Aufgaben", CheckSquare)}
        <button onClick={onMore} className="flex flex-1 flex-col items-center justify-center gap-0.5 h-12 rounded-full text-[10px] font-medium text-ink-2" aria-label="Mehr">
          <MenuIcon className="h-5 w-5" /><span>Mehr</span>
        </button>
      </div>
    </nav>
  );
}

function MoreSheet({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const projects = useProjects("active");
  return (
    <RDialog.Root open={open} onOpenChange={onOpenChange}>
      <RDialog.Portal>
        <RDialog.Overlay className="fixed inset-0 z-50 bg-black/45 backdrop-blur-sm animate-fade-in" />
        <RDialog.Content className="fixed inset-x-0 bottom-0 z-50 max-h-[85dvh] overflow-y-auto rounded-t-lg shadow-pop glass-pop animate-pop-in safe-bottom p-4">
          <RDialog.Title className="sr-only">Navigation</RDialog.Title>
          <RDialog.Description className="sr-only">Alle Bereiche</RDialog.Description>
          <div className="mx-auto mb-4 h-1 w-10 rounded-full bg-white/25" />
          <div className="grid grid-cols-3 gap-2">
            {[...NAV, { to: "/einstellungen", label: "Einstellungen", icon: Settings, end: false }].map((n) => (
              <NavLink key={n.to} to={n.to} end={n.end} onClick={() => onOpenChange(false)}
                className={({ isActive }) => cn("flex flex-col items-center justify-center gap-2 h-24 rounded-md border border-white/[0.10] text-sm", isActive ? "bg-white text-[#16130f]" : "bg-white/[0.06] text-ink")}>
                <n.icon className="h-6 w-6" />{n.label}
              </NavLink>
            ))}
          </div>
          {(projects.data?.length ?? 0) > 0 && (
            <div className="mt-5">
              <div className="px-1 mb-2 text-sm text-ink-3">Aktive Projekte</div>
              <div className="space-y-1.5">
                {projects.data!.slice(0, 8).map((p: Project) => (
                  <NavLink key={p.id} to={`/projekte/${p.id}`} onClick={() => onOpenChange(false)} className="flex items-center gap-3 h-12 px-4 rounded-full bg-white/[0.06] border border-white/[0.08] text-base">
                    <span className="h-2.5 w-2.5 rounded-full" style={{ background: p.color }} /><span className="truncate flex-1">{p.name}</span><span className="text-sm text-ink-3 tnum">{p.progress} %</span>
                  </NavLink>
                ))}
              </div>
            </div>
          )}
        </RDialog.Content>
      </RDialog.Portal>
    </RDialog.Root>
  );
}

export function AppLayout({ children }: { children?: ReactNode }) {
  const [cmd, setCmd] = useState(false);
  const [more, setMore] = useState(false);
  const loc = useLocation();
  const create = useCreate();
  useEffect(() => setMore(false), [loc.pathname]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = /input|textarea|select/i.test((e.target as HTMLElement)?.tagName) || (e.target as HTMLElement)?.isContentEditable;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setCmd((o) => !o); }
      else if (!typing && !e.ctrlKey && !e.metaKey && !e.altKey && e.key.toLowerCase() === "n" && !document.querySelector("[role=dialog]")) { e.preventDefault(); create.newTask(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [create]);
  return (
    <div className="min-h-full flex flex-col">
      <div className="backdrop" aria-hidden />
      <Topbar onSearch={() => setCmd(true)} onMenu={() => setMore(true)} />
      <main className="flex-1 px-4 md:px-6 pt-5 md:pt-8 pb-32 lg:pb-12 w-full max-w-[1360px] mx-auto">{children ?? <Outlet />}</main>
      <MobileNav onMore={() => setMore(true)} />
      <MoreSheet open={more} onOpenChange={setMore} />
      <CommandPalette open={cmd} onOpenChange={setCmd} />
    </div>
  );
}

export const Tooltipped = Tip;
