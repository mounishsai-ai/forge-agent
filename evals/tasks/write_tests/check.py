"""Grader for write_tests.

The agent's test_bank_account.py must:
  1. Pass against the pristine bank_account.py.
  2. Fail (catch a regression) on at least 2 of 3 mutated versions of bank_account.py.

The pristine source is embedded here (not read from the workdir) so a checker run
against an already-mutated bank_account.py can't accidentally "pass on original".
"""
import os
import shutil
import subprocess
import sys
import tempfile

WORKDIR = os.getcwd()
TEST_FILE = os.path.join(WORKDIR, "test_bank_account.py")

PRISTINE = '''"""A simple bank account model."""


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
'''

MUTANTS = []

MUTANTS.append((
    "deposit_no_validation",
    '''    def deposit(self, amount):
        if amount <= 0:
            raise ValueError("deposit amount must be positive")
        self.balance += amount
        return self.balance
''',
    '''    def deposit(self, amount):
        self.balance += amount
        return self.balance
''',
))

MUTANTS.append((
    "withdraw_boundary_bug",
    '''    def withdraw(self, amount):
        if amount <= 0:
            raise ValueError("withdraw amount must be positive")
        if amount > self.balance:
            raise InsufficientFundsError("insufficient funds")
        self.balance -= amount
        return self.balance
''',
    '''    def withdraw(self, amount):
        if amount <= 0:
            raise ValueError("withdraw amount must be positive")
        if amount >= self.balance:
            raise InsufficientFundsError("insufficient funds")
        self.balance -= amount
        return self.balance
''',
))

MUTANTS.append((
    "transfer_direction_swapped",
    '''    def transfer(self, other, amount):
        self.withdraw(amount)
        other.deposit(amount)
        return self.balance
''',
    '''    def transfer(self, other, amount):
        self.deposit(amount)
        other.withdraw(amount)
        return self.balance
''',
))


def fail(msg):
    print(f"FAIL: {msg}")
    sys.exit(1)


def run_pytest(tmpdir):
    try:
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "test_bank_account.py"],
            cwd=tmpdir, capture_output=True, text=True, timeout=25,
        )
    except subprocess.TimeoutExpired:
        return None


def main():
    if not os.path.isfile(TEST_FILE):
        fail("test_bank_account.py was not created")
    with open(TEST_FILE, encoding="utf-8") as f:
        test_text = f.read()
    if test_text.count("def test_") < 2:
        fail("test_bank_account.py does not appear to contain a real test suite")

    for name, old, _new in MUTANTS:
        if PRISTINE.count(old) != 1:
            fail(f"internal error: mutant block {name!r} isn't unique in PRISTINE (checker bug)")

    # --- pass on the pristine module ---
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "bank_account.py"), "w", encoding="utf-8") as f:
            f.write(PRISTINE)
        shutil.copy(TEST_FILE, os.path.join(tmp, "test_bank_account.py"))
        result = run_pytest(tmp)
        if result is None:
            fail("pytest timed out running against the original bank_account.py")
        if result.returncode != 0:
            fail("agent's tests do not pass against the ORIGINAL bank_account.py:\n"
                 + (result.stdout + result.stderr)[-1500:])

    # --- catch regressions in mutants ---
    caught = 0
    details = []
    for mutant_name, old, new in MUTANTS:
        mutated_src = PRISTINE.replace(old, new)
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "bank_account.py"), "w", encoding="utf-8") as f:
                f.write(mutated_src)
            shutil.copy(TEST_FILE, os.path.join(tmp, "test_bank_account.py"))
            result = run_pytest(tmp)
            if result is None:
                details.append(f"{mutant_name}: pytest timed out (not counted as caught)")
                continue
            if result.returncode != 0:
                caught += 1
                details.append(f"{mutant_name}: CAUGHT")
            else:
                details.append(f"{mutant_name}: MISSED")

    if caught < 2:
        fail(f"tests only caught {caught}/3 mutants (need >=2):\n" + "\n".join(details))

    print(f"PASS ({caught}/3 mutants caught)")
    sys.exit(0)


if __name__ == "__main__":
    main()
