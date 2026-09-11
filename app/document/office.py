"""
LibreOffice conversion, in one place.

``WordExtractor`` already converted .doc/.docx to PDF to get faithful text, and the
page/line model needs the same PDF for a different reason: page and line numbers only
mean something once the document has been laid out.  Both callers use this helper so a
document is never converted by two slightly different command lines.
"""
import os
import subprocess
import tempfile
from typing import Optional

from loguru import logger

CONVERTIBLE_SUFFIXES = (".doc", ".docx", ".odt", ".rtf")

_TIMEOUT_SECONDS = 120


def convert_to_pdf(raw_input: bytes, suffix: str = ".docx", timeout: int = _TIMEOUT_SECONDS) -> bytes:
    """
    Renders an office document to PDF and returns the bytes.

    A private user profile is used per call: LibreOffice refuses to start a second
    headless instance against a profile already in use, which is exactly what happens
    when two uploads are processed at once.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, f"input{suffix}")
        with open(input_path, "wb") as handle:
            handle.write(raw_input)

        profile_dir = os.path.join(tmpdir, "profile")
        command = [
            "libreoffice",
            f"-env:UserInstallation=file://{profile_dir}",
            "--headless",
            "--convert-to", "pdf",
            os.path.basename(input_path),
            "--outdir", tmpdir,
        ]

        logger.info(f"Converting {suffix} document to PDF for pagination.")
        result = subprocess.run(
            command, cwd=tmpdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout
        )
        if result.returncode != 0:
            message = result.stderr.decode("utf-8", errors="ignore")
            raise RuntimeError(f"LibreOffice conversion failed: {message}")

        pdf_path = os.path.join(tmpdir, "input.pdf")
        if not os.path.exists(pdf_path):
            raise RuntimeError("LibreOffice reported success but produced no PDF.")

        with open(pdf_path, "rb") as handle:
            return handle.read()


def suffix_for(filename: str) -> Optional[str]:
    """The conversion suffix for a filename, or None when it needs no conversion."""
    lowered = (filename or "").lower()
    for suffix in CONVERTIBLE_SUFFIXES:
        if lowered.endswith(suffix):
            return suffix
    return None
