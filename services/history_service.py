import json
import os
from datetime import datetime


def default_history_file() -> str:
    folder = os.path.join(os.path.expanduser("~"), ".streammate")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "history.json")


class HistoryService:
    def __init__(self, history_file: str | None = None):
        self.history_file = history_file or default_history_file()
        self.history = self.load_history()

    def load_history(self):
        # Migra o histórico antigo que ficava na pasta do executável
        candidates = [self.history_file, "history.json"]
        for path in candidates:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    return data if isinstance(data, list) else []
                except (OSError, json.JSONDecodeError):
                    return []
        return []

    def save_history(self):
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(self.history, f, indent=4, ensure_ascii=False)

    def add_record(self, action_type, filename, path):
        record = {
            "type": action_type,
            "filename": filename,
            "path": path,
            "status": "Completed",
            "date": datetime.now().strftime("%d/%m/%Y %H:%M"),
        }
        self.history.append(record)
        self.save_history()

    def get_history(self, action_type: str | None = None, limit: int | None = None):
        items = [h for h in self.history if action_type is None or h.get("type") == action_type]
        items = list(reversed(items))
        return items[:limit] if limit else items

    def clear_history(self):
        self.history = []
        self.save_history()
