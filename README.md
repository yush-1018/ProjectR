# Webhook Reconciliation Engine (Payment Duplicate Detector)

> **Razorpay AI Buildathon — Track 04: AI Finance Controller**  
> An automated, dual-layer payment reconciliation engine that ingests payment and webhook streams, detects duplicate charges caused by webhook lag/retry loops, routes ambiguous edge cases to an AI reasoning layer, and outputs an audit log and summary report with an honest exception list.

---

## 1. Problem Statement & Real-World Evidence

In modern payment systems, payment processing happens synchronously with the banking network, but merchant notifications arrive asynchronously via HTTP webhooks. Server congestion, gateway delays, or mobile network dropouts can delay webhooks by several seconds. 

During this lag window:
- Customers may refresh or hit "Pay Again".
- System retries or automated cron jobs issue secondary webhook callbacks for the exact same `intent_id`.
- The merchant's order system, if lacking strict idempotency reconciliation, treats the second callback as a new transaction and creates a **duplicate order or double credit**.

### Evidence from Production (Razorpay WooCommerce Plugin)
This is not a hypothetical bug. Razorpay's official WordPress/WooCommerce plugin ([`razorpay-woocommerce`](https://github.com/razorpay/razorpay-woocommerce)) has had to patch this exact class of bug multiple times across its changelog:
- *"Bug fix, remove duplicate order creation"*
- *"Enhanced webhook cron"*
- *"Fixed empty callback handling"*
- *"Resolved double callback processing race condition"*

---

## 2. Why It Matters

- **Financial Leakage**: Merchants risk fulfilling double goods/services or issuing double refunds for single payments.
- **Finance-Ops Overhead**: Manual reconciliation teams spend dozens of hours auditing ledger discrepancies.
- **Trust & UX**: Double-charging customers leads to chargebacks and support escalations.

---

## 3. What This Builds

A CLI-run reconciliation batch processor that:
1. Ingests synthetic payment and webhook event streams (55 intent records).
2. Performs **Rule-Based Reconciliation** (matching `intent_id`, evaluating inter-arrival time deltas).
3. Routes ambiguous timing and payload edge cases to an **AI Classifier Layer** (Anthropic Claude API / OpenAI GPT-4o-mini with intelligent offline fallback).
4. Computes performance metrics (`match_rate_percent`, `total_amount_saved_inr`).
5. Persists a full structured audit log (`logs/audit_log.json`) and a detailed summary report with an **Honest Exception List** (`reports/summary_report.md`).

---

## 4. System Architecture

For a complete breakdown of data flow and component interactions, see [architecture.md](architecture.md).

```
Payment Stream (JSON) + Webhook Stream (JSON)
                      │
                      ▼
        Rule-Based Reconciler Engine
        ├── Single callback ──────> CLEAN
        ├── Gap < 10.0s ──────────> DUPLICATE_PREVENTED
        └── Gap >= 10.0s / Mismatch > EXCEPTION ──► AI Classifier Layer (LLM)
                                                        │
                                                        ├── Retry Verified ──> DUPLICATE_PREVENTED
                                                        └── Payload Anomaly ─> NEEDS_MANUAL_REVIEW
                                                                                    │
                                                                                    ▼
                                                                       Audit Log & Honest Summary
```

---

## 5. How to Run

### Prerequisites
- Python 3.11+
- (Optional) Set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` in `.env` for live LLM inference. If omitted, built-in intelligent heuristic reasoning is used automatically.

### Installation & Execution

```bash
# 1. Navigate to project root directory
cd webhook-reconciliation-engine

# 2. (Optional) Install dependencies if using live LLM APIs
pip install -r requirements.txt

# 3. Run the reconciliation pipeline
python run.py
```

---

## 6. Live Measured Results & Honest Exception Log

Below are the actual measured results from running `python run.py`:

```text
======================================================================
 RECONCILIATION RUN COMPLETE — SUMMARY METRICS
======================================================================
 Total Batch Volume        : 55 payments
 Clean Transactions        : 46
 Duplicates Blocked        : 6
 Unresolved Exceptions     : 3
 Total Financial Loss Saved: INR 24,943.11
 Measured Match Rate       : 94.55%
======================================================================
```

### Measured Key Indicators
- **Batch Volume**: 55 synthetic transactions total.
- **Clean Transactions**: 46 single-callback payments matched with 100% confidence.
- **Duplicates Prevented**: 6 duplicate webhook retries blocked (4 rule-based, 2 AI-resolved ambiguous timing retries).
- **Financial Loss Prevented**: **INR 24,943.11** saved in duplicate charges.
- **Engine Match Rate**: **94.55%** accuracy (52 out of 55 resolved automatically).

---

### Honest Exception Log (3 Unresolved Edge Cases)

Track 04 judges require an honest reporting of exceptions that cannot be automatically resolved. The engine flagged 3 genuine edge cases for human review:

| Intent ID | Status | Amount at Risk | Confidence | AI Classifier Reasoning |
| :--- | :--- | :--- | :--- | :--- |
| `intent_008` | `NEEDS_MANUAL_REVIEW` | INR 9,434.81 | 0.40 | **Data Mismatch**: Payment customer 'Dev Gupta' does not match webhook customer payload 'UNKNOWN (Meera Singh)'. Flagged for human review. |
| `intent_016` | `NEEDS_MANUAL_REVIEW` | INR 1,204.37 | 0.30 | **Missing Callback**: Intent recorded in system but 0 webhooks received from payment gateway despite creation timestamp. Requires manual gateway audit. |
| `intent_040` | `NEEDS_MANUAL_REVIEW` | INR 9,954.68 | 0.35 | **Financial Discrepancy**: Primary webhook amount (INR 9,954.68) differs from secondary webhook amount (INR 4,977.34). Potential partial capture / refund collision. |

---

## 7. Limitations & Production Roadmap

### Honest Limitations
1. **Simulated Webhook Lag**: Real-world network latency and server delays cannot be reliably forced in Razorpay test mode. Therefore, timing lag (0.5s–15.0s) and payload anomalies are deterministically simulated in `data/generate_data.py`.
2. **Stateless JSON Storage**: For simplicity and zero-dependency execution, state is stored in JSON files (`payments.json`, `webhooks.json`, `audit_log.json`) rather than an ACID database like PostgreSQL or Redis.

### Extension to Production
To deploy this engine in a live production Razorpay environment:
- **Redis Idempotency Lock**: Replace JSON lookups with an atomic Redis distributed lock (`SET intent_id NX EX 30`) to block secondary webhook execution within 30 seconds.
- **Kafka / SQS Stream Ingestion**: Connect the reconciler directly to a real-time message queue to process incoming webhooks with sub-millisecond overhead.
- **Human-in-the-loop Dashboard**: Send low-confidence LLM exceptions directly to a Slack / Retool queue for finance manager approval.
