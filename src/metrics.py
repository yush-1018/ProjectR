from typing import List, Dict, Any
from src.models import ReconciliationResult

def compute_metrics(results: List[ReconciliationResult]) -> Dict[str, Any]:
    """
    Computes summary metrics from reconciliation results.
    Returns dictionary with match rates, financial savings, and exception breakdowns.
    """
    total_processed = len(results)
    clean_count = sum(1 for r in results if r.status == "CLEAN")
    duplicates_prevented_count = sum(1 for r in results if r.status == "DUPLICATE_PREVENTED")
    exception_count = sum(1 for r in results if r.status in ("EXCEPTION", "NEEDS_MANUAL_REVIEW"))

    total_amount_saved = sum(r.amount_at_risk for r in results if r.status == "DUPLICATE_PREVENTED")

    resolved_count = clean_count + duplicates_prevented_count
    match_rate_percent = (resolved_count / total_processed * 100.0) if total_processed > 0 else 0.0

    exceptions_list = [
        {
            "intent_id": r.intent_id,
            "status": r.status,
            "confidence": r.confidence,
            "reasoning": r.reasoning,
            "amount_at_risk": r.amount_at_risk
        }
        for r in results if r.status in ("EXCEPTION", "NEEDS_MANUAL_REVIEW")
    ]

    return {
        "total_processed": total_processed,
        "clean_count": clean_count,
        "duplicates_prevented_count": duplicates_prevented_count,
        "exception_count": exception_count,
        "total_amount_saved_inr": round(total_amount_saved, 2),
        "match_rate_percent": round(match_rate_percent, 2),
        "exceptions_list": exceptions_list
    }
