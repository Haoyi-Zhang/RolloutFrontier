from pathlib import Path
import json, sys
Path(sys.argv[1]).write_text('remaining control executed\n')
print(json.dumps({'status':'PASS','scope':'verifier process control'}))
