"""
Side-by-side comparison of LLMs for query expansion.
For each test query, runs the same retrieval with each model's expansion
and shows the top-1 of each. Helps eyeball which LLM gives better expansions.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from retrieve import Retriever, expand_label, fmt_hit, TESTS

MODELS = [
    ("Qwen2.5-7B",   "qwen2.5:7b-instruct-q4_K_M"),
    ("Mistral-7B",   "mistral:7b-instruct-v0.3-q4_K_M"),
]


def main() -> None:
    r = Retriever()
    print(f"Index: {len(r.meta)} entries — comparing {len(MODELS)} LLMs\n")

    for label, dom in TESTS:
        print(f"\n{'='*90}")
        print(f"  '{label}'    [domain={dom or 'ALL'}]")
        print(f"{'='*90}")

        # Baseline
        baseline = r.search(label, domain=dom, top_k=1)[0]
        print(f"\n  [SANS LLM]                                {fmt_hit(baseline)}")

        # Each LLM
        for name, model in MODELS:
            try:
                expanded = expand_label(label, model=model)
            except Exception as e:
                print(f"\n  [{name}] ERROR: {e}")
                continue
            hits = r.search(expanded, domain=dom, top_k=1)
            top = hits[0] if hits else None
            print(f"\n  [{name}] expansion:")
            print(f"    → {expanded[:120]}{'...' if len(expanded) > 120 else ''}")
            if top:
                print(f"    → {fmt_hit(top)}")


if __name__ == "__main__":
    main()
