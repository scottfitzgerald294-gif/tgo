"""Unit tests for deterministic risk routing and strict rule configuration."""

import json
from pathlib import Path
from typing import cast

import pytest

from app.models import (
    ConversationKey,
    ConversationMode,
    HandoffReason,
    HandoffRiskLevel,
    KnowledgeAvailability,
    RoutingAction,
    RoutingContext,
)
from app.services import RiskConfigurationError, RiskRuleEngine
from tests.fixtures.handoff import RULE_CASES, RuleCase

REPOSITORY_ROOT = Path(__file__).parents[4]
TRANSFER_RULES_PATH = REPOSITORY_ROOT / "config" / "pdd" / "transfer_rules.yml"
FORBIDDEN_CLAIMS_PATH = REPOSITORY_ROOT / "config" / "pdd" / "forbidden_claims.yml"
CONVERSATION_KEY = ConversationKey(
    shop_id="fake-shop",
    buyer_id="fake-buyer",
    conversation_id="fake-conversation",
)


def transfer_config() -> dict[str, object]:
    return {
        "schema_version": 1,
        "handoff_message": "您的问题需要人工客服进一步处理，已为您转接，请稍候。",
        "text_rules": [
            {
                "priority": 2,
                "reason_code": "human_requested",
                "risk_level": "medium",
                "keywords": ["真人客服"],
            }
        ],
    }


def forbidden_config() -> dict[str, object]:
    return {
        "schema_version": 1,
        "claims": [
            {
                "claim_id": "fake-guarantee",
                "risk_level": "high",
                "phrases": ["保证退款"],
            }
        ],
    }


def write_config(path: Path, value: dict[str, object]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False),
        encoding="utf-8",
    )


@pytest.mark.unit
def test_rule_configuration_is_strict_and_safe(tmp_path: Path) -> None:
    transfer_path = tmp_path / "transfer_rules.yml"
    forbidden_path = tmp_path / "forbidden_claims.yml"
    write_config(transfer_path, transfer_config())
    write_config(forbidden_path, forbidden_config())

    engine = RiskRuleEngine.from_files(transfer_path, forbidden_path)

    assert engine.handoff_message.endswith("请稍候。")

    valid_rules = cast(list[dict[str, object]], transfer_config()["text_rules"])
    invalid_values = [
        {**transfer_config(), "unexpected": True},
        {
            **transfer_config(),
            "text_rules": [
                *valid_rules,
                {
                    "priority": 2,
                    "reason_code": "complaint_legal_regulatory",
                    "risk_level": "high",
                    "keywords": ["投诉"],
                },
            ],
        },
        {
            **transfer_config(),
            "text_rules": [
                {
                    "priority": 2,
                    "reason_code": "human_requested",
                    "risk_level": "medium",
                    "keywords": [],
                }
            ],
        },
    ]
    for value in invalid_values:
        write_config(transfer_path, value)
        with pytest.raises(RiskConfigurationError) as captured:
            RiskRuleEngine.from_files(transfer_path, forbidden_path)
        assert str(transfer_path) not in str(captured.value)
        assert "真人客服" not in str(captured.value)

    write_config(transfer_path, transfer_config())
    duplicate_claims = forbidden_config()
    valid_claims = cast(list[dict[str, object]], forbidden_config()["claims"])
    duplicate_claims["claims"] = [
        *valid_claims,
        *valid_claims,
    ]
    write_config(forbidden_path, duplicate_claims)
    with pytest.raises(RiskConfigurationError):
        RiskRuleEngine.from_files(transfer_path, forbidden_path)

    with pytest.raises(RiskConfigurationError) as captured:
        RiskRuleEngine.from_files(tmp_path / "missing.yml", forbidden_path)
    assert str(tmp_path) not in str(captured.value)


@pytest.mark.unit
@pytest.mark.parametrize("case", RULE_CASES, ids=lambda case: case.case_id)
def test_deterministic_routing_covers_at_least_fifty_independent_rules(
    case: RuleCase,
) -> None:
    assert len(RULE_CASES) >= 60
    engine = RiskRuleEngine.from_files(
        TRANSFER_RULES_PATH,
        FORBIDDEN_CLAIMS_PATH,
    )
    context = RoutingContext(
        conversation_key=CONVERSATION_KEY,
        message_text=case.message_text,
        knowledge_status=case.knowledge_status,
        service_available=case.service_available,
        unresolved_count=case.unresolved_count,
        candidate_reply=case.candidate_reply,
    )

    decision = engine.evaluate(context, current_mode=ConversationMode.AI)

    assert decision.action is case.expected_action
    assert decision.reason is case.expected_reason
    assert decision.risk_level is case.expected_risk
    if decision.action is RoutingAction.HANDOFF:
        assert decision.response_text == engine.handoff_message
    else:
        assert decision.response_text is None


@pytest.mark.unit
@pytest.mark.parametrize(
    ("mode", "action", "reason"),
    [
        (
            ConversationMode.WAITING_HUMAN,
            RoutingAction.HANDOFF,
            HandoffReason.HUMAN_ALREADY_ACTIVE,
        ),
        (
            ConversationMode.HUMAN,
            RoutingAction.HANDOFF,
            HandoffReason.HUMAN_ALREADY_ACTIVE,
        ),
        (
            ConversationMode.CLOSED,
            RoutingAction.BLOCKED,
            HandoffReason.CONVERSATION_CLOSED,
        ),
    ],
)
def test_conversation_mode_precedes_message_rules(
    mode: ConversationMode,
    action: RoutingAction,
    reason: HandoffReason,
) -> None:
    engine = RiskRuleEngine.from_files(
        TRANSFER_RULES_PATH,
        FORBIDDEN_CLAIMS_PATH,
    )
    context = RoutingContext(
        conversation_key=CONVERSATION_KEY,
        message_text="我要退款并投诉还要找真人客服",
        knowledge_status=KnowledgeAvailability.MISSING,
        service_available=False,
        unresolved_count=9,
        candidate_reply="保证退款",
    )

    decision = engine.evaluate(context, current_mode=mode)

    assert decision.action is action
    assert decision.reason is reason


@pytest.mark.unit
def test_message_rule_priority_uses_first_approved_match() -> None:
    engine = RiskRuleEngine.from_files(
        TRANSFER_RULES_PATH,
        FORBIDDEN_CLAIMS_PATH,
    )
    context = RoutingContext(
        conversation_key=CONVERSATION_KEY,
        message_text="我要投诉退款并找真人客服",
        knowledge_status=KnowledgeAvailability.CONFLICT,
        service_available=False,
        unresolved_count=3,
        candidate_reply="保证退款",
    )

    decision = engine.evaluate(context, current_mode=ConversationMode.AI)

    assert decision.reason is HandoffReason.HUMAN_REQUESTED
    assert decision.risk_level is HandoffRiskLevel.MEDIUM
