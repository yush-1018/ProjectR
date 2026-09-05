from datetime import datetime
from typing import List, Dict
from collections import defaultdict
from src.models import Payment, Webhook, ReconciliationResult

def parse_iso_timestamp(ts_str: str) -> datetime:
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"
    return datetime.fromisoformat(ts_str)

def reconcile(payments: List[Payment], webhooks: List[Webhook]) -> List[ReconciliationResult]:
    """
    Reconciles payments against incoming webhook events.
    Groups webhooks by intent_id and analyzes arrival counts, payload consistency, and inter-arrival time gaps.

    Rules:
    - 0 Webhooks -> EXCEPTION (Unconfirmed payment intent)
    - 1 Webhook:
      - Payload attributes match payment -> CLEAN
      - Payload attribute mismatch -> EXCEPTION (Data corruption/cross-session anomaly)
    - 2+ Webhooks:
      - Amount discrepancy between webhooks -> EXCEPTION (Possible partial capture / ledger mismatch)
      - Gap < 10.0s & payload consistent -> DUPLICATE_PREVENTED (Clear duplicate/retry spike)
      - Gap >= 10.0s -> EXCEPTION (Ambiguous timing edge-case, requires AI classifier reasoning)
    """
    payments_by_intent: Dict[str, Payment] = {p.intent_id: p for p in payments}
    webhooks_by_intent: Dict[str, List[Webhook]] = defaultdict(list)

    for wh in webhooks:
        webhooks_by_intent[wh.intent_id].append(wh)

    for intent_id in webhooks_by_intent:
        webhooks_by_intent[intent_id].sort(key=lambda w: parse_iso_timestamp(w.received_at))

    results: List[ReconciliationResult] = []

    for payment in payments:
        intent_id = payment.intent_id
        associated_webhooks = webhooks_by_intent.get(intent_id, [])
        wh_count = len(associated_webhooks)

        if wh_count == 0:
            results.append(ReconciliationResult(
                intent_id=intent_id,
                status="EXCEPTION",
                confidence=0.30,
                reasoning="No webhook received for payment intent. Unconfirmed transaction requiring manual verification.",
                amount_at_risk=payment.amount
            ))

        elif wh_count == 1:
            wh = associated_webhooks[0]
            wh_time = parse_iso_timestamp(wh.received_at)
            pay_time = parse_iso_timestamp(payment.created_at)
            lag_sec = (wh_time - pay_time).total_seconds()

            # Check payload customer consistency if available
            if wh.customer_name and wh.customer_name != payment.customer_name:
                results.append(ReconciliationResult(
                    intent_id=intent_id,
                    status="EXCEPTION",
                    confidence=0.40,
                    reasoning=f"Payload customer anomaly: Payment customer is '{payment.customer_name}' but webhook payload customer is '{wh.customer_name}'. Routed to AI Classifier.",
                    amount_at_risk=payment.amount
                ))
            else:
                results.append(ReconciliationResult(
                    intent_id=intent_id,
                    status="CLEAN",
                    confidence=1.0,
                    reasoning=f"Single webhook received cleanly after {lag_sec:.2f}s delay. Order matched.",
                    amount_at_risk=0.0
                ))

        elif wh_count > 1:
            wh1 = associated_webhooks[0]
            wh2 = associated_webhooks[1]

            wh1_time = parse_iso_timestamp(wh1.received_at)
            wh2_time = parse_iso_timestamp(wh2.received_at)
            gap_sec = (wh2_time - wh1_time).total_seconds()

            # Check for amount discrepancy across webhooks
            if wh1.amount is not None and wh2.amount is not None and wh1.amount != wh2.amount:
                results.append(ReconciliationResult(
                    intent_id=intent_id,
                    status="EXCEPTION",
                    confidence=0.35,
                    reasoning=f"Amount discrepancy detected across webhooks (WH1: INR {wh1.amount}, WH2: INR {wh2.amount}). Routed to AI Classifier.",
                    amount_at_risk=payment.amount
                ))
            elif gap_sec < 10.0:
                results.append(ReconciliationResult(
                    intent_id=intent_id,
                    status="DUPLICATE_PREVENTED",
                    confidence=0.98,
                    reasoning=f"Detected {wh_count} webhooks for same intent. Time gap between webhooks is {gap_sec:.2f}s (< 10s rule limit). Duplicate order creation prevented.",
                    amount_at_risk=payment.amount
                ))
            else:
                results.append(ReconciliationResult(
                    intent_id=intent_id,
                    status="EXCEPTION",
                    confidence=0.50,
                    reasoning=f"Ambiguous inter-webhook arrival gap of {gap_sec:.2f}s (>= 10s threshold). Routed to AI Classifier.",
                    amount_at_risk=payment.amount
                ))

    return results
