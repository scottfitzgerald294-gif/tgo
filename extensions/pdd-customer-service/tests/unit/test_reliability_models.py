"""Unit tests for durable message reliability models."""

from datetime import UTC, datetime, timedelta

import pytest

from app.models import MessageStatus, ReplyOwner, RetryPolicy, SimulationResult


@pytest.mark.unit
def test_retry_policy_uses_capped_exponential_delays() -> None:
    policy = RetryPolicy(
        max_attempts=4,
        base_delay_seconds=1,
        max_delay_seconds=3,
    )

    assert [policy.delay_after_failure(i) for i in (1, 2, 3)] == [1, 2, 3]


@pytest.mark.unit
def test_retry_policy_classifies_replay_window_boundaries() -> None:
    policy = RetryPolicy(
        replay_window_seconds=300,
        future_tolerance_seconds=60,
    )
    now = datetime(2026, 7, 18, 9, 5, tzinfo=UTC)

    assert (
        policy.timestamp_reason(
            occurred_at=now - timedelta(seconds=301),
            now=now,
        )
        == "message_too_old"
    )
    assert (
        policy.timestamp_reason(
            occurred_at=now + timedelta(seconds=61),
            now=now,
        )
        == "message_from_future"
    )
    assert (
        policy.timestamp_reason(
            occurred_at=now - timedelta(seconds=300),
            now=now,
        )
        is None
    )
    assert (
        policy.timestamp_reason(
            occurred_at=now + timedelta(seconds=60),
            now=now,
        )
        is None
    )


@pytest.mark.unit
def test_reliability_state_values_are_stable() -> None:
    assert tuple(status.value for status in MessageStatus) == (
        "pending",
        "sent",
        "failed",
        "retrying",
        "dead_letter",
    )
    assert tuple(owner.value for owner in ReplyOwner) == ("ai", "human")


@pytest.mark.unit
def test_phase_five_result_has_backward_compatible_reliability_defaults() -> None:
    fields = SimulationResult.model_fields

    assert fields["processing_status"].default is MessageStatus.SENT
    assert fields["duplicate"].default is False
    assert fields["attempts"].default == 1
