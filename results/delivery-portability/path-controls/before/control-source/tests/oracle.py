"""Direct specification evaluator; no imports from controller or planner."""
def relation_truth(alternatives, support):
    for alternative in alternatives:
        missing = 0
        for node in alternative:
            for atom in alternative[node]:
                if atom not in support[node]:
                    missing += 1
        if missing == 0:
            return True
    return False
