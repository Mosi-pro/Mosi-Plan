export type Priority = "low" | "normal" | "high" | "critical";
export type TaskStatus = "open" | "in_progress" | "waiting" | "done" | "archived";
export type ProjectStatus = "planned" | "active" | "paused" | "completed" | "archived";

export interface User { id: number; username: string; display_name: string; timezone: string; language: string; has_avatar: boolean }

export interface Project {
  id: number; name: string; description: string; goal: string; status: ProjectStatus; priority: Priority;
  start_date: string | null; deadline: string | null; color: string; categories: string[]; notes: string;
  created_at: string; updated_at: string; ai_summary: string | null; ai_summary_at: string | null;
  progress: number; task_total: number; task_done: number; task_open: number; task_overdue: number; next_due: string | null;
}

export interface Task {
  id: number; title: string; description: string; status: TaskStatus; priority: Priority; project_id: number | null;
  parent_id: number | null; due_date: string | null; estimated_minutes: number | null; actual_minutes: number | null;
  completed_at: string | null; created_at: string; updated_at: string; sort_order: number; depends_on: number[]; origin: string;
  project_name: string | null; project_color: string | null; subtask_total: number; subtask_done: number; overdue: boolean;
}

export interface CalEvent {
  id: string; event_id: number; occurrence: string | null; source: "internal" | "google"; google_calendar_id: string | null;
  title: string; notes: string; location: string; start: string; end: string; all_day: boolean;
  start_date: string | null; end_date: string | null; busy: boolean; recurring: boolean; rrule: string | null;
  category_id: number | null; reminders: number[]; task_id: number | null; project_id: number | null; origin: string;
  sync_state: string; editable: boolean; color: string | null;
}

export interface Category { id: number; name: string; color: string }

export interface MemoryEntry { id: number; content: string; category: string; source: string; project_id: number | null; pinned: boolean; created_at: string; updated_at: string }

export interface PendingAction { id: number; tool: string; description: string; preview: Record<string, unknown>; status: string; result?: Record<string, unknown> | null }

export interface ChatMessage { id: number; role: "user" | "assistant"; content: string; created_at: string; meta: { backend?: string; tools?: string[]; error?: boolean; voice?: boolean; actions?: PendingAction[] } }

export interface Overview {
  date: string; date_label: string; greeting: string; name: string; summary: string; headline: string;
  events_today: CalEvent[]; upcoming_events: CalEvent[]; tasks_today: Task[]; overdue: Task[];
  deadlines: { type: "task" | "project"; id: number; title: string; date: string; project_name: string | null; priority: Priority }[];
  active_projects: Project[];
}

export interface PlanItem {
  id: number; task_id: number | null; project_id: number | null; project_name: string | null; project_color: string | null;
  title: string; priority: Priority; start: string; end: string; date: string; minutes: number; status: "planned" | "moved" | "removed";
  original_start: string | null; event_id: number | null; note: string; task_status: string | null; done: boolean;
}

export interface WeeklyPlan {
  id: number; week_start: string; week_number: number; status: "draft" | "confirmed" | "discarded" | "superseded"; generated_by: string;
  created_at: string; confirmed_at: string | null; items: PlanItem[];
  review: { planned_tasks: number; done_tasks: number; moved: number; removed: number; per_project: Record<string, { planned: number; done: number }> } | null;
  data: {
    days: { date: string; label: string; workday: boolean; events: { title: string; start: string; end: string; all_day: boolean; source: string }[]; capacity_minutes: number; planned_minutes: number; free_slots: { start: string; end: string }[] }[];
    goals: { project_id: number | null; title: string }[];
    deadlines: { type: string; id: number; title: string; date: string; priority: Priority }[];
    carryover: { task_id: number; title: string; due_date: string | null; priority: Priority }[];
    project_progress: { project_id: number; name: string; progress: number; open: number; overdue: number; color: string }[];
    recommendations: string[]; warnings: string[];
    unscheduled: { task_id: number; title: string; minutes: number; due_date: string | null; reason: string }[];
    blocked: { task_id: number; title: string; reason: string }[];
    stats: { capacity_minutes: number; planned_minutes: number; items: number };
    ai_notes?: string;
  };
}

export interface NotificationItem { id: number; type: string; title: string; body: string; link: string; created_at: string; read: boolean }
