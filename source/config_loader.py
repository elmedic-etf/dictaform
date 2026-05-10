"""Loads ``config.json`` and validates it into typed dataclasses.

The same ``FormConfig`` instance drives:
  * the right-hand UI form (``FormView`` builds widgets per field), and
  * the LLM extraction prompt (``Structurer`` describes the schema to the model).
Keeping a single source of truth means renaming a field touches one file.
"""
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# Field types we currently render and coerce to. Add new types in
# FormView._make_editor and Structurer._coerce when you extend this.
#   string  — single-line text (e.g. patient name)
#   text    — multi-line narrative text (e.g. diagnosis, treatment plan)
#   integer — whole number (e.g. year of birth)
FieldType = Literal["string", "text", "integer"]


@dataclass(frozen=True)
class Field:
    key: str       # JSON key emitted to the LLM and saved to output.
    label: str     # Human-readable label shown in the UI.
    type: FieldType


@dataclass(frozen=True)
class Group:
    name: str
    fields: tuple[Field, ...]


@dataclass(frozen=True)
class FormConfig:
    groups: tuple[Group, ...]

    def all_fields(self) -> list[Field]:
        """Flat list of every field across all groups."""
        return [field for group in self.groups for field in group.fields]


def load_config(path: Path) -> FormConfig:
    """Read and validate config.json. Raises ValueError on a bad config."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if "groups" not in raw or not isinstance(raw["groups"], list):
        raise ValueError("config.json must contain a top-level 'groups' list")

    groups: list[Group] = []
    seen_keys: set[str] = set()
    for group_raw in raw["groups"]:
        fields: list[Field] = []
        for field_raw in group_raw.get("fields", []):
            field = Field(
                key=field_raw["key"],
                label=field_raw["label"],
                type=field_raw["type"],
            )
            if field.type not in ("string", "text", "integer"):
                raise ValueError(
                    f"Field '{field.key}' has unsupported type '{field.type}'"
                )
            if field.key in seen_keys:
                raise ValueError(f"Duplicate field key '{field.key}' in config.json")
            seen_keys.add(field.key)
            fields.append(field)
        groups.append(Group(name=group_raw["name"], fields=tuple(fields)))

    if not groups:
        raise ValueError("config.json must define at least one group")
    return FormConfig(groups=tuple(groups))
