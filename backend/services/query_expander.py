"""
Expand one search term into many LinkedIn queries.

LinkedIn's content search returns at most ~12 results per query — verified by
scrolling a query to exhaustion: the card count stalls at 12 and there is no
"show more" control. So a 200-post target cannot come from one search; it comes
from many searches whose results are merged and de-duplicated.

Intent phrases are the useful axis: recruiters phrase the same opening a dozen
ways, and each phrasing surfaces a mostly different result set.
"""

# Ordered by how strongly each phrase correlates with a contact email in the
# post body — "send resume"/"share cv" posts almost always carry one.
INTENT_PHRASES = [
    "send resume",
    "share your resume",
    "share cv",
    "drop your cv",
    "share profile",
    "hiring",
    "we are hiring",
    "urgent hiring",
    "immediate joiner",
    "urgent requirement",
    "job opening",
    "openings",
    "now hiring",
    "interested candidates",
    "apply now",
    "walk in drive",
    "looking for candidates",
    "mail your resume",
    "resume to",
    "contact us hiring",
]

# Seniority/qualifier variants, applied to the highest-yield intents only so the
# query list does not explode.
QUALIFIERS = ["", "fresher", "immediate", "remote", "urgent"]

# Recruiters advertise the same role under many names. Searching only the exact
# phrase the user typed leaves most of the matching posts unfound, so a title
# containing these keywords is expanded into its common phrasings.
TITLE_VARIANTS = {
    "spring": [
        "java spring boot developer",
        "spring boot developer",
        "java backend developer",
        "java microservices developer",
        "backend developer java",
        "java developer",
    ],
    "java": [
        "java developer",
        "java backend developer",
        "java spring boot developer",
        "backend developer java",
        "java microservices developer",
    ],
    "python": [
        "python developer",
        "python backend developer",
        "django developer",
        "fastapi developer",
    ],
    "react": [
        "react developer",
        "reactjs developer",
        "frontend developer react",
    ],
    "node": [
        "node js developer",
        "nodejs backend developer",
        "backend developer node",
    ],
    "backend": [
        "backend developer",
        "backend engineer",
        "server side developer",
    ],
}


def expand_title(title: str) -> list[str]:
    """Related phrasings for a job title, most specific first.

    "java spring boot backend developer" becomes "spring boot developer",
    "java backend developer", and so on — each surfaces a different result set.
    The original title always leads.
    """
    t = " ".join((title or "").split()).lower()
    if not t:
        return []

    variants: list[str] = [t]
    for keyword, alts in TITLE_VARIANTS.items():
        if keyword in t:
            for alt in alts:
                if alt not in variants:
                    variants.append(alt)
    return variants


def build_queries(title: str, target_posts: int, per_query: int = 10) -> list[str]:
    """Query variants for `title`, enough to plausibly reach `target_posts`.

    Roughly `per_query` results come back per search and overlap between
    phrasings is heavy, so this asks for about 2.5x the naive number. Titles are
    expanded into synonyms first, then crossed with intent phrases — the two
    axes together cover far more ground than either alone.
    """
    titles = expand_title(title)
    if not titles:
        return []

    needed = max(1, int((target_posts / max(1, per_query)) * 2.5))
    queries: list[str] = list(titles)
    if len(queries) >= needed:
        return queries[:needed]

    # Interleave: every title paired with intent #1, then #2, ... so an early
    # stop still spans all the title variants rather than exhausting just one.
    for phrase in INTENT_PHRASES:
        for t in titles:
            q = f"{t} {phrase}"
            if q not in queries:
                queries.append(q)
            if len(queries) >= needed:
                return queries

    for qual in QUALIFIERS[1:]:
        for t in titles[:3]:
            for phrase in INTENT_PHRASES[:6]:
                q = f"{t} {qual} {phrase}"
                if q not in queries:
                    queries.append(q)
                if len(queries) >= needed:
                    return queries

    return queries
