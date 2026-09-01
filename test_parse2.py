import re

text = """1. A system comprising:
a slider diagonally extends
in a direction;
2.
The system of claim 1.
3.The system of claim 2."""

claim_start_old = re.compile(r'^\s*(?:claim\s+)?\d+\.\s+', re.IGNORECASE)
claim_start_new = re.compile(r'^\s*(?:claim\s+)?\d+\.(?:\s|$)', re.IGNORECASE)

for line in text.split('\n'):
    print(f"Line: '{line}', old: {bool(claim_start_old.match(line))}, new: {bool(claim_start_new.match(line))}")
