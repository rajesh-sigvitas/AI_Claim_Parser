import sys
import os
sys.path.append(os.getcwd())
from app.parser.engine import ParserEngine
from app.core.constants import InputType
from loguru import logger
logger.remove()

engine = ParserEngine()

claims_text = """
1. A hitch system comprising:
a clevis; and
a pin.
2. The hitch system of claim 1, wherein the clevis is configured to enable the first
agricultural implement to rotate.
3. The hitch system of claim 1, wherein the first connector end comprises: a third opening;
and a fourth opening.
4. The hitch system of claim 1, wherein the system has (a) part A and (b) part B.
"""

doc = engine.parse(claims_text, InputType.RAW_TEXT)

for c in doc.claims:
    print(f"Claim {c.number}:")
    print(f"  Header: {c.header!r}")
    for el in c.elements:
        print(f"  Element: {el.text!r}")
