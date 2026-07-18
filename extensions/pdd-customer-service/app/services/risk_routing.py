"""Strict configuration loading for deterministic risk routing."""

import json
import unicodedata
from pathlib import Path

from pydantic import ValidationError

from app.models import (
    ConversationMode,
    ForbiddenClaimsConfig,
    HandoffReason,
    HandoffRiskLevel,
    KnowledgeAvailability,
    RoutingAction,
    RoutingContext,
    RoutingDecision,
    TransferRulesConfig,
)

_RISK_ORDER = {
    HandoffRiskLevel.LOW: 0,
    HandoffRiskLevel.MEDIUM: 1,
    HandoffRiskLevel.HIGH: 2,
    HandoffRiskLevel.CRITICAL: 3,
}


class RiskConfigurationError(RuntimeError):
    """Raised when reviewed risk configuration cannot be loaded safely."""


class RiskRuleEngine:
    """Hold validated deterministic rules without external side effects."""

    def __init__(
        self,
        transfer_rules: TransferRulesConfig,
        forbidden_claims: ForbiddenClaimsConfig,
    ) -> None:
        self._transfer_rules = transfer_rules
        self._forbidden_claims = forbidden_claims

    @classmethod
    def from_files(
        cls,
        transfer_rules_path: Path,
        forbidden_claims_path: Path,
    ) -> "RiskRuleEngine":
        """Load strict JSON-compatible YAML without exposing source content."""

        try:
            transfer_rules = TransferRulesConfig.model_validate_json(
                transfer_rules_path.read_text(encoding="utf-8")
            )
            forbidden_claims = ForbiddenClaimsConfig.model_validate_json(
                forbidden_claims_path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as error:
            raise RiskConfigurationError(
                "Risk rule configuration is invalid or unavailable"
            ) from error
        return cls(transfer_rules, forbidden_claims)

    @property
    def handoff_message(self) -> str:
        """Return the reviewed fixed handoff prompt."""

        return self._transfer_rules.handoff_message

    def evaluate(
        self,
        context: RoutingContext,
        *,
        current_mode: ConversationMode,
    ) -> RoutingDecision:
        """Apply the approved deterministic priority without model inference."""

        if current_mode is ConversationMode.CLOSED:
            return RoutingDecision(
                action=RoutingAction.BLOCKED,
                reason=HandoffReason.CONVERSATION_CLOSED,
                risk_level=HandoffRiskLevel.HIGH,
                response_text=None,
            )
        if current_mode in {
            ConversationMode.WAITING_HUMAN,
            ConversationMode.HUMAN,
        }:
            return self._handoff(
                HandoffReason.HUMAN_ALREADY_ACTIVE,
                HandoffRiskLevel.HIGH,
            )

        normalized_message = self._normalize(context.message_text)
        for rule in self._transfer_rules.text_rules:
            if any(
                self._normalize(keyword) in normalized_message
                for keyword in rule.keywords
            ):
                return self._handoff(rule.reason_code, rule.risk_level)

        if context.knowledge_status is KnowledgeAvailability.MISSING:
            return self._handoff(
                HandoffReason.NO_VALID_KNOWLEDGE,
                HandoffRiskLevel.MEDIUM,
            )
        if context.knowledge_status is KnowledgeAvailability.CONFLICT:
            return self._handoff(
                HandoffReason.KNOWLEDGE_CONFLICT,
                HandoffRiskLevel.HIGH,
            )
        if context.knowledge_status is KnowledgeAvailability.EXPIRED:
            return self._handoff(
                HandoffReason.KNOWLEDGE_EXPIRED,
                HandoffRiskLevel.MEDIUM,
            )
        if not context.service_available:
            return self._handoff(
                HandoffReason.SERVICE_FAILURE,
                HandoffRiskLevel.HIGH,
            )
        if context.unresolved_count >= 2:
            return self._handoff(
                HandoffReason.REPEATED_UNRESOLVED,
                HandoffRiskLevel.MEDIUM,
            )

        forbidden_risks: list[HandoffRiskLevel] = []
        if context.candidate_reply is not None:
            normalized_candidate = self._normalize(context.candidate_reply)
            for claim in self._forbidden_claims.claims:
                if any(
                    self._normalize(phrase) in normalized_candidate
                    for phrase in claim.phrases
                ):
                    forbidden_risks.append(claim.risk_level)
        if forbidden_risks:
            return self._handoff(
                HandoffReason.FORBIDDEN_CLAIM,
                max(forbidden_risks, key=_RISK_ORDER.__getitem__),
            )

        return RoutingDecision(
            action=RoutingAction.CONTINUE_AI,
            reason=None,
            risk_level=HandoffRiskLevel.LOW,
            response_text=None,
        )

    def _handoff(
        self,
        reason: HandoffReason,
        risk_level: HandoffRiskLevel,
    ) -> RoutingDecision:
        return RoutingDecision(
            action=RoutingAction.HANDOFF,
            reason=reason,
            risk_level=risk_level,
            response_text=self.handoff_message,
        )

    @staticmethod
    def _normalize(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value)
        without_controls = "".join(
            character
            for character in normalized
            if not unicodedata.category(character).startswith("C")
        )
        return " ".join(without_controls.casefold().split())
