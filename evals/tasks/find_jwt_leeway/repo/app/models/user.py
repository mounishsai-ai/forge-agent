class User:
    def __init__(self, id, username, permissions=None):
        self.id = id
        self.username = username
        self.permissions = permissions or []
