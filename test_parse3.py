import re
_BOUNDARY = re.compile(r'(?:^|\n)[ \t]*(?:claim[ \t]+)?(\d+)\.[ \t]*', re.IGNORECASE)
m = _BOUNDARY.match("3.14")
if m:
    print("Matches 3.14!")
else:
    print("Does not match")
