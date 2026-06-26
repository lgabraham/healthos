r"""Parse a free-text intake/journal entry into behavioral tags.

Mirrors the calendar keyword tagger (``sync/calendar.py``): a keyword map matched
case-insensitively against the entry text — but here a keyword can carry several
tags ("latte" -> caffeine + dairy, "beer" -> alcohol + gluten). Tags are
deliberately coarse: they flag an *exposure*, not a dose, and feed the
inflammation-correlation view, so NSAIDs / alcohol / common dietary triggers are
first-class for chronic-sinus tracking.

Matching is word-boundary aware, so ``\bgin\b`` fires on "gin and tonic" but not
on "ginger tea".
"""

from __future__ import annotations

import re

# keyword -> tags. Lowercase keywords; a keyword may carry multiple tags. Edit
# freely as you learn what matters — order only affects tag display order.
INTAKE_TAGS: dict[str, tuple[str, ...]] = {
    # NSAIDs — first-class for inflammatory / sinus disease
    "advil": ("nsaid",),
    "ibuprofen": ("nsaid",),
    "motrin": ("nsaid",),
    "aleve": ("nsaid",),
    "naproxen": ("nsaid",),
    "aspirin": ("nsaid",),
    "nsaid": ("nsaid",),
    # alcohol (beer/wine also carry their dietary tags)
    "alcohol": ("alcohol",),
    "wine": ("alcohol", "high_histamine"),
    "beer": ("alcohol", "gluten"),
    "ipa": ("alcohol", "gluten"),
    "cocktail": ("alcohol",),
    "whiskey": ("alcohol",),
    "vodka": ("alcohol",),
    "tequila": ("alcohol",),
    "gin": ("alcohol",),
    "margarita": ("alcohol",),
    "champagne": ("alcohol",),
    "prosecco": ("alcohol",),
    # supplements
    "magnesium": ("magnesium",),
    "fish oil": ("omega3",),
    "omega": ("omega3",),
    "turmeric": ("turmeric",),
    "curcumin": ("turmeric",),
    "vitamin d": ("vitamin_d",),
    "zinc": ("zinc",),
    "quercetin": ("quercetin",),
    "melatonin": ("melatonin",),
    "probiotic": ("probiotic",),
    # caffeine
    "coffee": ("caffeine",),
    "espresso": ("caffeine",),
    "latte": ("caffeine", "dairy"),
    "cappuccino": ("caffeine", "dairy"),
    "caffeine": ("caffeine",),
    "matcha": ("caffeine",),
    "green tea": ("caffeine",),
    "energy drink": ("caffeine", "sugar"),
    # dairy
    "milk": ("dairy",),
    "cheese": ("dairy",),
    "yogurt": ("dairy",),
    "ice cream": ("dairy", "sugar"),
    "butter": ("dairy",),
    "dairy": ("dairy",),
    "cream": ("dairy",),
    # gluten / wheat
    "bread": ("gluten",),
    "pasta": ("gluten",),
    "pizza": ("gluten", "dairy"),
    "bagel": ("gluten",),
    "cereal": ("gluten",),
    "gluten": ("gluten",),
    "sandwich": ("gluten",),
    # sugar / sweets
    "sugar": ("sugar",),
    "dessert": ("sugar",),
    "candy": ("sugar",),
    "soda": ("sugar",),
    "cake": ("sugar", "gluten"),
    "cookie": ("sugar", "gluten"),
    "donut": ("sugar", "gluten"),
    "chocolate": ("sugar",),
    # high-histamine (relevant to inflammation / sinus congestion)
    "aged cheese": ("dairy", "high_histamine"),
    "cured": ("high_histamine",),
    "salami": ("high_histamine",),
    "prosciutto": ("high_histamine",),
    "pepperoni": ("high_histamine",),
    "fermented": ("high_histamine",),
    "kimchi": ("high_histamine",),
    "sauerkraut": ("high_histamine",),
    "kombucha": ("high_histamine",),
    "soy sauce": ("high_histamine",),
    "vinegar": ("high_histamine",),
    "smoked": ("high_histamine",),
    # spicy
    "spicy": ("spicy",),
    "hot sauce": ("spicy",),
    "sriracha": ("spicy",),
    "chili": ("spicy",),
    "jalapeno": ("spicy",),
    "curry": ("spicy",),
}

# Pre-compile word-boundary patterns once at import.
_PATTERNS: list[tuple[re.Pattern[str], tuple[str, ...]]] = [
    (re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE), tags)
    for kw, tags in INTAKE_TAGS.items()
]


def tag_intake(text: str | None) -> list[str]:
    """Coarse exposure tags for a free-text intake entry.

    Order-stable (keyword order, then each keyword's tag order) and de-duplicated.
    Returns ``[]`` for empty input or text with no recognized keywords.
    """
    if not text:
        return []
    tags: list[str] = []
    for pattern, kw_tags in _PATTERNS:
        if pattern.search(text):
            for tag in kw_tags:
                if tag not in tags:
                    tags.append(tag)
    return tags


def known_tags() -> list[str]:
    """The full set of tags the parser can emit (for UI hints / docs)."""
    seen: list[str] = []
    for kw_tags in INTAKE_TAGS.values():
        for tag in kw_tags:
            if tag not in seen:
                seen.append(tag)
    return seen
