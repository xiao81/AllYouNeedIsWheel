"""
Currency conversion and currency-related utilities for AllYouNeedIsWheel
"""

from currency_converter import CurrencyConverter
import logging

logger = logging.getLogger("autotrader.currency")

BASE_CURRENCY = "USD"


class CurrencyHelper:
    converter = CurrencyConverter()

    @staticmethod
    def get_exchange_rate(from_currency, to_currency=BASE_CURRENCY):
        if from_currency == to_currency:
            return 1.0
        try:
            return CurrencyHelper.converter.convert(1, from_currency, to_currency)
        except Exception as e:
            logger.warning(
                f"Could not get exchange rate for {from_currency} to {to_currency}: {e}"
            )
            return 1.0

    @staticmethod
    def convert_amount(amount, from_currency, to_currency=BASE_CURRENCY):
        rate = CurrencyHelper.get_exchange_rate(from_currency, to_currency)
        return amount * rate
