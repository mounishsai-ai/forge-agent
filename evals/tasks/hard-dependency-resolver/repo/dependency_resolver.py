r"""A mini package-manager dependency resolver.

Versions are plain semver triples: "MAJOR.MINOR.PATCH", all non-negative
integers, no pre-release/build tags. Compare them the obvious way (compare
MAJOR, then MINOR, then PATCH numerically).

Constraint strings (each package can be required under one constraint from
each thing that depends on it):

  "1.2.3"    exact      -- only version 1.2.3 satisfies it.
  ">=1.2.3"  at-least   -- 1.2.3 or any higher version.
  "<1.2.3"   below      -- any version strictly lower than 1.2.3.
  "~1.2.3"   tilde      -- >=1.2.3 and <1.3.0 (patch-level changes only:
                            minor is pinned, patch can float).
  "^1.2.3"   caret      -- >=1.2.3 and below the next change that npm would
                            consider breaking:
                              MAJOR > 0:            < (MAJOR+1).0.0
                              MAJOR == 0, MINOR > 0: < 0.(MINOR+1).0
                              MAJOR == 0, MINOR == 0: < 0.0.(PATCH+1)

index format:

    index = {
        "pkgname": {
            "1.0.0": {"dependencies": {"other_pkg": ">=2.0.0", ...}},
            "1.2.0": {"dependencies": {...}},
            ...
        },
        ...
    }

resolve(requirements, index):
    requirements is a dict of top-level package name -> constraint string
    (e.g. {"app": "^1.0.0"}).

    Returns a dict mapping EVERY package name in the resolved dependency
    closure (top-level requirements plus every transitive dependency) to the
    exact version string chosen for it, such that:
      - each chosen version exists in index[name],
      - each chosen version satisfies every constraint placed on that
        package (the top-level requirement, if any, AND the constraint from
        every package whose chosen version depends on it),
      - among versions that satisfy all of a package's constraints, prefer
        the highest one (by the comparison above) -- but only among
        choices that let the OVERALL resolution succeed. A greedy
        highest-first pick that later turns out to make some other package
        unsatisfiable must be abandoned in favor of a different (lower)
        version for the earlier package: this requires backtracking search,
        not just a single greedy pass.

    Raises ConflictError if there is no combination of versions that
    satisfies every constraint. The error's message must name the package
    that has no viable version and should mention the conflicting
    constraints.

    Raises CycleError if the package-name dependency graph has a cycle --
    i.e. some package A is reachable from itself by following, for every
    package name, the union (over ALL of that package's versions in index)
    of the dependency names it lists. Detect this before/independently of
    version selection and report the cycle in the message (e.g. the names
    involved, such as "a -> b -> a").
"""
from __future__ import annotations


class ResolutionError(Exception):
    pass


class ConflictError(ResolutionError):
    pass


class CycleError(ResolutionError):
    pass


def parse_version(s: str) -> tuple[int, int, int]:
    raise NotImplementedError


def satisfies(version: tuple[int, int, int], constraint: str) -> bool:
    """Return True iff the parsed version satisfies the constraint string."""
    raise NotImplementedError


def resolve(requirements: dict[str, str], index: dict[str, dict[str, dict]]) -> dict[str, str]:
    raise NotImplementedError
