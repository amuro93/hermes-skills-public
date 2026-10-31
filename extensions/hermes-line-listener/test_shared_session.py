"""Tests for shared-session routing candidate (session_candidate.py).

Verifies the scoped LINE quiet-listening shared session routing invariants:
- Dynamic import via importlib with sys.modules registration.
- Approved LINE group with shared_group=True routes distinct users to identical session key.
- Real user IDs are preserved on source.user_id.
- Without flag, approved LINE group keeps distinct keys per user.
- Other LINE groups with flag remain isolated per user.
- Other platforms (e.g. Discord) even with matching group ID and flag remain isolated per user.
- DMs with flag remain unchanged.
- Wire JSON / from_dict does NOT grant shared_group flag.
- to_dict does NOT export shared_group flag.
- Default original sources round-trip unchanged.
- Malformed truthy flag values ("true", "True", 1, etc.) do NOT activate shared routing.
- Profile namespace and thread baseline behavior are fully preserved.
- Centralized predicate is_approved_line_shared_group unit tests.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
import pytest

# ---------------------------------------------------------------------------
# Module dynamic loading via importlib with sys.modules registration
# ---------------------------------------------------------------------------

_PKG_DIR = Path(__file__).resolve().parent
POLICY_PATH = _PKG_DIR / "line_group_policy.py"
POLICY_MODULE_NAME = "gateway.line_group_policy"
CANDIDATE_PATH = _PKG_DIR / "session_candidate.py"
MODULE_NAME = "gateway.session_candidate"

_orig_gateway_policy = sys.modules.get(POLICY_MODULE_NAME)
if _orig_gateway_policy is not None and getattr(_orig_gateway_policy, "__file__", None) == str(POLICY_PATH):
    _orig_gateway_policy = None


def _load_policy_module():
    import gateway  # real framework package
    existing = sys.modules.get(POLICY_MODULE_NAME)
    if existing is not None and getattr(existing, "__file__", None) == str(POLICY_PATH):
        setattr(gateway, "line_group_policy", existing)
        return existing
    spec = importlib.util.spec_from_file_location(POLICY_MODULE_NAME, str(POLICY_PATH))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load spec from {POLICY_PATH}")
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "gateway"
    sys.modules[POLICY_MODULE_NAME] = mod
    setattr(gateway, "line_group_policy", mod)
    spec.loader.exec_module(mod)
    return mod


policy_mod = _load_policy_module()

if MODULE_NAME in sys.modules:
    session_mod = sys.modules[MODULE_NAME]
else:
    spec = importlib.util.spec_from_file_location(MODULE_NAME, str(CANDIDATE_PATH))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load spec from {CANDIDATE_PATH}")
    session_mod = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = session_mod
    # Also register top-level alias
    sys.modules["session_candidate"] = session_mod
    spec.loader.exec_module(session_mod)

SessionSource = session_mod.SessionSource
Platform = session_mod.Platform
build_session_key = session_mod.build_session_key
is_shared_multi_user_session = session_mod.is_shared_multi_user_session
is_approved_line_shared_group = session_mod.is_approved_line_shared_group
get_configured_line_listener_groups = policy_mod.get_configured_line_listener_groups
is_configured_line_listener_group = policy_mod.is_configured_line_listener_group

# Test-only synthetic IDs (never exported from product modules)
APPROVED_GROUP = "C" + "a" * 32
SECOND_APPROVED_GROUP = "C" + "b" * 32
OTHER_GROUP = "C" + "9" * 32
USER_ALICE = "U0123456789abcdef0123456789abcdef"
USER_BOB = "U9876543210fedcba9876543210fedcba"


@pytest.fixture(scope="module", autouse=True)
def _restore_policy_module():
    """Ensure candidate gateway.line_group_policy is registered for this module and restored on teardown."""
    import gateway
    sys.modules[POLICY_MODULE_NAME] = policy_mod
    setattr(gateway, "line_group_policy", policy_mod)
    yield
    if _orig_gateway_policy is not None:
        sys.modules[POLICY_MODULE_NAME] = _orig_gateway_policy
        setattr(gateway, "line_group_policy", _orig_gateway_policy)
    else:
        sys.modules.pop(POLICY_MODULE_NAME, None)
        if hasattr(gateway, "line_group_policy"):
            delattr(gateway, "line_group_policy")


@pytest.fixture(autouse=True)
def _configure_listener_group_env(monkeypatch):
    """Explicitly configure synthetic listener group in env so tests never depend on host config."""
    monkeypatch.setenv("LINE_LISTENER_GROUP_IDS", APPROVED_GROUP)


# ===========================================================================
# 1. Approved LINE Group Shared Session Routing
# ===========================================================================

def test_approved_line_group_shared_routing_two_users():
    """Two different LINE users in configured group with shared_group=True share session key.

    Invariants verified:
    - Identical session key: agent:main:line:group:Caaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    - is_shared_multi_user_session returns True for both
    - source.user_id preserves authentic user identity (no faking / stripping)
    """
    source_alice = SessionSource(
        platform=Platform('line'),
        chat_id=APPROVED_GROUP,
        chat_type="group",
        user_id=USER_ALICE,
        user_name="Alice",
        shared_group=True,
    )
    source_bob = SessionSource(
        platform=Platform('line'),
        chat_id=APPROVED_GROUP,
        chat_type="group",
        user_id=USER_BOB,
        user_name="Bob",
        shared_group=True,
    )

    key_alice = build_session_key(source_alice)
    key_bob = build_session_key(source_bob)

    expected_shared_key = f"agent:main:line:group:{APPROVED_GROUP}"
    assert key_alice == expected_shared_key
    assert key_bob == expected_shared_key
    assert key_alice == key_bob

    assert is_shared_multi_user_session(source_alice) is True
    assert is_shared_multi_user_session(source_bob) is True

    # Real user identities must remain authentic and unchanged
    assert source_alice.user_id == USER_ALICE
    assert source_bob.user_id == USER_BOB


def test_approved_line_group_without_flag_isolated():
    """Approved LINE group without shared_group flag keeps distinct keys per user."""
    source_alice = SessionSource(
        platform=Platform('line'),
        chat_id=APPROVED_GROUP,
        chat_type="group",
        user_id=USER_ALICE,
        shared_group=False,
    )
    source_bob = SessionSource(
        platform=Platform('line'),
        chat_id=APPROVED_GROUP,
        chat_type="group",
        user_id=USER_BOB,
        # shared_group defaults to False
    )

    key_alice = build_session_key(source_alice)
    key_bob = build_session_key(source_bob)

    assert key_alice != key_bob
    assert key_alice == f"agent:main:line:group:{APPROVED_GROUP}:{USER_ALICE}"
    assert key_bob == f"agent:main:line:group:{APPROVED_GROUP}:{USER_BOB}"

    assert is_shared_multi_user_session(source_alice) is False
    assert is_shared_multi_user_session(source_bob) is False


# ===========================================================================
# 2. Strict Isolation for Other Groups, Platforms, and DMs
# ===========================================================================

def test_other_line_group_with_flag_stays_isolated():
    """Non-approved LINE group even with shared_group=True stays isolated per participant."""
    source_alice = SessionSource(
        platform=Platform('line'),
        chat_id=OTHER_GROUP,
        chat_type="group",
        user_id=USER_ALICE,
        shared_group=True,
    )
    source_bob = SessionSource(
        platform=Platform('line'),
        chat_id=OTHER_GROUP,
        chat_type="group",
        user_id=USER_BOB,
        shared_group=True,
    )

    key_alice = build_session_key(source_alice)
    key_bob = build_session_key(source_bob)

    assert key_alice != key_bob
    assert key_alice == f"agent:main:line:group:{OTHER_GROUP}:{USER_ALICE}"
    assert key_bob == f"agent:main:line:group:{OTHER_GROUP}:{USER_BOB}"

    assert is_shared_multi_user_session(source_alice) is False
    assert is_shared_multi_user_session(source_bob) is False


def test_discord_even_same_chat_id_with_flag_stays_isolated():
    """Discord group even matching approved chat_id and shared_group=True stays isolated."""
    source_alice = SessionSource(
        platform=Platform.DISCORD,
        chat_id=APPROVED_GROUP,
        chat_type="group",
        user_id=USER_ALICE,
        shared_group=True,
    )
    source_bob = SessionSource(
        platform=Platform.DISCORD,
        chat_id=APPROVED_GROUP,
        chat_type="group",
        user_id=USER_BOB,
        shared_group=True,
    )

    key_alice = build_session_key(source_alice)
    key_bob = build_session_key(source_bob)

    assert key_alice != key_bob
    assert key_alice == f"agent:main:discord:group:{APPROVED_GROUP}:{USER_ALICE}"
    assert key_bob == f"agent:main:discord:group:{APPROVED_GROUP}:{USER_BOB}"

    assert is_shared_multi_user_session(source_alice) is False
    assert is_shared_multi_user_session(source_bob) is False


def test_dm_even_with_flag_stays_unchanged():
    """DM sessions even with shared_group=True remain standard isolated DM sessions."""
    source_dm = SessionSource(
        platform=Platform('line'),
        chat_id=USER_ALICE,
        chat_type="dm",
        user_id=USER_ALICE,
        shared_group=True,
    )
    source_dm_noflag = SessionSource(
        platform=Platform('line'),
        chat_id=USER_ALICE,
        chat_type="dm",
        user_id=USER_ALICE,
        shared_group=False,
    )

    key_dm = build_session_key(source_dm)
    key_noflag = build_session_key(source_dm_noflag)

    assert key_dm == key_noflag
    assert key_dm == f"agent:main:line:dm:{USER_ALICE}"
    assert is_shared_multi_user_session(source_dm) is False


# ===========================================================================
# 3. Serialization and Untrusted Wire Ingress Protection
# ===========================================================================

def test_from_dict_must_not_grant_flag():
    """from_dict receiving wire JSON with shared_group=True MUST NOT set the flag."""
    wire_data = {
        "platform": "line",
        "chat_id": APPROVED_GROUP,
        "chat_type": "group",
        "user_id": USER_ALICE,
        "shared_group": True,  # Untrusted inbound attempt to override participant isolation
    }

    source = SessionSource.from_dict(wire_data)

    assert source.shared_group is False
    assert is_shared_multi_user_session(source) is False
    # Key must isolate to Alice, not route to shared group
    key = build_session_key(source)
    assert key == f"agent:main:line:group:{APPROVED_GROUP}:{USER_ALICE}"


def test_to_dict_must_not_export_trusted_flag():
    """to_dict MUST NOT export the trusted process-local shared_group flag."""
    source = SessionSource(
        platform=Platform('line'),
        chat_id=APPROVED_GROUP,
        chat_type="group",
        user_id=USER_ALICE,
        shared_group=True,
    )

    data = source.to_dict()
    assert "shared_group" not in data


def test_default_original_sources_round_trip_unchanged():
    """Original standard sources serialize and deserialize byte-for-byte unchanged."""
    source = SessionSource(
        platform=Platform('line'),
        chat_id=APPROVED_GROUP,
        chat_type="group",
        user_id=USER_ALICE,
        user_name="Alice",
    )

    data = source.to_dict()
    source_restored = SessionSource.from_dict(data)

    assert source_restored.to_dict() == data
    assert source_restored.shared_group is False
    assert source_restored.platform == Platform('line')
    assert source_restored.chat_id == APPROVED_GROUP
    assert source_restored.user_id == USER_ALICE


# ===========================================================================
# 4. Strict Boolean Predicate & Malformed Truthy Flag Rejection
# ===========================================================================

@pytest.mark.parametrize("malformed_flag", [
    "true",
    "True",
    "1",
    1,
    [True],
    {"flag": True},
    object(),
])
def test_malformed_truthy_flag_values_rejected(malformed_flag):
    """Malformed truthy flag values must NOT activate shared group routing."""
    source_alice = SessionSource(
        platform=Platform('line'),
        chat_id=APPROVED_GROUP,
        chat_type="group",
        user_id=USER_ALICE,
        shared_group=malformed_flag,
    )
    source_bob = SessionSource(
        platform=Platform('line'),
        chat_id=APPROVED_GROUP,
        chat_type="group",
        user_id=USER_BOB,
        shared_group=malformed_flag,
    )

    assert is_approved_line_shared_group(source_alice) is False
    assert is_shared_multi_user_session(source_alice) is False

    key_alice = build_session_key(source_alice)
    key_bob = build_session_key(source_bob)

    assert key_alice != key_bob
    assert key_alice == f"agent:main:line:group:{APPROVED_GROUP}:{USER_ALICE}"
    assert key_bob == f"agent:main:line:group:{APPROVED_GROUP}:{USER_BOB}"


def test_centralized_predicate_direct():
    """Unit test the centralized is_approved_line_shared_group predicate across all branches."""
    # 1. Exact matching source -> True
    valid = SessionSource(
        platform=Platform('line'),
        chat_id=APPROVED_GROUP,
        chat_type="group",
        user_id=USER_ALICE,
        shared_group=True,
    )
    assert is_approved_line_shared_group(valid) is True

    # 2. Flag is False -> False
    assert is_approved_line_shared_group(
        SessionSource(platform=Platform('line'), chat_id=APPROVED_GROUP, chat_type="group", shared_group=False)
    ) is False

    # 3. Wrong platform -> False
    assert is_approved_line_shared_group(
        SessionSource(platform=Platform.DISCORD, chat_id=APPROVED_GROUP, chat_type="group", shared_group=True)
    ) is False

    # 4. Wrong chat_type -> False
    assert is_approved_line_shared_group(
        SessionSource(platform=Platform('line'), chat_id=APPROVED_GROUP, chat_type="dm", shared_group=True)
    ) is False
    assert is_approved_line_shared_group(
        SessionSource(platform=Platform('line'), chat_id=APPROVED_GROUP, chat_type="channel", shared_group=True)
    ) is False

    # 5. Wrong chat_id -> False
    assert is_approved_line_shared_group(
        SessionSource(platform=Platform('line'), chat_id=OTHER_GROUP, chat_type="group", shared_group=True)
    ) is False

    # 6. Naked string platform rejected -> False
    assert is_approved_line_shared_group(
        SessionSource(platform="line", chat_id=APPROVED_GROUP, chat_type="group", shared_group=True)  # type: ignore
    ) is False


# ===========================================================================
# 5. Profile Namespacing and Thread Baseline Preservation
# ===========================================================================

def test_preserve_profile_namespacing():
    """Profile namespacing produces correct prefix for approved shared group."""
    source = SessionSource(
        platform=Platform('line'),
        chat_id=APPROVED_GROUP,
        chat_type="group",
        user_id=USER_ALICE,
        shared_group=True,
    )

    # Default / None profile -> agent:main
    assert build_session_key(source, profile=None) == f"agent:main:line:group:{APPROVED_GROUP}"
    assert build_session_key(source, profile="default") == f"agent:main:line:group:{APPROVED_GROUP}"

    # Named profile -> agent:<profile>
    assert build_session_key(source, profile="support") == f"agent:support:line:group:{APPROVED_GROUP}"

    # Profile named "main" -> agent:main~
    assert build_session_key(source, profile="main") == f"agent:main~:line:group:{APPROVED_GROUP}"


def test_preserve_thread_baseline():
    """Baseline thread behavior for Discord/Slack remains unaffected."""
    # Standard Discord thread with default thread_sessions_per_user=False (threads shared)
    source_discord_thread_alice = SessionSource(
        platform=Platform.DISCORD,
        chat_id="chan_1",
        chat_type="channel",
        thread_id="thread_1",
        user_id=USER_ALICE,
    )
    source_discord_thread_bob = SessionSource(
        platform=Platform.DISCORD,
        chat_id="chan_1",
        chat_type="channel",
        thread_id="thread_1",
        user_id=USER_BOB,
    )

    key_thread_alice = build_session_key(source_discord_thread_alice, thread_sessions_per_user=False)
    key_thread_bob = build_session_key(source_discord_thread_bob, thread_sessions_per_user=False)
    assert key_thread_alice == key_thread_bob
    assert key_thread_alice == "agent:main:discord:channel:chan_1:thread_1"

    # Discord thread with thread_sessions_per_user=True (threads isolated per user)
    key_isolated_alice = build_session_key(source_discord_thread_alice, thread_sessions_per_user=True)
    key_isolated_bob = build_session_key(source_discord_thread_bob, thread_sessions_per_user=True)
    assert key_isolated_alice != key_isolated_bob
    assert key_isolated_alice == f"agent:main:discord:channel:chan_1:thread_1:{USER_ALICE}"
    assert key_isolated_bob == f"agent:main:discord:channel:chan_1:thread_1:{USER_BOB}"


def test_global_group_sessions_per_user_default_preserved():
    """build_session_key and is_shared_multi_user_session retain group_sessions_per_user=True default."""
    source_default = SessionSource(
        platform=Platform('line'),
        chat_id=OTHER_GROUP,
        chat_type="group",
        user_id=USER_ALICE,
    )

    # Calling with default parameters isolates by user
    key_default = build_session_key(source_default)
    assert key_default == f"agent:main:line:group:{OTHER_GROUP}:{USER_ALICE}"
    assert is_shared_multi_user_session(source_default) is False


# ===========================================================================
# 6. Fail-Closed Environment Configuration (LINE_LISTENER_GROUP_IDS)
# ===========================================================================

def test_no_product_exported_hardcoded_group_constant():
    """Product modules must not export hardcoded or synthetic group ID constants."""
    assert not hasattr(session_mod, "APPROVED_LINE_SHARED_GROUP_ID")
    assert not hasattr(session_mod, "APPROVED_LINE_GROUP_ID")
    assert not hasattr(policy_mod, "APPROVED_LINE_SHARED_GROUP_ID")
    assert not hasattr(policy_mod, "APPROVED_LINE_GROUP_ID")


def test_without_env_disables_shared_routing_for_every_group(monkeypatch):
    """When LINE_LISTENER_GROUP_IDS is unset or empty, no group is shared even with shared_group=True."""
    source_alice = SessionSource(
        platform=Platform("line"),
        chat_id=APPROVED_GROUP,
        chat_type="group",
        user_id=USER_ALICE,
        shared_group=True,
    )
    source_bob = SessionSource(
        platform=Platform("line"),
        chat_id=APPROVED_GROUP,
        chat_type="group",
        user_id=USER_BOB,
        shared_group=True,
    )

    for unset_mode in ("delenv", "", "   "):
        if unset_mode == "delenv":
            monkeypatch.delenv("LINE_LISTENER_GROUP_IDS", raising=False)
        else:
            monkeypatch.setenv("LINE_LISTENER_GROUP_IDS", unset_mode)

        assert get_configured_line_listener_groups() == frozenset()
        assert is_configured_line_listener_group(APPROVED_GROUP) is False
        assert is_approved_line_shared_group(source_alice) is False
        assert is_shared_multi_user_session(source_alice) is False

        key_alice = build_session_key(source_alice)
        key_bob = build_session_key(source_bob)
        assert key_alice != key_bob
        assert key_alice == f"agent:main:line:group:{APPROVED_GROUP}:{USER_ALICE}"
        assert key_bob == f"agent:main:line:group:{APPROVED_GROUP}:{USER_BOB}"


@pytest.mark.parametrize("invalid_env", [
    "U" + "a" * 32,
    "R" + "a" * 32,
    "G" + "a" * 32,
    "C" + "A" * 32,
    "C" + "a" * 31 + "F",
    "C" + "a" * 31,
    "C" + "a" * 33,
    "C" + "g" * 32,
    "C12345",
    f"{APPROVED_GROUP},invalid_entry",
    f"{APPROVED_GROUP},",
    f",{APPROVED_GROUP}",
    f"{APPROVED_GROUP},,{SECOND_APPROVED_GROUP}",
])
def test_invalid_env_values_fail_closed_and_reject_entire_value(monkeypatch, invalid_env):
    """Malformed entries in LINE_LISTENER_GROUP_IDS fail closed by rejecting the entire value."""
    monkeypatch.setenv("LINE_LISTENER_GROUP_IDS", invalid_env)

    assert get_configured_line_listener_groups() == frozenset()
    assert is_configured_line_listener_group(APPROVED_GROUP) is False
    assert is_configured_line_listener_group(SECOND_APPROVED_GROUP) is False

    source_alice = SessionSource(
        platform=Platform("line"),
        chat_id=APPROVED_GROUP,
        chat_type="group",
        user_id=USER_ALICE,
        shared_group=True,
    )
    source_bob = SessionSource(
        platform=Platform("line"),
        chat_id=APPROVED_GROUP,
        chat_type="group",
        user_id=USER_BOB,
        shared_group=True,
    )
    assert is_approved_line_shared_group(source_alice) is False
    assert is_shared_multi_user_session(source_alice) is False
    assert build_session_key(source_alice) != build_session_key(source_bob)


def test_line_allowed_groups_does_not_implicitly_enable_shared_routing(monkeypatch):
    """LINE_ALLOWED_GROUPS must never implicitly enable shared-group session routing."""
    monkeypatch.delenv("LINE_LISTENER_GROUP_IDS", raising=False)
    monkeypatch.setenv("LINE_ALLOWED_GROUPS", APPROVED_GROUP)

    source_alice = SessionSource(
        platform=Platform("line"),
        chat_id=APPROVED_GROUP,
        chat_type="group",
        user_id=USER_ALICE,
        shared_group=True,
    )
    assert is_configured_line_listener_group(APPROVED_GROUP) is False
    assert is_approved_line_shared_group(source_alice) is False
    assert build_session_key(source_alice) == f"agent:main:line:group:{APPROVED_GROUP}:{USER_ALICE}"


def test_multiple_configured_groups_route_independently_without_mixing(monkeypatch):
    """Multiple comma-separated valid group IDs in LINE_LISTENER_GROUP_IDS route independently."""
    monkeypatch.setenv("LINE_LISTENER_GROUP_IDS", f" {APPROVED_GROUP} , {SECOND_APPROVED_GROUP} ")

    assert get_configured_line_listener_groups() == frozenset({APPROVED_GROUP, SECOND_APPROVED_GROUP})

    g1_alice = SessionSource(platform=Platform("line"), chat_id=APPROVED_GROUP, chat_type="group", user_id=USER_ALICE, shared_group=True)
    g1_bob = SessionSource(platform=Platform("line"), chat_id=APPROVED_GROUP, chat_type="group", user_id=USER_BOB, shared_group=True)
    g2_alice = SessionSource(platform=Platform("line"), chat_id=SECOND_APPROVED_GROUP, chat_type="group", user_id=USER_ALICE, shared_group=True)
    g2_bob = SessionSource(platform=Platform("line"), chat_id=SECOND_APPROVED_GROUP, chat_type="group", user_id=USER_BOB, shared_group=True)
    other_alice = SessionSource(platform=Platform("line"), chat_id=OTHER_GROUP, chat_type="group", user_id=USER_ALICE, shared_group=True)

    assert build_session_key(g1_alice) == build_session_key(g1_bob) == f"agent:main:line:group:{APPROVED_GROUP}"
    assert build_session_key(g2_alice) == build_session_key(g2_bob) == f"agent:main:line:group:{SECOND_APPROVED_GROUP}"
    assert build_session_key(g1_alice) != build_session_key(g2_alice)
    assert build_session_key(other_alice) == f"agent:main:line:group:{OTHER_GROUP}:{USER_ALICE}"

