"""Core math: weighted-average cost basis per asset, and the
"how much do I need to buy to reach a target average" solver.

Average-cost method (not FIFO): each buy adds to a running pool of
quantity + total EUR cost. Each sell removes quantity from the pool *at
the pool's current average cost* (so a sell doesn't change the average,
it only reduces total cost and quantity proportionally, and yields a
realized P/L figure). This matches what most portfolio trackers show as
"average buy price" and is the standard reading of "my purchase average".

Note this is for your own tracking, not a tax-lot method - Spain's tax
authority (Hacienda) uses FIFO for crypto capital gains, which can differ
from this average-cost figure. If you ever need FIFO-based realized gains
for a tax filing, that's a separate calculation from what's built here.
"""
from dataclasses import dataclass
from typing import List, Optional

from .models import Transaction, TxType


@dataclass
class Holding:
    symbol: str
    quantity: float
    avg_cost_eur: float          # EUR per unit, weighted average of what's still held
    total_cost_eur: float         # quantity * avg_cost_eur (what's still "invested")
    realized_pl_eur: float        # cumulative P/L from sells, at average-cost method


def compute_holding(transactions: List[Transaction]) -> Optional[Holding]:
    """transactions: all Transaction rows for a single asset, any order."""
    if not transactions:
        return None

    txs = sorted(transactions, key=lambda t: t.timestamp)
    symbol = txs[0].asset.symbol if txs[0].asset else "?"

    qty = 0.0
    total_cost = 0.0
    realized_pl = 0.0

    for t in txs:
        if t.tx_type == TxType.buy:
            qty += t.quantity
            total_cost += t.total_eur
        else:  # sell
            avg_cost_before = (total_cost / qty) if qty > 0 else 0.0
            cost_removed = avg_cost_before * t.quantity
            realized_pl += t.total_eur - cost_removed
            total_cost -= cost_removed
            qty -= t.quantity
            # Guard against float drift pushing qty/cost slightly negative
            if qty < 1e-12:
                qty = 0.0
                total_cost = 0.0

    avg_cost = (total_cost / qty) if qty > 0 else 0.0

    return Holding(
        symbol=symbol,
        quantity=qty,
        avg_cost_eur=avg_cost,
        total_cost_eur=total_cost,
        realized_pl_eur=realized_pl,
    )


@dataclass
class TargetAverageResult:
    reachable: bool
    message: str
    required_quantity: Optional[float] = None
    required_eur: Optional[float] = None


def solve_target_average(
    current_qty: float,
    current_avg_cost: float,
    buy_price: float,
    target_avg: float,
) -> TargetAverageResult:
    """How much do I need to buy at `buy_price` so my average cost becomes
    `target_avg`?

    New average after buying X units at buy_price:
        (current_qty*current_avg_cost + X*buy_price) / (current_qty + X) = target_avg
    Solve for X:
        X = current_qty * (current_avg_cost - target_avg) / (target_avg - buy_price)

    Only makes sense when target_avg is strictly between buy_price and
    current_avg_cost (whichever order - this formula covers both
    averaging down and averaging up).
    """
    if current_qty <= 0:
        return TargetAverageResult(
            False, "You don't hold any of this asset yet, so there's no average to move."
        )

    if buy_price <= 0 or target_avg <= 0:
        return TargetAverageResult(False, "Price and target average must be positive.")

    if target_avg == buy_price:
        return TargetAverageResult(
            False, "Target average equals the buy price - that's only reachable by buying an infinite amount."
        )

    lo, hi = sorted([buy_price, current_avg_cost])
    if not (lo < target_avg < hi) :
        if current_avg_cost == target_avg:
            return TargetAverageResult(
                False, "That's already your current average - no purchase needed."
            )
        return TargetAverageResult(
            False,
            f"Not reachable: a target average of {target_avg:.4f} needs to sit strictly between "
            f"the buy price ({buy_price:.4f}) and your current average ({current_avg_cost:.4f}). "
            f"No finite purchase gets you there."
        )

    x = current_qty * (current_avg_cost - target_avg) / (target_avg - buy_price)
    required_eur = x * buy_price

    direction = "down" if target_avg < current_avg_cost else "up"
    return TargetAverageResult(
        True,
        f"Buy {x:.8f} units at {buy_price:.4f} EUR ({required_eur:.2f} EUR total) to move your "
        f"average {direction} to {target_avg:.4f} EUR.",
        required_quantity=x,
        required_eur=required_eur,
    )
