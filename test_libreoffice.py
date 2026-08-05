import subprocess
import os
import tempfile

def docx_to_pdf(raw_input: bytes) -> bytes:
    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, "input.docx")
        with open(input_path, "wb") as f:
            f.write(raw_input)
            
        cmd = ["libreoffice", "--headless", "--convert-to", "pdf", "input.docx", "--outdir", tmpdir]
        subprocess.run(cmd, cwd=tmpdir, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        pdf_path = os.path.join(tmpdir, "input.pdf")
        with open(pdf_path, "rb") as f:
            return f.read()

print("Function defined.")
