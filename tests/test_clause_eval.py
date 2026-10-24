from scripts.run_clause_eval import scores


def test_scores_perfect_and_binary():
    s = scores([("applicable", "applicable"), ("partial", "partial"), ("not_applicable", "not_applicable")])
    assert s["accuracy"] == 1.0 and s["kappa"] == 1.0
    assert s["binary_actionable"] == {"precision": 1.0, "recall": 1.0, "f1": 1.0}


def test_scores_conservative_errors():
    # 에이전트가 not_applicable을 partial로 올린 경우: 정확도는 깎이고 이진 재현율은 유지
    s = scores([("applicable", "applicable"), ("not_applicable", "partial")])
    assert s["accuracy"] == 0.5
    assert s["binary_actionable"]["recall"] == 1.0 and s["binary_actionable"]["precision"] == 0.5
    assert s["confusion"]["not_applicable→partial"] == 1


def test_scores_empty():
    assert scores([]) == {"n": 0}
