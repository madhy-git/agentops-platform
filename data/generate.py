"""Synthetic data generator for Wattle Bank (fictional). No real customer data, ever.

Usage:
    uv run python data/generate.py                 # writes data/generated/*.jsonl (seed 7)
    uv run python data/generate.py --shift 0.5     # a *drifted* population (Phase 1 drift experiment)

LEARNING NOTES
- Seeded: the same seed always produces the same files, so experiments are reproducible and a
  diff in data/generated/ means someone changed the generator, not that randomness moved.
- The churn label is produced by a known hidden formula plus noise. That sounds like cheating,
  but it's how you *test* a model pipeline: you know the true signal, so you can check whether
  the risk model (decision/risk.py) recovers it, and see what drift does to it.
- `--shift` moves feature distributions (fewer logins, more missed payments). Same formula,
  different inputs = *data drift*. Changing the formula itself would be *concept drift*.
- Messages come in two styles: "keyword" (phrased the way the rules expect) and "paraphrase"
  (same meaning, none of the trigger words). The gap between them is the lesson from A11.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).parent / "generated"
TODAY = date(2026, 11, 1)  # fixed "now" so generated dates are stable across runs

STAGES = ["onboarding", "everyday", "growth", "distress", "resolution", "retention"]
STAGE_WEIGHTS = [0.10, 0.55, 0.12, 0.08, 0.05, 0.10]
FIRST = ["Alex", "Sam", "Jordan", "Priya", "Wei", "Aroha", "Liam", "Mia", "Noah", "Zara", "Tom", "Ivy"]
LAST = ["Nguyen", "Smith", "Patel", "Chen", "Walker", "Kaur", "Brown", "Wilson", "Taylor", "Singh"]
PRODUCTS = ["everyday", "savings", "credit_card", "personal_loan", "home_loan"]

# (category, needs_human, keyword templates, paraphrase templates)
MESSAGES = [
    ("fraud", True,
     ["My card was stolen at {place}", "I think this is a scam, someone called pretending to be you",
      "There are unauthorised charges on my account from {place}"],
     ["Someone used my card without permission at {place}", "There's a ${amt} payment I never made",
      "A man on the phone said he was from the bank and I gave him a code"]),
    ("hardship", True,
     ["I lost my job and can't pay my {product} this month", "I'm struggling to make repayments",
      "Financial hardship, I cannot pay the loan"],
     ["My hours were cut and the {product} repayment is due Friday", "My partner passed away and money is tight",
      "I've been unwell and haven't been able to work"]),
    ("dispute", True,
     ["I was charged twice at {place}, please refund", "I want to dispute a wrong charge of ${amt}",
      "Please refund the duplicate payment to {place}"],
     ["The merchant never delivered my order", "{place} took ${amt} but I cancelled weeks ago",
      "I paid for something that never arrived"]),
    ("complaint", True,
     ["I want to make a complaint about terrible service", "I'm very unhappy and will go to the ombudsman",
      "This is a formal complaint"],
     ["Your staff were rude to me on the phone", "I've called four times and nobody fixed it",
      "I'm fed up with how I've been treated"]),
    ("general", False,
     ["What are the fees on the everyday account?", "How do I download my statement?",
      "How is credit card interest calculated?"],
     ["What time does the {place} branch open?", "Can I set up a direct debit in the app?",
      "What's the rate on the savings account?"]),
]  # fmt: skip
PLACES = ["the airport", "Parramatta", "Bondi", "a petrol station", "an online store", "Fitzroy"]


def churn_probability(c: dict) -> float:
    """The hidden 'true' churn signal. The risk model never sees this function, only its outputs."""
    z = (
        -2.0
        + 1.2 * (c["monthly_logins"] < 4)
        + 0.8 * c["complaints_12m"]
        + 0.9 * (c["balance_trend"] < -0.3)
        - 0.6 * (len(c["products"]) >= 3)
        - 0.002 * c["tenure_days"] / 10
    )
    return 1 / (1 + math.exp(-z))


def customer(i: int, rng: random.Random, shift: float) -> dict:
    stage = rng.choices(STAGES, STAGE_WEIGHTS)[0]
    c = {
        "customer_id": f"CUS-{i:05d}",
        "name": f"{rng.choice(FIRST)} {rng.choice(LAST)}",
        "lifecycle_stage": stage,
        "tenure_days": rng.randint(5, 90) if stage == "onboarding" else rng.randint(90, 4000),
        "products": sorted(rng.sample(PRODUCTS, rng.randint(1, 3))),
        # shift > 0 lowers logins and worsens balance trends: data drift.
        "monthly_logins": max(0, int(rng.gauss(12 - 6 * shift, 5))),
        "balance_trend": round(max(-1.0, min(1.0, rng.gauss(0.05 - 0.4 * shift, 0.35))), 2),
        "missed_payments_90d": rng.choices([0, 1, 2, 3], [0.85 - 0.3 * shift, 0.08 + 0.15 * shift, 0.05, 0.02])[0],
        "complaints_12m": rng.choices([0, 1, 2], [0.88, 0.09, 0.03])[0],
        "vulnerable": rng.random() < 0.04,
    }
    c["churned"] = rng.random() < churn_probability(c)
    return c


def message(i: int, rng: random.Random, customers: list[dict]) -> dict:
    cat, human, keyword, paraphrase = rng.choice(MESSAGES)
    style = "paraphrase" if rng.random() < 0.35 else "keyword"
    tpl = rng.choice(paraphrase if style == "paraphrase" else keyword)
    cust = rng.choice(customers)
    text = tpl.format(place=rng.choice(PLACES), amt=rng.choice([45, 120, 640, 900, 1500]), product="credit card")
    return {
        "message_id": f"MSG-{i:05d}",
        "customer_id": cust["customer_id"],
        "text": text,
        "category": cat,
        "needs_human": human,
        "style": style,
    }


def transaction(i: int, rng: random.Random, customers: list[dict]) -> dict:
    # Ages up to 200 days so some disputes fall outside the 120-day window (rule R3).
    return {
        "txn_id": f"TXN-{i:06d}",
        "customer_id": rng.choice(customers)["customer_id"],
        "date": (TODAY - timedelta(days=rng.randint(0, 200))).isoformat(),
        "merchant": rng.choice(PLACES),
        "amount": round(rng.uniform(5, 2000), 2),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    # 3000, not 600: with 600 the model could not recover the rare `complaints_12m` effect (see model card).
    ap.add_argument("--customers", type=int, default=3000)
    ap.add_argument("--messages", type=int, default=300)
    ap.add_argument("--shift", type=float, default=0.0, help="0 = baseline population; >0 = drifted")
    ap.add_argument("--suffix", default="", help="filename suffix, e.g. _drifted")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    customers = [customer(i, rng, args.shift) for i in range(1, args.customers + 1)]
    messages = [message(i, rng, customers) for i in range(1, args.messages + 1)]
    txns = [transaction(i, rng, customers) for i in range(1, args.customers * 2 + 1)]

    OUT.mkdir(exist_ok=True)
    for name, rows in (("customers", customers), ("messages", messages), ("transactions", txns)):
        path = OUT / f"{name}{args.suffix}.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        print(
            f"wrote {len(rows):>5} rows -> {path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path}"
        )


if __name__ == "__main__":
    main()
