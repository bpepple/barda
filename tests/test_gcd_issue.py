from decimal import Decimal

from barda.gcd.gcd_issue import GCD_Issue


def test_set_price() -> None:
    gcd = GCD_Issue(gcd_id=294322, number="244", price="USD 0.60")
    assert gcd.price == Decimal("0.6")
