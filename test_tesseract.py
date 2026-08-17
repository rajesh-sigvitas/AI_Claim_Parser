import pdfplumber
import io
import pytesseract
from reportlab.pdfgen import canvas

# Create a dummy scanned PDF
c = canvas.Canvas("dummy.pdf")
c.drawString(100, 100, "Hello World")
c.save()

try:
    with pdfplumber.open("dummy.pdf") as pdf:
        page = pdf.pages[0]
        img = page.to_image(resolution=300).original
        ocr_text = pytesseract.image_to_string(img)
        print("OCR Text:", ocr_text)
except Exception as e:
    print("Error:", repr(e))
