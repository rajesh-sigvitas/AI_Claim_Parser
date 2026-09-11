import os
from app.services.parser_service import parser_service
from app.analysis.service import analysis_service

def run():
    path = "/home/sig/Downloads/test_Aug_18.docx"
    with open(path, "rb") as f:
        doc_bytes = f.read()
    
    doc = parser_service.parse(doc_bytes, "test_Aug_18.docx", generate_pdf=False)
    result = analysis_service.analyze_antecedents(doc)
    
    print(f"\nTotal findings: {result.total_findings}")
    for f in result.findings:
        print(f"Claim {f.claim_number}: [{f.type.value}] {f.term} ({f.message})")
        
if __name__ == "__main__":
    run()
