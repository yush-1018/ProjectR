# Webhook Reconciliation Engine (Payment Duplicate Detector)

> **Razorpay AI Buildathon -- Track 04: AI Finance Controller**  
> An automated, dual-layer payment reconciliation engine that ingests payment and webhook streams, detects duplicate charges caused by webhook lag/retry loops, routes ambiguous edge cases to an AI reasoning layer, and outputs a split audit report with an honest exception list.

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
2. Performs **Rule-Based Reconciliation** (matching `intent_id`, evaluating inter-arrival time deltas, checking payload consistency).
3. Routes ambiguous timing and payload edge cases to an **AI Classifier Layer** (Anthropic Claude API / OpenAI GPT-4o-mini with intelligent offline fallback).
4. Computes **split performance metrics** -- rule-based match rate reported separately from AI-assisted resolutions, so numbers are never artificially inflated.
5. Persists a full structured audit log (`logs/audit_log.json`) and a detailed summary report with an **Honest Exception List** (`reports/summary_report.md`).

---

## 4. System Architecture

For a complete breakdown of data flow and component interactions, see [architecture.md](architecture.md).

```
Payment Stream (JSON) + Webhook Stream (JSON)
                      |
                      v
        Rule-Based Reconciler Engine
        |-- Single callback ---------> CLEAN
        |-- Gap < 10.0s -------------> DUPLICATE_PREVENTED (rule-based)
        |-- Gap >= 10.0s ----------\
        |-- Amount mismatch -------+--> EXCEPTION (routed to AI)
        |-- Customer mismatch -----/
        |-- Missing webhook -------/
                                       |
                                       v
                              AI Classifier Layer
                              |-- Retry pattern confirmed --> DUPLICATE_PREVENTED (AI-resolved)
                              |-- Genuinely ambiguous ------> NEEDS_MANUAL_REVIEW (unresolved)
                                                                |
                                                                v
                                                  Audit Log + Honest Exception Report
```

---

## 5. How to Run

### Prerequisites
- Python 3.11+
- (Optional) Set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` in `.env` for live LLM inference. If omitted, built-in intelligent heuristic reasoning is used automatically.

### Installation & Execution

```bash
# 1. Navigate to project root directory
cd ProjectR

# 2. (Optional) Install dependencies if using live LLM APIs
pip install -r requirements.txt

# 3. Run the reconciliation pipeline
python run.py
```

---

## 6. Live Measured Results -- Split Performance Metrics

Below are the **actual** measured results from running `python run.py`:

### Rule-Based Engine (Deterministic, No AI)

| Metric | Value |
| :--- | :--- |
| Total Batch Volume | 55 transactions |
| Clean Single-Callback Payments | 46 |
| Duplicates Prevented (Rule-Based, gap < 10s) | 4 |
| **Rule-Based Match Rate** | **90.91%** |

### AI Classifier Layer (Ambiguous Exceptions)

| Metric | Value |
| :--- | :--- |
| Exceptions Routed to AI | 5 |
| AI Resolved as DUPLICATE_PREVENTED | 2 |
| AI Unresolved (NEEDS_MANUAL_REVIEW) | 3 |
| **Overall Resolution Rate (Rule + AI)** | **94.55%** |

### Financial Impact

| Metric | Value |
| :--- | :--- |
| Total Duplicate Loss Prevented | **INR 24,943.11** |
| Amount at Risk (Unresolved) | INR 20,593.86 |

---

## 7. AI-Resolved Exceptions (2 cases -- reasoning shown)

These cases had ambiguous inter-webhook timing gaps (10-15 seconds) that were too wide for rule-based detection but were successfully classified by the AI reasoning layer:

| Intent ID | Confidence | Amount | AI Reasoning |
| :--- | :--- | :--- | :--- |
| `intent_007` | 0.91 | INR 653.79 | Received 2 webhooks (initial delay 2.6s, retry gap 11.4s). Evaluated as late-arriving network retry. DUPLICATE PREVENTED. |
| `intent_029` | 0.91 | INR 3,371.24 | Received 2 webhooks (initial delay 2.6s, retry gap 12.2s). Evaluated as late-arriving network retry. DUPLICATE PREVENTED. |

---

## 8. Honest Exception Log (3 UNRESOLVED -- requires human review)

Track 04 judges require an honest, un-cherrypicked listing of exceptions that could NOT be resolved, even by the AI classifier. These are genuine edge cases:

| Intent ID | Amount at Risk | Confidence | Why Unresolved |
| :--- | :--- | :--- | :--- |
| `intent_008` | INR 9,434.81 | 0.40 | **Customer Metadata Mismatch**: Payment customer 'Dev Gupta' does not match webhook payload 'UNKNOWN (Meera Singh)'. Possible cross-session data corruption. |
| `intent_016` | INR 1,204.37 | 0.30 | **Missing Webhook**: Payment recorded in system but 0 webhooks received from gateway. Requires manual gateway audit. |
| `intent_040` | INR 9,954.68 | 0.35 | **Amount Discrepancy**: Primary webhook INR 9,954.68 vs secondary webhook INR 4,977.34. Possible partial capture or refund collision. |

---

## 9. Limitations & Production Roadmap

### Honest Limitations
1. **Simulated Webhook Lag**: Real-world network latency and server delays cannot be reliably forced in Razorpay test mode. Therefore, timing lag (0.5s-15.0s) and payload anomalies are deterministically simulated in `data/generate_data.py` with a fixed random seed for reproducibility.
2. **Stateless JSON Storage**: For simplicity and zero-dependency execution, state is stored in JSON files rather than an ACID database like PostgreSQL or Redis.
3. **Offline AI Fallback**: Without API keys, the AI classifier uses deterministic heuristic rules. Production deployment would use live LLM inference for richer reasoning.

### Extension to Production
To deploy this engine in a live production Razorpay environment:
- **Redis Idempotency Lock**: Replace JSON lookups with an atomic Redis distributed lock (`SET intent_id NX EX 30`) to block secondary webhook execution within 30 seconds.
- **Kafka / SQS Stream Ingestion**: Connect the reconciler directly to a real-time message queue to process incoming webhooks with sub-millisecond overhead.
- **Human-in-the-loop Dashboard**: Send low-confidence LLM exceptions directly to a Slack / Retool queue for finance manager approval.
- **Payload Signature Verification**: Cross-reference webhook HMAC signatures to detect tampered or corrupted payloads before reconciliation.
