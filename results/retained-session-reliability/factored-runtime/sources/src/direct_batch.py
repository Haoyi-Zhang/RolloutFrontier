"""Direct exact batch optimization and reusable frontier queries.

Both routes optimize installed changes for a catalog-covered supplied batch.
The direct route branches over the same bounded local guard language as the
frontier producer, with an admissible sum-of-owner upper bound. It never builds
the nondominated frontier. Local-language preparation can be reused by this
route too; repeated-query comparisons must account for that reuse.

Returned guards are independently checked for safety. An exact optimum follows
from completed bounded search, rather than from the safety checker alone.
Equal optima use deterministic first-encounter order; matching the older batch
selector's mass/canonical tie rule is deliberately not an API promise.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import prod
from types import MappingProxyType

from .checker import safe_envelope, frontier_certificate
from .controller import atoms, MAX_CONTRACTS
from .envelope import (MAX_CORNERS, MAX_FRONTIER_STATES, normalize,
    _projected_inputs, _local_guards, _partial_safe, _branch_masks, verify_box)
from .batch import MAX_BATCH_PROPOSALS


@dataclass(frozen=True)
class Choice:
    guard: tuple
    accepted_mask: int
    mass: int


@dataclass(frozen=True, init=False)
class PreparedProblem:
    nodes: tuple
    branches: tuple
    current: tuple
    candidates: tuple
    weights: tuple | None
    relevant: tuple
    profiles: tuple
    local: tuple
    branch_sets: tuple
    term_memberships: object
    term_branch_masks: object

    def __init__(self, *args, **kwargs):
        raise TypeError('use prepare_problem to create a validated problem')


@dataclass(frozen=True, init=False)
class FrontierQueries:
    problem: PreparedProblem
    members: tuple

    def __init__(self, *args, **kwargs):
        raise TypeError('use prepare_frontier to create a checked frontier cache')


def _prepared_handle(kind, *values):
    """Factory-private immutable handles, not an untrusted serialization format.

    Public constructors and dataclasses.replace must not bypass preparation or
    drop checked members while retaining an exact-result promise. These handles
    live in the trusted Python caller; hostile reflection is outside this API.
    """
    fields = tuple(kind.__dataclass_fields__)
    if len(fields) != len(values):
        raise TypeError('internal prepared-handle arity')
    result = object.__new__(kind)
    for name, value in zip(fields, values):
        object.__setattr__(result, name, value)
    return result


class DirectSearchLimit(ValueError):
    def __init__(self, counters):
        super().__init__('direct batch search-state bound')
        self.search = dict(counters)


def prepare_problem(branches, current, candidates, weights=None):
    """Freeze the local language once; reuse is available to direct optimization."""
    branches = normalize(branches)
    nodes, relevant, projected, raw = _projected_inputs(branches, current, candidates)
    if weights is not None and sorted(weights) != nodes:
        raise ValueError('weight placement mismatch')
    seed = {n: [list(projected[n])] for n in nodes}
    if not verify_box(branches, seed)['safe']:
        raise ValueError('current placement is incompatible')
    local, domains = {}, {}
    for n in nodes:
        choices, domains[n] = _local_guards(n, branches, projected[n], raw[n], weights)
        local[n] = tuple(Choice(c['guard'], c['accepted_mask'], c['mass']) for c in choices)
    memberships = {term: frozenset(term) for choices in local.values()
                   for c in choices for term in c.guard}
    branch_sets = tuple(MappingProxyType({n: frozenset(b[n]) for n in nodes}) for b in branches)
    masks = _branch_masks(branch_sets,
        [(n, c.guard) for n in nodes for c in local[n]], memberships)
    return _prepared_handle(PreparedProblem, tuple(nodes),
        tuple(tuple((n, tuple(b[n])) for n in nodes) for b in branches),
        tuple(tuple(atoms(current[n], MAX_CONTRACTS)) for n in nodes),
        tuple(tuple(tuple(atoms(p, MAX_CONTRACTS)) for p in candidates[n]) for n in nodes),
        None if weights is None else tuple(tuple(weights[n]) for n in nodes),
        tuple(frozenset(relevant[n]) for n in nodes),
        tuple(tuple(domains[n]) for n in nodes),
        tuple(local[n] for n in nodes), branch_sets,
        MappingProxyType(memberships), MappingProxyType(masks))


def _batch(problem, proposals):
    if type(problem) is not PreparedProblem:
        raise TypeError('prepared direct-batch problem required')
    if not isinstance(proposals, list) or len(proposals) > MAX_BATCH_PROPOSALS:
        raise ValueError('proposal batch bound')
    node_index = {n: i for i, n in enumerate(problem.nodes)}
    profile_index = [{p: i for i, p in enumerate(domain)} for domain in problem.profiles]
    streams = [[] for _ in problem.nodes]
    for item in proposals:
        if (not isinstance(item, dict) or set(item) != {'node', 'support'}
                or type(item['node']) is not str or item['node'] not in node_index):
            raise ValueError('proposal batch item')
        i = node_index[item['node']]
        support = tuple(atoms(item['support'], MAX_CONTRACTS))
        projection = tuple(a for a in support if a in problem.relevant[i])
        if projection not in profile_index[i]:
            raise ValueError('direct batch requires catalog coverage')
        streams[i].append((support, 1 << profile_index[i][projection]))
    return tuple(tuple(s) for s in streams)


def _local_forecast(current, stream, mask):
    installed = blocked = unchanged = 0
    for support, bit in stream:
        if support == current:
            unchanged += 1
        elif mask & bit:
            current = support
            installed += 1
        else:
            blocked += 1
    return installed, blocked, unchanged, current


def _forecasts(problem, streams):
    return tuple({mask: _local_forecast(problem.current[i], streams[i], mask)
                  for mask in {c.accepted_mask for c in choices}}
                 for i, choices in enumerate(problem.local))


def _external(problem, choices, forecasts, search, mode):
    box = {n: [list(term) for term in choices[i].guard]
           for i, n in enumerate(problem.nodes)}
    branches = [{n: list(term) for n, term in b} for b in problem.branches]
    if not safe_envelope(branches, box):
        raise ValueError('direct batch safety certificate rejected')
    local = [forecasts[i][c.accepted_mask] for i, c in enumerate(choices)]
    forecast = {name: sum(r[k] for r in local)
                for k, name in enumerate(('installed', 'blocked', 'unchanged'))}
    forecast['proposals'] = sum(forecast.values())
    forecast['final'] = {n: list(local[i][3]) for i, n in enumerate(problem.nodes)}
    return {'box': box, 'forecast': forecast, 'exact': True, 'search': dict(search),
            'mode': mode, 'scope': 'covered supplied batch; isolated unchanged guards; sufficient generation headroom',
            'tie_rule': 'deterministic first encountered maximum installation count'}


def choose_direct(problem, proposals, max_states=MAX_FRONTIER_STATES):
    """Maximize the supplied batch directly, without materializing a frontier.

    Each owner contributes an independent subsequence count. Summing the best
    remaining owner's count is an admissible bound even when their guards cannot
    coexist. Unsafe prefixes and excessive corner products are pruned separately.
    The search raises on budget exhaustion and returns no partial optimum.
    """
    if type(max_states) is not int or not 1 <= max_states <= MAX_FRONTIER_STATES:
        raise ValueError('direct batch search-state bound')
    streams = _batch(problem, proposals)
    forecasts = _forecasts(problem, streams)
    local = [tuple(sorted(choices, key=lambda c: (
        -forecasts[i][c.accepted_mask][0], -c.mass, len(c.guard), c.guard)))
        for i, choices in enumerate(problem.local)]
    order = sorted(range(len(problem.nodes)), key=lambda i: (len(local[i]), problem.nodes[i]))
    maximum = [max(forecasts[i][c.accepted_mask][0] for c in local[i]) for i in order]
    remaining = [0] * (len(order) + 1)
    for depth in range(len(order) - 1, -1, -1):
        remaining[depth] = maximum[depth] + remaining[depth + 1]
    counters = dict(states=0, safe_complete=0, bound_pruned=0,
                    unsafe_pruned=0, corner_pruned=0)
    best_score, best = -1, None
    selected = [None] * len(order)

    def visit(depth, assigned, corners, score):
        nonlocal best_score, best
        counters['states'] += 1
        if counters['states'] > max_states:
            raise DirectSearchLimit(counters)
        if score + remaining[depth] <= best_score:
            counters['bound_pruned'] += 1
            return
        if depth == len(order):
            counters['safe_complete'] += 1
            best_score, best = score, tuple(selected)
            return
        i = order[depth]
        for choice in local[i]:
            next_corners = corners * len(choice.guard)
            if next_corners > MAX_CORNERS:
                counters['corner_pruned'] += 1
                continue
            value = forecasts[i][choice.accepted_mask][0]
            if score + value + remaining[depth + 1] <= best_score:
                counters['bound_pruned'] += 1
                continue
            following = assigned + [(problem.nodes[i], choice.guard)]
            if not _partial_safe(problem.branch_sets, following,
                                 problem.term_memberships, problem.term_branch_masks):
                counters['unsafe_pruned'] += 1
                continue
            selected[i] = choice
            visit(depth + 1, following, next_corners, score + value)
            selected[i] = None

    visit(0, [], 1, 0)
    if best is None:
        raise RuntimeError('current-safe seed produced no direct batch product')
    return _external(problem, best, forecasts, counters, 'direct branch-and-bound')


def prepare_frontier(problem, plan):
    """Independently check completeness, then compile for repeated queries.

    The complete checker is run once at preparation, separately from the selected
    guard safety check at each query. The study records this preparation cost.
    """
    if type(problem) is not PreparedProblem or not isinstance(plan, dict):
        raise TypeError('prepared problem and frontier plan required')
    branches = [{n: list(term) for n, term in b} for b in problem.branches]
    current = {n: list(problem.current[i]) for i, n in enumerate(problem.nodes)}
    candidates = {n: [list(p) for p in problem.candidates[i]] for i, n in enumerate(problem.nodes)}
    weights = None if problem.weights is None else {
        n: list(problem.weights[i]) for i, n in enumerate(problem.nodes)}
    if not frontier_certificate(branches, current, candidates, plan, weights):
        raise ValueError('cached frontier completeness certificate rejected')
    members = plan.get('frontier')
    if not isinstance(members, list) or not members:
        raise ValueError('frontier members required')
    lookups = [{c.guard: c for c in choices} for choices in problem.local]
    compiled = []
    for member in members:
        box = member['box']
        if sorted(box) != list(problem.nodes):
            raise ValueError('frontier placement mismatch')
        row = tuple(lookups[i][tuple(tuple(term) for term in box[n])]
                    for i, n in enumerate(problem.nodes))
        if prod(len(c.guard) for c in row) > MAX_CORNERS:
            raise ValueError('frontier corner bound')
        branches = [{n: list(term) for n, term in b} for b in problem.branches]
        if not safe_envelope(branches, box):
            raise ValueError('frontier member safety rejected')
        compiled.append(row)
    return _prepared_handle(FrontierQueries, problem, tuple(compiled))


def choose_frontier(problem, compiled, proposals):
    """Score cached frontier members using the same local subsequence statistic."""
    streams = _batch(problem, proposals)
    if (type(compiled) is not FrontierQueries or compiled.problem is not problem
            or not compiled.members):
        raise ValueError('compiled frontier required')
    members = compiled.members
    forecasts = tuple({mask: _local_forecast(problem.current[i], streams[i], mask)
                       for mask in {row[i].accepted_mask for row in members}}
                      for i in range(len(problem.nodes)))
    best = max(members, key=lambda row: sum(forecasts[i][c.accepted_mask][0]
                                           for i, c in enumerate(row)))
    return _external(problem, best, forecasts,
        {'scored_frontier_members': len(members)}, 'cached complete frontier')
