from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import utterplan
from utterplan import (
    AudioDirective,
    FlowPlan,
    FlowSegment,
    FlowUnit,
    SegmentDirectives,
    VoiceDirective,
)
from utterplan.bundle_role_inventory import (
    BundleRole,
    BundleRoleInventory,
    BundleRoleInventoryError,
    BundleRoleInventoryItem,
    build_bundle_role_inventory,
    load_bundle_role_inventory,
    save_bundle_role_inventory,
    sha256_file,
)


def _plan(*segments: FlowSegment) -> FlowPlan:
    return FlowPlan(language="en-US", flow=(FlowUnit(tuple(segments)),))


def _simple_inventory() -> BundleRoleInventory:
    item = BundleRoleInventoryItem(
        id="document-0001",
        source="document.ssmd.md",
        source_sha256="b" * 64,
        plan="utterplan/document.utterplan.toml",
        plan_id="sha256:" + "c" * 64,
        explicit_roles=("host",),
        explicit_occurrences={"host": 1},
        uses_default_role=False,
        implicit_occurrences=0,
    )
    return BundleRoleInventory(
        bundle_kind="document",
        manifest_sha256="a" * 64,
        roles=(BundleRole("host", 1),),
        uses_default_role=False,
        implicit_occurrences=0,
        items=(item,),
    )


def _item(
    bundle_root: Path,
    item_id: str,
    source_name: str,
    plan_name: str,
    plan: FlowPlan,
) -> SimpleNamespace:
    source = bundle_root / source_name
    plan_path = bundle_root / plan_name
    source.write_bytes(f"source for {item_id}".encode())
    plan.save(plan_path, create_parent=True)
    return SimpleNamespace(
        id=item_id,
        source_path=source,
        source_relative_path=source_name,
        plan_path=plan_path,
        plan_relative_path=plan_name,
    )


def test_builder_aggregates_compiled_roles_in_manifest_order_and_hashes_exact_files(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(b'{ "bundle_kind" : "book" }\n')
    first = _item(
        tmp_path,
        "chapter-0001",
        "chapter-1.ssmd.md",
        "plans/chapter-1.toml",
        _plan(
            FlowSegment(
                "Narration.",
                "en-US",
                directives=SegmentDirectives(voice=VoiceDirective("narrator")),
            ),
            FlowSegment("Default speech.", "en-US"),
            FlowSegment("", "en-US", directives=SegmentDirectives(voice=VoiceDirective("empty"))),
            FlowSegment(
                "Music",
                "en-US",
                directives=SegmentDirectives(audio=AudioDirective(src="music.wav")),
            ),
        ),
    )
    second = _item(
        tmp_path,
        "chapter-0002",
        "chapter-2.ssmd.md",
        "plans/chapter-2.toml",
        _plan(
            FlowSegment(
                "Host.", "en-US", directives=SegmentDirectives(voice=VoiceDirective("host"))
            ),
            FlowSegment(
                "Narration again.",
                "en-US",
                directives=SegmentDirectives(voice=VoiceDirective("narrator")),
            ),
            FlowSegment(
                "Another host.", "en-US", directives=SegmentDirectives(voice=VoiceDirective("host"))
            ),
        ),
    )

    inventory = build_bundle_role_inventory(
        bundle_root=tmp_path,
        bundle_kind="book",
        manifest_path=manifest,
        compiled_items=(first, second),
    )

    assert inventory.bundle_kind == "book"
    assert inventory.manifest_sha256 == sha256_file(manifest)
    assert [role.name for role in inventory.roles] == ["narrator", "host"]
    assert [role.occurrences for role in inventory.roles] == [2, 2]
    assert inventory.uses_default_role is True
    assert inventory.implicit_occurrences == 1
    assert [item.id for item in inventory.items] == ["chapter-0001", "chapter-0002"]
    assert inventory.items[0].source == "chapter-1.ssmd.md"
    assert inventory.items[0].plan == "plans/chapter-1.toml"
    assert inventory.items[0].source_sha256 == sha256_file(first.source_path)
    assert inventory.items[0].plan_id == FlowPlan.load(first.plan_path).plan_id
    assert inventory.items[0].explicit_roles == ("narrator",)
    assert inventory.items[0].implicit_occurrences == 1
    assert inventory.items[1].explicit_roles == ("host", "narrator")
    with pytest.raises(TypeError):
        inventory.items[0].explicit_occurrences["new"] = 1  # type: ignore[index]


def test_save_load_is_deterministic_and_round_trips(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(b"{}")
    compiled = _item(
        tmp_path,
        "document-0001",
        "document.ssmd.md",
        "document.utterplan.toml",
        _plan(
            FlowSegment(
                "Host.", "en-US", directives=SegmentDirectives(voice=VoiceDirective("host"))
            ),
            FlowSegment(
                "Host again.", "en-US", directives=SegmentDirectives(voice=VoiceDirective("host"))
            ),
        ),
    )
    inventory = build_bundle_role_inventory(
        bundle_root=tmp_path,
        bundle_kind="document",
        manifest_path=manifest,
        compiled_items=(compiled,),
    )
    first = tmp_path / "first.toml"
    second = tmp_path / "second.toml"

    save_bundle_role_inventory(inventory, first)
    save_bundle_role_inventory(inventory, second)

    assert first.read_bytes() == second.read_bytes()
    assert load_bundle_role_inventory(first) == inventory
    assert 'format = "utterplan.bundle-role-inventory"' in first.read_text(encoding="utf-8")
    assert 'name = "host"' in first.read_text(encoding="utf-8")


def test_loader_rejects_unsupported_version_and_inconsistent_aggregate(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(b"{}")
    compiled = _item(
        tmp_path,
        "document-0001",
        "document.ssmd.md",
        "document.utterplan.toml",
        _plan(
            FlowSegment(
                "Host.", "en-US", directives=SegmentDirectives(voice=VoiceDirective("host"))
            )
        ),
    )
    inventory = build_bundle_role_inventory(
        bundle_root=tmp_path,
        bundle_kind="document",
        manifest_path=manifest,
        compiled_items=(compiled,),
    )
    path = tmp_path / "inventory.toml"
    save_bundle_role_inventory(inventory, path)
    original = path.read_text(encoding="utf-8")

    path.write_text(original.replace("version = 1", "version = 2", 1), encoding="utf-8")
    with pytest.raises(BundleRoleInventoryError, match="version"):
        load_bundle_role_inventory(path)

    path.write_text(original.replace("occurrences = 1", "occurrences = 2", 1), encoding="utf-8")
    with pytest.raises(BundleRoleInventoryError, match="aggregate role"):
        load_bundle_role_inventory(path)


def test_models_reject_duplicate_roles_and_inconsistent_implicit_metadata() -> None:
    with pytest.raises(BundleRoleInventoryError, match="duplicate aggregate role"):
        BundleRoleInventory(
            bundle_kind="document",
            manifest_sha256="a" * 64,
            roles=(BundleRole("host", 1), BundleRole("host", 1)),
            uses_default_role=False,
            implicit_occurrences=0,
            items=(),
        )


def test_inventory_contract_is_exported_from_package_root() -> None:
    assert utterplan.BundleRole is BundleRole
    assert utterplan.BundleRoleInventory is BundleRoleInventory
    assert utterplan.BundleRoleInventoryError is BundleRoleInventoryError
    assert utterplan.build_bundle_role_inventory is build_bundle_role_inventory
    assert utterplan.load_bundle_role_inventory is load_bundle_role_inventory
    assert utterplan.save_bundle_role_inventory is save_bundle_role_inventory


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('format = "utterplan.bundle-role-inventory"', 'format = "other"', "format"),
        ('manifest_sha256 = "' + "a" * 64 + '"', 'manifest_sha256 = "bad"', "manifest_sha256"),
        ('source_sha256 = "' + "b" * 64 + '"', 'source_sha256 = "bad"', "source_sha256"),
        ("occurrences = 1", "occurrences = -1", "non-negative integer"),
        ("occurrences = 1", "occurrences = true", "non-negative integer"),
        ('explicit_roles = ["host"]', 'explicit_roles = ["host", "host"]', "duplicate"),
        ('source = "document.ssmd.md"', 'source = "/tmp/document.ssmd.md"', "relative path"),
        ("host = 1\n", "", "exactly the roles"),
        ("uses_default_role = false", "uses_default_role = true", "uses_default_role"),
        ('plan = "utterplan/document.utterplan.toml"\n', "", "missing"),
    ],
)
def test_loader_rejects_malformed_or_inconsistent_contract(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    path = tmp_path / "inventory.toml"
    save_bundle_role_inventory(_simple_inventory(), path)
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")

    with pytest.raises(BundleRoleInventoryError, match=message):
        load_bundle_role_inventory(path)


def test_loader_rejects_duplicate_item_ids() -> None:
    inventory = _simple_inventory()
    item = inventory.items[0]
    with pytest.raises(BundleRoleInventoryError, match="duplicate bundle item id"):
        BundleRoleInventory(
            bundle_kind="document",
            manifest_sha256=inventory.manifest_sha256,
            roles=(BundleRole("host", 2),),
            uses_default_role=False,
            implicit_occurrences=0,
            items=(item, item),
        )


def test_uppercase_sha256_values_are_normalized() -> None:
    item = BundleRoleInventoryItem(
        id="document-0001",
        source="document.ssmd.md",
        source_sha256="B" * 64,
        plan="document.utterplan.toml",
        plan_id="sha256:" + "c" * 64,
        explicit_roles=("host",),
        explicit_occurrences={"host": 1},
        uses_default_role=False,
        implicit_occurrences=0,
    )
    inventory = BundleRoleInventory(
        bundle_kind="document",
        manifest_sha256="A" * 64,
        roles=(BundleRole("host", 1),),
        uses_default_role=False,
        implicit_occurrences=0,
        items=(item,),
    )
    assert inventory.manifest_sha256 == "a" * 64
    assert inventory.items[0].source_sha256 == "b" * 64


def test_implicit_only_builder_does_not_invent_an_explicit_role(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(b"{}")
    compiled = _item(
        tmp_path,
        "document-0001",
        "document.ssmd.md",
        "document.utterplan.toml",
        _plan(
            FlowSegment("Unassigned speech.", "en-US"),
            FlowSegment("", "en-US", directives=SegmentDirectives(voice=VoiceDirective("empty"))),
            FlowSegment(
                "Audio only",
                "en-US",
                directives=SegmentDirectives(audio=AudioDirective(src="music.wav")),
            ),
        ),
    )

    inventory = build_bundle_role_inventory(
        bundle_root=tmp_path,
        bundle_kind="document",
        manifest_path=manifest,
        compiled_items=(compiled,),
    )

    assert inventory.roles == ()
    assert inventory.uses_default_role is True
    assert inventory.implicit_occurrences == 1
    assert inventory.items[0].explicit_roles == ()


def test_manifest_and_source_content_hashes_change_when_bytes_change(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(b'{"version":1}')
    compiled = _item(
        tmp_path,
        "document-0001",
        "document.ssmd.md",
        "document.utterplan.toml",
        _plan(
            FlowSegment(
                "Host.", "en-US", directives=SegmentDirectives(voice=VoiceDirective("host"))
            )
        ),
    )
    first = build_bundle_role_inventory(
        bundle_root=tmp_path,
        bundle_kind="document",
        manifest_path=manifest,
        compiled_items=(compiled,),
    )
    manifest.write_bytes(b'{ "version": 1 }')
    compiled.source_path.write_bytes(b"updated source bytes")
    second = build_bundle_role_inventory(
        bundle_root=tmp_path,
        bundle_kind="document",
        manifest_path=manifest,
        compiled_items=(compiled,),
    )

    assert first.manifest_sha256 != second.manifest_sha256
    assert first.items[0].source_sha256 != second.items[0].source_sha256
    assert first.items[0].plan_id == second.items[0].plan_id


def test_save_failure_preserves_previous_inventory_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "role-inventory.toml"
    path.write_bytes(b"previous inventory")

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr("utterplan.atomic_io.os.replace", fail_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        save_bundle_role_inventory(_simple_inventory(), path)

    assert path.read_bytes() == b"previous inventory"
    assert list(tmp_path.iterdir()) == [path]
