"""LINE Group Quiet-Listening Inbox (group_inbox.py).

Implements:
1. `is_bot_mentioned`: Pure predicate for live LINE webhook mention structures.
2. `GroupInbox`: SQLite storage for per-group quiet-listening message buffering,
   immutable snapshotting with bounded chars, tagged security envelope,
   monotonic acknowledgment, deduplication across restarts, and retention cleanup.
"""

from __future__ import annotations

import contextlib
import datetime
from dataclasses import dataclass
import math
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Iterator, Optional, Tuple, Union


# ---------------------------------------------------------------------------
# Mentions
# ---------------------------------------------------------------------------

def is_bot_mentioned(message: Any, bot_user_id: Optional[str] = None) -> bool:
    """Check if the bot is mentioned in a LINE message event.

    Pure function.
    Live LINE mention structure:
      message.mention.mentionees = [{"index": 0, "length": 3, "type": "user", "isSelf": True}]

    Rules:
    - isSelf must be boolean True OR type must be 'user' with exact nonempty bot userId match.
    - @all (type: 'all') must not trigger.
    - Malformed values fail closed (return False).
    """
    if not isinstance(message, dict):
        return False

    try:
        mention = message.get("mention")
        if not isinstance(mention, dict):
            return False

        mentionees = mention.get("mentionees")
        if not isinstance(mentionees, list):
            return False

        clean_bot_id = (
            str(bot_user_id).strip()
            if isinstance(bot_user_id, str) and bot_user_id.strip()
            else None
        )

        for item in mentionees:
            if not isinstance(item, dict):
                continue

            m_type = item.get("type")

            # @all must never trigger
            if m_type == "all":
                continue

            # isSelf must be boolean True (exact bool check, not falsy or truthy integer)
            is_self = item.get("isSelf")
            if type(is_self) is bool and is_self is True:
                return True

            # OR type user with exact nonempty bot userId match
            if m_type == "user" and clean_bot_id is not None:
                user_id = item.get("userId")
                if isinstance(user_id, str) and user_id.strip() == clean_bot_id:
                    return True

        return False
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Errors and Data Models
# ---------------------------------------------------------------------------

class MessageOverflowError(Exception):
    """Raised when an oversize single message cannot fit within max_chars bound."""

    def __init__(
        self,
        message: str,
        *,
        group_id: str,
        seq: int,
        message_id: str,
        size: int,
        max_chars: int,
    ) -> None:
        super().__init__(message)
        self.group_id = group_id
        self.seq = seq
        self.message_id = message_id
        self.size = size
        self.max_chars = max_chars


class InvalidAckError(ValueError):
    """Raised when an acknowledgment violates monotonic or valid batch boundary rules."""
    pass


@dataclass(frozen=True)
class InboxMessage:
    """Immutable representation of a stored group message."""

    seq: int
    group_id: str
    event_id: str
    message_id: str
    user_id: str
    timestamp: float
    kind: str
    text: str


@dataclass(frozen=True)
class PendingBatch:
    """Immutable snapshot of pending group messages."""

    group_id: str
    high_water: int
    messages: Tuple[InboxMessage, ...]
    formatted_text: str
    more_pending: bool

    @property
    def count(self) -> int:
        return len(self.messages)

    def __len__(self) -> int:
        return len(self.messages)

    def __iter__(self) -> Iterator[InboxMessage]:
        return iter(self.messages)


@dataclass(frozen=True)
class SnapshotReceipt:
    """Immutable snapshot boundary receipt."""

    group_id: str
    high_water: int
    created_at: float


@dataclass(frozen=True)
class MessageChunk:
    """A slice of an oversized message text split across or within pages."""

    seq: int
    group_id: str
    event_id: str
    message_id: str
    user_id: str
    timestamp: float
    kind: str
    text: str
    part_index: int = 1
    total_parts: int = 1
    is_continuation: bool = False
    has_more: bool = False
    start_offset: int = 0
    end_offset: int = 0

    @property
    def offset(self) -> int:
        return self.start_offset

    @property
    def text_chunk(self) -> str:
        return self.text


@dataclass(frozen=True)
class HistoryPage:
    """Immutable page of group discussion messages."""

    page_num: int
    start_seq: int
    end_seq: int
    formatted_text: str
    messages: Tuple[Union[InboxMessage, MessageChunk], ...]
    chunks: Tuple[MessageChunk, ...]
    char_count: int

    def __str__(self) -> str:
        return self.formatted_text

    def __len__(self) -> int:
        return len(self.messages)


# ---------------------------------------------------------------------------
# GroupInbox
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Lossless transcript escaping & physical-line wrapping
# ---------------------------------------------------------------------------

#: Marker appended to an artificially wrapped physical line. The marker char
#: U+23CE is ALWAYS entity-escaped inside user-controlled text, so every
#: occurrence of this marker in a rendered page was inserted by the renderer.
WRAP_MARKER = " \u23ce[wrap]"

#: Line-break characters other than LF recognised by ``str.splitlines()`` (and
#: partly by universal-newline readers). They are entity-escaped in rendered
#: transcripts so physical lines are identical under ``split("\n")``,
#: ``splitlines()`` and universal-newline reads.
NON_LF_LINE_BREAKS = "\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029"

_DANGEROUS_TAGS = (
    "</untrusted_group_discussion>",
    "<untrusted_group_discussion>",
    "<system>",
    "</system>",
    "<|im_start|>",
    "<|im_end|>",
    "<|endoftext|>",
)
_ENTITY_BODY = r"(?:lt|gt|amp|#x[0-9a-fA-F]{1,6});"
_ENTITY_RE = re.compile("&" + _ENTITY_BODY)
_ESCAPE_RE = re.compile(
    "|".join(re.escape(tag) for tag in _DANGEROUS_TAGS)
    # A literal '&' is escaped only when it would otherwise read as an entity.
    + "|&(?=" + _ENTITY_BODY + ")"
    # Wrap-marker char and every non-LF line break are always escaped.
    + "|[\u23ce" + NON_LF_LINE_BREAKS + "]"
    # '[' at the start of a payload line could forge a speaker header line.
    + "|(?<=\n)\\["
)


def _escape_repl(match: "re.Match[str]") -> str:
    s = match.group(0)
    if s == "&":
        return "&amp;"
    if len(s) > 1:
        return s.replace("<", "&lt;").replace(">", "&gt;")
    return "&#x%x;" % ord(s)


def _decode_repl(match: "re.Match[str]") -> str:
    s = match.group(0)
    body = s[1:-1]
    if body == "lt":
        return "<"
    if body == "gt":
        return ">"
    if body == "amp":
        return "&"
    cp = int(body[2:], 16)
    if cp > 0x10FFFF:
        return s
    return chr(cp)


def escape_transcript_content(text: str) -> str:
    """Escape delimiter-breakout attempts in untrusted chat transcripts.

    The escaping is lossless: ``decode_transcript_content(escape_transcript_content(x)) == x``
    for every string ``x``. Escaped output never contains a dangerous delimiter tag,
    the wrap-marker character U+23CE, any non-LF line break, or a ``[`` directly after
    a newline (speaker-header forgery). Ordinary text is left unchanged.
    """
    if not text:
        return ""
    return _ESCAPE_RE.sub(_escape_repl, text)


def decode_transcript_content(text: str) -> str:
    """Exact inverse of :func:`escape_transcript_content` (pure data decoding, never executed)."""
    if not text:
        return ""
    return _ENTITY_RE.sub(_decode_repl, text)


escape_delimiters_fn = escape_transcript_content


class GroupInbox:
    """Thread-safe SQLite inbox for LINE group messages."""

    DISCUSSION_HEADER = "<untrusted_group_discussion>\n"
    DISCUSSION_FOOTER = "\n</untrusted_group_discussion>"

    def __init__(
        self,
        db_path: Union[str, Path],
        retention_days: int = 30,
        busy_timeout: float = 10.0,
    ) -> None:
        self.db_path = str(db_path)
        self.retention_days = int(retention_days)
        self.busy_timeout = float(busy_timeout)

        if self.db_path != ":memory:":
            p = Path(self.db_path)
            if p.parent and not p.parent.exists():
                p.parent.mkdir(parents=True, exist_ok=True)

        self._init_db()

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open a single SQLite connection with busy timeout and WAL mode, closing explicitly."""
        conn = sqlite3.connect(self.db_path, timeout=self.busy_timeout)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(f"PRAGMA busy_timeout = {int(self.busy_timeout * 1000)}")
            if self.db_path != ":memory:":
                conn.execute("PRAGMA journal_mode = WAL")
                conn.execute("PRAGMA synchronous = NORMAL")
            yield conn
        finally:
            conn.close()

    @contextlib.contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        """Thread-safe transaction context using BEGIN IMMEDIATE to avoid writer deadlocks."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except Exception:
                with contextlib.suppress(Exception):
                    conn.rollback()
                raise

    def _init_db(self) -> None:
        """Initialize SQLite database tables and indices."""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS group_meta (
                    group_id TEXT PRIMARY KEY,
                    last_seq INTEGER NOT NULL DEFAULT 0,
                    ack_high_water INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    event_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    kind TEXT NOT NULL,
                    text TEXT NOT NULL,
                    acked INTEGER NOT NULL DEFAULT 0,
                    acked_at REAL,
                    created_at REAL NOT NULL,
                    UNIQUE(group_id, event_id),
                    UNIQUE(group_id, seq)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_pending
                ON messages (group_id, acked, seq)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS snapshot_boundaries (
                    group_id TEXT NOT NULL,
                    high_water INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (group_id, high_water)
                )
            """)
            conn.commit()

    @staticmethod
    def _format_message_line(msg: InboxMessage) -> str:
        """Format single message with speaker ID, UTC timestamp, kind and text."""
        try:
            val = float(msg.timestamp)
            if val > 1e11:  # milliseconds timestamp from LINE
                val /= 1000.0
            dt = datetime.datetime.fromtimestamp(val, tz=datetime.timezone.utc)
            time_str = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        except Exception:
            time_str = str(msg.timestamp)

        if msg.kind and msg.kind != "text":
            return f"[{time_str}] [{msg.user_id}] ({msg.kind}): {msg.text}"
        return f"[{time_str}] [{msg.user_id}]: {msg.text}"

    @staticmethod
    def _format_chunk_line(
        msg: Union[InboxMessage, MessageChunk],
        chunk_text: Optional[str] = None,
        part_index: int = 1,
        total_parts: int = 1,
        escape_delimiters: bool = True,
    ) -> str:
        try:
            val = float(msg.timestamp)
            if val > 1e11:  # milliseconds timestamp from LINE
                val /= 1000.0
            dt = datetime.datetime.fromtimestamp(val, tz=datetime.timezone.utc)
            time_str = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        except Exception:
            time_str = str(msg.timestamp)

        txt = chunk_text if chunk_text is not None else msg.text
        uid = str(msg.user_id)
        kind = str(msg.kind)
        if escape_delimiters:
            txt = escape_transcript_content(txt)
            uid = escape_transcript_content(uid)
            kind = escape_transcript_content(kind)

        if total_parts > 1:
            cont_label = " continuation" if part_index > 1 else ""
            part_info = f" [seq {msg.seq} part {part_index}/{total_parts}{cont_label}]"
        else:
            part_info = ""

        if msg.kind and msg.kind != "text":
            return f"[{time_str}] [{uid}] ({kind}){part_info}: {txt}"
        return f"[{time_str}] [{uid}]{part_info}: {txt}"

    def append(
        self,
        group_id: str,
        event_id: str,
        message_id: str,
        user_id: str,
        timestamp: Optional[Union[float, int]] = None,
        kind: str = "text",
        text: str = "",
    ) -> bool:
        """Append an incoming group message.

        event_id is unique per group for deduplication.
        Normalizes millisecond timestamps (> 1e11) to seconds.
        Rejects non-finite timestamps (NaN, Inf).

        Returns:
            True if inserted, False if already exists in group (duplicate).
        """
        if not group_id or not isinstance(group_id, str):
            raise ValueError("group_id must be a non-empty string")
        if not event_id or not isinstance(event_id, str):
            raise ValueError("event_id must be a non-empty string")

        if timestamp is not None:
            try:
                ts = float(timestamp)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"timestamp must be a finite number, got {timestamp!r}") from exc
            if math.isnan(ts) or math.isinf(ts):
                raise ValueError(f"timestamp must be a finite number, got {timestamp!r}")
            if ts > 1e11:  # LINE millisecond timestamp
                ts /= 1000.0
        else:
            ts = time.time()

        now = time.time()
        k = str(kind) if kind is not None else "text"
        txt = str(text) if text is not None else ""
        mid = str(message_id) if message_id is not None else ""
        uid = str(user_id) if user_id is not None else ""

        with self._transaction() as conn:
            # Check deduplication
            cur = conn.execute(
                "SELECT 1 FROM messages WHERE group_id = ? AND event_id = ?",
                (group_id, event_id),
            )
            if cur.fetchone() is not None:
                return False

            # Monotonically increment per-group sequence
            conn.execute(
                """
                INSERT INTO group_meta (group_id, last_seq, ack_high_water)
                VALUES (?, 1, 0)
                ON CONFLICT(group_id) DO UPDATE SET last_seq = last_seq + 1
                """,
                (group_id,),
            )
            cur = conn.execute(
                "SELECT last_seq FROM group_meta WHERE group_id = ?",
                (group_id,),
            )
            row = cur.fetchone()
            next_seq = row[0]

            conn.execute(
                """
                INSERT INTO messages (
                    group_id, seq, event_id, message_id, user_id, timestamp, kind, text, acked, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (group_id, next_seq, event_id, mid, uid, ts, k, txt, now),
            )
            return True

    def get_sequence(
        self,
        group_id: str,
        *,
        event_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> Optional[int]:
        """Get sequence number for a message in a group by exact event_id or message_id."""
        if not group_id or not isinstance(group_id, str):
            return None
        with self._connect() as conn:
            if event_id is not None:
                cur = conn.execute(
                    "SELECT seq FROM messages WHERE group_id = ? AND event_id = ? LIMIT 1",
                    (group_id, str(event_id)),
                )
            elif message_id is not None:
                cur = conn.execute(
                    "SELECT seq FROM messages WHERE group_id = ? AND message_id = ? ORDER BY seq DESC LIMIT 1",
                    (group_id, str(message_id)),
                )
            else:
                return None
            row = cur.fetchone()
            return row[0] if row else None

    get_seq = get_sequence

    def pending(
        self,
        group_id: str,
        max_chars: int = 24000,
        up_to_seq: Optional[int] = None,
    ) -> PendingBatch:
        """Snapshot pending messages for group fitting within max_chars.

        If up_to_seq is provided, only messages with seq <= up_to_seq are considered.

        Returns an immutable PendingBatch with:
        - high_water integer sequence
        - formatted text tagged <untrusted_group_discussion> with speaker IDs and time
        - oldest messages fitting bound
        - explicit more_pending flag
        Never silently truncates or drops messages.
        If an oversize single message cannot fit within max_chars, raises MessageOverflowError
        without marking it consumed.
        """
        if not group_id or not isinstance(group_id, str):
            raise ValueError("group_id must be a non-empty string")
        if not isinstance(max_chars, int) or max_chars <= 0:
            raise ValueError("max_chars must be a positive integer")
        if up_to_seq is not None:
            if not isinstance(up_to_seq, int) or up_to_seq <= 0:
                raise ValueError("up_to_seq must be a positive integer")

        with self._transaction() as conn:
            cur = conn.execute(
                "SELECT ack_high_water FROM group_meta WHERE group_id = ?",
                (group_id,),
            )
            row = cur.fetchone()
            ack_high_water = row[0] if row else 0

            if up_to_seq is not None:
                cur = conn.execute(
                    """
                    SELECT seq, group_id, event_id, message_id, user_id, timestamp, kind, text
                    FROM messages
                    WHERE group_id = ? AND acked = 0 AND seq <= ?
                    ORDER BY seq ASC
                    """,
                    (group_id, up_to_seq),
                )
            else:
                cur = conn.execute(
                    """
                    SELECT seq, group_id, event_id, message_id, user_id, timestamp, kind, text
                    FROM messages
                    WHERE group_id = ? AND acked = 0
                    ORDER BY seq ASC
                    """,
                    (group_id,),
                )
            rows = cur.fetchall()

            if not rows:
                return PendingBatch(
                    group_id=group_id,
                    high_water=ack_high_water,
                    messages=(),
                    formatted_text="",
                    more_pending=False,
                )

            base_overhead = len(self.DISCUSSION_HEADER) + len(self.DISCUSSION_FOOTER)
            if max_chars < base_overhead:
                first = rows[0]
                raise MessageOverflowError(
                    f"max_chars ({max_chars}) is too small to fit discussion envelope ({base_overhead} chars)",
                    group_id=group_id,
                    seq=first[0],
                    message_id=first[3],
                    size=base_overhead,
                    max_chars=max_chars,
                )

            messages_to_include: list[InboxMessage] = []
            lines: list[str] = []
            current_content_chars = 0
            more_pending = False

            for idx, r in enumerate(rows):
                msg = InboxMessage(
                    seq=r[0],
                    group_id=r[1],
                    event_id=r[2],
                    message_id=r[3],
                    user_id=r[4],
                    timestamp=r[5],
                    kind=r[6],
                    text=r[7],
                )
                line = self._format_message_line(msg)
                line_len = len(line)

                if idx == 0:
                    # Oldest single message
                    total_needed = base_overhead + line_len
                    if total_needed > max_chars:
                        raise MessageOverflowError(
                            f"Single message {msg.message_id} (seq {msg.seq}) requires {total_needed} chars, exceeding max_chars={max_chars}",
                            group_id=group_id,
                            seq=msg.seq,
                            message_id=msg.message_id,
                            size=total_needed,
                            max_chars=max_chars,
                        )
                    messages_to_include.append(msg)
                    lines.append(line)
                    current_content_chars = line_len
                else:
                    # Subsequent messages add newline delimiter
                    total_needed = base_overhead + current_content_chars + 1 + line_len
                    if total_needed <= max_chars:
                        messages_to_include.append(msg)
                        lines.append(line)
                        current_content_chars += 1 + line_len
                    else:
                        more_pending = True
                        break

            if len(messages_to_include) < len(rows):
                more_pending = True

            high_water = messages_to_include[-1].seq
            formatted_text = (
                f"{self.DISCUSSION_HEADER}"
                + "\n".join(lines)
                + f"{self.DISCUSSION_FOOTER}"
            )

            # Persist valid snapshot boundary
            now = time.time()
            conn.execute(
                """
                INSERT OR REPLACE INTO snapshot_boundaries (group_id, high_water, created_at)
                VALUES (?, ?, ?)
                """,
                (group_id, high_water, now),
            )

            return PendingBatch(
                group_id=group_id,
                high_water=high_water,
                messages=tuple(messages_to_include),
                formatted_text=formatted_text,
                more_pending=more_pending,
            )

    def ack(self, group_id: str, high_water: int, *, strict: bool = False) -> bool:
        """Acknowledge processed messages up to high_water.

        Rules:
        - Advances monotonically only.
        - Must match a valid snapshot batch boundary.
        - No new message arriving after snapshot may be acknowledged.
        - Failure to ack leaves batch pending.

        Returns True on success. If boundary is invalid, returns False (or raises
        InvalidAckError if strict=True).
        """
        if not group_id or not isinstance(group_id, str):
            if strict:
                raise InvalidAckError("group_id must be a non-empty string")
            return False
        if not isinstance(high_water, int) or high_water <= 0:
            if strict:
                raise InvalidAckError(f"high_water must be a positive integer, got {high_water}")
            return False

        with self._transaction() as conn:
            cur = conn.execute(
                "SELECT ack_high_water FROM group_meta WHERE group_id = ?",
                (group_id,),
            )
            row = cur.fetchone()
            current_ack = row[0] if row else 0

            # Monotonic advancement check
            if high_water <= current_ack:
                if strict:
                    raise InvalidAckError(
                        f"high_water ({high_water}) does not advance monotonically past current_ack ({current_ack})"
                    )
                return False

            # Valid batch boundary check (prevents post-snapshot arrivals or arbitrary sequences from being acked)
            cur = conn.execute(
                """
                SELECT 1 FROM snapshot_boundaries
                WHERE group_id = ? AND high_water = ?
                """,
                (group_id, high_water),
            )
            if cur.fetchone() is None:
                if strict:
                    raise InvalidAckError(
                        f"high_water {high_water} is not a valid snapshot boundary for group {group_id}"
                    )
                return False

            now = time.time()

            conn.execute(
                """
                UPDATE messages
                SET acked = 1, acked_at = ?
                WHERE group_id = ? AND seq <= ? AND acked = 0
                """,
                (now, group_id, high_water),
            )
            conn.execute(
                """
                UPDATE group_meta
                SET ack_high_water = ?
                WHERE group_id = ?
                """,
                (high_water, group_id),
            )
            # Remove snapshot boundaries that are now settled
            conn.execute(
                """
                DELETE FROM snapshot_boundaries
                WHERE group_id = ? AND high_water <= ?
                """,
                (group_id, high_water),
            )
            return True

    def cleanup(
        self,
        older_than_days: Optional[int] = None,
        *,
        now: Optional[float] = None,
    ) -> int:
        """Delete acknowledged messages older than retention period.

        Never deletes unprocessed (unacknowledged) messages regardless of age.
        Returns number of deleted rows.
        """
        days = older_than_days if older_than_days is not None else self.retention_days
        current_time = float(now) if now is not None else time.time()
        cutoff_ts = current_time - (days * 86400.0)

        with self._transaction() as conn:
            cur = conn.execute(
                """
                DELETE FROM messages
                WHERE acked = 1 AND timestamp < ?
                """,
                (cutoff_ts,),
            )
            deleted = cur.rowcount

            conn.execute(
                "DELETE FROM snapshot_boundaries WHERE created_at < ?",
                (cutoff_ts,),
            )
            return deleted

    def get_ack_high_water(self, group_id: str) -> int:
        """Inspect current acknowledged high-water mark for group."""
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT ack_high_water FROM group_meta WHERE group_id = ?",
                (group_id,),
            )
            row = cur.fetchone()
            return row[0] if row else 0

    def get_pending_count(self, group_id: str) -> int:
        """Inspect count of pending (unacknowledged) messages for group."""
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE group_id = ? AND acked = 0",
                (group_id,),
            )
            row = cur.fetchone()
            return row[0] if row else 0

    def register_snapshot_boundary(self, group_id: str, high_water: int) -> SnapshotReceipt:
        """Register an ack boundary for a snapshot cutoff, returning an immutable SnapshotReceipt."""
        if not group_id or not isinstance(group_id, str):
            raise ValueError("group_id must be a non-empty string")
        if not isinstance(high_water, int) or high_water <= 0:
            raise ValueError(f"high_water must be a positive integer, got {high_water}")

        now = time.time()
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO snapshot_boundaries (group_id, high_water, created_at)
                VALUES (?, ?, ?)
                """,
                (group_id, high_water, now),
            )
        return SnapshotReceipt(group_id=group_id, high_water=high_water, created_at=now)

    register_boundary = register_snapshot_boundary

    def get_snapshot_receipt(self, group_id: str, high_water: int) -> Optional[SnapshotReceipt]:
        """Inspect snapshot boundary receipt if registered."""
        if not group_id or not isinstance(group_id, str) or not isinstance(high_water, int) or high_water <= 0:
            return None
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT created_at FROM snapshot_boundaries WHERE group_id = ? AND high_water = ?",
                (group_id, high_water),
            )
            row = cur.fetchone()
            if row:
                return SnapshotReceipt(group_id=group_id, high_water=high_water, created_at=row[0])
        return None

    def iter_messages(
        self,
        group_id: str,
        after_seq: int = 0,
        up_to_seq: Optional[int] = None,
        batch_size: int = 100,
    ) -> Iterator[InboxMessage]:
        """Keyset iterator yielding stored messages bounded to (after_seq, up_to_seq].

        Performs bounded keyset queries in batches of `batch_size` to avoid fetchall of
        an unbounded backlog. Messages are ordered chronologically by seq ASC.
        """
        if not group_id or not isinstance(group_id, str):
            raise ValueError("group_id must be a non-empty string")
        curr_seq = int(after_seq) if after_seq is not None else 0
        limit = max(1, int(batch_size))
        bound = int(up_to_seq) if up_to_seq is not None else None

        while True:
            with self._connect() as conn:
                if bound is not None:
                    cur = conn.execute(
                        """
                        SELECT seq, group_id, event_id, message_id, user_id, timestamp, kind, text
                        FROM messages
                        WHERE group_id = ? AND seq > ? AND seq <= ?
                        ORDER BY seq ASC
                        LIMIT ?
                        """,
                        (group_id, curr_seq, bound, limit),
                    )
                else:
                    cur = conn.execute(
                        """
                        SELECT seq, group_id, event_id, message_id, user_id, timestamp, kind, text
                        FROM messages
                        WHERE group_id = ? AND seq > ?
                        ORDER BY seq ASC
                        LIMIT ?
                        """,
                        (group_id, curr_seq, limit),
                    )
                rows = cur.fetchall()

            if not rows:
                break

            for r in rows:
                msg = InboxMessage(
                    seq=r[0],
                    group_id=r[1],
                    event_id=r[2],
                    message_id=r[3],
                    user_id=r[4],
                    timestamp=r[5],
                    kind=r[6],
                    text=r[7],
                )
                curr_seq = msg.seq
                yield msg

    @staticmethod
    def _slice_with_prefix_budget(full_text: str, budget: int) -> Optional[list[str]]:
        """Split full_text into raw slices whose escaped lengths each fit within budget."""
        if not full_text:
            return [""] if budget >= 0 else None
        if budget < 1:
            return None

        slices: list[str] = []
        curr_idx = 0
        text_len = len(full_text)

        while curr_idx < text_len:
            upper = min(text_len - curr_idx, budget)
            rem_window = full_text[curr_idx : curr_idx + upper]
            if len(escape_transcript_content(rem_window)) <= budget:
                best_k = upper
            else:
                if len(escape_transcript_content(rem_window[:1])) > budget:
                    return None
                low = 1
                high = upper
                best_k = 1
                while low <= high:
                    mid = (low + high) // 2
                    if len(escape_transcript_content(rem_window[:mid])) <= budget:
                        best_k = mid
                        low = mid + 1
                    else:
                        high = mid - 1

            # Avoid splitting a multi-character dangerous tag across chunk boundaries when avoidable
            if curr_idx + best_k < text_len and budget >= 36:
                win_start = max(curr_idx, curr_idx + best_k - 30)
                win_end = min(text_len, curr_idx + best_k + 30)
                for m in _ESCAPE_RE.finditer(full_text, win_start, win_end):
                    if m.start() > curr_idx and m.start() < curr_idx + best_k < m.end():
                        best_k = m.start() - curr_idx
                        break

            slices.append(full_text[curr_idx : curr_idx + best_k])
            curr_idx += best_k

        return slices

    def _split_oversized_message(
        self,
        msg: InboxMessage,
        max_content_chars: int,
        max_chars: int,
    ) -> Tuple[list[str], list[str]]:
        """Split an oversized message into raw text slices and formatted lines <= max_content_chars."""
        full_text = msg.text

        # Tier 1: Full chunk header including [seq ... part i/N continuation] accounting for actual digit count
        for digits in range(1, 7):
            max_t = (10 ** digits) - 1
            worst_prefix_len = len(
                self._format_chunk_line(msg, chunk_text="", part_index=max_t, total_parts=max_t)
            )
            budget = max_content_chars - worst_prefix_len
            if budget < 1:
                break
            candidate_slices = self._slice_with_prefix_budget(full_text, budget)
            if candidate_slices is None:
                break
            if len(candidate_slices) <= max_t:
                total_parts = len(candidate_slices)
                chunk_lines = [
                    self._format_chunk_line(
                        msg,
                        chunk_text=s,
                        part_index=idx,
                        total_parts=total_parts,
                    )
                    for idx, s in enumerate(candidate_slices, 1)
                ]
                return candidate_slices, chunk_lines

        # Tier 2: Standard message header ([timestamp] [uid]: ) when max_chars is too small for part_info
        prefix_no_part = self._format_chunk_line(msg, chunk_text="", part_index=1, total_parts=1)
        budget_no_part = max_content_chars - len(prefix_no_part)
        candidate_slices = self._slice_with_prefix_budget(full_text, budget_no_part)
        if candidate_slices is not None:
            chunk_lines = [
                self._format_chunk_line(msg, chunk_text=s, part_index=1, total_parts=1)
                for s in candidate_slices
            ]
            return candidate_slices, chunk_lines

        # Tier 3: Minimal speaker header ([uid]: ) for very tight max_chars
        compact_prefix = f"[{escape_transcript_content(str(msg.user_id))}]: "
        budget_compact = max_content_chars - len(compact_prefix)
        candidate_slices = self._slice_with_prefix_budget(full_text, budget_compact)
        if candidate_slices is not None:
            chunk_lines = [
                f"{compact_prefix}{escape_transcript_content(s)}"
                for s in candidate_slices
            ]
            return candidate_slices, chunk_lines

        raise ValueError(
            f"max_chars ({max_chars}) is too small to fit formatted message header and content"
        )

    def iter_pages(
        self,
        group_id: str,
        after_seq: Optional[int] = None,
        up_to_seq: Optional[int] = None,
        max_chars: int = 24000,
        batch_size: int = 100,
    ) -> Iterator[HistoryPage]:
        """Read-only keyset iterator yielding immutable HistoryPage batches <= max_chars.

        Bounds iteration to (after_seq, up_to_seq] in chronological order for exact group_id.
        Splits oversize single messages into MessageChunk slices with explicit continuation
        so that no tail is lost and chunks reassemble byte-equivalent original text.
        """
        if not group_id or not isinstance(group_id, str):
            raise ValueError("group_id must be a non-empty string")
        if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars <= 0:
            raise ValueError("max_chars must be a positive integer")

        base_overhead = len(self.DISCUSSION_HEADER) + len(self.DISCUSSION_FOOTER)
        if max_chars <= base_overhead:
            raise ValueError(f"max_chars ({max_chars}) must be greater than envelope overhead ({base_overhead})")

        max_content_chars = max_chars - base_overhead

        start_after = int(after_seq) if after_seq is not None else self.get_ack_high_water(group_id)
        bound_up_to = int(up_to_seq) if up_to_seq is not None else None

        current_lines: list[str] = []
        current_messages: list[Union[InboxMessage, MessageChunk]] = []
        current_chunks: list[MessageChunk] = []
        current_content_len = 0
        current_start_seq: Optional[int] = None
        current_end_seq: Optional[int] = None
        page_num = 1

        for msg in self.iter_messages(group_id, after_seq=start_after, up_to_seq=bound_up_to, batch_size=batch_size):
            single_line = self._format_chunk_line(msg, chunk_text=msg.text, part_index=1, total_parts=1)
            msg_line_len = len(single_line)

            if msg_line_len > max_content_chars:
                slices, chunk_lines = self._split_oversized_message(msg, max_content_chars, max_chars)

                # Flush current page before starting chunked message
                if current_lines:
                    page_text = (
                        f"{self.DISCUSSION_HEADER}"
                        + "\n".join(current_lines)
                        + f"{self.DISCUSSION_FOOTER}"
                    )
                    assert len(page_text) <= max_chars
                    yield HistoryPage(
                        page_num=page_num,
                        start_seq=current_start_seq if current_start_seq is not None else msg.seq,
                        end_seq=current_end_seq if current_end_seq is not None else msg.seq,
                        formatted_text=page_text,
                        messages=tuple(current_messages),
                        chunks=tuple(current_chunks),
                        char_count=len(page_text),
                    )
                    page_num += 1
                    current_lines = []
                    current_messages = []
                    current_chunks = []
                    current_content_len = 0
                    current_start_seq = None
                    current_end_seq = None

                total_parts = len(slices)
                offset_tracker = 0

                for part_idx, (chunk_text, chunk_line) in enumerate(zip(slices, chunk_lines), 1):
                    start_pos = offset_tracker
                    end_pos = start_pos + len(chunk_text)
                    offset_tracker = end_pos

                    chunk = MessageChunk(
                        seq=msg.seq,
                        group_id=msg.group_id,
                        event_id=msg.event_id,
                        message_id=msg.message_id,
                        user_id=msg.user_id,
                        timestamp=msg.timestamp,
                        kind=msg.kind,
                        text=chunk_text,
                        part_index=part_idx,
                        total_parts=total_parts,
                        is_continuation=(part_idx > 1),
                        has_more=(part_idx < total_parts),
                        start_offset=start_pos,
                        end_offset=end_pos,
                    )

                    page_text = (
                        f"{self.DISCUSSION_HEADER}"
                        + chunk_line
                        + f"{self.DISCUSSION_FOOTER}"
                    )
                    assert len(page_text) <= max_chars
                    yield HistoryPage(
                        page_num=page_num,
                        start_seq=msg.seq,
                        end_seq=msg.seq,
                        formatted_text=page_text,
                        messages=(chunk,),
                        chunks=(chunk,),
                        char_count=len(page_text),
                    )
                    page_num += 1
                continue

            # Standard message fitting within max_content_chars
            line_len = msg_line_len

            additional_len = line_len if not current_lines else (1 + line_len)
            if current_content_len + additional_len <= max_content_chars:
                current_lines.append(single_line)
                current_messages.append(msg)
                current_content_len += additional_len
                if current_start_seq is None:
                    current_start_seq = msg.seq
                current_end_seq = msg.seq
            else:
                page_text = (
                    f"{self.DISCUSSION_HEADER}"
                    + "\n".join(current_lines)
                    + f"{self.DISCUSSION_FOOTER}"
                )
                assert len(page_text) <= max_chars
                yield HistoryPage(
                    page_num=page_num,
                    start_seq=current_start_seq if current_start_seq is not None else msg.seq,
                    end_seq=current_end_seq if current_end_seq is not None else msg.seq,
                    formatted_text=page_text,
                    messages=tuple(current_messages),
                    chunks=tuple(current_chunks),
                    char_count=len(page_text),
                )
                page_num += 1
                current_lines = [single_line]
                current_messages = [msg]
                current_chunks = []
                current_content_len = line_len
                current_start_seq = msg.seq
                current_end_seq = msg.seq

        if current_lines:
            page_text = (
                f"{self.DISCUSSION_HEADER}"
                + "\n".join(current_lines)
                + f"{self.DISCUSSION_FOOTER}"
            )
            assert len(page_text) <= max_chars
            yield HistoryPage(
                page_num=page_num,
                start_seq=current_start_seq if current_start_seq is not None else 0,
                end_seq=current_end_seq if current_end_seq is not None else 0,
                formatted_text=page_text,
                messages=tuple(current_messages),
                chunks=tuple(current_chunks),
                char_count=len(page_text),
            )

    iter_history_pages = iter_pages
