"""Owned subprocess endpoint for durable-ACK kill/restart checks only."""
import json
import sys
from pathlib import Path
from src.controller import Endpoint, canonical

if __name__ == "__main__":
    endpoint = Endpoint(0, ["a"], Path(sys.argv[1]))
    print(canonical({"status": "ready"}), flush=True)
    for line in sys.stdin:
        print(canonical(endpoint.handle(json.loads(line))), flush=True)
    endpoint.disconnect()
