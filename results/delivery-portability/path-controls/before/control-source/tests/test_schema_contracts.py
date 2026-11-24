"""Live library checks of migration boundaries, independent of the planner."""
import unittest
from google.protobuf import json_format
from src.schema_contracts import decode_wire, encode_wire, payloads, actual_probes

class SchemaContracts(unittest.TestCase):
    def test_alias_removal_rejects_old_name(self):
        old = encode_wire('enum-alias', 0, payloads('enum-alias', 0)[0])
        for rank in (0,1,2): self.assertEqual(decode_wire('enum-alias',rank,old)['status'],1)
        with self.assertRaises(json_format.ParseError): decode_wire('enum-alias',3,old)

    def test_key_bridge_accepts_both_emitted_names(self):
        for producer in (0,2):
            record=payloads('field-key',producer)[2]
            wire=encode_wire('field-key',producer,record)
            for consumer in (1,2):self.assertEqual(decode_wire('field-key',consumer,wire),record)
        with self.assertRaises(json_format.ParseError):decode_wire('field-key',0,wire)

    def test_unknown_field_is_not_silently_dropped(self):
        record=payloads('field-addition',2)[0];wire=encode_wire('field-addition',2,record)
        with self.assertRaises(json_format.ParseError):decode_wire('field-addition',0,wire)
        self.assertEqual(decode_wire('field-addition',1,wire),record)

    def test_narrow_writer_contract_remains_until_activation(self):
        record={'key':'wide','value':1<<40}
        with self.assertRaises(ValueError):encode_wire('integer-widening',1,record)
        wire=encode_wire('integer-widening',2,record)
        with self.assertRaises(json_format.ParseError):decode_wire('integer-widening',0,wire)
        self.assertEqual(decode_wire('integer-widening',1,wire),record)

    def test_int64_boundaries_round_trip_exactly(self):
        for value in (-(1<<63),(1<<63)-1):
            record={'key':'整数','value':value}
            self.assertEqual(decode_wire('integer-widening',2,encode_wire('integer-widening',2,record)),record)

    def test_common_narrow_domain_handles_number_and_string_wires(self):
        for producer in (0,1):
            for record in payloads('integer-widening',producer):
                self.assertEqual(decode_wire('integer-widening',0,encode_wire('integer-widening',producer,record)),record)

    def test_invalid_producer_record_rejected(self):
        for value in (True,1.5,1<<63,-(1<<63)-1):
            with self.assertRaises(ValueError):encode_wire('integer-widening',2,{'key':'bad','value':value})

    def test_every_retained_success_preserves_exact_record(self):
        for family in actual_probes():
            inputs={row['id']:row['input'] for row in family['wires']}
            for row in family['parses']:
                if row['accepted']:self.assertEqual(row['output'],inputs[row['wire_id']])

if __name__=='__main__':unittest.main()
