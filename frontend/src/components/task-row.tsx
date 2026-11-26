import { CornerDownRight, Repeat, Sparkles } from "lucide-react";
import { minutes, relDay, TASK_STATUS } from "@/lib/format";
import type { Task } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useTaskMutations } from "@/hooks/queries";
import { useCreate } from "./dialogs";
import { Checkbox, PriorityMark } from "./ui";

export function TaskRow({ task, showProject = true, dense }: { task: Task; showProject?: boolean; dense?: boolean }) {
  const { toggle } = useTaskMutations();
  const { editTask } = useCreate();
  const done = task.status === "done";
  return (
    <div role="button" tabIndex={0} onClick={() => editTask(task)} onKeyDown={(e) => e.key === "Enter" && editTask(task)}
      className={cn("group flex items-center gap-3 px-4 cursor-pointer hover:bg-raised/60 transition-colors", dense ? "h-10" : "min-h-[44px] py-2")}>
      <Checkbox checked={done} onChange={() => toggle(task)} label={done ? "Als offen markieren" : "Als erledigt markieren"} />
      {task.parent_id && <CornerDownRight className="h-3.5 w-3.5 text-ink-3 -ml-1" />}
      <div className="min-w-0 flex-1 flex items-center gap-2">
        <span className={cn("truncate text-base", done ? "text-ink-3 line-through" : "text-ink")}>{task.title}</span>
        {task.origin === "assistant" && <Sparkles className="h-3 w-3 text-ink-3 shrink-0" aria-label="Vom Assistenten erstellt" />}
        {task.subtask_total > 0 && <span className="text-xs text-ink-3 tnum shrink-0">{task.subtask_done}/{task.subtask_total}</span>}
        {task.status === "waiting" && <span className="text-xs text-warn shrink-0">{TASK_STATUS.waiting}</span>}
        {task.status === "in_progress" && <span className="text-xs text-accent-ink shrink-0">{TASK_STATUS.in_progress}</span>}
      </div>
      {showProject && task.project_name && (
        <span className="hidden sm:flex items-center gap-1.5 text-sm text-ink-3 max-w-[160px] shrink-0">
          <span className="h-2 w-2 rounded-[3px] shrink-0" style={{ background: task.project_color ?? undefined }} /><span className="truncate">{task.project_name}</span>
        </span>
      )}
      {task.estimated_minutes ? <span className="hidden md:inline text-sm text-ink-3 tnum w-16 text-right shrink-0">{minutes(task.estimated_minutes)}</span> : null}
      <span className={cn("text-sm tnum w-[72px] text-right shrink-0", task.overdue ? "text-danger" : "text-ink-3")}>{task.due_date ? relDay(task.due_date) : ""}</span>
      <PriorityMark priority={task.priority} className="w-3.5" />
    </div>
  );
}

export const RecurringIcon = Repeat;
