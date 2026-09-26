"""Task model for the todo CLI."""


class Task:
    def __init__(self, id, title, done=False, created_at=None):
        self.id = id
        self.title = title
        self.done = done
        self.created_at = created_at

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "done": self.done,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            id=data["id"],
            title=data["title"],
            done=data.get("done", False),
            created_at=data.get("created_at"),
        )

    def __repr__(self):
        return f"Task(id={self.id}, title={self.title!r}, done={self.done})"
