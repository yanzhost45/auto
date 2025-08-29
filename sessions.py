from typing import Any, Dict

class SessionManager:
    def __init__(self):
        self.sessions: Dict[int, dict] = {}

    def get(self, user_id: int, default: dict = None) -> dict:
        if user_id not in self.sessions:
            self.sessions[user_id] = {} if default is None else dict(default)
        return self.sessions[user_id]

    def set(self, user_id: int, data: dict) -> None:
        """Overwrite the whole session for a user (use with care)."""
        self.sessions[user_id] = dict(data)

    def update(self, user_id: int, data: dict) -> None:
        """Update/add some fields, keep the rest."""
        session = self.get(user_id)
        session.update(data)
        self.sessions[user_id] = session

    def clear(self, user_id: int) -> None:
        if user_id in self.sessions:
            del self.sessions[user_id]

    def all(self) -> Dict[int, dict]:
        return self.sessions

# Singleton instance
sessions = SessionManager()