"""A small in-memory bank service used to move money between accounts.

Meant to be called from many threads at once (e.g. one worker thread per
incoming HTTP request in a small transfer API). A flat per-transfer fee is
collected into a shared house account called "fees".
"""
import threading
import time

FEE = 1


class InsufficientFundsError(Exception):
    pass


class Account:
    def __init__(self, account_id, balance=0):
        self.id = account_id
        self.balance = balance
        self.lock = threading.Lock()


class Bank:
    def __init__(self):
        self.accounts = {}
        self.open_account("fees", 0)

    def open_account(self, account_id, balance=0):
        if account_id in self.accounts:
            raise ValueError(f"account {account_id!r} already exists")
        self.accounts[account_id] = Account(account_id, balance)

    def get_balance(self, account_id):
        return self.accounts[account_id].balance

    def total_balance(self):
        return sum(acc.balance for acc in self.accounts.values())

    def _audit_log(self, from_id, to_id, amount):
        # Placeholder for an audit-trail write (e.g. appending to a ledger
        # file or calling a logging service) - has a bit of I/O latency.
        time.sleep(0.001)

    def transfer(self, from_id, to_id, amount):
        """Move `amount` from account `from_id` to account `to_id`, minus a
        flat FEE credited to the "fees" house account.

        Raises ValueError for a non-positive amount or a transfer to itself,
        and InsufficientFundsError if from_id can't cover amount + FEE.
        """
        if amount <= 0:
            raise ValueError("transfer amount must be positive")
        if from_id == to_id:
            raise ValueError("cannot transfer to the same account")

        from_acc = self.accounts[from_id]
        to_acc = self.accounts[to_id]

        with from_acc.lock:
            self._audit_log(from_id, to_id, amount)
            with to_acc.lock:
                total_debit = amount + FEE
                if from_acc.balance < total_debit:
                    raise InsufficientFundsError(
                        f"account {from_id} has insufficient funds for {amount} (+{FEE} fee)"
                    )
                from_acc.balance -= total_debit
                to_acc.balance += amount

        # Credit the house fee account. Done outside the from/to lock pair
        # above since it's a separate, unrelated account.
        fee_acc = self.accounts["fees"]
        current = fee_acc.balance
        time.sleep(0.0005)
        fee_acc.balance = current + FEE
