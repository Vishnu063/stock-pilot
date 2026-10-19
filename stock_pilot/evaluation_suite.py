"""Keep all declared instruments and evaluation periods, including failed runs."""

from datetime import date
from statistics import median
from .backtest import evaluate
from .risk import money


def evaluate_suite(jobs, schedule):
    if not isinstance(jobs, list) or not jobs or len(jobs) > 50:
        raise ValueError("Declare between 1 and 50 evaluation jobs")
    intervals = {}
    for job in jobs:
        symbol = job["symbol"]
        start = date.fromisoformat(job["split_date"])
        end = date.fromisoformat(job["holdout_end"])
        if not isinstance(symbol, str) or not symbol or end < start:
            raise ValueError("Invalid symbol or period")
        for old_start, old_end in intervals.get(symbol, []):
            if start <= old_end and old_start <= end:
                raise ValueError(
                    "Holdout periods for the same stock overlap; declare disjoint periods"
                )
        intervals.setdefault(symbol, []).append((start, end))
    results = []
    for job in jobs:
        try:
            result = evaluate(
                job["csv"],
                schedule,
                job["split_date"],
                benchmark_path=job.get("benchmark"),
                holdout_end=job["holdout_end"],
            )
            results.append(
                {"symbol": job["symbol"], "status": "completed", "result": result}
            )
        except Exception as exc:
            results.append(
                {
                    "symbol": job["symbol"],
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "split_date": job["split_date"],
                    "holdout_end": job["holdout_end"],
                }
            )
    completed = [r["result"] for r in results if r["status"] == "completed"]
    returns = [money(r["holdout"]["net_return"]) for r in completed]
    return {
        "jobs": results,
        "declared_jobs": len(jobs),
        "completed_jobs": len(completed),
        "failed_jobs": len(jobs) - len(completed),
        "training_trials": sum(len(r["training_trials"]) for r in completed),
        "positive_holdouts": sum(r > 0 for r in returns),
        "median_holdout_return": str(median(returns)) if returns else None,
        "worst_holdout_return": str(min(returns)) if returns else None,
        "best_holdout_return": str(max(returns)) if returns else None,
        "execution_allowed": False,
        "strategy_promoted": False,
        "limitations": [
            "Descriptive per-run results, not a capital-weighted portfolio or confidence estimate",
            "Cross-stock dependence and training-trial dependence are not statistically corrected",
            "All declared failures and losses remain in the report; do not select only favorable periods",
            "Disjoint periods can still be contaminated by repeated human tuning",
        ],
    }
