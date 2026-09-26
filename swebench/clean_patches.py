"""Strip mode-only file sections ("old mode 100644 / new mode 100755" with no content change)
from a predictions.jsonl, writing a cleaned copy.

Why: in the first main run, patch extraction staged files without core.fileMode=false, so a
blanket permission flip inside some containers put every file of the repo into the patch.
The agent's real code changes are untouched by this script; only sections that change
nothing but the file mode are dropped. Fixed at the source in run_forge.py afterwards.

    python swebench/clean_patches.py IN_predictions.jsonl OUT_predictions.jsonl
"""
import json
import re
import sys


def clean(patch: str) -> str:
    sections = re.split(r"(?m)^(?=diff --git )", patch)
    kept = []
    for s in sections:
        if not s.startswith("diff --git "):
            kept.append(s)
            continue
        body = [l for l in s.splitlines()[1:] if l.strip()]
        mode_only = body and all(l.startswith(("old mode ", "new mode ")) for l in body)
        if not mode_only:
            # also drop the mode lines inside a real content change, so modes stay as in the repo
            s = "\n".join(l for l in s.split("\n") if not l.startswith(("old mode ", "new mode ")))
            kept.append(s)
    return "".join(kept)


def main(src: str, dst: str) -> None:
    changed = 0
    with open(src, encoding="utf-8") as f, open(dst, "w", encoding="utf-8") as out:
        for line in f:
            p = json.loads(line)
            new = clean(p["model_patch"])
            if new != p["model_patch"]:
                changed += 1
                p["model_patch"] = new
            out.write(json.dumps(p) + "\n")
    print(f"cleaned {changed} patches -> {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
