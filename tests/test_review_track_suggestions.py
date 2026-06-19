from forza.domain.review_rules import track_suggestions


def test_track_suggestions_use_raw_ambiguous_prefix():
    tracks = [
        "Mugello Circuit Club Circuit",
        "Mugello Circuit Full Circuit",
        "Hakone Grand Prix Circuit",
    ]

    suggestions = track_suggestions("Unknown (ambiguous layout): Mugello Circuit", tracks)

    assert suggestions == [
        "Mugello Circuit Club Circuit",
        "Mugello Circuit Full Circuit",
    ]

