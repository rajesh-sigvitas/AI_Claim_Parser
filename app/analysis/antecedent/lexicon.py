"""
Closed-class vocabulary used by the antecedent analyser.

Everything in this file is deliberately *general* English / patent-drafting
vocabulary rather than terminology harvested from any one specimen document.
The previous implementation terminated noun phrases using a hand-written list
of verbs observed in a single test file ("rolling", "facing", "overlaps", ...),
which silently corrupted terms in every other document.  Here the noun phrase
boundary is decided by closed word classes (determiners, prepositions,
conjunctions, auxiliaries, relatives) plus morphology, which generalises.
"""

# --------------------------------------------------------------------------
# Determiners
# --------------------------------------------------------------------------
# Multi-word determiners must be listed before their single-word prefixes so
# that the alternation in the compiled regex prefers the longest match.
INTRODUCTORY_DETERMINERS = [
    "at least one of",
    "at least one",
    "at least two of",
    "at least two",
    "one or more of",
    "one or more",
    "two or more of",
    "two or more",
    "a plurality of",
    "a number of",
    "a set of",
    "a pair of",
    "a single pair of",
    "an",
    "a",
    "each",
    "every",
    "multiple",
    "several",
    "various",
]

REFERENTIAL_DETERMINERS = [
    "said plurality of",
    "the plurality of",
    "each of the",
    "each of said",
    "one of the",
    "one of said",
    "the",
    "said",
]

ALL_DETERMINERS = REFERENTIAL_DETERMINERS + INTRODUCTORY_DETERMINERS

# Determiners that make the noun phrase plural-by-construction.
PLURALITY_DETERMINERS = {
    "a plurality of", "the plurality of", "said plurality of",
    "one or more", "one or more of", "two or more", "two or more of",
    "at least two", "at least two of", "several", "various",
    "multiple", "a number of", "a set of", "a pair of", "a single pair of",
}

# Determiners that quantify over an already-introduced group.  They read as a
# reference in prose but are not a reliable antecedent *source*, so they are
# treated as introductions with singular number (the conservative choice that
# avoids inventing missing-antecedent findings).
DISTRIBUTIVE_DETERMINERS = {"each", "every", "each of the", "each of said", "one of the", "one of said"}

# --------------------------------------------------------------------------
# Function words: any of these terminates a noun phrase.
# --------------------------------------------------------------------------
PREPOSITIONS = {
    "of", "in", "on", "at", "to", "for", "with", "by", "from", "into", "onto",
    "upon", "within", "without", "through", "throughout", "across", "along",
    "between", "among", "amongst", "against", "about", "above", "below",
    "under", "over", "beneath", "behind", "beside", "besides", "toward",
    "towards", "around", "near", "off", "out", "outside", "inside", "during",
    "via", "per", "than", "as", "like", "unlike", "except", "including",
    "such", "relative", "respect", "respectively",
}

CONJUNCTIONS = {"and", "or", "nor", "but", "either", "neither", "both", "plus"}

SUBORDINATORS = {
    "wherein", "whereby", "whereas", "thereby", "thereof", "therein",
    "therebetween", "thereto", "therefrom", "thereon", "when", "while",
    "where", "if", "unless", "although", "though", "because", "since",
    "so", "thus", "hence", "therefore", "that", "which", "who", "whom",
    "whose", "what", "whether",
}

AUXILIARIES = {
    "is", "are", "was", "were", "be", "been", "being", "am",
    "has", "have", "had", "having",
    "do", "does", "did", "doing",
    "can", "could", "shall", "should", "will", "would", "may", "might",
    "must", "ought", "not", "no",
}

# Transitional / structural words in claim language.
CLAIM_STRUCTURE_WORDS = {
    "comprising", "comprises", "comprise", "comprised",
    "consisting", "consists", "consist",
    "essentially", "characterized", "characterised",
    "further", "additionally", "also", "only", "least", "more", "most",
    "configured", "adapted", "operable", "capable", "arranged", "constructed",
    "according", "set", "forth", "claim", "claims", "any", "preceding",
}

# The union used as a hard stop while scanning a noun phrase.
NP_TERMINATORS = (
    PREPOSITIONS | CONJUNCTIONS | SUBORDINATORS | AUXILIARIES | CLAIM_STRUCTURE_WORDS
)

# Prepositions that bind a noun phrase together instead of ending it: "a level of
# understanding", "a range of motion".  Every other preposition ends the phrase
# ("a sensor for the vehicle" -> "sensor").  This set is the configuration point for
# where term spans stop; it is read at extraction time, so it can be changed without
# touching the extractor.  A binding preposition never ends a term: "the frame of the
# vehicle" still yields "frame", because the dangling "of" is trimmed.
NON_BREAKING_PREPOSITIONS = {"of"}

# Words that can follow a noun without belonging to it: adverbs that do not end in -ly,
# and adjectives used predicatively or as an object complement ("connecting the wheels
# of the vehicle together", "holding the vehicle stationary").  Trimmed only from the
# end of a phrase; in front of the noun they are ordinary modifiers ("a stationary rail").
TRAILING_MODIFIERS = {
    "together", "apart", "away", "aside", "alone", "stationary", "upright", "intact",
    "flush", "taut", "open", "closed", "parallel", "perpendicular",
}

# --------------------------------------------------------------------------
# Morphology helpers
# --------------------------------------------------------------------------
# Words ending in -ing / -ed that are ordinary nouns in mechanical/electrical
# claim drafting.  Without this whitelist the participle rule would truncate
# perfectly good heads such as "the opening" or "the bearing".
NOMINAL_ING_ED = {
    "opening", "openings", "housing", "housings", "bearing", "bearings",
    "casing", "casings", "coating", "coatings", "covering", "coverings",
    "lining", "linings", "tubing", "wiring", "piping", "packaging", "padding",
    "spring", "springs", "ring", "rings", "string", "strings", "wing", "wings",
    "fitting", "fittings", "setting", "settings", "reading", "readings",
    "recording", "recordings", "grating", "gratings", "winding", "windings",
    "bushing", "bushings", "fastening", "fastenings", "coupling", "couplings",
    "landing", "landings", "ceiling", "ceilings", "building", "buildings",
    "thing", "things", "being", "beings", "sling", "slings", "swing", "swings",
    "bed", "beds", "seed", "seeds", "feed", "feeds", "speed", "speeds",
    "thread", "threads", "shield", "shields", "weld", "welds", "field",
    "fields", "head", "heads", "lead", "leads", "shed", "sheds", "reed",
    "reeds", "bead", "beads", "tread", "treads", "spread", "spreads",
    "electrode", "electrodes", "node", "nodes", "code", "codes", "mode",
    "modes", "diode", "diodes", "blade", "blades", "grade", "grades",
    "side", "sides", "guide", "guides", "slide", "slides", "oxide", "oxides",
}

# Third-person singular verb forms that are unambiguously verbal in claim
# prose.  Deliberately excludes forms that are also common plural nouns in
# patents ("contacts", "supports", "outputs", "displays", "controls", "leads",
# "guides", "seals", "springs"), because trimming those would destroy a real
# noun head.  Used to cut a finite verb off the end of a noun phrase:
# "the flange extends from the base" -> "the flange".
FINITE_VERB_S = {
    "extends", "includes", "defines", "comprises", "consists", "moves",
    "rotates", "connects", "couples", "engages", "allows", "enables",
    "causes", "retains", "surrounds", "overlaps", "abuts", "protrudes",
    "projects", "traverses", "transmits", "generates", "determines",
    "actuates", "urges", "spans", "passes", "flows", "enters", "converts",
    "senses", "detects", "ranges", "varies", "differs", "provides",
    "receives", "stores", "carries", "holds", "permits", "prevents",
    "corresponds", "serves", "operates", "exerts", "applies", "attaches",
    "secures", "fastens", "mounts", "aligns", "separates", "joins",
    "divides", "reduces", "increases", "decreases", "maintains", "ensures",
    "requires", "contains", "encloses", "covers", "protects", "actuates",
    "communicates", "cooperates", "interacts", "responds", "translates",
    "rolls", "slopes", "tapers", "curves", "bends",
}


def is_finite_verb_s(word: str) -> bool:
    """True for a third-person singular verb that must not end a noun phrase."""
    return word.lower() in FINITE_VERB_S


def is_predicative_adjective(word: str) -> bool:
    """
    True for -able/-ible adjectives.

    Attributive adjectives precede their noun ("a movable body"), so an
    -able word appearing *after* the head is predicative and sits outside the
    noun phrase ("making a movable body slidable with respect to ..." ->
    "a movable body").  The length guard keeps ordinary nouns such as "cable"
    and "table" out.
    """
    w = word.lower()
    return len(w) > 5 and (w.endswith("able") or w.endswith("ible"))


# --------------------------------------------------------------------------
# Modifiers that are stripped before matching a reference to its antecedent.
# "the corresponding stationary rail bearings" must resolve against
# "stationary rail bearings" -- the modifier is deictic, not identifying.
# --------------------------------------------------------------------------
DEICTIC_MODIFIERS = {
    "corresponding", "respective", "aforementioned", "aforesaid",
    "same", "given", "particular", "certain", "specific", "respectively",
    "above", "aforedescribed", "described", "mentioned", "noted",
}

# --------------------------------------------------------------------------
# Relational / inherent nouns.
#
# A structure's inherent parts ("the bottom of the housing") do not need their
# own explicit introduction -- MPEP 2173.05(e) treats them as having inherent
# antecedent basis.  Matching is by *exact normalised term*, so a qualified
# phrase such as "the open bottom" is still reported.
# --------------------------------------------------------------------------
RELATIONAL_NOUNS = {
    "bottom", "top", "side", "end", "edge", "center", "centre", "middle",
    "front", "rear", "back", "interior", "exterior", "inside", "outside",
    "surface", "periphery", "circumference", "perimeter", "length", "width",
    "height", "depth", "thickness", "diameter", "radius", "area", "volume",
    "shape", "size", "position", "orientation", "direction", "angle",
    "distance", "movement", "motion", "rotation", "axis", "plane",
    "upper portion", "lower portion", "inner surface", "outer surface",
    "upper end", "lower end", "inner side", "outer side", "upper side",
    "lower side", "opposite corner", "opposite corners", "opposite side",
    "opposite sides", "opposite end", "opposite ends",
    "number", "amount", "plurality", "one", "other", "others", "rest",
    "remainder", "combination", "group", "type", "kind", "portion", "part",
}

# Ordinals recognised when expanding "the first and second X".
ORDINALS = [
    "first", "second", "third", "fourth", "fifth", "sixth", "seventh",
    "eighth", "ninth", "tenth", "eleventh", "twelfth",
]

# Standalone ordinals / bare quantifiers are never a term on their own.
NON_TERMS = set(ORDINALS) | {
    "plurality", "pair", "set", "number", "one", "two", "three", "four",
    "five", "six", "seven", "eight", "nine", "ten", "least", "more", "less",
    "same", "other", "another", "such", "said", "the", "a", "an",
    # List pointers: "one of the following: A and B" names no element of its own.
    "following", "foregoing",
}


# Nouns ending in -ly that must not be mistaken for adverbs.
NOMINAL_LY = {
    "assembly", "assemblies", "supply", "supplies", "family", "families",
    "reply", "replies", "ply", "plies", "poly", "jelly", "belly", "ally",
    "allies", "folly", "rally", "tally", "gully", "pulley", "pulleys",
    "trolley", "trolleys", "valley", "valleys", "alley", "alleys", "holly",
    "dolly", "lily", "filly", "anomaly", "anomalies",
}


def is_adverb(word: str) -> bool:
    """True for -ly adverbs, which never belong to a noun phrase."""
    w = word.lower()
    if w in NOMINAL_LY:
        return False
    return len(w) > 4 and w.endswith("ly")


def is_participle(word: str) -> bool:
    """True when the word looks like a verb participle rather than a noun."""
    w = word.lower()
    if w in NOMINAL_ING_ED:
        return False
    if len(w) > 4 and (w.endswith("ing") or w.endswith("ed")):
        return True
    return False


def is_plural_form(word: str) -> bool:
    """Cheap plural test for the head noun of a phrase."""
    w = word.lower()
    if w.endswith("ss") or w.endswith("us") or w.endswith("is"):
        return False
    return w.endswith("s")
