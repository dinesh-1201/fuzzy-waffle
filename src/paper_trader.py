from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class Signal:
    symbol: str
    side: Side
    timestamp: str
    reference_price: float
    stop_price: float
    target_price: float


@dataclass
class RiskLimits:
    max_trades_per_day: int = 1
    max_daily_loss_rupees: float = 5000.0
    risk_per_trade_rupees: float = 2500.0


class PaperBroker:
    """Execution-free broker adapter for testing signal/risk plumbing.

    This class intentionally does not connect to a live broker or place orders.
    """

    def __init__(self, limits: RiskLimits | None = None):
        self.limits = limits or RiskLimits()
        self.trades_today = 0
        self.daily_pnl = 0.0
        self.kill_switch = False

    def can_trade(self) -> bool:
        return (
            not self.kill_switch
            and self.trades_today < self.limits.max_trades_per_day
            and self.daily_pnl > -self.limits.max_daily_loss_rupees
        )

    def submit(self, signal: Signal) -> dict:
        if not self.can_trade():
            raise RuntimeError("Paper broker rejected signal: risk limit or kill switch")
        self.trades_today += 1
        return {
            "status": "PAPER_ACCEPTED",
            "symbol": signal.symbol,
            "side": signal.side.value,
            "timestamp": signal.timestamp,
            "reference_price": signal.reference_price,
            "stop_price": signal.stop_price,
            "target_price": signal.target_price,
        }

    def record_pnl(self, pnl_rupees: float) -> None:
        self.daily_pnl += pnl_rupees
        if self.daily_pnl <= -self.limits.max_daily_loss_rupees:
            self.kill_switch = True

    def reset_day(self) -> None:
        self.trades_today = 0
        self.daily_pnl = 0.0
        self.kill_switch = False
