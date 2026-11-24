"""Executable ProtoJSON contract families for rolling schema changes.

Each program uses its own actual protobuf descriptor pool. Program ranks are
permitted installation order, not a claim about deployed software populations.
The emitted wire classes are explicit application contracts. In particular the
middle integer program uses int64 parsing while its producer is restricted to
int32 values until peers are ready for the widened input domain.
"""
from __future__ import annotations

import json
from functools import lru_cache
from google.protobuf import descriptor_pb2, descriptor_pool, json_format, message_factory

FAMILIES = {
    'enum-alias': {'programs': ('legacy', 'accepting', 'emitting', 'current'),
                   'classes': ('old-name', 'new-name'), 'emits': (0, 0, 1, 1)},
    'field-key': {'programs': ('legacy', 'accepting', 'emitting', 'current'),
                  'classes': ('old-key', 'new-key'), 'emits': (0, 0, 1, 1)},
    'field-addition': {'programs': ('legacy', 'accepting', 'emitting'),
                       'classes': ('base', 'extended'), 'emits': (0, 0, 1)},
    'integer-widening': {'programs': ('legacy', 'accepting', 'emitting'),
                         'classes': ('narrow', 'wide'), 'emits': (0, 0, 1)},
}
NARROW = (-(1 << 31), -1, 0, 1, (1 << 31) - 1)
WIDE = (-(1 << 63), -(1 << 40), *NARROW, 1 << 40, (1 << 63) - 1)
KEYS = ('alpha', 'κλειδί', '中文', 'emoji-λ', 'boundary')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def specification(family, rank):
    if family not in FAMILIES or type(rank) is not int or not 0 <= rank < len(FAMILIES[family]['programs']):
        raise ValueError('unknown schema program')
    return FAMILIES[family]


def descriptor(family, rank):
    specification(family, rank)
    file = descriptor_pb2.FileDescriptorProto(name='contract.proto', package='schema', syntax='proto3')
    message = file.message_type.add(name='Record')
    message.field.add(name='key', number=1, label=1, type=9)
    if family == 'field-key':
        name = 'quantity' if rank == 3 else 'count'
        json_name = 'count' if rank == 0 else 'quantity'
        message.field.add(name=name, json_name=json_name, number=2, label=1, type=3)
    else:
        dtype = 5 if family == 'integer-widening' and rank == 0 else 3
        message.field.add(name='value', number=2, label=1, type=dtype)
    if family == 'enum-alias':
        enum = file.enum_type.add(name='Status')
        enum.value.add(name='UNSPECIFIED', number=0)
        names = (('ACTIVE',), ('ACTIVE', 'ENABLED'), ('ENABLED', 'ACTIVE'), ('ENABLED',))[rank]
        enum.options.allow_alias = len(names) > 1
        for name in names:
            enum.value.add(name=name, number=1)
        message.field.add(name='status', number=3, label=1, type=14, type_name='.schema.Status')
    if family == 'field-addition' and rank >= 1:
        message.field.add(name='tag', number=3, label=1, type=9)
    return file


@lru_cache(maxsize=None)
def message_class(family, rank):
    file = descriptor(family, rank)
    pool = descriptor_pool.DescriptorPool()
    pool.Add(file)
    return message_factory.GetMessageClass(pool.FindMessageTypeByName('schema.Record'))


def payloads(family, rank):
    specification(family, rank)
    values = WIDE if family == 'integer-widening' and rank == 2 else NARROW
    result = []
    for index, value in enumerate(values):
        payload = {'key': KEYS[index % len(KEYS)], 'value': value}
        if family == 'enum-alias':
            payload['status'] = 1
        if family == 'field-addition':
            payload['tag'] = 'migrated-δ' if rank == 2 else ''
        result.append(payload)
    return result


def validate_payload(family, rank, payload):
    specification(family, rank)
    expected = {'key', 'value'}
    if family == 'enum-alias': expected.add('status')
    if family == 'field-addition': expected.add('tag')
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ValueError('semantic record fields')
    if not isinstance(payload['key'], str) or not payload['key'] or len(payload['key']) > 128:
        raise ValueError('semantic key')
    try:
        payload['key'].encode('utf-8')
    except UnicodeEncodeError as error:
        raise ValueError('semantic key must be valid UTF-8') from error
    value = payload['value']
    if type(value) is not int or not -(1 << 63) <= value < (1 << 63):
        raise ValueError('semantic integer')
    if family == 'integer-widening' and rank < 2 and not -(1 << 31) <= value < (1 << 31):
        raise ValueError('producer remains in int32 contract')
    if family == 'enum-alias' and payload['status'] != 1:
        raise ValueError('active enum value')
    if family == 'field-addition' and payload['tag'] != ('migrated-δ' if rank == 2 else ''):
        raise ValueError('producer field contract')


def encode_wire(family, rank, payload):
    validate_payload(family, rank, payload)
    values = {'key': payload['key']}
    if family == 'field-key': values['quantity' if rank == 3 else 'count'] = payload['value']
    else: values['value'] = payload['value']
    if family == 'enum-alias': values['status'] = 1
    if family == 'field-addition' and rank == 2: values['tag'] = payload['tag']
    message = message_class(family, rank)(**values)
    # Rank one keeps the old proto field spelling while its descriptor also
    # accepts the new json_name. Rank two changes the emitted spelling.
    options = {'preserving_proto_field_name': family == 'field-key' and rank == 1}
    # Default zero values must appear in the numeric contract probes. The
    # optional tag is deliberately omitted by rank one until writer activation.
    data = json_format.MessageToDict(message, always_print_fields_with_no_presence=True, **options)
    if family == 'field-addition' and rank == 1: data.pop('tag', None)
    return canonical(data)


def decode_wire(family, rank, wire):
    specification(family, rank)
    if not isinstance(wire, str) or len(wire) > 16384:
        raise ValueError('wire frame')
    message = message_class(family, rank)()
    json_format.Parse(wire, message)
    result = {'key': message.key,
              'value': getattr(message, 'quantity' if family == 'field-key' and rank == 3 else
                               'count' if family == 'field-key' else 'value')}
    if family == 'enum-alias': result['status'] = message.status
    if family == 'field-addition': result['tag'] = message.tag if rank >= 1 else ''
    return result


def actual_probes():
    """Execute every registered producer and parser pair on the fixed corpus."""
    result = []
    for family, spec in FAMILIES.items():
        wires, parses = [], []
        for rank, program in enumerate(spec['programs']):
            for sample, payload in enumerate(payloads(family, rank)):
                wires.append({'id': f'{rank}:{sample}', 'rank': rank, 'program': program,
                              'class': spec['classes'][spec['emits'][rank]],
                              'input': payload, 'wire': encode_wire(family, rank, payload)})
        for rank, program in enumerate(spec['programs']):
            for row in wires:
                item = {'consumer_rank': rank, 'consumer_program': program, 'wire_id': row['id']}
                try:
                    item.update(accepted=True, output=decode_wire(family, rank, row['wire']))
                except (ValueError, json_format.ParseError) as error:
                    item.update(accepted=False, error_type=type(error).__name__, error=str(error))
                parses.append(item)
        table = {(p['consumer_rank'], p['wire_id']): p for p in parses}
        profiles, accepts = [], []
        for rank, program in enumerate(spec['programs']):
            accepted_classes = []
            for cls in spec['classes']:
                examples = [w for w in wires if w['class'] == cls]
                if all(table[rank, w['id']]['accepted'] and table[rank, w['id']]['output'] == w['input']
                       for w in examples):
                    accepted_classes.append(cls)
            accepts.append(accepted_classes)
            profiles.append(sorted(['program:' + family + ':' + program,
                                     'emit:' + spec['classes'][spec['emits'][rank]],
                                     *('accept:' + cls for cls in accepted_classes)]))
        relation = [[int(spec['classes'][spec['emits'][sender]] in accepts[receiver])
                     for receiver in range(len(profiles))] for sender in range(len(profiles))]
        result.append({'family': family, 'programs': list(spec['programs']), 'classes': list(spec['classes']),
                       'emitted_classes': [spec['classes'][i] for i in spec['emits']],
                       'accepted_classes': accepts, 'profiles': profiles, 'relation': relation,
                       'descriptors': [{'rank': rank, 'serialized_hex': descriptor(family, rank).SerializeToString().hex()}
                                       for rank in range(len(profiles))], 'wires': wires, 'parses': parses})
    return result
