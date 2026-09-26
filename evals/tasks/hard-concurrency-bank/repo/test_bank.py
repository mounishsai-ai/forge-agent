import pytest

from bank import Bank, InsufficientFundsError, FEE


def test_basic_transfer_with_fee():
    bank = Bank()
    bank.open_account("a", 100)
    bank.open_account("b", 50)
    bank.transfer("a", "b", 30)
    assert bank.get_balance("a") == 100 - 30 - FEE
    assert bank.get_balance("b") == 50 + 30
    assert bank.get_balance("fees") == FEE


def test_insufficient_funds():
    bank = Bank()
    bank.open_account("a", 10)
    bank.open_account("b", 0)
    with pytest.raises(InsufficientFundsError):
        bank.transfer("a", "b", 10)  # 10 + FEE > 10
    assert bank.get_balance("a") == 10


def test_invalid_amount():
    bank = Bank()
    bank.open_account("a", 10)
    bank.open_account("b", 0)
    with pytest.raises(ValueError):
        bank.transfer("a", "b", 0)
    with pytest.raises(ValueError):
        bank.transfer("a", "b", -5)


def test_self_transfer_rejected():
    bank = Bank()
    bank.open_account("a", 10)
    with pytest.raises(ValueError):
        bank.transfer("a", "a", 5)


def test_total_conserved_single_threaded():
    bank = Bank()
    bank.open_account("a", 100)
    bank.open_account("b", 100)
    total_before = bank.total_balance()
    bank.transfer("a", "b", 10)
    bank.transfer("b", "a", 20)
    assert bank.total_balance() == total_before
