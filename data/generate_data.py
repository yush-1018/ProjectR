import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Tuple, List, Dict, Any

RANDOM_SEED = 42

FIRST_NAMES = ["Aarav", "Ananya", "Rohan", "Priya", "Vikram", "Sneha", "Aditya", "Kavya", "Rahul", "Neha", "Dev", "Isha", "Arjun", "Diya", "Siddharth", "Meera", "Kabir", "Riya", "Karan", "Pooja"]
LAST_NAMES = ["Sharma", "Verma", "Patel", "Gupta", "Rao", "Nair", "Singh", "Reddy", "Joshi", "Kumar", "Iyer", "Chopra", "Mehta", "Das"]

def generate_customer_name(rnd: random.Random) -> str:
    return f"{rnd.choice(FIRST_NAMES)} {rnd.choice(LAST_NAMES)}"

def generate_synthetic_dataset(data_dir: Path = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    rnd = random.Random(RANDOM_SEED)
    base_time = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc)

    payments = []
    webhooks = []

    webhook_counter = 1001
    payment_counter = 5001

    # Total 55 intent records:
    # - 36 NORMAL: single webhook, 0.5 - 2.0s lag -> CLEAN
    # - 10 DELAYED: single webhook, 3.0 - 8.0s server lag -> CLEAN
    # - 4 DUPLICATE_CLEAR: 2 webhooks, gap 0.5 - 4.0s -> DUPLICATE_PREVENTED (rule-based)
    # - 2 AMBIGUOUS_RETRY: 2 webhooks, gap 10.5 - 14.0s -> AI resolves as DUPLICATE_PREVENTED
    # - 3 TRICKY_EXCEPTIONS:
    #     * 1 Amount mismatch (Payment 4500, Webhook 2 2250 - possible partial refund/mismatch) -> NEEDS_MANUAL_REVIEW
    #     * 1 Customer mismatch (Webhook payload metadata corrupted/mismatched) -> NEEDS_MANUAL_REVIEW
    #     * 1 Missing Webhook (Payment created but 0 webhooks received) -> NEEDS_MANUAL_REVIEW

    record_types = (
        ["NORMAL"] * 36 +
        ["DELAYED"] * 10 +
        ["DUPLICATE_CLEAR"] * 4 +
        ["AMBIGUOUS_RETRY"] * 2 +
        ["AMOUNT_MISMATCH"] * 1 +
        ["CUSTOMER_MISMATCH"] * 1 +
        ["MISSING_WEBHOOK"] * 1
    )
    rnd.shuffle(record_types)

    current_time = base_time

    for idx, rec_type in enumerate(record_types, start=1):
        intent_id = f"intent_{idx:03d}"
        payment_id = f"pay_{payment_counter}"
        payment_counter += 1

        current_time += timedelta(seconds=rnd.uniform(1.0, 5.0))
        payment_created_at = current_time

        amount = round(rnd.uniform(100.0, 10000.0), 2)
        customer_name = generate_customer_name(rnd)

        payment_entry = {
            "payment_id": payment_id,
            "intent_id": intent_id,
            "amount": amount,
            "customer_name": customer_name,
            "created_at": payment_created_at.isoformat()
        }
        payments.append(payment_entry)

        if rec_type == "NORMAL":
            lag = rnd.uniform(0.5, 2.0)
            wh1_time = payment_created_at + timedelta(seconds=lag)
            webhooks.append({
                "webhook_id": f"wh_{webhook_counter}",
                "intent_id": intent_id,
                "amount": amount,
                "customer_name": customer_name,
                "received_at": wh1_time.isoformat(),
                "event_type": "payment.captured"
            })
            webhook_counter += 1

        elif rec_type == "DELAYED":
            lag = rnd.uniform(3.0, 8.0)
            wh1_time = payment_created_at + timedelta(seconds=lag)
            webhooks.append({
                "webhook_id": f"wh_{webhook_counter}",
                "intent_id": intent_id,
                "amount": amount,
                "customer_name": customer_name,
                "received_at": wh1_time.isoformat(),
                "event_type": "payment.captured"
            })
            webhook_counter += 1

        elif rec_type == "DUPLICATE_CLEAR":
            wh1_lag = rnd.uniform(1.0, 3.0)
            wh1_time = payment_created_at + timedelta(seconds=wh1_lag)
            webhooks.append({
                "webhook_id": f"wh_{webhook_counter}",
                "intent_id": intent_id,
                "amount": amount,
                "customer_name": customer_name,
                "received_at": wh1_time.isoformat(),
                "event_type": "payment.captured"
            })
            webhook_counter += 1

            retry_gap = rnd.uniform(0.5, 4.0)
            wh2_time = wh1_time + timedelta(seconds=retry_gap)
            webhooks.append({
                "webhook_id": f"wh_{webhook_counter}",
                "intent_id": intent_id,
                "amount": amount,
                "customer_name": customer_name,
                "received_at": wh2_time.isoformat(),
                "event_type": "payment.captured"
            })
            webhook_counter += 1

        elif rec_type == "AMBIGUOUS_RETRY":
            wh1_lag = rnd.uniform(2.0, 4.0)
            wh1_time = payment_created_at + timedelta(seconds=wh1_lag)
            webhooks.append({
                "webhook_id": f"wh_{webhook_counter}",
                "intent_id": intent_id,
                "amount": amount,
                "customer_name": customer_name,
                "received_at": wh1_time.isoformat(),
                "event_type": "payment.captured"
            })
            webhook_counter += 1

            # Borderline gap: 10.5 to 14.0 seconds (triggers AI reasoning layer)
            retry_gap = rnd.uniform(10.5, 14.0)
            wh2_time = wh1_time + timedelta(seconds=retry_gap)
            webhooks.append({
                "webhook_id": f"wh_{webhook_counter}",
                "intent_id": intent_id,
                "amount": amount,
                "customer_name": customer_name,
                "received_at": wh2_time.isoformat(),
                "event_type": "payment.captured"
            })
            webhook_counter += 1

        elif rec_type == "AMOUNT_MISMATCH":
            # Webhook 1 arrives normally, Webhook 2 arrives with partial/mismatched amount (e.g. 50% of payment amount)
            wh1_time = payment_created_at + timedelta(seconds=1.5)
            webhooks.append({
                "webhook_id": f"wh_{webhook_counter}",
                "intent_id": intent_id,
                "amount": amount,
                "customer_name": customer_name,
                "received_at": wh1_time.isoformat(),
                "event_type": "payment.captured"
            })
            webhook_counter += 1

            wh2_time = wh1_time + timedelta(seconds=5.0)
            mismatched_amount = round(amount * 0.5, 2)
            webhooks.append({
                "webhook_id": f"wh_{webhook_counter}",
                "intent_id": intent_id,
                "amount": mismatched_amount,
                "customer_name": customer_name,
                "received_at": wh2_time.isoformat(),
                "event_type": "payment.captured"
            })
            webhook_counter += 1

        elif rec_type == "CUSTOMER_MISMATCH":
            # Webhook metadata contains mismatched customer name (data corruption/cross-session leak simulation)
            wh1_time = payment_created_at + timedelta(seconds=2.0)
            different_customer = f"UNKNOWN ({generate_customer_name(rnd)})"
            webhooks.append({
                "webhook_id": f"wh_{webhook_counter}",
                "intent_id": intent_id,
                "amount": amount,
                "customer_name": different_customer,
                "received_at": wh1_time.isoformat(),
                "event_type": "payment.captured"
            })
            webhook_counter += 1

        elif rec_type == "MISSING_WEBHOOK":
            # Payment recorded in system, but 0 webhooks received from gateway
            pass

    if data_dir is not None:
        data_dir.mkdir(parents=True, exist_ok=True)
        payments_path = data_dir / "payments.json"
        webhooks_path = data_dir / "webhooks.json"

        with open(payments_path, "w", encoding="utf-8") as f:
            json.dump(payments, f, indent=2)

        with open(webhooks_path, "w", encoding="utf-8") as f:
            json.dump(webhooks, f, indent=2)

    return payments, webhooks

if __name__ == "__main__":
    current_dir = Path(__file__).resolve().parent
    payments, webhooks = generate_synthetic_dataset(current_dir)
    print(f"Generated {len(payments)} payment records and {len(webhooks)} webhook events in {current_dir}")
