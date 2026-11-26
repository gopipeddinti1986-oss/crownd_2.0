from decimal import Decimal

import pytest

from app.services.rewards_engine import _calculation, cash, validate_rule_values


def test_reward_calculation_uses_decimal_and_half_up_rounding():
    percentage, formula = _calculation(Decimal("199.95"), "percentage", Decimal("12.500"), None)
    fixed, fixed_formula = _calculation(Decimal("199.95"), "fixed", None, Decimal("37.35"))
    assert percentage == Decimal("24.99")
    assert formula == "199.95 * 12.500 / 100"
    assert fixed == Decimal("37.35")
    assert fixed_formula == "fixed 37.35 per eligible order-item group"
    assert cash(Decimal("10.005")) == Decimal("10.01")


def test_reward_rule_validation_rejects_unsupported_currency_and_invalid_rate():
    base={"reward_type":"percentage","rate":Decimal("10"),"fixed_amount":None,"currency":"INR","minimum_eligible_amount":Decimal("0"),"max_reward":None,"max_creator_total":None,"max_campaign_total":None}
    validate_rule_values(**base)
    with pytest.raises(ValueError,match="INR"):
        validate_rule_values(**{**base,"currency":"USD"})
    with pytest.raises(ValueError,match="rate"):
        validate_rule_values(**{**base,"rate":Decimal("100.001")})
