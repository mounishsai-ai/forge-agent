"""Argument parsing and command dispatch for the todo CLI."""
import argparse
import sys

import storage
import formatting
from models import Task

DEFAULT_PATH = "tasks.json"


def build_parser():
    parser = argparse.ArgumentParser(prog="todo")
    parser.add_argument("--file", default=DEFAULT_PATH)
    sub = parser.add_subparsers(dest="command", required=True)

    add_p = sub.add_parser("add")
    add_p.add_argument("title")

    done_p = sub.add_parser("done")
    done_p.add_argument("id", type=int)

    sub.add_parser("list")

    remove_p = sub.add_parser("remove")
    remove_p.add_argument("id", type=int)

    return parser


def cmd_add(args):
    tasks = storage.load_tasks(args.file)
    task = Task(id=storage.next_id(tasks), title=args.title)
    tasks.append(task)
    storage.save_tasks(args.file, tasks)
    print(f"Added task #{task.id}: {task.title}")


def cmd_done(args):
    tasks = storage.load_tasks(args.file)
    for t in tasks:
        if t.id == args.id:
            t.done = True
            storage.save_tasks(args.file, tasks)
            print(f"Marked #{t.id} done")
            return
    print(f"No task with id {args.id}", file=sys.stderr)
    sys.exit(1)


def cmd_list(args):
    tasks = storage.load_tasks(args.file)
    print(formatting.format_task_list(tasks))


def cmd_remove(args):
    tasks = storage.load_tasks(args.file)
    remaining = [t for t in tasks if t.id != args.id]
    if len(remaining) == len(tasks):
        print(f"No task with id {args.id}", file=sys.stderr)
        sys.exit(1)
    storage.save_tasks(args.file, remaining)
    print(f"Removed #{args.id}")


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    {
        "add": cmd_add,
        "done": cmd_done,
        "list": cmd_list,
        "remove": cmd_remove,
    }[args.command](args)


if __name__ == "__main__":
    main()
