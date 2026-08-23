"""Immutable, checksummed on-disk store for durable SHADOW work payloads."""

from __future__ import annotations

import errno
import hashlib
import hmac
import json
import math
import os
import re
import uuid
from collections.abc import Callable
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from src.execution.shadow_loop import DurableShadowQueue, ShadowWork

SHADOW_WORK_SCHEMA_VERSION = 1
SHADOW_WORK_URI_SCHEME = "shadow-work:"

# os.O_NOFOLLOW does not exist on Windows (typeshed gates it behind
# `sys.platform != "win32"`, so a direct `os.O_NOFOLLOW` reference is also a
# static-analysis problem there, not just a runtime AttributeError) -
# getattr() with a default sidesteps that structurally rather than needing
# an `if` per platform. On POSIX/Ubuntu (the deployment target) this is
# still the real flag: ORing 0 into the open() flags is a no-op there, so
# protection on the target platform is unchanged (Cycle 6 remediation).
_NOFOLLOW_OPEN_FLAG: int = getattr(os, "O_NOFOLLOW", 0)
# A local flag rather than checking os.name directly at the call site so
# tests can flip just this module's behavior without mutating the
# process-wide os.name (which pathlib itself also reads - mutating it
# globally breaks Path() everywhere, including inside pytest itself).
_IS_WINDOWS: bool = os.name == "nt"

# No '/' or '\\' is permitted, so the observation id can never encode a
# directory traversal: the resolved path is always base_dir / f"{id}.json".
_OBSERVATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")


class ShadowWorkStoreError(RuntimeError):
    """Raised when a shadow work payload cannot be trusted or located."""


def build_shadow_work_uri(observation_id: str) -> str:
    if not _OBSERVATION_ID_PATTERN.match(observation_id):
        raise ShadowWorkStoreError(f"invalid shadow work observation id: {observation_id!r}")
    return f"{SHADOW_WORK_URI_SCHEME}{observation_id}"


def parse_shadow_work_uri(uri: str) -> str:
    if not uri.startswith(SHADOW_WORK_URI_SCHEME):
        raise ShadowWorkStoreError(f"unsupported shadow work URI scheme: {uri!r}")
    observation_id = uri[len(SHADOW_WORK_URI_SCHEME) :]
    if not _OBSERVATION_ID_PATTERN.match(observation_id):
        raise ShadowWorkStoreError(f"invalid shadow work observation id in URI: {uri!r}")
    return observation_id


class ShadowWorkStore:
    """Single allowed base directory; one immutable file per observation id."""

    def __init__(
        self,
        base_dir: Path,
        *,
        now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
        clock_skew_tolerance_seconds: float = 5.0,
    ) -> None:
        given = Path(base_dir)
        if given.is_symlink():
            raise ShadowWorkStoreError(f"shadow work base directory must not be a symlink: {given}")
        resolved = given.resolve(strict=True)
        if not resolved.is_dir():
            raise ShadowWorkStoreError(f"shadow work base directory is not a directory: {resolved}")
        self.base_dir = resolved
        self._now_fn = now_fn
        self._clock_skew_tolerance_seconds = clock_skew_tolerance_seconds

    def write(self, work: ShadowWork, *, written_at_utc: datetime) -> str:
        uri = build_shadow_work_uri(work.observation_id)
        path = self._path_for(work.observation_id)
        envelope = {
            "schema_version": SHADOW_WORK_SCHEMA_VERSION,
            "observation_id": work.observation_id,
            "written_at_utc": _utc(written_at_utc, "shadow work written_at_utc").isoformat(),
            "payload_sha256": _digest(to_json_safe(work)),
            "payload": to_json_safe(work),
        }
        encoded = (_canonical_dumps(envelope) + "\n").encode("utf-8")

        if path.is_symlink():
            raise ShadowWorkStoreError(f"refusing to write over a symlink: {path}")
        if path.exists():
            existing = _read_no_symlink(path)
            if existing == encoded:
                return uri
            raise ShadowWorkStoreError(
                "immutable shadow payload already exists with different content: "
                f"{work.observation_id}"
            )
        _atomic_write_immutable(path, encoded)
        return uri

    def load(self, uri: str) -> ShadowWork:
        observation_id = parse_shadow_work_uri(uri)
        path = self._path_for(observation_id)
        if path.parent != self.base_dir:
            raise ShadowWorkStoreError("shadow work path escapes the allowed base directory")

        raw = _read_no_symlink(path)
        try:
            envelope = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ShadowWorkStoreError(f"shadow work payload is not valid JSON: {path}") from exc
        if not isinstance(envelope, dict):
            raise ShadowWorkStoreError("shadow work envelope must be a JSON object")

        schema_version = envelope.get("schema_version")
        if schema_version != SHADOW_WORK_SCHEMA_VERSION:
            raise ShadowWorkStoreError(
                f"unsupported shadow work schema version: {schema_version!r}"
            )
        if envelope.get("observation_id") != observation_id:
            raise ShadowWorkStoreError("shadow work observation id does not match its URI")

        written_at_utc = _parse_iso(envelope.get("written_at_utc"), "shadow work written_at_utc")
        now = self._now_fn()
        if (written_at_utc - now).total_seconds() > self._clock_skew_tolerance_seconds:
            raise ShadowWorkStoreError("shadow work written_at_utc is in the future")

        payload = envelope.get("payload")
        expected_checksum = envelope.get("payload_sha256")
        if not isinstance(expected_checksum, str) or len(expected_checksum) != 64:
            raise ShadowWorkStoreError("shadow work payload checksum is missing or malformed")
        if not hmac.compare_digest(_digest(payload), expected_checksum):
            raise ShadowWorkStoreError(
                f"shadow work payload checksum mismatch (corrupted or altered): {observation_id}"
            )

        work = from_json_safe(ShadowWork, payload)
        if work.observation_id != observation_id:
            raise ShadowWorkStoreError("shadow work payload observation id does not match its URI")
        return work

    def _path_for(self, observation_id: str) -> Path:
        if not _OBSERVATION_ID_PATTERN.match(observation_id):
            raise ShadowWorkStoreError(f"invalid shadow work observation id: {observation_id!r}")
        return self.base_dir / f"{observation_id}.json"


def enqueue_shadow_work(
    *,
    queue: DurableShadowQueue,
    store: ShadowWorkStore,
    work: ShadowWork,
    written_at_utc: datetime,
    available_at_utc: datetime,
) -> bool:
    """Write the immutable payload, then durably enqueue it. Safe to retry."""
    uri = store.write(work, written_at_utc=written_at_utc)
    return queue.enqueue(
        item_id=work.observation_id,
        payload_uri=uri,
        available_at_utc=available_at_utc,
    )


def _read_no_symlink(path: Path) -> bytes:
    if _NOFOLLOW_OPEN_FLAG == 0:
        # No atomic no-follow open available on this platform (Windows) - a
        # best-effort pre-check. This has a TOCTOU race the real O_NOFOLLOW
        # flag below closes on POSIX/Ubuntu, where protection is unchanged.
        try:
            if path.is_symlink():
                raise ShadowWorkStoreError(f"refusing to follow symlink: {path}")
        except OSError as exc:
            if exc.errno == errno.ENOENT:
                raise ShadowWorkStoreError(f"shadow work payload not found: {path}") from exc
            raise
    try:
        descriptor = os.open(path, os.O_RDONLY | _NOFOLLOW_OPEN_FLAG)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ShadowWorkStoreError(f"refusing to follow symlink: {path}") from exc
        if exc.errno == errno.ENOENT:
            raise ShadowWorkStoreError(f"shadow work payload not found: {path}") from exc
        raise
    with os.fdopen(descriptor, "rb") as handle:
        return handle.read()


def _fsync_directory(path: Path) -> None:
    """No directory file descriptors on Windows - fsync-ing one raises
    there, so this is a deliberate, documented no-op on that platform
    rather than a crash. POSIX/Ubuntu (the deployment target) is unchanged:
    this still fsyncs the directory entry so a completed rename in
    `_atomic_write_immutable` cannot be lost to a crash before the parent
    directory's own metadata is durable.
    """
    if _IS_WINDOWS:
        return
    directory_descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)


def _atomic_write_immutable(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o640)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    os.chmod(path, 0o440)
    _fsync_directory(path.parent)


def _canonical_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_dumps(value).encode("utf-8")).hexdigest()


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ShadowWorkStoreError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _parse_iso(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise ShadowWorkStoreError(f"{name} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ShadowWorkStoreError(f"{name} is not a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ShadowWorkStoreError(f"{name} must be timezone-aware")
    return parsed.astimezone(UTC)


# --- Generic, reflection-based (de)serialization for the frozen dataclass
# graphs used by SHADOW work (MetaDecision, SetupDecision, portfolio
# proposals, ...). Kept generic rather than hand-mapped per type so the store
# stays correct as those engine contracts evolve.


def to_json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return _utc(value, "dataclass timestamp field").isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: to_json_safe(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, tuple):
        return [to_json_safe(item) for item in value]
    if isinstance(value, bool):
        return value
    if isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ShadowWorkStoreError("shadow work payload cannot contain non-finite numbers")
        return value
    raise ShadowWorkStoreError(f"unsupported shadow work payload type: {type(value)!r}")


def from_json_safe(target_type: Any, value: Any) -> Any:
    origin = get_origin(target_type)

    if origin is tuple:
        args = get_args(target_type)
        if not isinstance(value, list):
            raise ShadowWorkStoreError("shadow work payload expected a list for a tuple field")
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(from_json_safe(args[0], item) for item in value)
        if len(value) != len(args):
            raise ShadowWorkStoreError("shadow work payload tuple has the wrong arity")
        return tuple(
            from_json_safe(item_type, item)
            for item_type, item in zip(args, value, strict=True)
        )

    if origin is Union or origin is UnionType:
        options = [option for option in get_args(target_type) if option is not type(None)]
        if value is None:
            if len(options) == len(get_args(target_type)):
                raise ShadowWorkStoreError("shadow work payload field cannot be null")
            return None
        return from_json_safe(options[0], value)

    if isinstance(target_type, type) and is_dataclass(target_type):
        if not isinstance(value, dict):
            raise ShadowWorkStoreError(
                f"shadow work payload expected an object for {target_type!r}"
            )
        declared = fields(target_type)
        expected_names = {field.name for field in declared}
        if set(value.keys()) != expected_names:
            raise ShadowWorkStoreError(
                f"shadow work payload fields do not match {target_type.__name__}"
            )
        hints = get_type_hints(target_type)
        try:
            kwargs = {
                field.name: from_json_safe(hints[field.name], value[field.name])
                for field in declared
            }
            return target_type(**kwargs)
        except (TypeError, ValueError) as exc:
            raise ShadowWorkStoreError(
                f"shadow work payload is not a valid {target_type.__name__}: {exc}"
            ) from exc

    if isinstance(target_type, type) and issubclass(target_type, Enum):
        try:
            return target_type(value)
        except ValueError as exc:
            raise ShadowWorkStoreError(
                f"invalid enum value for {target_type.__name__}: {value!r}"
            ) from exc

    if target_type is datetime:
        return _parse_iso(value, "shadow work payload timestamp")

    if target_type is bool:
        if not isinstance(value, bool):
            raise ShadowWorkStoreError("shadow work payload expected a boolean")
        return value

    if target_type is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ShadowWorkStoreError("shadow work payload expected a number")
        return float(value)

    if target_type is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ShadowWorkStoreError("shadow work payload expected an integer")
        return value

    if target_type is str:
        if not isinstance(value, str):
            raise ShadowWorkStoreError("shadow work payload expected a string")
        return value

    raise ShadowWorkStoreError(f"unsupported shadow work field type: {target_type!r}")
