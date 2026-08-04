import json
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Union, cast

from pydantic import Discriminator, Tag, TypeAdapter, ValidationError

from app.promotions import PROMOTION_REGISTRY, Promotion


class SeedLoadError(ValueError):
    """A promotion seed file or payload could not be loaded.

    Raised for unreadable files, invalid JSON, unknown `type` keys, invalid
    kind config, and duplicate promotion ids — the loader fails loud rather
    than skipping bad entries.
    """


def _seed_entry_type(entry: object) -> str | None:
    """Extract the `type` discriminator from one raw seed entry.

    Args:
        entry: One element of the seed array, as parsed from JSON.

    Returns:
        The entry's `type` string, or None when the entry is not a mapping or
        carries no string `type` — Pydantic then reports the standard
        missing-discriminator validation error instead of this helper raising.
    """
    if isinstance(entry, Mapping):
        type_key = cast(Mapping[object, object], entry).get("type")
        if isinstance(type_key, str):
            return type_key
    return None


def _registry_adapter() -> TypeAdapter[list[Promotion]]:
    """Build the seed-validation union from the current promotion registry.

    Constructed from `PROMOTION_REGISTRY` on every call — never a
    hand-maintained `Union[...]` — so a kind registered at any time, from any
    module, round-trips with no loader edits (the contained-change property in
    docs/promotion-abstraction-spec.md). Registry keys are sorted so the built
    union is deterministic regardless of registration order.

    Returns:
        A `TypeAdapter` validating a list of seed entries, discriminated on
        each entry's `type` key.

    Raises:
        SeedLoadError: If no promotion kinds are registered — there is
            nothing any seed entry could validate into.
    """
    if not PROMOTION_REGISTRY:
        raise SeedLoadError(
            "no promotion kinds registered; cannot validate seed entries"
        )
    members = tuple(
        Annotated[cls, Tag(type_key)]
        for type_key, cls in sorted(PROMOTION_REGISTRY.items())
    )
    # Union[<single member>] is invalid at runtime, so special-case size one.
    union: Any = members[0] if len(members) == 1 else Union[members]  # noqa: UP007
    entry: Any = Annotated[union, Discriminator(_seed_entry_type)]
    return cast(TypeAdapter[list[Promotion]], TypeAdapter(list[entry]))


def parse_promotions(data: object) -> list[Promotion]:
    """Validate parsed seed data into concrete promotion instances.

    Args:
        data: The parsed seed payload — must be a list of mappings, each with
            a `type` key naming a registered kind plus that kind's fields.

    Returns:
        One promotion instance per entry, in seed order, each an instance of
        the registered class its `type` names.

    Raises:
        SeedLoadError: If the payload is not a list, an entry's `type` is
            missing or not registered, a kind's own fields fail validation,
            or two entries share an `id`.
    """
    adapter = _registry_adapter()
    try:
        promotions = adapter.validate_python(data)
    except ValidationError as exc:
        raise SeedLoadError(f"invalid promotion seed data: {exc}") from exc
    ids = [promotion.id for promotion in promotions]
    if len(ids) != len(set(ids)):
        raise SeedLoadError("promotion seed entries must have unique ids")
    return promotions


def load_promotions(path: Path) -> list[Promotion]:
    """Load a JSON seed file into concrete promotion instances.

    The file holds a top-level JSON array; each entry carries a `type` key
    naming a registered kind (docs/seed-promotions.md's Type column) plus
    that kind's own fields. JSON over YAML: it needs no new runtime
    dependency and the seed set is small enough that comments aren't missed.

    Args:
        path: Path to the seed file.

    Returns:
        One promotion instance per entry, in file order.

    Raises:
        SeedLoadError: If the file cannot be read, is not valid JSON, or its
            entries fail `parse_promotions` validation.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SeedLoadError(f"cannot read promotion seed file {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SeedLoadError(
            f"promotion seed file {path} is not valid JSON: {exc}"
        ) from exc
    try:
        return parse_promotions(data)
    except SeedLoadError as exc:
        raise SeedLoadError(f"promotion seed file {path}: {exc}") from exc
