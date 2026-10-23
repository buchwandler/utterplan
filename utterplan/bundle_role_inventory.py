"""Portable, renderer-neutral role inventory for compiled SSMD bundles."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Literal, cast

import tomlkit
from tomlkit.exceptions import ParseError

from .atomic_io import atomic_write_text
from .model import FlowPlan
from .role_coverage import logical_role_inventory

BUNDLE_ROLE_INVENTORY_FORMAT = "utterplan.bundle-role-inventory"
BUNDLE_ROLE_INVENTORY_VERSION = 1
_SHA256_PATTERN = re.compile(r"[0-9a-fA-F]{64}\Z")


class BundleRoleInventoryError(ValueError):
    """A bundle role inventory is malformed or internally inconsistent."""


@dataclass(frozen=True, slots=True)
class BundleRole:
    """An explicit logical role and its speech-segment occurrence count."""

    name: str
    occurrences: int

    def __post_init__(self) -> None:
        _require_nonempty_string(self.name, "role name")
        _require_count(self.occurrences, "role occurrences")


@dataclass(frozen=True, slots=True)
class BundleRoleInventoryItem:
    """Role and freshness metadata for one compiled bundle item."""

    id: str
    source: str
    source_sha256: str
    plan: str
    plan_id: str
    explicit_roles: tuple[str, ...]
    explicit_occurrences: Mapping[str, int]
    uses_default_role: bool
    implicit_occurrences: int

    def __post_init__(self) -> None:
        _require_nonempty_string(self.id, "item id")
        _require_bundle_path(self.source, "source path")
        object.__setattr__(
            self, "source_sha256", _normalize_sha256(self.source_sha256, "source_sha256")
        )
        _require_bundle_path(self.plan, "plan path")
        _require_nonempty_string(self.plan_id, "plan_id")

        roles = _tuple_of_strings(self.explicit_roles, "explicit_roles")
        if len(set(roles)) != len(roles):
            raise BundleRoleInventoryError("duplicate explicit role name within item")
        for role in roles:
            _require_nonempty_string(role, "explicit role name")
        object.__setattr__(self, "explicit_roles", roles)

        if not isinstance(self.explicit_occurrences, Mapping):
            raise BundleRoleInventoryError("explicit_occurrences must be a mapping")
        counts = dict(self.explicit_occurrences)
        if set(counts) != set(roles):
            raise BundleRoleInventoryError(
                "explicit_occurrences must contain exactly the roles in explicit_roles"
            )
        ordered_counts: dict[str, int] = {}
        for role in roles:
            _require_nonempty_string(role, "explicit role name")
            count = counts[role]
            _require_count(count, f"occurrences for role {role!r}")
            ordered_counts[role] = count
        object.__setattr__(self, "explicit_occurrences", MappingProxyType(ordered_counts))

        _require_bool(self.uses_default_role, "item uses_default_role")
        _require_count(self.implicit_occurrences, "item implicit_occurrences")
        if self.uses_default_role != (self.implicit_occurrences > 0):
            raise BundleRoleInventoryError(
                "item uses_default_role must match whether implicit_occurrences is positive"
            )


@dataclass(frozen=True, slots=True)
class BundleRoleInventory:
    """Aggregate logical-role inventory for one complete document or book bundle."""

    bundle_kind: Literal["book", "document"]
    manifest_sha256: str
    roles: tuple[BundleRole, ...]
    uses_default_role: bool
    implicit_occurrences: int
    items: tuple[BundleRoleInventoryItem, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.bundle_kind, str) or self.bundle_kind not in {"book", "document"}:
            raise BundleRoleInventoryError("bundle_kind must be 'book' or 'document'")
        object.__setattr__(
            self, "manifest_sha256", _normalize_sha256(self.manifest_sha256, "manifest_sha256")
        )

        roles = _tuple_of_instances(self.roles, BundleRole, "roles")
        role_names = tuple(role.name for role in roles)
        if len(set(role_names)) != len(role_names):
            raise BundleRoleInventoryError("duplicate aggregate role name")
        object.__setattr__(self, "roles", roles)

        items = _tuple_of_instances(self.items, BundleRoleInventoryItem, "items")
        item_ids = tuple(item.id for item in items)
        if len(set(item_ids)) != len(item_ids):
            raise BundleRoleInventoryError("duplicate bundle item id")
        object.__setattr__(self, "items", items)

        _require_bool(self.uses_default_role, "inventory uses_default_role")
        _require_count(self.implicit_occurrences, "inventory implicit_occurrences")
        if self.uses_default_role != (self.implicit_occurrences > 0):
            raise BundleRoleInventoryError(
                "inventory uses_default_role must match whether implicit_occurrences is positive"
            )

        expected_order: list[str] = []
        expected_counts: dict[str, int] = {}
        expected_implicit = 0
        for item in items:
            for role in item.explicit_roles:
                if role not in expected_counts:
                    expected_order.append(role)
                    expected_counts[role] = 0
                expected_counts[role] += item.explicit_occurrences[role]
            expected_implicit += item.implicit_occurrences

        actual_counts = {role.name: role.occurrences for role in roles}
        if role_names != tuple(expected_order) or actual_counts != expected_counts:
            raise BundleRoleInventoryError(
                "aggregate role order/counts do not match the bundle items"
            )
        if self.implicit_occurrences != expected_implicit:
            raise BundleRoleInventoryError(
                "aggregate implicit_occurrences do not match the bundle items"
            )


def sha256_file(path: str | Path) -> str:
    """Return the lowercase SHA-256 digest of a file's exact bytes."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_bundle_role_inventory(
    *,
    bundle_root: str | Path,
    bundle_kind: str,
    manifest_path: str | Path,
    compiled_items: Sequence[object],
) -> BundleRoleInventory:
    """Build a complete bundle inventory from compiled item path records.

    Each item must expose ``id``, ``source_path``, and ``plan_path``. Optional
    ``source_relative_path`` and ``plan_relative_path`` values avoid recomputing
    bundle-relative paths when the orchestration layer already has them.
    Items are consumed in the supplied (manifest) order.
    """
    if not isinstance(bundle_kind, str) or bundle_kind not in {"book", "document"}:
        raise BundleRoleInventoryError("bundle_kind must be 'book' or 'document'")

    root = Path(bundle_root).resolve()
    aggregate_order: list[str] = []
    aggregate_counts: dict[str, int] = {}
    items: list[BundleRoleInventoryItem] = []
    implicit_occurrences = 0

    for compiled_item in compiled_items:
        item_id = _item_value(compiled_item, "id")
        source_path = _path_value(_item_value(compiled_item, "source_path"), "source_path")
        plan_path = _path_value(_item_value(compiled_item, "plan_path"), "plan_path")
        source_relative = _item_relative_path(
            compiled_item, "source_relative_path", source_path, root
        )
        plan_relative = _item_relative_path(compiled_item, "plan_relative_path", plan_path, root)

        plan = FlowPlan.load(plan_path)
        role_inventory = logical_role_inventory(plan)
        explicit_roles = tuple(role_inventory.explicit_roles)
        explicit_occurrences = {
            role: role_inventory.explicit_occurrences[role] for role in explicit_roles
        }

        for role in explicit_roles:
            if role not in aggregate_counts:
                aggregate_order.append(role)
                aggregate_counts[role] = 0
            aggregate_counts[role] += explicit_occurrences[role]
        implicit_occurrences += role_inventory.implicit_occurrences

        items.append(
            BundleRoleInventoryItem(
                id=_require_nonempty_string(item_id, "item id"),
                source=source_relative,
                source_sha256=sha256_file(source_path),
                plan=plan_relative,
                plan_id=plan.plan_id,
                explicit_roles=explicit_roles,
                explicit_occurrences=explicit_occurrences,
                uses_default_role=role_inventory.uses_default_role,
                implicit_occurrences=role_inventory.implicit_occurrences,
            )
        )

    return BundleRoleInventory(
        bundle_kind=cast(Literal["book", "document"], bundle_kind),
        manifest_sha256=sha256_file(manifest_path),
        roles=tuple(
            BundleRole(name=role, occurrences=aggregate_counts[role]) for role in aggregate_order
        ),
        uses_default_role=implicit_occurrences > 0,
        implicit_occurrences=implicit_occurrences,
        items=tuple(items),
    )


def save_bundle_role_inventory(inventory: BundleRoleInventory, path: str | Path) -> None:
    """Atomically serialize *inventory* as deterministic UTF-8 TOML."""
    if not isinstance(inventory, BundleRoleInventory):
        raise BundleRoleInventoryError("inventory must be a BundleRoleInventory")
    atomic_write_text(path, _dumps_bundle_role_inventory(inventory), create_parent=True)


def load_bundle_role_inventory(path: str | Path) -> BundleRoleInventory:
    """Load and strictly validate a version-1 bundle role inventory TOML file."""
    source = Path(path)
    try:
        parsed = tomlkit.parse(source.read_text(encoding="utf-8")).unwrap()
    except ParseError as exc:
        raise BundleRoleInventoryError(f"invalid bundle role inventory TOML: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise BundleRoleInventoryError("bundle role inventory is not valid UTF-8") from exc
    return _inventory_from_data(parsed)


def _dumps_bundle_role_inventory(inventory: BundleRoleInventory) -> str:
    data = {
        "format": BUNDLE_ROLE_INVENTORY_FORMAT,
        "version": BUNDLE_ROLE_INVENTORY_VERSION,
        "bundle_kind": inventory.bundle_kind,
        "manifest_sha256": inventory.manifest_sha256,
        "uses_default_role": inventory.uses_default_role,
        "implicit_occurrences": inventory.implicit_occurrences,
        "roles": [{"name": role.name, "occurrences": role.occurrences} for role in inventory.roles],
        "items": [
            {
                "id": item.id,
                "source": item.source,
                "source_sha256": item.source_sha256,
                "plan": item.plan,
                "plan_id": item.plan_id,
                "explicit_roles": list(item.explicit_roles),
                "uses_default_role": item.uses_default_role,
                "implicit_occurrences": item.implicit_occurrences,
                "explicit_occurrences": {
                    role: item.explicit_occurrences[role] for role in item.explicit_roles
                },
            }
            for item in inventory.items
        ],
    }
    return tomlkit.dumps(data)


def _inventory_from_data(data: object) -> BundleRoleInventory:
    root = _mapping(data, "inventory")
    _require_exact_keys(
        root,
        {
            "format",
            "version",
            "bundle_kind",
            "manifest_sha256",
            "uses_default_role",
            "implicit_occurrences",
            "roles",
            "items",
        },
        "inventory",
    )
    if root["format"] != BUNDLE_ROLE_INVENTORY_FORMAT:
        raise BundleRoleInventoryError("unsupported bundle role inventory format")
    if type(root["version"]) is not int or root["version"] != BUNDLE_ROLE_INVENTORY_VERSION:
        raise BundleRoleInventoryError("unsupported bundle role inventory version")

    bundle_kind = root["bundle_kind"]
    if not isinstance(bundle_kind, str) or bundle_kind not in {"book", "document"}:
        raise BundleRoleInventoryError("bundle_kind must be 'book' or 'document'")

    roles_data = _list(root["roles"], "roles")
    roles: list[BundleRole] = []
    for index, value in enumerate(roles_data):
        role = _mapping(value, f"roles[{index}]")
        _require_exact_keys(role, {"name", "occurrences"}, f"roles[{index}]")
        roles.append(
            BundleRole(
                name=_require_nonempty_string(role["name"], f"roles[{index}].name"),
                occurrences=_require_count(role["occurrences"], f"roles[{index}].occurrences"),
            )
        )

    items_data = _list(root["items"], "items")
    items: list[BundleRoleInventoryItem] = []
    for index, value in enumerate(items_data):
        location = f"items[{index}]"
        item = _mapping(value, location)
        _require_exact_keys(
            item,
            {
                "id",
                "source",
                "source_sha256",
                "plan",
                "plan_id",
                "explicit_roles",
                "uses_default_role",
                "implicit_occurrences",
                "explicit_occurrences",
            },
            location,
        )
        explicit_roles = _tuple_of_strings(item["explicit_roles"], f"{location}.explicit_roles")
        counts_data = _mapping(item["explicit_occurrences"], f"{location}.explicit_occurrences")
        counts = {
            _require_nonempty_string(role, f"{location}.explicit_occurrences key"): _require_count(
                count, f"{location}.explicit_occurrences[{role!r}]"
            )
            for role, count in counts_data.items()
        }
        items.append(
            BundleRoleInventoryItem(
                id=_require_nonempty_string(item["id"], f"{location}.id"),
                source=_require_nonempty_string(item["source"], f"{location}.source"),
                source_sha256=_require_nonempty_string(
                    item["source_sha256"], f"{location}.source_sha256"
                ),
                plan=_require_nonempty_string(item["plan"], f"{location}.plan"),
                plan_id=_require_nonempty_string(item["plan_id"], f"{location}.plan_id"),
                explicit_roles=explicit_roles,
                explicit_occurrences=counts,
                uses_default_role=_require_bool(
                    item["uses_default_role"], f"{location}.uses_default_role"
                ),
                implicit_occurrences=_require_count(
                    item["implicit_occurrences"], f"{location}.implicit_occurrences"
                ),
            )
        )

    return BundleRoleInventory(
        bundle_kind=cast(Literal["book", "document"], bundle_kind),
        manifest_sha256=_require_nonempty_string(root["manifest_sha256"], "manifest_sha256"),
        roles=tuple(roles),
        uses_default_role=_require_bool(root["uses_default_role"], "uses_default_role"),
        implicit_occurrences=_require_count(root["implicit_occurrences"], "implicit_occurrences"),
        items=tuple(items),
    )


def _path_value(value: object, field: str) -> Path:
    if not isinstance(value, (str, Path)):
        raise BundleRoleInventoryError(f"{field} must be a filesystem path")
    return Path(value)


def _item_value(item: object, field: str) -> object:
    if isinstance(item, Mapping):
        if field not in item:
            raise BundleRoleInventoryError(f"compiled item is missing {field}")
        return item[field]
    if not hasattr(item, field):
        raise BundleRoleInventoryError(f"compiled item is missing {field}")
    return getattr(item, field)


def _item_relative_path(item: object, field: str, actual_path: Path, root: Path) -> str:
    value = item.get(field) if isinstance(item, Mapping) else getattr(item, field, None)
    if value is None:
        try:
            relative = actual_path.resolve().relative_to(root)
        except ValueError as exc:
            raise BundleRoleInventoryError(
                f"{field.removesuffix('_relative_path')} is outside the bundle root"
            ) from exc
        value = relative.as_posix()
    if isinstance(value, Path):
        value = value.as_posix()
    if not isinstance(value, str):
        raise BundleRoleInventoryError(f"{field} must be a bundle-relative path")
    return _require_bundle_path(value, field)


def _require_bundle_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise BundleRoleInventoryError(f"{field} must be a non-empty bundle-relative path")
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        path.is_absolute()
        or re.match(r"^[A-Za-z]:/", normalized) is not None
        or any(part in {"", "."} for part in normalized.split("/"))
    ):
        raise BundleRoleInventoryError(f"{field} must be a normalized bundle-relative path")
    return path.as_posix()


def _require_nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise BundleRoleInventoryError(f"{field} must be a non-empty string")
    return value


def _require_count(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise BundleRoleInventoryError(f"{field} must be a non-negative integer")
    return value


def _require_bool(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise BundleRoleInventoryError(f"{field} must be a boolean")
    return value


def _normalize_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise BundleRoleInventoryError(f"{field} must be a 64-character hexadecimal SHA-256")
    return value.lower()


def _tuple_of_strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise BundleRoleInventoryError(f"{field} must be an array of strings")
    result = tuple(value)
    if any(not isinstance(item, str) for item in result):
        raise BundleRoleInventoryError(f"{field} must contain only strings")
    return cast(tuple[str, ...], result)


def _tuple_of_instances(value: object, expected_type: type, field: str) -> tuple:
    if not isinstance(value, (tuple, list)):
        raise BundleRoleInventoryError(f"{field} must be an array")
    result = tuple(value)
    if any(not isinstance(item, expected_type) for item in result):
        raise BundleRoleInventoryError(f"{field} contains an invalid value")
    return result


def _list(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise BundleRoleInventoryError(f"{field} must be an array")
    return value


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise BundleRoleInventoryError(f"{field} must be a table")
    return cast(Mapping[str, object], value)


def _require_exact_keys(value: Mapping[str, object], expected: set[str], field: str) -> None:
    actual = set(value)
    missing = expected - actual
    unknown = actual - expected
    if missing or unknown:
        details = []
        if missing:
            details.append(f"missing {sorted(missing)}")
        if unknown:
            details.append(f"unknown {sorted(unknown)}")
        raise BundleRoleInventoryError(f"{field} has {' and '.join(details)} fields")


__all__ = [
    "BUNDLE_ROLE_INVENTORY_FORMAT",
    "BUNDLE_ROLE_INVENTORY_VERSION",
    "BundleRole",
    "BundleRoleInventory",
    "BundleRoleInventoryError",
    "BundleRoleInventoryItem",
    "build_bundle_role_inventory",
    "load_bundle_role_inventory",
    "save_bundle_role_inventory",
    "sha256_file",
]
