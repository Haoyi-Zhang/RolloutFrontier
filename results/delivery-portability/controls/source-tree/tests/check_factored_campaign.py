"""Aggregate the independent physical replays in the publication record format."""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    record = verify.factored_execution()
    result = {
        'status': 'checked', 'checked': record['status'] == 'PASS',
        'completion_bound_to_final_owners': True,
        'source_files_equal': record['source_files'],
        'cohorts': len(record['cases']),
        'totals': {
            'requests': record['total_requests'],
            'effects': record['total_effects'],
            'installations': record['total_conditional_installations'],
        },
        'cases': [{'directory': row['directory'], **row['verification']} for row in record['cases']],
        'scope': record['scope'],
    }
    encoded = json.dumps(result, indent=2, sort_keys=True) + '\n'
    if args.output:
        if args.output.exists():
            raise ValueError('Use a new output file; retained check records are not overwritten.')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
    print(encoded, end='')


if __name__ == '__main__':
    main()
