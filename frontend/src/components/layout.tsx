import * as RPopover from "@radix-ui/react-popover";
import * as RDialog from "@radix-ui/react-dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Command } from "cmdk";
import {
  Bell, BookMarked, CalendarDays, CalendarRange, CheckSquare, FolderKanban, LayoutGrid, LogOut, Menu as MenuIcon, MessageSquare, Mic, Plus, Search,
  Settings, MessageSquareText, User as UserIcon, X,
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
        <rect width="32" height="32" rx="8" fill="#1D2635" />
        <rect x="8" y="9" width="16" height="2.6" rx="1.3" fill="#5B8DEF" />
        <rect x="8" y="14.7" width="11" height="2.6" rx="1.3" fill="#E8EBF0" />
        <rect x="8" y="20.4" width="7" height="2.6" rx="1.3" fill="#6B7484" />
      </svg>
      <span className="text-[15px] font-semibold tracking-[-0.01em] text-ink">MOSI PLAN</span>
    </div>
  );
}

function NavItem({ to, label, icon: Icon, end, onClick }: { to: string; label: string; icon: React.ComponentType<{ className?: string }>; end?: boolean; onClick?: () => void }) {
  return (
    <NavLink to={to} end={end} onClick={onClick}
      className={({ isActive }) => cn("group flex items-center gap-2.5 h-8 px-2.5 rounded text-[13.5px] font-medium transition-colors",
        isActive ? "bg-raised text-ink" : "text-ink-2 hover:text-ink hover:bg-surface")}>
      {({ isActive }) => (<><Icon className={cn("h-4 w-4", isActive ? "text-accent" : "text-ink-3 group-hover:text-ink-2")} />{label}</>)}
    </NavLink>
  );
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const projects = useProjects("active");
  const { newTask } = useCreate();
  return (
    <div className="flex h-full flex-col">
      <div className="px-4 h-14 flex items-center"><Logo /></div>
      <div className="px-3">
        <Button variant="subtle" className="w-full justify-start text-ink-2" onClick={() => { newTask(); onNavigate?.(); }}>
          <Plus className="h-4 w-4" />Neue Aufgabe<span className="ml-auto"><Kbd>N</Kbd></span>
        </Button>
      </div>
      <nav className="mt-4 px-3 space-y-0.5" aria-label="Hauptnavigation">
        {NAV.map((n) => <NavItem key={n.to} {...n} onClick={onNavigate} />)}
      </nav>
      <div className="mt-6 px-3 flex-1 overflow-y-auto">
        <div className="px-2.5 mb-1.5 text-xs font-medium text-ink-3">Aktive Projekte</div>
        <div className="space-y-0.5">
          {projects.data?.slice(0, 12).map((p: Project) => (
            <NavLink key={p.id} to={`/projekte/${p.id}`} onClick={onNavigate}
              className={({ isActive }) => cn("flex items-center gap-2.5 h-7 px-2.5 rounded text-sm", isActive ? "bg-raised text-ink" : "text-ink-2 hover:bg-surface hover:text-ink")}>
              <span className="h-2 w-2 rounded-[3px] shrink-0" style={{ background: p.color }} />
              <span className="truncate flex-1">{p.name}</span>
              {p.task_overdue > 0 && <span className="tnum text-2xs text-danger">{p.task_overdue}</span>}
            </NavLink>
          ))}
          {projects.data?.length === 0 && <p className="px-2.5 text-sm text-ink-3">Noch keine aktiven Projekte.</p>}
        </div>
      </div>
      <div className="p-3 border-t border-line">
        <NavItem to="/einstellungen" label="Einstellungen" icon={Settings} onClick={onNavigate} />
      </div>
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
        <Button variant="ghost" size="icon" aria-label={`Benachrichtigungen${unread ? ` (${unread} ungelesen)` : ""}`} className="relative">
          <Bell className="h-4 w-4" />
          {unread > 0 && <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-accent ring-2 ring-canvas" />}
        </Button>
      </RPopover.Trigger>
      <RPopover.Portal>
        <RPopover.Content align="end" sideOffset={8} className="z-50 w-[min(380px,calc(100vw-24px))] rounded-md bg-raised shadow-pop animate-pop-in">
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
        <RDialog.Overlay className="fixed inset-0 z-50 bg-black/55 animate-fade-in" />
        <RDialog.Content className="fixed z-50 left-1/2 top-[10vh] -translate-x-1/2 w-[min(640px,calc(100vw-24px))] rounded-lg bg-raised shadow-pop animate-pop-in overflow-hidden">
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

/* --------------------------------------------------------------------- Kopfzeile */
function Topbar({ onSearch, onMenu }: { onSearch: () => void; onMenu: () => void }) {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const create = useCreate();
  return (
    <header className="sticky top-0 z-30 flex items-center gap-2 h-14 px-4 md:px-6 bg-canvas/85 backdrop-blur border-b border-line">
      <Button variant="ghost" size="icon" className="md:hidden -ml-2" aria-label="Menü öffnen" onClick={onMenu}><MenuIcon className="h-5 w-5" /></Button>
      <Logo className="md:hidden" />
      <button onClick={onSearch} className="hidden md:flex items-center gap-2.5 h-9 w-full max-w-[420px] px-3 rounded border border-line bg-surface text-sm text-ink-3 hover:border-line-strong transition-colors">
        <Search className="h-4 w-4" />Suchen oder Befehl eingeben<span className="ml-auto flex gap-1"><Kbd>Strg</Kbd><Kbd>K</Kbd></span>
      </button>
      <div className="ml-auto flex items-center gap-1">
        <Button variant="ghost" size="icon" className="md:hidden" aria-label="Suchen" onClick={onSearch}><Search className="h-4 w-4" /></Button>
        <Menu>
          <MenuTrigger asChild><Button variant="ghost" size="icon" aria-label="Neu erstellen" className="hidden md:inline-flex"><Plus className="h-4 w-4" /></Button></MenuTrigger>
          <MenuContent>
            <MenuItem icon={CheckSquare} onSelect={() => create.newTask()}>Neue Aufgabe</MenuItem>
            <MenuItem icon={CalendarDays} onSelect={() => create.newEvent()}>Neuer Termin</MenuItem>
            <MenuItem icon={FolderKanban} onSelect={() => create.newProject()}>Neues Projekt</MenuItem>
          </MenuContent>
        </Menu>
        <Notifications />
        <div className="hidden md:block ml-1"><MicButton /></div>
        <Menu>
          <MenuTrigger asChild>
            <button className="ml-1 h-8 w-8 rounded-full overflow-hidden bg-raised border border-line-strong grid place-items-center text-sm font-semibold text-ink-2" aria-label="Profil">
              {user?.has_avatar ? <img src="/api/auth/avatar" alt="" className="h-full w-full object-cover" /> : (user?.display_name || user?.username || "?").slice(0, 1).toUpperCase()}
            </button>
          </MenuTrigger>
          <MenuContent>
            <div className="px-2 py-1.5"><div className="text-sm text-ink">{user?.display_name || user?.username}</div><div className="text-xs text-ink-3">@{user?.username}</div></div>
            <MenuSeparator />
            <MenuItem icon={UserIcon} onSelect={() => nav("/einstellungen/profil")}>Profil</MenuItem>
            <MenuItem icon={Settings} onSelect={() => nav("/einstellungen")}>Einstellungen</MenuItem>
            <MenuSeparator />
            <MenuItem icon={LogOut} onSelect={logout}>Abmelden</MenuItem>
          </MenuContent>
        </Menu>
      </div>
    </header>
  );
}

/* --------------------------------------------------------------------- Mobile Navigation */
function MobileNav() {
  const item = (to: string, label: string, Icon: React.ComponentType<{ className?: string }>, end = false) => (
    <NavLink to={to} end={end} className={({ isActive }) => cn("flex flex-1 flex-col items-center justify-center gap-0.5 text-2xs font-medium", isActive ? "text-ink" : "text-ink-3")}>
      {({ isActive }) => (<><Icon className={cn("h-5 w-5", isActive && "text-accent")} />{label}</>)}
    </NavLink>
  );
  return (
    <nav className="md:hidden fixed bottom-0 inset-x-0 z-40 bg-rail/95 backdrop-blur border-t border-line safe-bottom" aria-label="Mobile Navigation">
      <div className="flex h-16 items-stretch px-2">
        {item("/", "Heute", LayoutGrid, true)}
        {item("/kalender", "Kalender", CalendarDays)}
        <div className="flex flex-1 items-center justify-center"><MicButton size="lg" className="-mt-7 ring-4 ring-rail" /></div>
        {item("/aufgaben", "Aufgaben", CheckSquare)}
        {item("/assistent", "Assistent", MessageSquare)}
      </div>
    </nav>
  );
}

export function AppLayout({ children }: { children?: ReactNode }) {
  const [cmd, setCmd] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const loc = useLocation();
  const create = useCreate();
  useEffect(() => setDrawer(false), [loc.pathname]);
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
    <div className="min-h-full">
      <aside className="hidden md:block fixed inset-y-0 left-0 w-[232px] bg-rail border-r border-line z-30"><Sidebar /></aside>
      <RDialog.Root open={drawer} onOpenChange={setDrawer}>
        <RDialog.Portal>
          <RDialog.Overlay className="fixed inset-0 z-50 bg-black/60 animate-fade-in md:hidden" />
          <RDialog.Content className="fixed inset-y-0 left-0 z-50 w-[78vw] max-w-[300px] bg-rail border-r border-line md:hidden animate-fade-in">
            <RDialog.Title className="sr-only">Navigation</RDialog.Title>
            <RDialog.Description className="sr-only">Hauptmenü</RDialog.Description>
            <RDialog.Close asChild><Button variant="ghost" size="icon-sm" className="absolute right-3 top-3.5" aria-label="Menü schließen"><X className="h-4 w-4" /></Button></RDialog.Close>
            <Sidebar onNavigate={() => setDrawer(false)} />
          </RDialog.Content>
        </RDialog.Portal>
      </RDialog.Root>
      <div className="md:pl-[232px] flex flex-col min-h-full">
        <Topbar onSearch={() => setCmd(true)} onMenu={() => setDrawer(true)} />
        <main className="flex-1 px-4 md:px-8 py-6 md:py-8 pb-28 md:pb-10 w-full max-w-[1360px] mx-auto">{children ?? <Outlet />}</main>
      </div>
      <MobileNav />
      <CommandPalette open={cmd} onOpenChange={setCmd} />
    </div>
  );
}

export const Tooltipped = Tip;
