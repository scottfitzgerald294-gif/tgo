"""Synthetic deterministic risk-routing cases."""

from dataclasses import dataclass

from app.models import (
    HandoffReason,
    HandoffRiskLevel,
    KnowledgeAvailability,
    RoutingAction,
)


@dataclass(frozen=True)
class RuleCase:
    """One independent FAKE/TEST routing expectation."""

    case_id: str
    message_text: str
    expected_action: RoutingAction
    expected_reason: HandoffReason | None
    expected_risk: HandoffRiskLevel
    knowledge_status: KnowledgeAvailability = KnowledgeAvailability.VALID
    service_available: bool = True
    unresolved_count: int = 0
    candidate_reply: str | None = None


def _text_cases(
    prefix: str,
    phrases: tuple[str, ...],
    reason: HandoffReason,
    risk: HandoffRiskLevel,
) -> list[RuleCase]:
    return [
        RuleCase(
            case_id=f"{prefix}-{index:02d}",
            message_text=phrase,
            expected_action=RoutingAction.HANDOFF,
            expected_reason=reason,
            expected_risk=risk,
        )
        for index, phrase in enumerate(phrases, start=1)
    ]


RULE_CASES = (
    *_text_cases(
        "human",
        (
            "找真人客服",
            "我要人工客服",
            "请转人工",
            "让客服人员处理",
            "联系人工处理",
            "我需要真人服务",
            "\u0000帮我找\u3000真人客服",
        ),
        HandoffReason.HUMAN_REQUESTED,
        HandoffRiskLevel.MEDIUM,
    ),
    *_text_cases(
        "complaint",
        (
            "我要投诉",
            "我要举报这个问题",
            "我会找律师",
            "准备起诉",
            "这违反法律",
            "我要找监管部门",
            "我会联系市监局",
            "我要去消协",
            "我打12315",
        ),
        HandoffReason.COMPLAINT_LEGAL_REGULATORY,
        HandoffRiskLevel.HIGH,
    ),
    *_text_cases(
        "refund",
        (
            "我要退款",
            "马上退钱",
            "你们要赔偿",
            "要求赔付",
            "必须补偿",
            "帮我改价",
            "现在给我降价",
            "退还差价",
            "我要价格保护",
        ),
        HandoffReason.REFUND_COMPENSATION_PRICE,
        HandoffRiskLevel.HIGH,
    ),
    *_text_cases(
        "order",
        (
            "帮我改地址",
            "修改地址",
            "我要换地址",
            "取消订单",
            "修改订单",
            "帮我改订单",
            "更改订单内容",
            "拦截订单",
        ),
        HandoffReason.ORDER_CHANGE,
        HandoffRiskLevel.HIGH,
    ),
    *_text_cases(
        "safety",
        (
            "使用后受伤了",
            "这个会造成伤害",
            "怀疑材料有毒",
            "产品漏电",
            "刚才起火了",
            "产品爆炸",
            "孩子误食了",
        ),
        HandoffReason.PRODUCT_SAFETY_INJURY,
        HandoffRiskLevel.CRITICAL,
    ),
    *_text_cases(
        "quality",
        (
            "有严重质量问题",
            "刚用就断裂",
            "收到就是破损的",
            "产品已经发霉",
            "有刺鼻气味",
            "完全无法使用",
            "表面大面积脱落",
        ),
        HandoffReason.SEVERE_QUALITY,
        HandoffRiskLevel.HIGH,
    ),
    RuleCase(
        "knowledge-missing-01",
        "这个虚构型号有什么参数",
        RoutingAction.HANDOFF,
        HandoffReason.NO_VALID_KNOWLEDGE,
        HandoffRiskLevel.MEDIUM,
        knowledge_status=KnowledgeAvailability.MISSING,
    ),
    RuleCase(
        "knowledge-missing-02",
        "未知商品参数是多少",
        RoutingAction.HANDOFF,
        HandoffReason.NO_VALID_KNOWLEDGE,
        HandoffRiskLevel.MEDIUM,
        knowledge_status=KnowledgeAvailability.MISSING,
    ),
    RuleCase(
        "knowledge-conflict-01",
        "两个测试说明不一致",
        RoutingAction.HANDOFF,
        HandoffReason.KNOWLEDGE_CONFLICT,
        HandoffRiskLevel.HIGH,
        knowledge_status=KnowledgeAvailability.CONFLICT,
    ),
    RuleCase(
        "knowledge-conflict-02",
        "虚构政策互相冲突",
        RoutingAction.HANDOFF,
        HandoffReason.KNOWLEDGE_CONFLICT,
        HandoffRiskLevel.HIGH,
        knowledge_status=KnowledgeAvailability.CONFLICT,
    ),
    RuleCase(
        "knowledge-expired-01",
        "这条测试说明还能用吗",
        RoutingAction.HANDOFF,
        HandoffReason.KNOWLEDGE_EXPIRED,
        HandoffRiskLevel.MEDIUM,
        knowledge_status=KnowledgeAvailability.EXPIRED,
    ),
    RuleCase(
        "knowledge-expired-02",
        "查询过期虚构政策",
        RoutingAction.HANDOFF,
        HandoffReason.KNOWLEDGE_EXPIRED,
        HandoffRiskLevel.MEDIUM,
        knowledge_status=KnowledgeAvailability.EXPIRED,
    ),
    RuleCase(
        "service-failure-01",
        "测试接口现在不可用",
        RoutingAction.HANDOFF,
        HandoffReason.SERVICE_FAILURE,
        HandoffRiskLevel.HIGH,
        service_available=False,
    ),
    RuleCase(
        "service-failure-02",
        "模拟模型故障",
        RoutingAction.HANDOFF,
        HandoffReason.SERVICE_FAILURE,
        HandoffRiskLevel.HIGH,
        service_available=False,
    ),
    RuleCase(
        "unresolved-01",
        "还是没有解决",
        RoutingAction.HANDOFF,
        HandoffReason.REPEATED_UNRESOLVED,
        HandoffRiskLevel.MEDIUM,
        unresolved_count=2,
    ),
    RuleCase(
        "unresolved-02",
        "第三次询问同一测试问题",
        RoutingAction.HANDOFF,
        HandoffReason.REPEATED_UNRESOLVED,
        HandoffRiskLevel.MEDIUM,
        unresolved_count=3,
    ),
    *[
        RuleCase(
            case_id=f"forbidden-{index:02d}",
            message_text="这是普通测试问题",
            expected_action=RoutingAction.HANDOFF,
            expected_reason=HandoffReason.FORBIDDEN_CLAIM,
            expected_risk=risk,
            candidate_reply=phrase,
        )
        for index, (phrase, risk) in enumerate(
            (
                ("我们保证退款", HandoffRiskLevel.HIGH),
                ("可以无条件退款", HandoffRiskLevel.HIGH),
                ("结果百分百有效", HandoffRiskLevel.CRITICAL),
                ("这个绝对安全", HandoffRiskLevel.CRITICAL),
                ("承诺永久有效", HandoffRiskLevel.HIGH),
                ("款项一定到账", HandoffRiskLevel.HIGH),
            ),
            start=1,
        )
    ],
    *[
        RuleCase(
            case_id=f"safe-{index:02d}",
            message_text=phrase,
            expected_action=RoutingAction.CONTINUE_AI,
            expected_reason=None,
            expected_risk=HandoffRiskLevel.LOW,
        )
        for index, phrase in enumerate(
            (
                "你好",
                "这个FAKE商品怎么使用",
                "请介绍测试规格",
                "虚构商品是什么颜色",
                "谢谢你的测试说明",
            ),
            start=1,
        )
    ],
)
