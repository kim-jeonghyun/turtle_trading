from src.commission import CommissionModel, KRXCommissionModel, USCommissionModel


class TestUSCommissionModel:
    def test_buy_commission(self):
        model = USCommissionModel(commission_rate=0.001)
        cost = model.entry_cost(price=100.0, quantity=10)
        assert cost == 100.0 * 10 * 0.001

    def test_sell_commission(self):
        model = USCommissionModel(commission_rate=0.001)
        cost = model.exit_cost(price=100.0, quantity=10)
        assert cost == 100.0 * 10 * 0.001

    def test_custom_rate(self):
        model = USCommissionModel(commission_rate=0.002)
        assert model.entry_cost(100.0, 10) == 2.0


class TestKRXCommissionModel:
    def test_buy_commission(self):
        """매수: 위탁수수료만"""
        model = KRXCommissionModel(brokerage_rate=0.00015)
        cost = model.entry_cost(price=70000.0, quantity=10)
        assert cost == 70000.0 * 10 * 0.00015

    def test_sell_commission(self):
        """매도: 위탁수수료 + 증권거래세"""
        model = KRXCommissionModel(brokerage_rate=0.00015, transaction_tax_rate=0.0018)
        cost = model.exit_cost(price=70000.0, quantity=10)
        expected = 70000.0 * 10 * (0.00015 + 0.0018)
        assert abs(cost - expected) < 0.01

    def test_sell_has_higher_cost_than_buy(self):
        """매도 비용 > 매수 비용 (거래세 때문)"""
        model = KRXCommissionModel()
        assert model.exit_cost(70000.0, 10) > model.entry_cost(70000.0, 10)


class TestCommissionModelFactory:
    def test_get_us_model(self):
        model = CommissionModel.for_currency("USD")
        assert isinstance(model, USCommissionModel)

    def test_get_kr_model(self):
        model = CommissionModel.for_currency("KRW")
        assert isinstance(model, KRXCommissionModel)

    def test_us_model_with_custom_rate(self):
        model = CommissionModel.for_currency("USD", commission_rate=0.002)
        assert isinstance(model, USCommissionModel)
        assert model.entry_cost(100.0, 10) == 2.0

    def test_unknown_currency_defaults_to_us(self):
        model = CommissionModel.for_currency("EUR")
        assert isinstance(model, USCommissionModel)
