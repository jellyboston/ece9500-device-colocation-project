import pytest

from colocation.evaluate import score_groups


def truth(groups, trial="trial"):
    return [
        {"trial_id": trial, "device_id": device, "group_id": f"G{index}"}
        for index, group in enumerate(groups)
        for device in group
    ]


def test_exact_partition_scores_one_and_zero_count_error():
    result = score_groups({"trial_id": "trial", "groups": [["B", "A"], ["C", "D"]]}, truth([["A", "B"], ["D", "C"]]))
    assert result["pairwise_precision"] == result["pairwise_recall"] == result["pairwise_f1"] == 1
    assert result["count_absolute_error"] == 0
    assert result["true_positive_pairs"] == 2


def test_pairwise_metrics_penalize_wrong_pairs_even_at_correct_group_count():
    result = score_groups([["A", "C"], ["B", "D"]], truth([["A", "B"], ["C", "D"]]))
    assert result["pairwise_f1"] == 0
    assert result["false_positive_pairs"] == result["false_negative_pairs"] == 2
    assert result["count_absolute_error"] == 0


def test_missed_pair_and_extra_singleton_have_expected_metrics():
    result = score_groups([["A", "B"], ["C"], ["D"]], truth([["A", "B"], ["C", "D"]]))
    assert result["pairwise_precision"] == 1
    assert result["pairwise_recall"] == 0.5
    assert result["pairwise_f1"] == pytest.approx(2 / 3)
    assert result["count_absolute_error"] == 1


def test_no_positive_pairs_convention_is_defined():
    exact = score_groups([["A"], ["B"]], truth([["A"], ["B"]]))
    assert exact["pairwise_f1"] == 1
    missed = score_groups([["A"], ["B"]], truth([["A", "B"]]))
    assert missed["pairwise_precision"] == missed["pairwise_recall"] == missed["pairwise_f1"] == 0
    false_pair = score_groups([["A", "B"]], truth([["A"], ["B"]]))
    assert false_pair["pairwise_precision"] == false_pair["pairwise_f1"] == 0
    assert false_pair["pairwise_recall"] == 1


@pytest.mark.parametrize("predictions", [[["A"]], [["A", "B"], ["A"]], [["A", "A"], ["B"]], [["A", "unknown"]], [[]]])
def test_invalid_or_incomplete_prediction_partitions_fail(predictions):
    with pytest.raises(ValueError):
        score_groups(predictions, truth([["A", "B"]]))


def test_duplicate_or_mixed_trial_truth_and_wrong_prediction_trial_fail():
    rows = truth([["A", "B"]])
    with pytest.raises(ValueError, match="more than once"):
        score_groups([["A", "B"]], rows + [rows[0]])
    rows[1]["trial_id"] = "other"
    with pytest.raises(ValueError, match="one trial"):
        score_groups([["A", "B"]], rows)
    with pytest.raises(ValueError, match="trial IDs"):
        score_groups({"trial_id": "other", "groups": [["A", "B"]]}, truth([["A", "B"]]))
