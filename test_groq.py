from app.extractor.ocr import OCRExtractor
with open("output/text_pdf_output.pdf", "rb") as f:
    pdf_bytes = f.read()

extractor = OCRExtractor()
print(f"Using provider: {type(extractor.provider)}")
try:
    text = extractor.extract(pdf_bytes)
    print("SUCCESS:")
    print(text[:200])
except Exception as e:
    print(f"FAILED: {e}")
