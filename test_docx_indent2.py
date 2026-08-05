import docx
doc_read = docx.Document("test_indent.docx")
for p in doc_read.paragraphs:
    indent = p.paragraph_format.left_indent
    if indent:
        print(f"Inches: {indent.inches}, Pt: {indent.pt}")
