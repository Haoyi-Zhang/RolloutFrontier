"""Actual protobuf descriptor, emitter, and strict-parser measurements.

The finite channel catalog is shared by all event-chain contexts. Parser rows
are measured once for each concrete directed channel/field set and each
emitted/prepared subset; no global chain context repeats serialization. Every
nonempty emitted field has an application value and every parser preparation
adds an actual field descriptor. This is an executable controlled field-
addition construction, not a deployment-frequency study.
"""
from __future__ import annotations

import argparse
from functools import lru_cache
from itertools import combinations
import json
from pathlib import Path

from google.protobuf import descriptor_pb2, descriptor_pool, json_format, message_factory

def require(condition, message):
    if not condition:
        raise ValueError(message)


CONFIGS = {
    "two_owner": [("ab0", 0, 1), ("ab1", 0, 1),
                  ("ba0", 1, 0), ("ba1", 1, 0)],
    "three_owner": [("ab0", 0, 1), ("ab1", 0, 1),
                    ("ba0", 1, 0), ("ba1", 1, 0),
                    ("bc0", 1, 2), ("cb0", 2, 1)],
    "three_owner_complete": [("ab0", 0, 1), ("ba0", 1, 0),
                             ("bc0", 1, 2), ("cb0", 2, 1),
                             ("ca0", 2, 0), ("ac0", 0, 2)],
    "three_owner_complete_extra": [("ab0", 0, 1), ("ba0", 1, 0),
                                   ("bc0", 1, 2), ("cb0", 2, 1),
                                   ("ca0", 2, 0), ("ac0", 0, 2),
                                   ("ab1", 0, 1)],
}


SAMPLES = (
    ("alpha", "present"),
    ("κλειδί", "migrated-δ"),
    ("中文", "扩展字段"),
    ("quoted\"key", "line\nbreak\\path"),
    ("emoji-λ", "field-🙂"),
)


def subsets(fields):
    return [tuple(p) for size in range(len(fields) + 1) for p in combinations(fields, size)]


def field_name(feature):
    return "tag_" + feature


def descriptor(fields, accepted):
    file = descriptor_pb2.FileDescriptorProto(name="event_channel.proto", package="events", syntax="proto3")
    message = file.message_type.add(name="Record")
    message.field.add(name="key", number=1, label=1, type=9)
    for index, feature in enumerate(fields):
        if feature in accepted:
            message.field.add(name=field_name(feature), number=index + 2, label=1, type=9)
    return file


@lru_cache(maxsize=None)
def message_class(fields, accepted):
    pool = descriptor_pool.DescriptorPool()
    pool.Add(descriptor(fields, accepted))
    return message_factory.GetMessageClass(pool.FindMessageTypeByName("events.Record"))


def emit(fields, active, sample):
    key, value = SAMPLES[sample]
    values = {"key": key}
    for feature in active:
        values[field_name(feature)] = feature + ":" + value
    message = message_class(fields, fields)(**values)
    wire_dict = json_format.MessageToDict(message)
    wire = json.dumps(wire_dict, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    semantic = {"key": key, **{feature: feature + ":" + value if feature in active else ""
                               for feature in fields}}
    return wire, semantic


def parse(fields, prepared, wire):
    message = message_class(fields, prepared)()
    json_format.Parse(wire, message)
    return {"key": message.key, **{feature: getattr(message, field_name(feature))
                                    if feature in prepared else "" for feature in fields}}


def measure_channel(sender, receiver, fields):
    choices = subsets(fields)
    wires, parses, acceptance = [], [], []
    for emitted in choices:
        for sample in range(len(SAMPLES)):
            wire, semantic = emit(fields, emitted, sample)
            wires.append({"id": str(len(wires)), "emitted_fields": list(emitted), "sample": sample,
                          "wire": wire, "semantic": semantic})
    for prepared in choices:
        row = []
        for emitted in choices:
            results = []
            for wire in [w for w in wires if w["emitted_fields"] == list(emitted)]:
                observation = {"prepared_fields": list(prepared), "wire_id": wire["id"]}
                try:
                    decoded = parse(fields, prepared, wire["wire"])
                    observation.update(accepted=True, decoded=decoded,
                                       semantic_equal=decoded == wire["semantic"])
                    results.append(decoded == wire["semantic"])
                except (ValueError, json_format.ParseError) as error:
                    observation.update(accepted=False, error_type=type(error).__name__, error=str(error))
                    results.append(False)
                parses.append(observation)
            observed = all(results)
            require(observed == (set(emitted) <= set(prepared)), "ProtoJSON subset contract differs")
            row.append(int(observed))
        acceptance.append(row)
    witnesses = []
    for feature in fields:
        for before in choices:
            if feature in before:
                continue
            after = tuple(f for f in fields if f in before or f == feature)
            before_wire, _ = emit(fields, before, 0)
            after_wire, _ = emit(fields, after, 0)
            require(before_wire != after_wire, "emitter activation has no wire effect")
            singleton_wire, singleton_semantic = emit(fields, (feature,), 0)
            rejected = False
            try:
                parse(fields, before, singleton_wire)
            except (ValueError, json_format.ParseError):
                rejected = True
            require(rejected, "parser preparation does not reject its previous witness")
            require(parse(fields, after, singleton_wire) == singleton_semantic,
                    "parser preparation does not accept its new witness")
            witnesses.append({"feature": feature, "before_subset": list(before), "after_subset": list(after),
                              "before_emit_wire": before_wire, "after_emit_wire": after_wire,
                              "prepare_witness_wire": singleton_wire,
                              "reader_before_rejects": True, "reader_after_preserves_semantics": True})
    return {"sender": sender, "receiver": receiver, "fields": list(fields),
            "subsets": [list(s) for s in choices],
            "matrix_axes": ["prepared_subset", "emitted_subset"], "matrix": acceptance,
            "descriptors": [{"prepared_fields": list(s),
                             "serialized_hex": descriptor(fields, s).SerializeToString().hex()}
                            for s in choices],
            "wires": wires, "parses": parses, "event_effect_witnesses": witnesses}


def channel_specs(config):
    grouped = {}
    for feature, sender, receiver in CONFIGS[config]:
        grouped.setdefault((sender, receiver), []).append(feature)
    return [(sender, receiver, tuple(sorted(fields)))
            for (sender, receiver), fields in sorted(grouped.items())]


def actual_probes():
    specs = sorted({spec for config in CONFIGS for spec in channel_specs(config)})
    return [measure_channel(*spec) for spec in specs]


def context_model(config, orders, channels):
    """Positive local factors compiled from measured channel matrices."""
    lookup = {(row['sender'], row['receiver'], tuple(row['fields'])): row for row in channels}
    specifications = channel_specs(config)
    candidates = {str(owner): [] for owner in range(len(orders))}
    for owner, order in enumerate(orders):
        for rank in range(len(order) + 1):
            completed = set(order[:rank])
            atoms = []
            for sender, receiver, fields in specifications:
                channel = lookup[sender, receiver, fields]
                name = str(sender) + '-' + str(receiver)
                if owner == sender:
                    emitted = [feature for feature in fields if 'e_' + feature in completed]
                    index = channel['subsets'].index(emitted)
                    atoms.append('emit:' + name + ':' + str(index))
                if owner == receiver:
                    prepared = [feature for feature in fields if 'p_' + feature in completed]
                    index = channel['subsets'].index(prepared)
                    atoms.extend('accept:' + name + ':' + str(emitted)
                                 for emitted, accepted in enumerate(channel['matrix'][index]) if accepted)
            candidates[str(owner)].append(sorted(atoms))
        require(len({tuple(p) for p in candidates[str(owner)]}) == len(order) + 1,
                'an event produced an identical complete physical support')
    transitions = {owner: [{'source': a, 'target': b} for a, b in zip(profiles, profiles[1:])]
                   for owner, profiles in candidates.items()}
    factors = []
    for sender, receiver, fields in specifications:
        channel = lookup[sender, receiver, fields]
        name = str(sender) + '-' + str(receiver)
        factors.append({'id': 'channel-' + name,
                        'branches': [{str(sender): ['emit:' + name + ':' + str(index)],
                                      str(receiver): ['accept:' + name + ':' + str(index)]}
                                     for index in range(len(channel['subsets']))]})
    return {'factors': factors, 'catalog': candidates, 'transitions': transitions,
            'initial': {owner: profiles[0] for owner, profiles in candidates.items()},
            'target': {owner: profiles[-1] for owner, profiles in candidates.items()}}


def produce(output):
    channels = actual_probes()
    output.mkdir(parents=True, exist_ok=True)
    (output / "channel-observations.json").write_text(json.dumps(channels, ensure_ascii=False, indent=2) + "\n")
    summary = {"status": "PASS", "configurations": {name: channel_specs(name) for name in CONFIGS},
               "channel_catalogs": len(channels), "descriptors": sum(len(c["descriptors"]) for c in channels),
               "wires": sum(len(c["wires"]) for c in channels),
               "parser_invocations": sum(len(c["parses"]) for c in channels),
               "accepted": sum(p["accepted"] for c in channels for p in c["parses"]),
               "rejected": sum(not p["accepted"] for c in channels for p in c["parses"]),
               "event_effect_witnesses": sum(len(c["event_effect_witnesses"]) for c in channels),
               "all_matrices_match_subset_contract": True,
               "every_prepare_and_emit_event_has_observable_effect": True}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    produce(arguments.output)
