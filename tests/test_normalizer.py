from forza.domain.normalizer import fix_track_name, fix_car_name


def test_fix_track_empty(refs):
    assert fix_track_name("", refs) == ""


def test_fix_track_hyphen_equivalent(refs):
    raw = "Le Mans Circuit International de la Sarthe Full Circuit"
    assert fix_track_name(raw, refs) == "Le Mans - Circuit International de la Sarthe Full Circuit"


def test_fix_car_no_match(refs):
    original = "XYZ inexistente"
    assert fix_car_name(original, refs) == original

