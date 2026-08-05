import sys
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFontFamily

pdfmetrics.registerFont(TTFont('DejaVuSerif', '/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf'))
pdfmetrics.registerFont(TTFont('DejaVuSerif-Bold', '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf'))
pdfmetrics.registerFont(TTFont('DejaVuSerif-Italic', '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf'))
pdfmetrics.registerFont(TTFont('DejaVuSerif-BoldItalic', '/usr/share/fonts/truetype/dejavu/DejaVuSerif-BoldItalic.ttf'))
registerFontFamily(
    'DejaVuSerif', 
    normal='DejaVuSerif', 
    bold='DejaVuSerif-Bold', 
    italic='DejaVuSerif-Italic', 
    boldItalic='DejaVuSerif-BoldItalic'
)

styles = getSampleStyleSheet()
style = styles['Normal']
style.fontName = 'DejaVuSerif'

text = "Fraction: ⅛, ½, H<sub>2</sub>O, E=mc<sup>2</sup>, Bold: <b>Bold</b>, Greek: αβγ"

doc = SimpleDocTemplate("test_output.pdf")
doc.build([Paragraph(text, style)])
print("Success!")
