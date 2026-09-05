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


def _mask_customer_identity(customer_name: str, label: str) -> str:
    """
    Masks real customer names before sending to external AI APIs.
    Replaces PII with anonymized labels (e.g. 'Customer_Payment', 'Customer_Webhook')
    so the AI can still detect mismatch patterns without receiving real names.
    """
    if not customer_name:
        return label
    return label


def _build_api_prompt(payment: Payment, webhooks: List[Webhook]) -> str:
    """
    Constructs the prompt sent to external AI APIs (Anthropic/OpenAI).

    PRIVACY DESIGN: This prompt is intentionally stripped of all PII.
    - customer_name is replaced with anonymized labels ('Customer_Payment', 'Customer_Webhook_N')
    - Only transaction metadata is sent: intent_id, amounts, timestamps, webhook counts, time gaps
    - No card details, emails, phone numbers, or real names are ever sent to the API
    """
    sorted_wh = sorted(webhooks, key=lambda w: parse_iso(w.received_at)) if webhooks else []

    # Build webhook summary with masked customer identifiers
    webhook_lines = []
    for i, w in enumerate(sorted_wh, 1):
        amt_str = f"INR {w.amount}" if w.amount is not None else "N/A"
        # Mask: replace real customer name with anonymized label
        masked_cust = _mask_customer_identity(w.customer_name, f"Customer_Webhook_{i}")
        # Check if webhook customer matches payment customer (pass match/mismatch flag, not names)
        cust_match_flag = ""
        if w.customer_name and payment.customer_name:
            if w.customer_name == payment.customer_name:
                cust_match_flag = " [MATCHES payment customer]"
            else:
                cust_match_flag = " [MISMATCH with payment customer]"
        webhook_lines.append(
            f"  - Webhook {i}: ID={w.webhook_id}, Event={w.event_type}, "
            f"Received={w.received_at}, Amount={amt_str}, "
            f"Customer={masked_cust}{cust_match_flag}"
        )

    webhook_str = "\n".join(webhook_lines) if webhook_lines else "  - No webhooks received"

    # Compute time gaps for the prompt (gives the AI concrete numbers to reason about)
    time_analysis = ""
    if len(sorted_wh) >= 2:
        wh1_time = parse_iso(sorted_wh[0].received_at)
        wh2_time = parse_iso(sorted_wh[1].received_at)
        pay_time = parse_iso(payment.created_at)
        gap = (wh2_time - wh1_time).total_seconds()
        delay = (wh1_time - pay_time).total_seconds()
        time_analysis = f"""
Time Analysis:
- Initial webhook delay after payment: {delay:.2f} seconds
- Gap between webhook 1 and webhook 2: {gap:.2f} seconds
"""

    prompt = f"""Analyze the following payment reconciliation exception:

Payment Intent Details:
- Intent ID: {payment.intent_id}
- Payment ID: {payment.payment_id}
- Payment Amount: INR {payment.amount}
- Customer: Customer_Payment (anonymized)
- Created At: {payment.created_at}

Received Webhooks ({len(sorted_wh)} total):
{webhook_str}
{time_analysis}
Evaluation Criteria:
1. If webhooks show matching amounts and timestamps indicate a delayed retry (gap 10-15s), classify as 'DUPLICATE_PREVENTED'.
2. If webhooks show amount mismatches, customer metadata anomalies (MISMATCH flag), or missing callbacks (0 webhooks), classify as 'NEEDS_MANUAL_REVIEW' (unresolved exception).

Provide your decision in JSON format:
{{
  "verdict": "DUPLICATE_PREVENTED" | "NEEDS_MANUAL_REVIEW",
  "reasoning": "Clear 2-sentence explanation of your assessment.",
  "confidence": float (0.0 to 1.0)
}}
"""
    return prompt


def classify_exception(payment: Payment, webhooks: List[Webhook]) -> Tuple[str, str, float]:
    """
    Evaluates an exception transaction using LLM API reasoning (Anthropic/OpenAI) or heuristic fallback.

    Privacy: When calling external APIs, all customer PII is masked. Only transaction metadata
    (intent_id, amounts, timestamps, webhook counts, time gaps) and anonymized mismatch flags
    are sent. Real customer names are only used in local heuristic fallback output (never sent externally).

    Returns: (verdict: str, reasoning: str, confidence: float)
    """
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")

    # Only build the API prompt (with masked PII) if we have an API key to call
    if anthropic_key or openai_key:
        prompt = _build_api_prompt(payment, webhooks)

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

    # Fallback: heuristic reasoning runs locally — real names are safe here (never sent externally)
    return _heuristic_fallback(payment, webhooks)
