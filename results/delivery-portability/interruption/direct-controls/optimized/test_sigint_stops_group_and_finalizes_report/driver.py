from pathlib import Path
import sys
import verify
root, mode, limit = Path(sys.argv[1]), sys.argv[2], float(sys.argv[3])
verify.tasks = lambda: [
    {'name':'blocking-control', 'arguments':[str(root/'worker.py'),str(root)],
     'anchors':[], 'assurance':'bounded verifier process control', 'timeout_seconds':limit},
    {'name':'remaining-control', 'arguments':[str(root/'remaining.py'),str(root/'remaining.txt')],
     'anchors':[], 'assurance':'bounded verifier process control', 'timeout_seconds':5},
]
sys.argv = [str(verify.__file__), '--out', str(root/'report'), '--mode', mode]
raise SystemExit(verify.main())
