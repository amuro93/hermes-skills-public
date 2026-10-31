"""Native admission and roundtrip integration tests for LINE quiet-listening adapter.

Tests cover:
1. Exact envelope _native_metadata whitelist enforcement (WhatsApp whitelist only; rejection of arbitrary LINE metadata).
2. Clean native MessageEvent metadata: verified empty in target LINE mention turns.
3. Native admission roundtrip (snapshot_native -> restore_native):
   - Provenance capture and revalidation.
   - restore_native_source_context trusted hook execution.
   - Shared group flag restored only after valid provenance and authz home check.
   - Session key stability before and after native serialization roundtrip.
4. Multi-user shared session key convergence:
   - Two different participants in approved LINE group produce identical session key.
   - Authentic user IDs are strictly preserved and never mutated.
5. Anti-forgery & boundary security:
   - Forged source dict shared_group is ignored by SessionSource.from_dict.
   - No restored flag for non-approved LINE groups, LINE DMs, or other platforms.
   - Bad provenance fails closed before invoking adapter hook.
   - Adapter hook exception fails closed with RuntimeStoreError.
6. Delivery ledger receipt correlation:
   - send_final_ledgered correlates exact (group_id, message_id) receipt and acks short batch.
   - Paged turn preserves backlog unacknowledged (paged not ack).
   - Regular notices and background tasks without matching receipt cannot ack.
"""

from __future__ import annotations

import asyncio
from copy import copy
from datetime import datetime
import json
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import time
from types import ModuleType, SimpleNamespace
from typing import Any, Dict, List, Optional
import pytest

from hermes_state import SessionDB

_PKG_DIR = Path(__file__).resolve().parent
_PKG_NAME = "line_adapter_bundle"

if _PKG_NAME not in sys.modules:
    _pkg_mod = ModuleType(_PKG_NAME)
    _pkg_mod.__path__ = [str(_PKG_DIR)]
    _pkg_mod.__file__ = str(_PKG_DIR / "__init__.py")
    sys.modules[_PKG_NAME] = _pkg_mod

# ---------------------------------------------------------------------------
# Setup Isolated Modules: candidate policy, ingress, session candidate, envelope
# ---------------------------------------------------------------------------

import gateway
from hermes_state_runtime import RuntimeStoreError
import gateway.session_ingress_media
import gateway.session_authorities

_POLICY_FILE = _PKG_DIR / "line_group_policy.py"
_SESSION_FILE = _PKG_DIR / "session_candidate.py"
_INGRESS_FILE = _PKG_DIR / "ingress_context_candidate.py"
_ENVELOPE_FILE = _PKG_DIR / "envelope_reference.py"

_orig_gw_policy = sys.modules.get("gateway.line_group_policy")
if _orig_gw_policy is not None and getattr(_orig_gw_policy, "__file__", None) == str(_POLICY_FILE):
    _orig_gw_policy = None

_orig_gw_session = sys.modules.get("gateway.session")
if _orig_gw_session is not None and getattr(_orig_gw_session, "__file__", None) == str(_SESSION_FILE):
    _orig_gw_session = None

_orig_gw_ingress = sys.modules.get("gateway.session_ingress_context")
if _orig_gw_ingress is not None and getattr(_orig_gw_ingress, "__file__", None) == str(_INGRESS_FILE):
    _orig_gw_ingress = None

_orig_gw_envelope = sys.modules.get("gateway.session_envelope")
if _orig_gw_envelope is not None and getattr(_orig_gw_envelope, "__file__", None) == str(_ENVELOPE_FILE):
    _orig_gw_envelope = None

# Load candidate line_group_policy under gateway.line_group_policy
_pspec = importlib.util.spec_from_file_location("gateway.line_group_policy", _POLICY_FILE)
policy_candidate = importlib.util.module_from_spec(_pspec)
policy_candidate.__package__ = "gateway"
sys.modules["gateway.line_group_policy"] = policy_candidate
setattr(gateway, "line_group_policy", policy_candidate)
_pspec.loader.exec_module(policy_candidate)

# Load candidate session candidate under gateway.session
_sspec = importlib.util.spec_from_file_location("gateway.session", _SESSION_FILE)
session_candidate = importlib.util.module_from_spec(_sspec)
session_candidate.__package__ = "gateway"
sys.modules["gateway.session"] = session_candidate
setattr(gateway, "session", session_candidate)
_sspec.loader.exec_module(session_candidate)

# Load candidate ingress context candidate under gateway.session_ingress_context
_ispec = importlib.util.spec_from_file_location("gateway.session_ingress_context", _INGRESS_FILE)
ingress_candidate = importlib.util.module_from_spec(_ispec)
ingress_candidate.__package__ = "gateway"
sys.modules["gateway.session_ingress_context"] = ingress_candidate
setattr(gateway, "session_ingress_context", ingress_candidate)
_ispec.loader.exec_module(ingress_candidate)

# Load envelope reference
_espec = importlib.util.spec_from_file_location("gateway.session_envelope", _ENVELOPE_FILE)
envelope_ref = importlib.util.module_from_spec(_espec)
envelope_ref.__package__ = "gateway"
sys.modules["gateway.session_envelope"] = envelope_ref
setattr(gateway, "session_envelope", envelope_ref)
_espec.loader.exec_module(envelope_ref)

# Load adapter_minimal
_ad_file = _PKG_DIR / "adapter_minimal.py"
_aspec = importlib.util.spec_from_file_location("line_adapter_bundle.adapter_minimal", _ad_file)
adapter_mod = importlib.util.module_from_spec(_aspec)
adapter_mod.__package__ = _PKG_NAME
sys.modules["line_adapter_bundle.adapter_minimal"] = adapter_mod
sys.modules["adapter_minimal"] = adapter_mod
_aspec.loader.exec_module(adapter_mod)

LineAdapter = adapter_mod.LineAdapter
# Test-only synthetic group ID (never exported from product code)
APPROVED_LINE_GROUP_ID = "C" + "a" * 32
_AckReceipt = adapter_mod._AckReceipt
GroupInbox = adapter_mod.GroupInbox
Platform = session_candidate.Platform
SessionSource = session_candidate.SessionSource
build_session_key = session_candidate.build_session_key
MessageEvent = envelope_ref.MessageEvent
MessageType = envelope_ref.MessageType

_native_metadata = envelope_ref._native_metadata
_validate_native = envelope_ref._validate_native
snapshot_native = envelope_ref.snapshot_native
restore_native = envelope_ref.restore_native
restore_native_source = envelope_ref.restore_native_source
check_native_route = envelope_ref.check_native_route

native_callback = ingress_candidate.native_callback
register_transport_home = ingress_candidate.register_transport_home
restore_provenance = ingress_candidate.restore_provenance
capture_provenance = ingress_candidate.capture_provenance


@pytest.fixture(scope="module", autouse=True)
def _restore_gateway_modules():
    """Ensure candidate gateway modules are active during this module and restored on teardown."""
    sys.modules["gateway.line_group_policy"] = policy_candidate
    setattr(gateway, "line_group_policy", policy_candidate)
    sys.modules["gateway.session"] = session_candidate
    setattr(gateway, "session", session_candidate)
    sys.modules["gateway.session_ingress_context"] = ingress_candidate
    setattr(gateway, "session_ingress_context", ingress_candidate)
    sys.modules["gateway.session_envelope"] = envelope_ref
    setattr(gateway, "session_envelope", envelope_ref)
    yield
    for mod_name, attr_name, orig in (
        ("gateway.line_group_policy", "line_group_policy", _orig_gw_policy),
        ("gateway.session", "session", _orig_gw_session),
        ("gateway.session_ingress_context", "session_ingress_context", _orig_gw_ingress),
        ("gateway.session_envelope", "session_envelope", _orig_gw_envelope),
    ):
        if orig is not None:
            sys.modules[mod_name] = orig
            setattr(gateway, attr_name, orig)
        else:
            sys.modules.pop(mod_name, None)
            if hasattr(gateway, attr_name):
                delattr(gateway, attr_name)


@pytest.fixture(autouse=True)
def _configure_listener_group_env(monkeypatch):
    """Explicitly configure synthetic listener group in env so tests never depend on host config."""
    monkeypatch.setenv("LINE_LISTENER_GROUP_IDS", APPROVED_LINE_GROUP_ID)


# ---------------------------------------------------------------------------
# Test Harness & Runner Binding
# ---------------------------------------------------------------------------

class FakeSessionStore:
    """Minimal session store implementing key generation and entry lookup."""

    def __init__(self, key_generator):
        self._gen_key = key_generator
        self._entries: dict[str, Any] = {}

    def _generate_session_key(self, source: SessionSource) -> str:
        return self._gen_key(source)

    def lookup_by_session_key(self, key: str) -> Optional[Any]:
        if key not in self._entries:
            self._entries[key] = SimpleNamespace(
                session_id=f"sess_{hash(key) & 0xFFFFFFFF:08x}",
                session_key=key,
            )
        return self._entries[key]


class MinimalRunner:
    """Minimal runner fixture providing exact owned-adapter and session bindings."""

    def __init__(self, adapter: LineAdapter, transport_home: Path, session_db: Optional[Any] = None):
        self.adapter = adapter
        self.transport_home = transport_home
        self.adapters = {Platform("line"): adapter}
        self._profile_adapters: dict[str, dict[Any, Any]] = {}
        self.config = SimpleNamespace(multiplex_profiles=False, profile_routes=[])
        if session_db is not None:
            self.session_db = session_db
        else:
            self.session_db = SessionDB(db_path=transport_home / "state.db", read_only=False)
        self.session_authority = SimpleNamespace(db=self.session_db, db_path=str(transport_home / "state.db"))
        self.session_store = FakeSessionStore(build_session_key)
        self._native_transport_homes: dict[Optional[str], Path] = {}

        register_transport_home(self, None, transport_home)

    def close(self) -> None:
        if getattr(self, "session_db", None) is not None:
            try:
                self.session_db.close()
            except Exception:
                pass

    def _adapter_for_source(self, source: SessionSource) -> Optional[LineAdapter]:
        if getattr(source, "platform", None) == Platform("line"):
            return self.adapter
        return None

    def _adapter_credential_fingerprint(self, adapter: Any) -> Optional[str]:
        return "adapter:line:test_credential_fingerprint"

    def _transport_owner(self, source: SessionSource) -> Optional[tuple[LineAdapter, Optional[str]]]:
        if getattr(source, "platform", None) == Platform("line"):
            return (self.adapter, None)
        return None

    def _is_user_authorized_for_source(self, source: SessionSource, allow_adapter_delegation: bool = False) -> bool:
        return True

    def _adapter_flag(self, platform: Any, flag: str, profile: Any) -> bool:
        return False

    def _adapter_profile_for_source(self, source: SessionSource) -> Optional[str]:
        return None


@pytest.fixture
def admission_env():
    """Builds clean isolated testing environment with minimal runner and transport home."""
    scratch_root = os.environ.get("TMPDIR")
    if not scratch_root:
        scratch_root = _PKG_DIR / "scratch"
    scratch_path = Path(scratch_root)
    scratch_path.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=str(scratch_path)) as tmp_dir:
        home_path = Path(tmp_dir) / "hermes_home"
        home_path.mkdir(parents=True, exist_ok=True)

        db_path = home_path / "data" / "line_group_inbox.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        inbox = GroupInbox(db_path)

        cfg = SimpleNamespace(
            extra={
                "channel_access_token": "test_access_token",
                "channel_secret": "test_channel_secret",
            }
        )
        adapter = LineAdapter(config=cfg, group_inbox=inbox)
        adapter.allow_all = True
        adapter._bot_user_id = "U_BOT_HERMES"
        adapter._mark_connected()

        state_db_path = home_path / "state.db"
        session_db = SessionDB(db_path=state_db_path, read_only=False)
        runner = MinimalRunner(adapter, home_path, session_db=session_db)
        try:
            yield runner, adapter, inbox, home_path
        finally:
            runner.close()
            try:
                session_db.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 1. Native Metadata Whitelist Tests (Never Weaken Whitelist)
# ---------------------------------------------------------------------------

def test_native_metadata_whitelist_strictly_enforced():
    """Verify envelope _native_metadata strictly rejects any nonempty LINE metadata."""
    line_src = SessionSource(platform=Platform("line"), chat_id=APPROVED_LINE_GROUP_ID, chat_type="group")

    # 1. Non-empty arbitrary metadata for LINE must be rejected (returns None -> invalid_params)
    event_with_custom = MessageEvent(
        text="Hello",
        source=line_src,
        metadata={"line_inbox_batch_token": "custom123"},
    )
    assert _native_metadata(event_with_custom) is None

    # 2. Even whatsapp metadata keys on a LINE source must be rejected
    event_wa_on_line = MessageEvent(
        text="Hello",
        source=line_src,
        metadata={"whatsapp_native_type": "image"},
    )
    assert _native_metadata(event_wa_on_line) is None

    # 3. Empty metadata on LINE passes cleanly (returns {})
    event_clean = MessageEvent(text="Hello", source=line_src, metadata={})
    assert _native_metadata(event_clean) == {}

    event_none_meta = MessageEvent(text="Hello", source=line_src, metadata=None)
    assert _native_metadata(event_none_meta) == {}

    # 4. WhatsApp whitelist remains intact for WhatsApp sources only
    wa_src = SessionSource(platform=Platform.WHATSAPP, chat_id="12345@s.whatsapp.net", chat_type="dm")
    event_wa = MessageEvent(
        text="Hello WA",
        source=wa_src,
        metadata={"whatsapp_native_type": "video", "whatsapp_from_owner": True},
    )
    projected = _native_metadata(event_wa)
    assert projected is not None
    assert projected.get("whatsapp_native_type") == "video"


@pytest.mark.asyncio
async def test_target_mention_turn_produces_empty_metadata(admission_env):
    """Verify adapter_minimal produces strictly empty event.metadata on mention turns."""
    runner, adapter, inbox, _ = admission_env

    received_events = []
    async def capture_event(ev: Any) -> str:
        received_events.append(ev)
        return "Reply text"

    adapter._message_handler = capture_event

    mention_event = {
        "type": "message",
        "webhookEventId": "evt_meta_clean_1",
        "timestamp": 1730332800000,
        "replyToken": "token_clean_1",
        "source": {"type": "group", "groupId": APPROVED_LINE_GROUP_ID, "userId": "U_ALICE"},
        "message": {
            "type": "text",
            "id": "msg_clean_1",
            "text": "@Hermes clean metadata check",
            "mention": {"mentionees": [{"index": 0, "length": 7, "type": "user", "isSelf": True}]},
        },
    }

    await adapter._handle_message_event(mention_event)
    await adapter.wait_group_idle()

    assert len(received_events) == 1
    event = received_events[0]

    # Critical admission contract check: event.metadata MUST be empty dict
    assert event.metadata == {}
    assert _native_metadata(event) == {}
    # Verified no custom fields remain in metadata
    assert "line_inbox_batch_token" not in event.metadata
    assert "line_inbox_paged" not in event.metadata
    assert "line_inbox_manifest_token" not in event.metadata
    assert "line_inbox_high_water" not in event.metadata


# ---------------------------------------------------------------------------
# 2. Native Admission Roundtrip & Shared Group Key Stability
# ---------------------------------------------------------------------------

def test_native_roundtrip_key_stability_and_shared_flag_restoration(admission_env):
    """Verify native serialization and candidate restore preserves shared group session key."""
    runner, adapter, inbox, home_path = admission_env

    source_alice = SessionSource(
        platform=Platform("line"),
        chat_id=APPROVED_LINE_GROUP_ID,
        chat_type="group",
        user_id="U_ALICE",
        user_name="Alice",
        shared_group=True,
    )
    event = MessageEvent(
        text="@Hermes question from Alice",
        source=source_alice,
        message_id="msg_roundtrip_alice",
        metadata={},
    )

    key_before = build_session_key(event.source)
    assert key_before == f"agent:main:line:group:{APPROVED_LINE_GROUP_ID}"

    # Snapshot with native_callback active
    with native_callback(runner, event, home_path, profile=None):
        payload = snapshot_native(runner, event)

    # 1. Wire/storage format MUST NOT expose shared_group
    encoded_source = payload["native_text_v1"]["source"]
    assert "shared_group" not in encoded_source
    assert payload["native_text_v1"]["route"] == key_before
    assert "provenance" in payload["native_text_v1"]

    # 2. Restore event using candidate ingress context
    restored_event = restore_native(payload, runner)
    restored_source = restored_event.source

    # Trusted hook must have re-established shared_group = True
    assert restored_source.shared_group is True
    assert restored_source.user_id == "U_ALICE"
    assert restored_source.chat_id == APPROVED_LINE_GROUP_ID

    # Route key after restore must be identical to route before snapshot
    key_after = build_session_key(restored_source)
    assert key_after == key_before

    # check_native_route preflight passes without admission_conflict
    available_source = copy(restored_source)
    session_id = runner.session_store.lookup_by_session_key(key_before).session_id
    matched_src, matched_route = asyncio.run(
        check_native_route(runner, payload, session_id, available_source, adapter)
    )
    assert matched_route == key_before
    assert matched_src.shared_group is True


def test_two_users_same_shared_group_key_with_authentic_ids(admission_env):
    """Two different users in approved group produce same session key and keep authentic IDs."""
    runner, adapter, inbox, home_path = admission_env

    src_alice = SessionSource(
        platform=Platform("line"),
        chat_id=APPROVED_LINE_GROUP_ID,
        chat_type="group",
        user_id="U_ALICE",
        shared_group=True,
    )
    event_alice = MessageEvent(text="Alice msg", source=src_alice, message_id="msg_alice", metadata={})

    src_bob = SessionSource(
        platform=Platform("line"),
        chat_id=APPROVED_LINE_GROUP_ID,
        chat_type="group",
        user_id="U_BOB",
        shared_group=True,
    )
    event_bob = MessageEvent(text="Bob msg", source=src_bob, message_id="msg_bob", metadata={})

    with native_callback(runner, event_alice, home_path):
        payload_alice = snapshot_native(runner, event_alice)
    with native_callback(runner, event_bob, home_path):
        payload_bob = snapshot_native(runner, event_bob)

    restored_alice = restore_native(payload_alice, runner)
    restored_bob = restore_native(payload_bob, runner)

    # Authentic IDs are strictly preserved
    assert restored_alice.source.user_id == "U_ALICE"
    assert restored_bob.source.user_id == "U_BOB"
    assert restored_alice.source.user_id != restored_bob.source.user_id

    # Both have shared_group restored
    assert restored_alice.source.shared_group is True
    assert restored_bob.source.shared_group is True

    # Same shared group key
    key_alice = build_session_key(restored_alice.source)
    key_bob = build_session_key(restored_bob.source)
    assert key_alice == key_bob
    assert key_alice == f"agent:main:line:group:{APPROVED_LINE_GROUP_ID}"


# ---------------------------------------------------------------------------
# 3. Anti-Forgery & Boundary Security Tests
# ---------------------------------------------------------------------------

def test_forged_source_dict_shared_group_strictly_ignored():
    """Forged source dictionary containing shared_group is completely ignored."""
    forged_dict = {
        "platform": "line",
        "chat_id": APPROVED_LINE_GROUP_ID,
        "chat_type": "group",
        "user_id": "U_HACKER",
        "shared_group": True,  # Attacker attempt
    }
    source = SessionSource.from_dict(forged_dict)
    assert source.shared_group is False, "SessionSource.from_dict must never deserialize shared_group"

    # to_dict also never outputs shared_group
    source.shared_group = True
    serialized = source.to_dict()
    assert "shared_group" not in serialized


def test_no_restored_flag_for_other_group_dm_or_platform(admission_env):
    """Adapter restore hook must never set shared_group for other groups, DMs, or platforms."""
    runner, adapter, _, _ = admission_env

    # 1. Nonapproved LINE group
    src_other_group = SessionSource(platform=Platform("line"), chat_id="C_OTHER_GROUP", chat_type="group", user_id="U_ALICE")
    adapter.restore_native_source_context(src_other_group)
    assert src_other_group.shared_group is False

    # 2. LINE DM
    src_dm = SessionSource(platform=Platform("line"), chat_id="U_ALICE", chat_type="dm", user_id="U_ALICE")
    adapter.restore_native_source_context(src_dm)
    assert src_dm.shared_group is False

    # 3. Other platform with approved group ID
    src_discord = SessionSource(platform=Platform.DISCORD, chat_id=APPROVED_LINE_GROUP_ID, chat_type="group", user_id="U_ALICE")
    adapter.restore_native_source_context(src_discord)
    assert src_discord.shared_group is False


def test_bad_provenance_never_invokes_adapter_hook(admission_env):
    """Tampered or invalid provenance fails closed before invoking adapter hook."""
    runner, adapter, _, home_path = admission_env

    hook_called = False
    orig_hook = adapter.restore_native_source_context
    def tracking_hook(src):
        nonlocal hook_called
        hook_called = True
        return orig_hook(src)

    adapter.restore_native_source_context = tracking_hook

    src = SessionSource(platform=Platform("line"), chat_id=APPROVED_LINE_GROUP_ID, chat_type="group", user_id="U_ALICE")

    # Tampered transport_home
    bad_prov = {
        "transport_home": "/nonexistent/fake/home",
        "runtime_home": str(home_path),
        "platform": "line",
        "connector": "adapter:line:test_credential_fingerprint",
    }
    with pytest.raises(RuntimeStoreError):
        restore_provenance(runner, src, bad_prov)

    assert hook_called is False, "Adapter hook must NEVER be invoked on bad provenance"
    assert src.shared_group is False


def test_adapter_hook_failure_fails_closed(admission_env):
    """If the adapter restore hook throws, restore_provenance must fail closed."""
    runner, adapter, _, home_path = admission_env

    def exploding_hook(src):
        raise RuntimeError("Hook explosion in adapter!")

    adapter.restore_native_source_context = exploding_hook

    src = SessionSource(platform=Platform("line"), chat_id=APPROVED_LINE_GROUP_ID, chat_type="group", user_id="U_ALICE")
    valid_prov = {
        "transport_home": str(home_path),
        "runtime_home": str(home_path),
        "platform": "line",
        "connector": "adapter:line:test_credential_fingerprint",
    }

    with pytest.raises(RuntimeStoreError):
        restore_provenance(runner, src, valid_prov)

    # Flag remained False
    assert src.shared_group is False


# ---------------------------------------------------------------------------
# 4. Delivery Ledger & Receipt Correlation Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_roundtrip_final_delivery_correlates_exact_receipt_and_acks(admission_env, monkeypatch):
    """Exact message_id and source.chat_id correlation acks short batch after roundtrip."""
    runner, adapter, inbox, home_path = admission_env

    # 1. Enqueue mention turn to register immutable receipt in adapter
    mention_msg_id = "msg_turn_101"
    inbox.append(APPROVED_LINE_GROUP_ID, "evt_101", mention_msg_id, "U_ALICE", text="@Hermes execute query")
    snapshot = inbox.pending(APPROVED_LINE_GROUP_ID)
    assert snapshot.high_water == 1

    # Simulate adapter mention processing establishing receipt
    receipt = _AckReceipt(
        group_id=APPROVED_LINE_GROUP_ID,
        high_water=1,
        message_id=mention_msg_id,
        is_paged=False,
    )
    adapter._turn_receipts[(APPROVED_LINE_GROUP_ID, mention_msg_id)] = receipt

    # 2. Build MessageEvent and perform roundtrip serialization
    src = SessionSource(
        platform=Platform("line"),
        chat_id=APPROVED_LINE_GROUP_ID,
        chat_type="group",
        user_id="U_ALICE",
        shared_group=True,
    )
    event = MessageEvent(
        text="@Hermes execute query",
        source=src,
        message_id=mention_msg_id,
        metadata={},
    )

    with native_callback(runner, event, home_path):
        payload = snapshot_native(runner, event)

    restored_event = restore_native(payload, runner)
    assert restored_event.message_id == mention_msg_id
    assert restored_event.source.chat_id == APPROVED_LINE_GROUP_ID

    # 3. Deliver final ledgered using restored event
    send_res = adapter_mod.SendResult(success=True, message_id="line_reply_token_123")
    async def fake_super_send(*args, **kwargs):
        return send_res, adapter

    adapter.send_final_ledgered = LineAdapter.send_final_ledgered.__get__(adapter, LineAdapter)
    monkeypatch.setattr(adapter.__class__.__bases__[0], "send_final_ledgered", fake_super_send)

    assert inbox.get_pending_count(APPROVED_LINE_GROUP_ID) == 1

    res, _ = await adapter.send_final_ledgered(
        restored_event,
        session_key=payload["native_text_v1"]["route"],
        text_content="Answer to user",
        metadata={},
    )
    assert res.success is True

    # Entire short batch acknowledged
    assert inbox.get_pending_count(APPROVED_LINE_GROUP_ID) == 0
    assert inbox.get_ack_high_water(APPROVED_LINE_GROUP_ID) == 1
    # Receipt consumed and removed
    assert (APPROVED_LINE_GROUP_ID, mention_msg_id) not in adapter._turn_receipts


@pytest.mark.asyncio
async def test_roundtrip_final_delivery_paged_not_acked(admission_env, monkeypatch):
    """Paged turn preserves unacknowledged backlog even after successful final delivery."""
    runner, adapter, inbox, home_path = admission_env

    paged_msg_id = "msg_paged_202"
    inbox.append(APPROVED_LINE_GROUP_ID, "evt_201", "m_p1", "U_USER1", text="Large history chunk 1")
    inbox.append(APPROVED_LINE_GROUP_ID, "evt_202", paged_msg_id, "U_ALICE", text="@Hermes paged request")

    # Receipt marks is_paged = True
    receipt = _AckReceipt(
        group_id=APPROVED_LINE_GROUP_ID,
        high_water=2,
        message_id=paged_msg_id,
        is_paged=True,
    )
    adapter._turn_receipts[(APPROVED_LINE_GROUP_ID, paged_msg_id)] = receipt

    src = SessionSource(
        platform=Platform("line"),
        chat_id=APPROVED_LINE_GROUP_ID,
        chat_type="group",
        user_id="U_ALICE",
        shared_group=True,
    )
    event = MessageEvent(
        text="@Hermes paged request",
        source=src,
        message_id=paged_msg_id,
        metadata={},
    )

    with native_callback(runner, event, home_path):
        payload = snapshot_native(runner, event)

    restored_event = restore_native(payload, runner)

    # Deliver final ledgered
    send_res = adapter_mod.SendResult(success=True, message_id="line_reply_token_paged")
    async def fake_super_send(*args, **kwargs):
        return send_res, adapter

    adapter.send_final_ledgered = LineAdapter.send_final_ledgered.__get__(adapter, LineAdapter)
    monkeypatch.setattr(adapter.__class__.__bases__[0], "send_final_ledgered", fake_super_send)

    res, _ = await adapter.send_final_ledgered(
        restored_event,
        session_key=payload["native_text_v1"]["route"],
        text_content="Answer to paged query",
        metadata={},
    )
    assert res.success is True

    # CRITICAL: Paged backlog is NOT acked!
    assert inbox.get_pending_count(APPROVED_LINE_GROUP_ID) == 2
    assert inbox.get_ack_high_water(APPROVED_LINE_GROUP_ID) == 0


@pytest.mark.asyncio
async def test_regular_notices_and_background_without_receipt_cannot_ack(admission_env, monkeypatch):
    """Regular notices or background events without a matching receipt cannot acknowledge."""
    runner, adapter, inbox, home_path = admission_env

    # Unacked message in inbox
    inbox.append(APPROVED_LINE_GROUP_ID, "evt_backlog", "msg_backlog", "U_USER", text="Backlog text")
    assert inbox.get_pending_count(APPROVED_LINE_GROUP_ID) == 1

    src = SessionSource(
        platform=Platform("line"),
        chat_id=APPROVED_LINE_GROUP_ID,
        chat_type="group",
        user_id="U_SYSTEM",
        shared_group=True,
    )
    # Notice event with message_id having no receipt in adapter._turn_receipts
    notice_event = MessageEvent(
        text="Background notification",
        source=src,
        message_id="msg_system_notice_999",
        metadata={},
    )

    send_res = adapter_mod.SendResult(success=True, message_id="push_notice_ok")
    async def fake_super_send(*args, **kwargs):
        return send_res, adapter

    adapter.send_final_ledgered = LineAdapter.send_final_ledgered.__get__(adapter, LineAdapter)
    monkeypatch.setattr(adapter.__class__.__bases__[0], "send_final_ledgered", fake_super_send)

    res, _ = await adapter.send_final_ledgered(
        notice_event,
        session_key=f"agent:main:line:group:{APPROVED_LINE_GROUP_ID}",
        text_content="Background notice content",
        metadata={},
    )
    assert res.success is True

    # Must NOT acknowledge group backlog
    assert inbox.get_pending_count(APPROVED_LINE_GROUP_ID) == 1
    assert inbox.get_ack_high_water(APPROVED_LINE_GROUP_ID) == 0


def test_native_restore_without_env_or_invalid_env_refuses_shared_flag(admission_env, monkeypatch):
    """When LINE_LISTENER_GROUP_IDS is unset, empty, or malformed, restore_provenance does not set shared_group=True."""
    runner, adapter, _, home_path = admission_env

    valid_prov = {
        "transport_home": str(home_path),
        "runtime_home": str(home_path),
        "platform": "line",
        "connector": "adapter:line:test_credential_fingerprint",
    }

    for env_val in (None, "", "   ", "C_INVALID", f"{APPROVED_LINE_GROUP_ID},bad"):
        if env_val is None:
            monkeypatch.delenv("LINE_LISTENER_GROUP_IDS", raising=False)
        else:
            monkeypatch.setenv("LINE_LISTENER_GROUP_IDS", env_val)

        src = SessionSource(
            platform=Platform("line"),
            chat_id=APPROVED_LINE_GROUP_ID,
            chat_type="group",
            user_id="U_ALICE",
        )
        restore_provenance(runner, src, valid_prov)
        assert src.shared_group is False
        assert build_session_key(src) == f"agent:main:line:group:{APPROVED_LINE_GROUP_ID}:U_ALICE"

