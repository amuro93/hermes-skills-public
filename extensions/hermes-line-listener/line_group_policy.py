"""Canonical LINE quiet-listening and shared-group session policy helper.

Deployment import path: ``gateway.line_group_policy``

Configuration is controlled exclusively via the ``LINE_LISTENER_GROUP_IDS``
environment variable:
- Format: comma-separated exact ``C`` + 32 lowercase hexadecimal characters
  (matching ``^C[0-9a-f]{32}$``).
- Default: empty (``""``), which disables quiet listening and shared-group
  session routing for every group.
- Fail-closed parsing: if any comma-separated entry is empty or malformed,
  the entire configuration value is rejected and an empty frozenset is returned.
- ``LINE_ALLOWED_GROUPS`` is never used as an implicit fallback, because the
  standard reply allowlist is a distinct authorization feature.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, FrozenSet, Optional

logger = logging.getLogger(__name__)

LINE_LISTENER_GROUP_IDS_ENV = "LINE_LISTENER_GROUP_IDS"
_LINE_GROUP_ID_PATTERN = re.compile(r"^C[0-9a-f]{32}$")


def is_valid_line_group_id(value: Any) -> bool:
    """Return True iff *value* is a string matching exact ``^C[0-9a-f]{32}$``."""
    return isinstance(value, str) and bool(_LINE_GROUP_ID_PATTERN.fullmatch(value))


def parse_line_listener_group_ids(raw: Optional[str]) -> FrozenSet[str]:
    """Parse comma-separated LINE group IDs fail-closed.

    Returns an empty frozenset when *raw* is None, empty, whitespace-only, or
    contains any malformed entry (rejecting the entire value).
    """
    if raw is None or not isinstance(raw, str):
        return frozenset()
    stripped = raw.strip()
    if not stripped:
        return frozenset()
    parts = [part.strip() for part in stripped.split(",")]
    validated: list[str] = []
    for part in parts:
        if not is_valid_line_group_id(part):
            logger.warning(
                "LINE: rejecting malformed %s configuration (invalid group ID entry %r)",
                LINE_LISTENER_GROUP_IDS_ENV,
                part,
            )
            return frozenset()
        validated.append(part)
    return frozenset(validated)


def get_configured_line_listener_groups() -> FrozenSet[str]:
    """Return the currently configured set of LINE listener group IDs from env."""
    raw = os.environ.get(LINE_LISTENER_GROUP_IDS_ENV, "")
    return parse_line_listener_group_ids(raw)


def is_configured_line_listener_group(chat_id: Any) -> bool:
    """Return True iff *chat_id* is an explicitly configured LINE listener group."""
    if not isinstance(chat_id, str) or not chat_id:
        return False
    return chat_id in get_configured_line_listener_groups()


def is_approved_line_shared_group(source: Any) -> bool:
    """Central predicate checking whether a SessionSource qualifies for shared group routing.

    Invariants:
    - ``getattr(source, 'shared_group', None) is True`` (strict boolean literal True)
    - ``getattr(getattr(source, 'platform', None), 'value', None) == 'line'``
    - ``getattr(source, 'chat_type', None) == 'group'``
    - ``source.chat_id`` is in the explicitly configured ``LINE_LISTENER_GROUP_IDS`` set
    """
    if getattr(source, "shared_group", None) is not True:
        return False
    platform = getattr(source, "platform", None)
    if getattr(platform, "value", None) != "line":
        return False
    if getattr(source, "chat_type", None) != "group":
        return False
    chat_id = getattr(source, "chat_id", None)
    if not is_configured_line_listener_group(chat_id):
        return False
    return True


def restore_line_shared_group_flag(source: Any) -> bool:
    """Trusted native-admission helper: sets ``source.shared_group = True`` ONLY when
    *source* has ``platform.value == 'line'``, ``chat_type == 'group'``, and ``chat_id``
    in the configured ``LINE_LISTENER_GROUP_IDS`` set.

    Never mutates ``user_id``, ``profile``, ``chat_id``, or any other attribute.
    Returns True if ``shared_group`` was set to True, False otherwise.
    """
    platform = getattr(source, "platform", None)
    if getattr(platform, "value", None) != "line":
        return False
    if getattr(source, "chat_type", None) != "group":
        return False
    chat_id = getattr(source, "chat_id", None)
    if not is_configured_line_listener_group(chat_id):
        return False
    source.shared_group = True
    return True
