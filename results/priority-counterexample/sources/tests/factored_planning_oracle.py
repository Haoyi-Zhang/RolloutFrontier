"""Standard-library oracle for factored-chain observations; no planner imports."""
from collections import deque
from itertools import combinations_with_replacement, product
from math import prod


def require(value, reason):
    if not value:
        raise ValueError(reason)


def canonical_terms(terms):
    values = sorted({tuple(sorted(set(t))) for t in terms})
    return [list(t) for t in values if not any(set(u) < set(t) for u in values)]


class Oracle:
    def __init__(self, factors, catalog, transitions):
        self.factors = factors
        self.nodes = sorted(catalog)
        require(set(transitions) == set(self.nodes), "oracle transition placement")
        self.profiles, self.rank = {}, {}
        for n in self.nodes:
            available = {tuple(sorted(p)) for p in catalog[n]}
            edges = {(tuple(sorted(e['source'])), tuple(sorted(e['target'])))
                     for e in transitions[n] if e['source'] != e['target']}
            require(all(a in available and b in available for a, b in edges), "oracle outside edge")
            roots = available - {b for _, b in edges}
            require(len(roots) == 1, "oracle needs one chain root")
            order = [next(iter(roots))]
            while True:
                following = [b for a, b in edges if a == order[-1]]
                if not following:
                    break
                require(len(following) == 1 and following[0] not in order, "oracle needs an acyclic chain")
                order.append(following[0])
            require(set(order) == available and len(edges) == len(available) - 1,
                    "oracle chain does not cover catalog")
            self.profiles[n] = order
            self.rank[n] = {p: r for r, p in enumerate(order)}
        self.positions = {n: i for i, n in enumerate(self.nodes)}
        self.shapes, self.local_relations = {}, {}
        for factor in factors:
            identity, scope = factor['id'], sorted(factor['branches'][0])
            shape = [len(self.profiles[n]) for n in scope]
            self.shapes[identity] = (scope, shape)
            self.local_relations[identity] = {
                s for s in product(*(range(q) for q in shape))
                if self.factor_truth(factor, s)}
        require(set(n for f in factors for n in f['branches'][0]) == set(self.nodes),
                "oracle factor coverage")
        self._graph, self._costs = None, {}

    def factor_truth(self, factor, ranks):
        scope = sorted(factor['branches'][0])
        supports = {n: set(self.profiles[n][r]) for n, r in zip(scope, ranks)}
        return any(all(set(required) <= supports[n] for n, required in branch.items())
                   for branch in factor['branches'])

    def state(self, raw):
        require(set(raw) == set(self.nodes), "oracle state placement")
        return tuple(self.rank[n][tuple(sorted(raw[n]))] for n in self.nodes)

    def external(self, state):
        return {n: list(self.profiles[n][r]) for n, r in zip(self.nodes, state)}

    def safe(self, state):
        return all(tuple(state[self.positions[n]] for n in self.shapes[f['id']][0])
                   in self.local_relations[f['id']] for f in self.factors)

    def closed(self):
        for factor in self.factors:
            relation = self.local_relations[factor['id']]
            for a, b in combinations_with_replacement(relation, 2):
                if tuple(map(max, a, b)) not in relation:
                    return False
        return True

    def check_refusal(self, result):
        require(result['reason'] == 'factor is not closed under componentwise maximum',
                "unexpected finite-relation refusal")
        witness = result['witness']
        relation = self.local_relations[witness['factor']]
        a, b, join = map(tuple, (witness['first'], witness['second'], witness['maximum']))
        require(a in relation and b in relation and join == tuple(map(max, a, b))
                and join not in relation, "false max-closure counterexample")
        require(not self.closed(), "refused a locally max-closed relation")

    def check_recognition(self, certificate):
        require(certificate['recognized'] is True and self.closed(), "false recognition")
        require(certificate['global_catalog_enumerated'] is False,
                "unexpected recognition assurance")
        require(certificate['criterion'] == 'factorwise componentwise-maximum closure',
                "unknown recognition criterion")
        require(certificate['owners'] == len(self.nodes), "recognition owner count")
        rows = certificate['factors']
        require([r['id'] for r in rows] == sorted(f['id'] for f in self.factors),
                "recognition factor inventory")
        placements, pairs = 0, 0
        for row in rows:
            scope, shape = self.shapes[row['id']]
            relation = self.local_relations[row['id']]
            require(row['owners'] == scope and row['shape'] == shape, "recognition factor shape")
            require(row['relation'] == [list(s) for s in sorted(relation)], "recognition relation changed")
            require(row['catalog_placements'] == prod(shape) and
                    row['compatible_placements'] == len(relation), "recognition denominator")
            count = len(relation) * (len(relation) + 1) // 2
            require(row['checked_join_pairs'] == count, "recognition join count")
            expected = []
            for s in sorted(relation):
                upper = []
                for i, q in enumerate(shape):
                    # Independent all-prefix definition, rather than the
                    # producer's incremental first-failure scan.
                    upper.append(max(t for t in range(s[i], q)
                        if all(s[:i] + (r,) + s[i + 1:] in relation for r in range(s[i], t + 1))))
                expected.append({'source': list(s), 'upper': upper})
            require(row['axis_limits'] == expected, "recognition axis table changed")
            placements += prod(shape)
            pairs += count
        require(certificate['checked_factor_placements'] == placements and
                certificate['checked_join_pairs'] == pairs, "recognition total count")

    def graph(self):
        if self._graph is not None:
            return self._graph
        shape = [len(self.profiles[n]) for n in self.nodes]
        require(prod(shape) <= 4096, "finite oracle global placement limit")
        relation = {s for s in product(*(range(q) for q in shape)) if self.safe(s)}
        self._graph = {}
        for source in sorted(relation):
            neighbors = []
            for target in sorted(relation):
                if source == target or any(a > b for a, b in zip(source, target)):
                    continue
                if all(s in relation for s in product(*(range(a, b + 1)
                                                        for a, b in zip(source, target)))):
                    neighbors.append(target)
            self._graph[source] = neighbors
        return self._graph

    def cost(self, source, target):
        graph = self.graph()
        require(source in graph, "oracle invalid initial state")
        if source not in self._costs:
            distances, queue = {source: 0}, deque([source])
            while queue:
                s = queue.popleft()
                for t in graph[s]:
                    if t not in distances:
                        distances[t] = distances[s] + 1
                        queue.append(t)
            self._costs[source] = distances
        phases = self._costs[source].get(target)
        if phases is None:
            return None
        return {'phases': phases, 'installations': sum(b - a for a, b in zip(source, target)),
                'handoffs': max(0, phases - 1)}

    def check_plan(self, plan, source, target):
        expected = self.cost(source, target)
        require(plan['initial'] == self.external(source) and plan['target'] == self.external(target),
                "query source/target mismatch")
        require(plan['cost'] == expected, "wrong exact cost")
        require(plan['status'] == ('unreachable' if expected is None else 'planned'), "wrong status")
        trace = plan['search']['rank_iterates']
        require(trace and trace[0] == list(source), "rank trace lost source")
        if expected is None:
            require(plan['phases'] == [], "unreachable query carries execution authority")
        else:
            require(all(type(x) is int for x in plan['cost'].values()), "noninteger exact cost")
            previous, installations = source, 0
            require(len(plan['phases']) == expected['phases'], "phase inventory changed")
            require(trace == [list(source)] + [list(self.state(p['target'])) for p in plan['phases']],
                    "rank trace differs from phases")
            for phase in plan['phases']:
                start, end = self.state(phase['source']), self.state(phase['target'])
                require(start == previous and end in self.graph()[start], "unsafe physical phase")
                box = phase['box']
                require(set(box) == set(self.nodes) and
                        all(box[n] == canonical_terms(box[n]) for n in self.nodes), "noncanonical guards")
                checks = []
                for factor in sorted(self.factors, key=lambda f: f['id']):
                    scope = self.shapes[factor['id']][0]
                    terms = {}
                    for n in scope:
                        relevant = {a for b in factor['branches'] for a in b[n]}
                        terms[n] = canonical_terms([sorted(set(term) & relevant) for term in box[n]])
                    corners = list(product(*(terms[n] for n in scope)))
                    for corner in corners:
                        state = dict(zip(scope, map(set, corner)))
                        require(any(all(set(req) <= state[n] for n, req in b.items())
                                    for b in factor['branches']), "unsafe positive guard corner")
                    checks.append({'id': factor['id'], 'corners': len(corners)})
                require(phase['factor_checks'] == checks, "positive guard inventory changed")
                require(set(phase['local_paths']) == set(self.nodes), "path owner inventory")
                for i, n in enumerate(self.nodes):
                    path = [list(self.profiles[n][r]) for r in range(start[i], end[i] + 1)]
                    require(phase['local_paths'][n] == path, "physical path changed")
                    require(all(any(set(term) <= set(p) for term in box[n]) for p in path),
                            "local path not authorized")
                current = list(start)
                for step in phase['steps']:
                    require(set(step) == {'node', 'support'} and step['node'] in self.positions,
                            "invalid installation step")
                    n, i = step['node'], self.positions[step['node']]
                    require(self.rank[n][tuple(step['support'])] == current[i] + 1,
                            "installation skips a chain edge")
                    current[i] += 1
                    require(current[i] <= end[i] and self.safe(tuple(current)), "unsafe installed state")
                    installations += 1
                require(tuple(current) == end, "phase did not reach endpoint")
                previous = end
            require(previous == target and installations == expected['installations'], "incomplete plan")
        # All nonterminal iterates must be the componentwise greatest outgoing
        # safe endpoint below this target, reconstructed from the full graph.
        for a, b in zip(trace, trace[1:]):
            a, b = tuple(a), tuple(b)
            endpoints = [a] + [t for t in self.graph()[a]
                               if all(x <= y for x, y in zip(t, target))]
            greatest = tuple(max(t[i] for t in endpoints) for i in range(len(self.nodes)))
            require(b == greatest, "incorrect greatest-endpoint trace")
        if expected is None and self.safe(target) and all(a <= b for a, b in zip(source, target)):
            require(len(trace) >= 2 and trace[-1] == trace[-2], "missing fixed-point certificate")

