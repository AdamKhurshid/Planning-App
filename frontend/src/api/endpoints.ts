/** Typed endpoint functions + API data shapes (mirror of the Django API). */
import { api } from "./client";

export interface UserInfo {
  id: number;
  username: string;
  first_name: string;
  email: string;
}

export interface Profile {
  timezone: string;
  working_days: number[];
  work_start: string;
  work_end: string;
  max_work_minutes_per_day: number;
  preferred_task_minutes: number;
  min_break_minutes: number;
  days_off: string[];
  latitude: number | null;
  longitude: number | null;
  elevation: number;
  prayer_method: string;
  asr_madhab: string;
  prayer_offsets: Record<string, number>;
  holidays_country: string;
  holidays_region: string;
}

export interface EventEntry {
  id: number;
  title: string;
  description: string;
  start: string;
  end: string;
  all_day: boolean;
  location: string;
  color: string;
  category: string;
  is_fixed: boolean;
  recurrence_rule: string;
}

export interface TaskEntry {
  id: number;
  title: string;
  description: string;
  estimated_minutes: number;
  deadline: string | null;
  priority: "low" | "medium" | "high" | "urgent";
  completed_at: string | null;
  is_completed: boolean;
  color: string;
  category: string;
  project: number | null;
  project_title: string;
  section: number | null;
  section_title: string;
  position: number;
  depends_on: number[];
  is_scheduled: boolean;
  scheduled_minutes: number;
}

export interface TimeBlockEntry {
  id: number;
  task: number;
  task_title: string;
  task_project: number | null;
  task_project_color: string;
  start: string;
  end: string;
  minutes: number;
  source: "manual" | "auto";
  locked: boolean;
}

export interface ProjectSummary {
  id: number;
  title: string;
  color: string;
  status: string;
  deadline: string | null;
  tasks_total: number;
  tasks_completed: number;
  completion_percent: number;
  hours_remaining: number;
}

export interface Dashboard {
  date: string;
  events: EventEntry[];
  time_blocks: TimeBlockEntry[];
  prayer_times: { name: string; start: string; end: string }[];
  holidays: { name: string }[];
  overdue_tasks: TaskEntry[];
  upcoming_deadlines: TaskEntry[];
  projects: ProjectSummary[];
  unscheduled_count: number;
  work_today: {
    scheduled_minutes: number;
    completed_minutes: number;
    remaining_minutes: number;
  };
}

export const endpoints = {
  login: (password: string) =>
    api<{ token: string; user: UserInfo }>("/api/auth/login/", { method: "POST", body: { password } }),
  logout: () => api<void>("/api/auth/logout/", { method: "POST" }),
  me: () => api<{ user: UserInfo; profile: Profile }>("/api/auth/me/"),

  dashboardToday: () => api<Dashboard>("/api/dashboard/today/"),

  listEvents: (params: { date_from?: string; date_to?: string; search?: string }) =>
    api<EventEntry[]>("/api/events/", { params }),
  listTimeBlocks: (params: { date_from?: string; date_to?: string; task?: number }) =>
    api<TimeBlockEntry[]>("/api/time-blocks/", { params }),
  listTasks: (params: {
    project?: number;
    section?: number;
    completed?: boolean;
    unscheduled?: boolean;
    priority?: string;
    search?: string;
  }) => api<TaskEntry[]>("/api/tasks/", { params }),
  completeTask: (id: number, completed: boolean) =>
    api<TaskEntry>(`/api/tasks/${id}/complete/`, { method: "POST", body: { completed } }),

  listProjects: () => api<ProjectSummary[]>("/api/projects/"),

  updatePreferences: (patch: Partial<Profile>) =>
    api<Profile>("/api/preferences/", { method: "PATCH", body: patch }),
};
