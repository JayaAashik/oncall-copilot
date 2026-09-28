"""Tiny project registry (saved to projects.json so projects survive a refresh)."""
import json
import os
import re


def _file():
    return os.environ.get("PROJECTS_FILE", "projects.json")


DEFAULT = [
    {"name": "Checkout Platform", "use_shared": True, "contribute": True},
    {"name": "Mobile Banking App", "use_shared": True, "contribute": True},
]


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "project"


def load():
    try:
        with open(_file(), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list) and data:
            return data
    except Exception:
        pass
    return [dict(p) for p in DEFAULT]


def save(projects):
    try:
        with open(_file(), "w", encoding="utf-8") as f:
            json.dump(projects, f, indent=2)
    except Exception:
        pass