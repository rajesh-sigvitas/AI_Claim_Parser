import sys
import re
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

pdfmetrics.registerFont(TTFont('DejaVuSerif', '/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf'))

styles = getSampleStyleSheet()
style = ParagraphStyle('Test', parent=styles['Normal'], fontName='Times-Roman', fontSize=12, leading=14)

def fallback_font(text):
    # Match any character that is not ASCII (ord > 127)
    # This is a simple test, we will replace it with a font tag
    return re.sub(r'([^\x00-\x7F]+)', r'<font name="DejaVuSerif">\1</font>', text)

text = "Fraction: ⅛, ½, H<sub>2</sub>O, E=mc<sup>2</sup>, Greek: αβγ"
safe_text = fallback_font(text)
print("Safe text:", safe_text)

doc = SimpleDocTemplate("test_output2.pdf")
doc.build([Paragraph(safe_text, style)])
print("Success!")
