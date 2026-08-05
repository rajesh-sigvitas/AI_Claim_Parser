import sys
from app.services.parser_service import parser_service

# Create dummy txt
with open("test.txt", "wb") as f:
    f.write(b"1. A dummy claim comprising: a test.")

try:
    with open("test.txt", "rb") as f:
        doc = parser_service.parse(f.read(), "test.txt", False)
        print("SUCCESS txt:", doc.claim_count)
except Exception as e:
    print("FAIL txt:", e)
