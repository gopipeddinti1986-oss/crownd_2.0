from decimal import Decimal, ROUND_HALF_UP

def calculate_reward(order_amount: Decimal, reward_model: str, rate: Decimal) -> Decimal:
    """Compute campaign reward using decimal currency arithmetic, rounded to paise."""
    if order_amount < 0 or rate < 0:
        raise ValueError("Amounts and rates cannot be negative")
    if reward_model == "percentage":
        amount=order_amount*rate/Decimal("100")
    elif reward_model == "fixed":
        amount=rate
    else:
        raise ValueError("Unsupported reward model")
    return amount.quantize(Decimal("0.01"),rounding=ROUND_HALF_UP)
