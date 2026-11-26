import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, qs } from "@/lib/api";
import type { Category, Project, Task } from "@/lib/types";
import { useToast } from "@/components/toast";

export const useProjects = (status?: string) => useQuery({ queryKey: ["projects", status ?? "all"], queryFn: () => api.get<Project[]>(`/api/projects?${qs({ status })}`) });
export const useCategories = () => useQuery({ queryKey: ["categories"], queryFn: () => api.get<Category[]>("/api/categories") });
export const useTasks = (params: Record<string, string | number | boolean | undefined>) =>
  useQuery({ queryKey: ["tasks", params], queryFn: () => api.get<Task[]>(`/api/tasks?${qs(params)}`) });
export const useSettings = () => useQuery({ queryKey: ["settings"], queryFn: () => api.get<Record<string, Record<string, any>>>("/api/settings") });

/** Nach Datenänderungen alle betroffenen Ansichten aktualisieren. */
export function useInvalidate() {
  const qc = useQueryClient();
  return () => {
    for (const k of ["tasks", "projects", "project", "overview", "events", "planner", "search", "memory"]) qc.invalidateQueries({ queryKey: [k] });
  };
}

export function useTaskMutations() {
  const inv = useInvalidate();
  const toast = useToast();
  const update = useMutation({
    mutationFn: ({ id, ...patch }: Partial<Task> & { id: number }) => api.patch<Task>(`/api/tasks/${id}`, patch),
    onSuccess: inv,
    onError: toast.error,
  });
  const toggle = (t: Task) =>
    update.mutate({ id: t.id, status: t.status === "done" ? "open" : "done" }, { onSuccess: () => t.status !== "done" && toast.ok(`„${t.title}“ erledigt`) });
  return { update, toggle };
}

export function useSaveSettings(section: string) {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: (patch: Record<string, unknown>) => api.put(`/api/settings/${section}`, patch),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["settings"] }); qc.invalidateQueries({ queryKey: ["overview"] }); toast.ok("Gespeichert"); },
    onError: toast.error,
  });
}
