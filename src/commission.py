"""시장별 수수료 모델

US: 단일 수수료율 (매수/매도 동일)
KRX: 매수(위탁수수료) + 매도(위탁수수료 + 증권거래세 0.18%)
"""

from abc import ABC, abstractmethod


class CommissionModel(ABC):
    @abstractmethod
    def entry_cost(self, price: float, quantity: int) -> float:
        """매수 수수료"""
        ...

    @abstractmethod
    def exit_cost(self, price: float, quantity: int) -> float:
        """매도 수수료"""
        ...

    def total_cost(self, entry_price: float, exit_price: float, quantity: int) -> float:
        return self.entry_cost(entry_price, quantity) + self.exit_cost(exit_price, quantity)

    @staticmethod
    def for_currency(currency: str, commission_rate: float = 0.001) -> "CommissionModel":
        """통화에 맞는 수수료 모델 생성.

        Args:
            currency: "USD" or "KRW"
            commission_rate: US 시장 수수료율 오버라이드 (BacktestConfig.commission_pct 전달용)
        """
        if currency == "KRW":
            return KRXCommissionModel()
        return USCommissionModel(commission_rate=commission_rate)


class USCommissionModel(CommissionModel):
    """US 시장: 매수/매도 동일 수수료율"""

    def __init__(self, commission_rate: float = 0.001):
        self.commission_rate = commission_rate

    def entry_cost(self, price: float, quantity: int) -> float:
        return price * quantity * self.commission_rate

    def exit_cost(self, price: float, quantity: int) -> float:
        return price * quantity * self.commission_rate


class KRXCommissionModel(CommissionModel):
    """한국거래소: 매수(위탁수수료) + 매도(위탁수수료 + 증권거래세)

    2026년 기준:
    - 위탁수수료: 약 0.015% (증권사별 상이, 온라인 기준)
    - 증권거래세: 0.18% (KOSPI/KOSDAQ 동일, 2026년)
    """

    def __init__(
        self,
        brokerage_rate: float = 0.00015,
        transaction_tax_rate: float = 0.0018,
    ):
        self.brokerage_rate = brokerage_rate
        self.transaction_tax_rate = transaction_tax_rate

    def entry_cost(self, price: float, quantity: int) -> float:
        return price * quantity * self.brokerage_rate

    def exit_cost(self, price: float, quantity: int) -> float:
        return price * quantity * (self.brokerage_rate + self.transaction_tax_rate)
