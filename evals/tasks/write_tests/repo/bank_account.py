"""A simple bank account model."""


class InsufficientFundsError(Exception):
    """Raised when a withdrawal or transfer would overdraw the account."""


class BankAccount:
    def __init__(self, owner, balance=0):
        if balance < 0:
            raise ValueError("initial balance cannot be negative")
        self.owner = owner
        self.balance = balance

    def deposit(self, amount):
        if amount <= 0:
            raise ValueError("deposit amount must be positive")
        self.balance += amount
        return self.balance

    def withdraw(self, amount):
        if amount <= 0:
            raise ValueError("withdraw amount must be positive")
        if amount > self.balance:
            raise InsufficientFundsError("insufficient funds")
        self.balance -= amount
        return self.balance

    def transfer(self, other, amount):
        self.withdraw(amount)
        other.deposit(amount)
        return self.balance
