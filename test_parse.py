import re

text = """1. A system comprising:
a slider diagonally extends
in a direction;
2. The system of claim 1.
3. The system of claim 2."""

# 4. Line Merging
text = re.sub(r'([a-zA-Z])-\s*\n\s*([a-zA-Z])', r'\1\2', text)

lines = text.split('\n')
merged_lines = []
claim_start = re.compile(r'^\s*(?:claim\s+)?\d+\.\s+', re.IGNORECASE)

for line in lines:
    stripped = line.strip()
    if not stripped:
        merged_lines.append("")
        continue
        
    if merged_lines and merged_lines[-1] != "":
        if claim_start.match(stripped):
            merged_lines.append(stripped)
        else:
            merged_lines[-1] = merged_lines[-1] + " " + stripped
    else:
        merged_lines.append(stripped)
        
text = '\n'.join(merged_lines)
text = re.sub(r'\n{2,}', '\n\n', text)
print("---NORMALIZED TEXT---")
print(repr(text))
print("---------------------")

_BOUNDARY = re.compile(
    r'(?:^|\n)[ \t]*(?:claim[ \t]+)?(\d+)\.[ \t]*',
    re.IGNORECASE
)
boundaries = []
for m in _BOUNDARY.finditer(text):
    boundaries.append((m.start(), int(m.group(1)), m.end()))
print("BOUNDARIES:", boundaries)
