/** Typed endpoint functions + API data shapes (mirror of the Django API). */
import { api, downloadFile } from "./client";

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
  reminder_lead_minutes: number;
  deadline_warning_days: number;
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
  recurrence_rule: string;
  preferred_time: string;
  scheduled_date: string | null;
  is_scheduled: boolean;
  scheduled_minutes: number;
}

/** One bucket of tasks that can be previewed and bulk-acted-on together. */
export interface TaskGroup {
  key: string;
  label: string;
  count: number;
}
export type GroupFacet = "title" | "project" | "category" | "recurring" | "status";
export interface TaskGroupFacets {
  title: TaskGroup[];
  project: TaskGroup[];
  category: TaskGroup[];
  recurring: TaskGroup[];
  status: TaskGroup[];
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

export interface PlanBlock {
  task_id: number;
  title: string;
  start: string;
  end: string;
  minutes: number;
  date: string; // local calendar day (YYYY-MM-DD) in the profile timezone
}

export interface PlanConflict {
  type: string;
  task_id?: number;
  message: string;
}

export interface SchedulePlan {
  id: number;
  project: number | null;
  status: "preview" | "applied" | "undone" | "discarded";
  is_feasible: boolean | null;
  feasibility_note: string;
  deficit_minutes_per_day: number | null;
  payload: {
    blocks: PlanBlock[];
    unplaced: { task_id: number; title: string; minutes: number }[];
    conflicts: PlanConflict[];
    per_day: { date: string; capacity_minutes: number; planned_minutes: number; existing_minutes: number; fixed_minutes: number }[];
    totals: { requested_minutes: number; planned_minutes: number; unplaced_minutes: number; days_available: number };
  };
  applied_at: string | null;
  undone_at: string | null;
}


export type Priority = "low" | "medium" | "high" | "urgent";

export interface ProjectEntry {
  id: number;
  title: string;
  description: string;
  deadline: string | null;
  priority: Priority;
  color: string;
  status: string;
  tasks_total: number;
  tasks_completed: number;
  completion_percent: number;
  hours_remaining: number;
}

export interface SectionEntry {
  id: number;
  project: number;
  title: string;
  description: string;
  position: number;
  tasks_total: number;
  tasks_completed: number;
  completion_percent: number;
  minutes_remaining: number;
}

export interface CalendarEvent {
  event_id: number;
  title: string;
  description: string;
  location: string;
  color: string;
  category: string;
  all_day: boolean;
  start: string;
  end: string;
  original_date: string;
  is_recurring: boolean;
}

export interface CalendarBlock {
  block_id: number;
  task_id: number;
  title: string;
  start: string;
  end: string;
  source: "manual" | "auto" | "recurring";
  locked: boolean;
  completed: boolean;
  recurring: boolean;
  done_occurrence: boolean;
  project_id: number | null;
  project_title: string;
  color: string;
}

export interface DayTaskEntry {
  task_id: number;
  title: string;
  scheduled_date: string;
  priority: Priority;
  completed: boolean;
  recurring_rule: string;
  project_id: number | null;
  color: string;
}

export interface CalendarRange {
  events: CalendarEvent[];
  blocks: CalendarBlock[];
  day_tasks: DayTaskEntry[];
}

export interface HolidayEntry {
  id?: number;
  date: string;
  name: string;
  local_name: string;
  country: string;
  region: string;
  source: "nager" | "manual";
}

export interface HolidayRange {
  configured: boolean;
  holidays: HolidayEntry[];
}

export interface NotificationItem {
  kind: "overdue" | "deadline" | "event" | "unscheduled" | string;
  severity: "high" | "medium" | "low";
  ref_type: "task" | "event";
  ref_id: number;
  title: string;
  detail: string;
  when_display: string | null;
  original_date?: string;
}

export interface NotificationList {
  count: number;
  items: NotificationItem[];
}

export interface SearchResults {
  q: string;
  events: EventEntry[];
  tasks: TaskEntry[];
  projects: ProjectEntry[];
  sections: SectionEntry[];
}

export interface CountryOption {
  country_code: string;
  name: string;
}

export interface PrayerDay {
  name: string;
  start: string;
  end: string;
}

export interface PrayerRange {
  configured: boolean;
  days: Record<string, PrayerDay[]>;
}

export type EventInput = Partial<Omit<EventEntry, "id">>;
export type TaskInput = Partial<
  Pick<
    TaskEntry,
    | "title" | "description" | "estimated_minutes" | "deadline" | "priority"
    | "color" | "category" | "project" | "section" | "position" | "depends_on"
  > & { recurrence_rule: string }
>;
export type ProjectInput = Partial<Omit<ProjectEntry, "id" | "tasks_total" | "tasks_completed" | "completion_percent" | "hours_remaining">>;

export interface ProjectSummaryDetail {
  id: number;
  title: string;
  hours_remaining: number;
  hours_total: number;
  completion_percent: number;
  days_remaining: number | null;
  hours_per_day_needed: number | null;
  is_overdue: boolean;
  sections: {
    id: number;
    title: string;
    tasks_total: number;
    tasks_completed: number;
    minutes_remaining: number;
    completion_percent: number;
  }[];
  overdue_tasks: { id: number; title: string; deadline: string | null; priority: Priority }[];
  unscheduled_tasks: { id: number; title: string; estimated_minutes: number; priority: Priority }[];
}

export const endpoints = {
  login: (password: string) =>
    api<{ token: string; user: UserInfo }>("/api/auth/login/", { method: "POST", body: { password } }),
  logout: () => api<void>("/api/auth/logout/", { method: "POST" }),
  me: () => api<{ user: UserInfo; profile: Profile }>("/api/auth/me/"),

  dashboardToday: () => api<Dashboard>("/api/dashboard/today/"),

  notifications: () => api<NotificationList>("/api/notifications/"),
  search: (q: string) => api<SearchResults>("/api/search/", { params: { q } }),

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
  getTask: (id: number) => api<TaskEntry>(`/api/tasks/${id}/`),
  setOccurrenceDone: (id: number, date: string, done: boolean) =>
    api<{ date: string; done: boolean }>(`/api/tasks/${id}/occurrence_done/`, { method: "POST", body: { date, done } }),

  // --- group (bulk) management ---
  taskGroups: () => api<TaskGroupFacets>("/api/tasks/groups/"),
  taskGroupMembers: (facet: GroupFacet, key: string) =>
    api<TaskEntry[]>("/api/tasks/group_members/", { params: { facet, key } }),
  bulkDeleteTasks: (ids: number[]) => api<{ deleted: number }>("/api/tasks/bulk_delete/", { method: "POST", body: { ids } }),
  bulkCompleteTasks: (ids: number[], completed: boolean) =>
    api<{ changed: number }>("/api/tasks/bulk_complete/", { method: "POST", body: { ids, completed } }),
  ghostBlocks: () => api<{ count: number }>("/api/tasks/ghost_blocks/"),
  purgeGhostBlocks: () => api<{ purged: number }>("/api/tasks/ghost_blocks/", { method: "POST" }),

  importData: (format: "json" | "text", content: string) =>
    api<{ projects_created: number; tasks_created: number; warnings: string[] }>("/api/import/", {
      method: "POST",
      body: { format, content },
    }),

  listProjects: () => api<ProjectEntry[]>("/api/projects/"),

  previewSchedule: (project: number, order: "manual" | "priority" = "manual") =>
    api<SchedulePlan>("/api/scheduling/plans/preview/", { method: "POST", body: { project, order } }),
  applySchedule: (planId: number) =>
    api<SchedulePlan>(`/api/scheduling/plans/${planId}/apply/`, { method: "POST" }),
  undoSchedule: (planId: number) =>
    api<SchedulePlan>(`/api/scheduling/plans/${planId}/undo/`, { method: "POST" }),
  discardSchedule: (planId: number) =>
    api<SchedulePlan>(`/api/scheduling/plans/${planId}/discard/`, { method: "POST" }),


  // --- calendar ---
  calendarRange: (start: string, end: string) =>
    api<CalendarRange>("/api/calendar/", { params: { start, end } }),
  prayerTimes: (start: string, end: string) =>
    api<PrayerRange>("/api/prayer-times/", { params: { start, end } }),
  holidays: (start: string, end: string) =>
    api<HolidayRange>("/api/holidays/", { params: { start, end } }),
  holidayCountries: () => api<{ countries: CountryOption[] }>("/api/holidays/countries/"),
  createHoliday: (body: { date: string; name: string; local_name?: string }) =>
    api<HolidayEntry>("/api/holidays/", { method: "POST", body }),
  deleteHoliday: (id: number) => api<void>(`/api/holidays/${id}/`, { method: "DELETE" }),

  // One occurrence of a recurring event: edit-this / delete-this / reset.
  overrideEventOccurrence: (
    id: number,
    body: { original_date: string; is_cancelled?: boolean; patch?: Record<string, string>; reset?: boolean },
  ) => api<unknown>(`/api/events/${id}/override/`, { method: "POST", body }),

  // Export: real files (JSON dump / ICS calendar), downloaded via the browser.
  exportJSON: () => downloadFile("/api/export/?type=json", "tempo-export.json"),
  exportICS: () => downloadFile("/api/export/?type=ics", "tempo-calendar.ics"),

  // --- events ---
  createEvent: (body: EventInput) => api<EventEntry>("/api/events/", { method: "POST", body }),
  getEvent: (id: number) => api<EventEntry>(`/api/events/${id}/`),
  updateEvent: (id: number, body: EventInput) => api<EventEntry>(`/api/events/${id}/`, { method: "PATCH", body }),
  deleteEvent: (id: number) => api<void>(`/api/events/${id}/`, { method: "DELETE" }),

  // --- tasks ---
  createTask: (body: TaskInput) => api<TaskEntry>("/api/tasks/", { method: "POST", body }),
  updateTask: (id: number, body: TaskInput) => api<TaskEntry>(`/api/tasks/${id}/`, { method: "PATCH", body }),
  deleteTask: (id: number) => api<void>(`/api/tasks/${id}/`, { method: "DELETE" }),
  moveTask: (id: number, body: { section_id?: number | null; project_id?: number | null; position?: number }) =>
    api<TaskEntry>(`/api/tasks/${id}/move/`, { method: "POST", body }),
  reorderTasks: (items: { id: number; position: number; section_id?: number | null }[]) =>
    api<TaskEntry[]>("/api/tasks/reorder/", { method: "POST", body: { items } }),

  // --- time blocks ---
  createTimeBlock: (body: { task: number; start: string; end: string; locked?: boolean }) =>
    api<TimeBlockEntry>("/api/time-blocks/", { method: "POST", body }),
  updateTimeBlock: (id: number, body: { start?: string; end?: string; locked?: boolean }) =>
    api<TimeBlockEntry>(`/api/time-blocks/${id}/`, { method: "PATCH", body }),
  deleteTimeBlock: (id: number) => api<void>(`/api/time-blocks/${id}/`, { method: "DELETE" }),

  // --- projects & sections ---
  getProject: (id: number) => api<ProjectEntry>(`/api/projects/${id}/`),
  projectSummary: (id: number) => api<ProjectSummaryDetail>(`/api/projects/${id}/summary/`),
  createProject: (body: ProjectInput) => api<ProjectEntry>("/api/projects/", { method: "POST", body }),
  updateProject: (id: number, body: ProjectInput) =>
    api<ProjectEntry>(`/api/projects/${id}/`, { method: "PATCH", body }),
  deleteProject: (id: number) => api<void>(`/api/projects/${id}/`, { method: "DELETE" }),
  listSections: (project: number) => api<SectionEntry[]>("/api/sections/", { params: { project } }),
  createSection: (body: { project: number; title: string; description?: string }) =>
    api<SectionEntry>("/api/sections/", { method: "POST", body }),
  updateSection: (id: number, body: { title?: string; description?: string }) =>
    api<SectionEntry>(`/api/sections/${id}/`, { method: "PATCH", body }),
  deleteSection: (id: number) => api<void>(`/api/sections/${id}/`, { method: "DELETE" }),
  reorderSections: (ordered_ids: number[]) =>
    api<SectionEntry[]>("/api/sections/reorder/", { method: "POST", body: { ordered_ids } }),

  updatePreferences: (patch: Partial<Profile>) =>
    api<Profile>("/api/preferences/", { method: "PATCH", body: patch }),
};

// --- AI agent (local Ollama + MCP tools) ---
export interface AgentToolCall {
  tool: string;
  arguments?: Record<string, unknown>;
  ok?: boolean;
  summary?: string;
  error?: string;
  ids?: Record<string, number>;
}

export interface AgentMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  tool_calls?: AgentToolCall[];
  backup?: string | null;
  ts?: string;
}

export interface AgentStatus {
  ollama: { ok: boolean; model: string; pulled: boolean; models?: string[]; error?: string; hint?: string; tools: string[] };
  model: string;
  host: string;
  max_rounds: number;
  undo_depth: number;
}

export interface AgentMessagesPayload {
  messages: AgentMessage[];
  mode: "native" | "json";
  model: string;
  undoable_ids: number[];
}

export interface AgentChatPayload extends AgentMessagesPayload {
  ok: boolean;
  error?: string;
  assistant_message?: AgentMessage;
}

export const agent = {
  status: () => api<AgentStatus>("/api/agent/status/"),
  messages: () => api<AgentMessagesPayload>("/api/agent/messages/"),
  chat: (message: string) =>
    api<AgentChatPayload>("/api/agent/chat/", { method: "POST", body: { message }, queueOnOffline: false }),
  undo: (message_id: number) =>
    api<AgentChatPayload & { ok: boolean; restored_from?: string; error?: string }>(
      "/api/agent/undo/", { method: "POST", body: { message_id }, queueOnOffline: false }),
  reset: () => api<AgentMessagesPayload>("/api/agent/reset/", { method: "POST", body: {}, queueOnOffline: false }),
};
