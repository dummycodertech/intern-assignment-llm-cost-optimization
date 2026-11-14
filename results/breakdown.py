# >>> Per-call points breakdown. Run from a repo root: python results/breakdown.py q1 T-1001 T-1002
import sys
sys.path.insert(0, ".")
which, ids = sys.argv[1], sys.argv[2:]
if which == "q1":
    from question1.agent import SupportCopilot as Agent
else:
    from question2.agent import SupportPipeline as Agent
grand = 0
for tid in ids:
    a = Agent()
    r = a.handle_ticket(tid)
    print(f"{tid}  action={r.action}  kb_article={r.kb_article}")
    for c in a.session.calls:
        print(f"   {c.label:10} input={c.input_tokens:>6}  output={c.output_tokens:>5}  cached={c.cached_prefix_tokens:>4}  points={c.points():>6}")
    print(f"   TOTAL points={a.session.total_points()}")
    grand += a.session.total_points()
print(f"SUM over {len(ids)} ticket(s): {grand}")

