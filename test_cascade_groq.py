import sys
from app.services.parser_service import parser_service

with open("test2.txt", "wb") as f:
    f.write(b"this is some garbage that has no claims")

import app.extractor.text
app.extractor.text.TextExtractor.extract = lambda self, r: 1/0 # Force exception

try:
    with open("test2.txt", "rb") as f:
        doc = parser_service.parse(f.read(), "test2.txt", False)
        print("SUCCESS txt:", doc.claim_count)
except Exception as e:
    print("FAIL txt:", e)
