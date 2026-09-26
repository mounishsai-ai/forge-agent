import os
import subprocess
import sys


def main():
    cwd = os.getcwd()

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "test_dependency_resolver.py", "-q"],
        cwd=cwd, capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print("Visible test test_dependency_resolver.py did not pass:")
        print(result.stdout[-2000:])
        print(result.stderr[-2000:])
        sys.exit(1)

    sys.path.insert(0, cwd)
    sys.modules.pop("dependency_resolver", None)
    from dependency_resolver import resolve, parse_version, satisfies, ConflictError, CycleError

    failures = []

    def check(label, cond):
        if not cond:
            failures.append(label)

    def validate_solution(label, requirements, index, result):
        """Generic validator: confirms `result` is an internally-consistent
        solution to (requirements, index), independent of any particular
        search order the implementation used."""
        for name, constraint in requirements.items():
            if name not in result:
                failures.append(f"{label}: missing top-level package {name!r}")
                return
            v = parse_version(result[name])
            if not satisfies(v, constraint):
                failures.append(
                    f"{label}: {name}={result[name]} violates top-level constraint {constraint!r}"
                )
        for name, version in result.items():
            if name not in index or version not in index[name]:
                failures.append(f"{label}: {name}={version} is not a version present in index")
                continue
            deps = index[name][version].get("dependencies", {})
            for dep_name, dep_constraint in deps.items():
                if dep_name not in result:
                    failures.append(f"{label}: {name}@{version} needs {dep_name!r} but it's missing from result")
                    continue
                dv = parse_version(result[dep_name])
                if not satisfies(dv, dep_constraint):
                    failures.append(
                        f"{label}: {dep_name}={result[dep_name]} violates constraint {dep_constraint!r} "
                        f"from {name}@{version}"
                    )

    # ---- A: simple, highest version wins, no dependencies ----
    index_a = {"a": {"1.0.0": {"dependencies": {}}, "1.2.0": {"dependencies": {}}, "2.0.0": {"dependencies": {}}}}
    result_a = resolve({"a": ">=1.0.0"}, index_a)
    check("A: picks highest satisfying version", result_a.get("a") == "2.0.0")

    # ---- B: transitive deps with caret / tilde / exact operators ----
    index_b = {
        "app": {
            "1.4.2": {"dependencies": {"utils": "~2.3.0", "core": "1.0.0"}},
            "2.0.0": {"dependencies": {}},
        },
        "utils": {"2.3.0": {"dependencies": {}}, "2.3.9": {"dependencies": {}}, "2.4.0": {"dependencies": {}}},
        "core": {"1.0.0": {"dependencies": {}}, "1.0.1": {"dependencies": {}}},
    }
    result_b = resolve({"app": "^1.0.0"}, index_b)
    check("B: app pinned below major bump by caret", result_b.get("app") == "1.4.2")
    check("B: utils highest within tilde range", result_b.get("utils") == "2.3.9")
    check("B: core exact pin respected", result_b.get("core") == "1.0.0")
    validate_solution("B", {"app": "^1.0.0"}, index_b, result_b)

    # ---- C: genuine conflict, no valid assignment exists ----
    index_c = {
        "a": {"1.0.0": {"dependencies": {"shared": ">=2.0.0"}}},
        "b": {"1.0.0": {"dependencies": {"shared": "<2.0.0"}}},
        "shared": {"1.5.0": {"dependencies": {}}, "2.0.0": {"dependencies": {}}},
    }
    try:
        resolve({"a": ">=1.0.0", "b": ">=1.0.0"}, index_c)
        failures.append("C: expected ConflictError, resolve() succeeded")
    except ConflictError as e:
        check("C: conflict error mentions 'shared'", "shared" in str(e))
    except Exception as e:
        failures.append(f"C: wrong exception type {e!r}")

    # ---- D: dependency cycle ----
    index_d = {
        "a": {"1.0.0": {"dependencies": {"b": ">=1.0.0"}}},
        "b": {"1.0.0": {"dependencies": {"a": ">=1.0.0"}}},
    }
    try:
        resolve({"a": ">=1.0.0"}, index_d)
        failures.append("D: expected CycleError, resolve() succeeded")
    except CycleError as e:
        msg = str(e)
        check("D: cycle error mentions both package names", "a" in msg and "b" in msg)
    except Exception as e:
        failures.append(f"D: wrong exception type {e!r}")

    # ---- E: requires backtracking (greedy highest-first fails) ----
    # a=2.0.0 needs shared>=2.0.0, which conflicts with b's shared<2.0.0 and
    # shared has no version satisfying both -- the ONLY valid global
    # solution downgrades a to 1.0.0 so shared can be 1.5.0.
    index_e = {
        "a": {
            "2.0.0": {"dependencies": {"shared": ">=2.0.0"}},
            "1.0.0": {"dependencies": {"shared": ">=1.0.0"}},
        },
        "b": {"1.0.0": {"dependencies": {"shared": "<2.0.0"}}},
        "shared": {"2.0.0": {"dependencies": {}}, "1.5.0": {"dependencies": {}}},
    }
    result_e = resolve({"a": ">=1.0.0", "b": ">=1.0.0"}, index_e)
    check(
        "E: backtracked to the only valid global solution",
        result_e.get("a") == "1.0.0" and result_e.get("b") == "1.0.0" and result_e.get("shared") == "1.5.0",
    )
    validate_solution("E", {"a": ">=1.0.0", "b": ">=1.0.0"}, index_e, result_e)

    # ---- F: a second, deeper backtracking case (two levels) ----
    # x picks between 3.0.0 (needs y>=3.0.0) and 2.0.0 (needs y>=2.0.0,<3.0.0).
    # z always needs y<3.0.0. Greedy picks x=3.0.0 -> y forced >=3.0.0 -> conflicts
    # with z's y<3.0.0 and no version of y satisfies both -> must backtrack x
    # down to 2.0.0, which is compatible.
    index_f = {
        "x": {
            "3.0.0": {"dependencies": {"y": ">=3.0.0"}},
            "2.0.0": {"dependencies": {"y": ">=2.0.0"}},
        },
        "z": {"1.0.0": {"dependencies": {"y": "<3.0.0"}}},
        "y": {"3.0.0": {"dependencies": {}}, "2.5.0": {"dependencies": {}}},
    }
    result_f = resolve({"x": ">=1.0.0", "z": ">=1.0.0"}, index_f)
    check(
        "F: backtracked x down to the only compatible version",
        result_f.get("x") == "2.0.0" and result_f.get("y") == "2.5.0",
    )
    validate_solution("F", {"x": ">=1.0.0", "z": ">=1.0.0"}, index_f, result_f)

    if failures:
        print("FAILED checks:")
        for f in failures:
            print(" -", f)
        sys.exit(1)

    print("OK")


if __name__ == "__main__":
    main()
