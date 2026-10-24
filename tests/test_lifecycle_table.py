import json
import unittest
from lifecycle_table import ROOT,derive

class LifecycleTable(unittest.TestCase):
    def setUp(self):
        self.data=json.loads((ROOT/'results/durable-state-costs/measurements.json').read_text())
    def test_exact_current_table(self):
        result=derive(self.data)
        self.assertIn('582.5/609.2',result)
        self.assertIn('1213.7/1025.9',result)
        self.assertEqual(len(result.splitlines()),5)
    def test_old_summary_is_not_current(self):
        old=json.loads((ROOT/'results/repair-full-path-summary.json').read_text())
        self.data['groups']=old['groups']
        with self.assertRaises(ValueError):derive(self.data)
    def test_missing_repetition(self):
        self.data['rows'][0]['repeat']=1
        with self.assertRaises(ValueError):derive(self.data)
    def test_timing_tamper(self):
        self.data['groups'][0]['full_lifecycle_median_ms']+=1
        with self.assertRaises(ValueError):derive(self.data)
    def test_omitted_trial(self):
        self.data['rows'].pop()
        with self.assertRaises(ValueError):derive(self.data)

if __name__=='__main__':unittest.main()
