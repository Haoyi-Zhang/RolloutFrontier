from pathlib import Path
import json, os, subprocess, sys, time
root = Path(sys.argv[1])
descendant = subprocess.Popen([sys.executable, '-B', '-u', '-c',
    "from pathlib import Path; import json,os,sys,time; "
    "Path(sys.argv[1]).write_text(json.dumps({'pid':os.getpid(),'group':os.getpgrp()})); "
    "print('control-descendant-ready',flush=True); time.sleep(60)",
    str(root / 'descendant.json')])
print('control-worker-ready', flush=True)
print('control-diagnostic', file=sys.stderr, flush=True)
(root / 'worker.json').write_text(json.dumps(
    {'pid':os.getpid(), 'group':os.getpgrp(), 'descendant':descendant.pid}))
time.sleep(60)
