from src.research.families.low_capacity_announcements import h065


def test_h065_subject_rule_is_exact_and_excludes_mous():
    assert h065._is_selected([{"subject": "Acquisition"}])
    assert h065._is_selected([{"subject": "Bagging/Receiving of orders/contracts"}])
    assert not h065._is_selected([
        {"subject": "Memorandum of Understanding/Agreements"}])
    assert not h065._is_selected([{"subject": "Resignation"}])
