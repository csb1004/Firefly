from collections.abc import Sequence


def calculate_reward(expected: Sequence[str], predicted: Sequence[str]) -> float:
    expected_set = set(expected)
    predicted_set = set(predicted)
    if not expected_set and not predicted_set:
        return 1.0
    if expected_set == predicted_set:
        return 1.0
    if not expected_set or not predicted_set:
        return -1.0

    overlap = len(expected_set & predicted_set)
    if overlap == 0:
        return -1.0
    precision = overlap / len(predicted_set)
    recall = overlap / len(expected_set)
    return round((precision + recall) / 2, 4)
