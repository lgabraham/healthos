"""The intake tagger: free text -> coarse exposure tags. DB-free (pure function).
"""

from __future__ import annotations

from healthos.intake import known_tags, tag_intake


def test_parses_a_realistic_entry():
    tags = tag_intake("2 Advil, glass of red wine, 400mg magnesium")
    assert "nsaid" in tags          # Advil
    assert "alcohol" in tags        # wine
    assert "high_histamine" in tags  # wine also flags histamine
    assert "magnesium" in tags


def test_multi_tag_keywords():
    assert set(tag_intake("oat milk latte")) >= {"caffeine", "dairy"}
    assert set(tag_intake("had a beer")) >= {"alcohol", "gluten"}


def test_word_boundary_avoids_false_matches():
    # "gin" must not fire inside "ginger"; no alcohol tag here.
    assert tag_intake("ginger tea with honey") == []
    # but a real "gin" does
    assert "alcohol" in tag_intake("gin and tonic")


def test_dedupes_and_is_order_stable():
    tags = tag_intake("wine, more wine, and cheese")
    assert tags.count("alcohol") == 1
    assert tags == list(dict.fromkeys(tags))  # no dupes


def test_empty_and_unknown():
    assert tag_intake("") == []
    assert tag_intake(None) == []
    assert tag_intake("plain grilled chicken and rice") == []


def test_known_tags_includes_first_class_ones():
    kt = known_tags()
    for t in ("nsaid", "alcohol", "magnesium", "dairy", "gluten", "high_histamine"):
        assert t in kt
