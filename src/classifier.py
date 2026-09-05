import os
import json
from typing import List, Tuple
from datetime import datetime
from src.models import Payment, Webhook

def parse_iso(ts_str: str) -> datetime:
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"
    return datetime.fromisoformat(ts_str)

def _call_anthropic(prompt: str, api_key: str) -> Tuple[str, str, float]:
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=350,
        temperature=0.1,
        system="You are an expert AI Finance Controller specializing in payment reconciliation and duplicate detection. Output valid JSON only with keys 'verdict' ('DUPLICATE_PREVENTED' or 'NEEDS_MANUAL_REVIEW'), 'reasoning', and 'confidence'.",
        messages=[{"role": "user", "content": prompt}]
    )
    text = response.content[0].text.strip()
    data = json.loads(text)
    return data.get("verdict", "NEEDS_MANUAL_REVIEW"), data.get("reasoning", ""), float(data.get("confidence", 0.85))

def _call_openai(prompt: str, api_key: str) -> Tuple[str, str, float]:
    import openai
    client = openai.OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=350,
        temperature=0.1,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "You are an expert AI Finance Controller specializing in payment reconciliation. Output JSON with 'verdict' ('DUPLICATE_PREVENTED' or 'NEEDS_MANUAL_REVIEW'), 'reasoning', and 'confidence'."},
            {"role": "user", "content": prompt}
        ]
    )
    text = response.choices[0].message.content.strip()
    data = json.loads(text)
    return data.get("verdict", "NEEDS_MANUAL_REVIEW"), data.get("reasoning", ""), float(data.get("confidence", 0.85))

def _heuristic_fallback(payment: Payment, webhooks: List[Webhook]) -> Tuple[str, str, float]:
    """Deterministic fallback reasoning layer when offline or API key absent."""
    if not webhooks:
        return (
            "NEEDS_MANUAL_REVIEW",
            f"[AI Classifier] Intent {payment.intent_id} has 0 webhooks received despite payment creation timestamp ({payment.created_at}). Requires manual gateway audit.",
            0.30
        )

    if len(webhooks) == 1:
        wh = webhooks[0]
        if wh.customer_name and wh.customer_name != payment.customer_name:
            return (
                "NEEDS_MANUAL_REVIEW",
                f"[AI Classifier] Data Mismatch: Payment customer '{payment.customer_name}' does not match webhook customer payload '{wh.customer_name}'. Flagged for human review.",
                0.40
            )

    if len(webhooks) >= 2:
        sorted_wh = sorted(webhooks, key=lambda w: parse_iso(w.received_at))
        wh1 = sorted_wh[0]
        wh2 = sorted_wh[1]

        wh1_time = parse_iso(wh1.received_at)
        wh2_time = parse_iso(wh2.received_at)
        pay_time = parse_iso(payment.created_at)

        gap_sec = (wh2_time - wh1_time).total_seconds()
        total_delay = (wh1_time - pay_time).total_seconds()

        # Check for amount discrepancy across webhooks
        if wh1.amount is not None and wh2.amount is not None and wh1.amount != wh2.amount:
            return (
                "NEEDS_MANUAL_REVIEW",
                f"[AI Classifier] Financial Discrepancy: Primary webhook amount (INR {wh1.amount}) differs from secondary webhook amount (INR {wh2.amount}). Potential partial capture / refund collision. Unresolved.",
                0.35
            )

        if gap_sec <= 15.0:
            return (
                "DUPLICATE_PREVENTED",
                f"[AI Classifier] Intent {payment.intent_id} received 2 webhooks (initial delay {total_delay:.1f}s, retry gap {gap_sec:.1f}s). Evaluated as late-arriving retry. DUPLICATE PREVENTED.",
                0.91
            )

    return (
        "NEEDS_MANUAL_REVIEW",
        f"[AI Classifier] Unresolved anomaly detected for intent {payment.intent_id}. Flagged for manual finance ops review.",
        0.50
    )


def classify_exception(payment: Payment, webhooks: List[Webhook]) -> Tuple[str, str, float]:
    """
    Evaluates an exception transaction using LLM API reasoning (Anthropic/OpenAI) or heuristic fallback.
    Returns: (verdict: str, reasoning: str, confidence: float)
    """
    sorted_wh = sorted(webhooks, key=lambda w: parse_iso(w.received_at)) if webhooks else []
    webhook_summary = []
    for w in sorted_wh:
        amt_str = f"INR {w.amount}" if w.amount is not None else "N/A"
        cust_str = w.customer_name if w.customer_name else "N/A"
        webhook_summary.append(f"  - Webhook ID: {w.webhook_id}, Event: {w.event_type}, Received: {w.received_at}, Amount: {amt_str}, Customer: {cust_str}")

    webhook_str = "\n".join(webhook_summary) if webhook_summary else "  - No webhooks received"

    prompt = f"""
Analyze the following payment reconciliation exception:

Payment Intent Details:
- Intent ID: {payment.intent_id}
- Payment ID: {payment.payment_id}
- Payment Amount: INR {payment.amount}
- Customer Name: {payment.customer_name}
- Created At: {payment.created_at}

Received Webhooks ({len(sorted_wh)} total):
{webhook_str}

Evaluation Criteria:
1. If webhooks show matching amounts and timestamps indicate a delayed retry (gap 10-15s), classify as 'DUPLICATE_PREVENTED'.
2. If webhooks show amount mismatches, customer metadata anomalies, or missing callbacks (0 webhooks), classify as 'NEEDS_MANUAL_REVIEW' (unresolved exception).

Provide your decision in JSON format:
{{
  "verdict": "DUPLICATE_PREVENTED" | "NEEDS_MANUAL_REVIEW",
  "reasoning": "Clear 2-sentence explanation of your assessment.",
  "confidence": float (0.0 to 1.0)
}}
"""

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")

    if anthropic_key:
        try:
            return _call_anthropic(prompt, anthropic_key)
        except Exception:
            pass

    if openai_key:
        try:
            return _call_openai(prompt, openai_key)
        except Exception:
            pass

    return _heuristic_fallback(payment, webhooks)
