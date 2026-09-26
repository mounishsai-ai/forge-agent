"""Generic time helpers used across the app."""
import time


def now():
    return time.time()


def seconds_until(ts):
    return ts - now()
