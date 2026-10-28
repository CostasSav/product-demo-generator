from split_voice import align, cut_between, tokens


def test_digits_are_spelled_in_the_voice_language():
    assert tokens("1. The axis", "en") == ["one", "the", "axis"]
    assert tokens("2. L'équipe", "fr") == ["deux", "l", "equipe"]


def test_a_short_word_opening_a_scene_stays_with_it():
    """Whisper dates "One" badly (zero length, too late): the cut must fall in the silence BEFORE
    it, i.e. the first silence after the previous scene's last word — not the longest one."""
    previous = {"start": 151.4, "end": 160.32, "confidence": 1.0}
    following = {"start": 160.88, "end": 165.0, "confidence": 1.0}  # "1." at 160.88 (wrong)
    pauses = [(160.30, 160.58), (160.76, 161.04)]  # "One" spoken 160.58–160.76
    at, length = cut_between(previous, following, pauses)
    assert 160.30 < at < 160.58
    assert length > 0.2


def test_without_silence_the_cut_is_between_the_words():
    at, length = cut_between({"end": 10.0}, {"start": 10.4}, [])
    assert at == 10.2 and length == 0.0


def test_alignment_finds_each_scene_and_flags_missing_ones():
    words = [{"word": w, "start": i * 0.4, "end": i * 0.4 + 0.3}
             for i, w in enumerate(["Hello", "there.", "2.", "Second", "line", "here"])]
    bounds = align(["Hello there.", "This line was never recorded.", "Two, second line here."],
                   words, "en")
    assert bounds[0]["confidence"] == 1.0
    assert bounds[1] is None
    assert bounds[2]["start"] == words[2]["start"]
