"""Aggregate independent saved-input checks across both execution modes."""
import argparse
import json
from pathlib import Path

from tests.check_utf8_inputs import check, altered_evidence_controls, require
from tests.check_input_counterexamples import verify as verify_counterexamples


def verify(directory, controls=False):
    cases = {}
    negative = {}
    for mode, flag in (('normal', 0), ('optimized', 1)):
        path = directory / mode
        metadata = json.loads((path / 'summary.json').read_text())
        require(metadata['optimization'] == flag, 'Saved interpreter mode differs: ' + mode)
        cases[mode] = check(path)
        if controls:
            negative[mode] = altered_evidence_controls(path)
    require(cases['normal'] == cases['optimized'], 'Normal and optimized input observations differ')
    counterexamples = verify_counterexamples(directory / 'counterexamples', controls=controls)
    return {'status': 'PASS', 'modes': 2, 'per_mode': cases['normal'],
            'totals': {name: 2 * value for name, value in cases['normal'].items()},
            'normal_and_optimized_agree': True, 'corruption_controls': negative,
            'historical_counterexamples': counterexamples,
            'scope': 'Saved TCP owner histories, rejected-input checkpoints, request bindings, '
                     'effects and retirement reconstruction; recorded call-site rejection outcomes.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--corruption-controls', action='store_true')
    args = parser.parse_args()
    print(json.dumps(verify(args.results.resolve(), args.corruption_controls), indent=2, sort_keys=True))
