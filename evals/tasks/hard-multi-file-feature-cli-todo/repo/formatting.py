"""Human-readable rendering of tasks."""


def format_task(task):
    status = "x" if task.done else " "
    return f"[{status}] #{task.id} {task.title}"


def format_task_list(tasks):
    if not tasks:
        return "(no tasks)"
    return "\n".join(format_task(t) for t in tasks)
