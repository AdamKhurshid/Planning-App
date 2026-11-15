"""Progress math for projects and sections.

All statistics are computed from the live task/block data in a single pass,
so the numbers can never disagree with reality. Personal-scale data makes
this cheap; Phase 7 may add caching if needed.
"""
from django.utils import timezone


def _task_is_completed(task):
    return task.completed_at is not None


def _sum_minutes(tasks):
    return sum(t.estimated_minutes for t in tasks)


def section_stats(section, tasks):
    """Stats for one section given its (active, unsolicited) tasks."""
    completed = [t for t in tasks if _task_is_completed(t)]
    total_minutes = _sum_minutes(tasks)
    completed_minutes = _sum_minutes(completed)
    return {
        "id": section.id,
        "title": section.title,
        "description": section.description,
        "position": section.position,
        "tasks_total": len(tasks),
        "tasks_completed": len(completed),
        "tasks_remaining": len(tasks) - len(completed),
        "minutes_total": total_minutes,
        "minutes_completed": completed_minutes,
        "minutes_remaining": total_minutes - completed_minutes,
        "completion_percent": round(completed_minutes / total_minutes * 100, 1) if total_minutes else 0.0,
    }


def project_stats(project):
    """Full stats dict for the project summary dashboard."""
    sections = list(project.sections.all())  # default manager: active only
    all_tasks = list(project.tasks.all())  # active only

    standalone = [t for t in all_tasks if t.section_id is None]
    section_results = []
    for section in sections:
        tasks_in_section = [t for t in all_tasks if t.section_id == section.id]
        section_results.append(section_stats(section, tasks_in_section))

    completed_tasks = [t for t in all_tasks if _task_is_completed(t)]
    total_minutes = _sum_minutes(all_tasks)
    completed_minutes = _sum_minutes(completed_tasks)

    now = timezone.now()
    days_remaining = None
    overdue = False
    if project.deadline:
        delta = project.deadline - now
        days_remaining = max(0, round(delta.total_seconds() / 86400, 1))
        overdue = delta.total_seconds() <= 0 and len(completed_tasks) < len(all_tasks)

    remaining_minutes = total_minutes - completed_minutes
    pace = None
    if project.deadline and remaining_minutes > 0 and days_remaining and days_remaining > 0:
        pace = round(remaining_minutes / days_remaining / 60, 2)  # hours per day needed

    upcoming_blocks = [
        b
        for t in all_tasks
        if not _task_is_completed(t)
        for b in t.blocks.all().order_by("start")
        if b.end >= now
    ]
    overdue_tasks = [
        t
        for t in all_tasks
        if not _task_is_completed(t) and t.deadline and t.deadline < now
    ]
    unscheduled_tasks = [t for t in all_tasks if not _task_is_completed(t) and not t.blocks.exists()]

    return {
        "id": project.id,
        "title": project.title,
        "description": project.description,
        "deadline": project.deadline,
        "priority": project.priority,
        "color": project.color,
        "status": project.status,
        "created_at": project.created_at,
        "tasks_total": len(all_tasks),
        "tasks_completed": len(completed_tasks),
        "tasks_remaining": len(all_tasks) - len(completed_tasks),
        "minutes_total": total_minutes,
        "hours_total": round(total_minutes / 60, 1),
        "minutes_completed": completed_minutes,
        "hours_completed": round(completed_minutes / 60, 1),
        "minutes_remaining": remaining_minutes,
        "hours_remaining": round(remaining_minutes / 60, 1),
        "completion_percent": round(completed_minutes / total_minutes * 100, 1) if total_minutes else 0.0,
        "completion_percent_by_tasks": (
            round(len(completed_tasks) / len(all_tasks) * 100, 1) if all_tasks else 0.0
        ),
        "days_remaining": days_remaining,
        "hours_per_day_needed": pace,
        "is_overdue": overdue,
        "sections": section_results,
        "upcoming_blocks": [
            {"id": b.id, "task_id": b.task_id, "task_title": b.task.title, "start": b.start, "end": b.end}
            for b in upcoming_blocks[:10]
        ],
        "overdue_tasks": [
            {"id": t.id, "title": t.title, "deadline": t.deadline, "priority": t.priority}
            for t in overdue_tasks
        ],
        "unscheduled_tasks": [
            {"id": t.id, "title": t.title, "estimated_minutes": t.estimated_minutes, "priority": t.priority}
            for t in unscheduled_tasks
        ],
    }


def compact_project_stats(project):
    """Lightweight stats used in lists (dashboard, project list)."""
    tasks = list(project.tasks.all())
    completed = [t for t in tasks if _task_is_completed(t)]
    total_minutes = _sum_minutes(tasks)
    completed_minutes = _sum_minutes(completed)
    return {
        "id": project.id,
        "title": project.title,
        "color": project.color,
        "status": project.status,
        "deadline": project.deadline,
        "tasks_total": len(tasks),
        "tasks_completed": len(completed),
        "completion_percent": round(completed_minutes / total_minutes * 100, 1) if total_minutes else 0.0,
        "hours_remaining": round((total_minutes - completed_minutes) / 60, 1),
    }
