"""CA Secretary of State — Statement of Information PDF parsing via LLM.

The CA SoS business portal (bizfileOnline.sos.ca.gov) provides PDF
Statements of Information for registered entities.  This parser extracts
entity details and principal information using an LLM provider.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.llm.base import LLMProvider

logger = logging.getLogger(__name__)

SOS_SYSTEM_PROMPT: str = """\
You are an expert at parsing California Secretary of State Statements of \
Information (Form SI-550 / SI-200).  Extract the following JSON fields from \
the document text:

- entity_name (str): The exact legal name of the business entity.
- entity_id (str): The California SOS entity number (e.g. "202412312345").
- filing_date (str | null): Date of the Statement of Information filing.
- registered_agent_name (str | null): The agent for service of process.
- registered_agent_address (str | null): Street address of the registered agent.
- principals (list[dict]): Each with keys:
    - name (str)
    - title (str)
    - address (str | null)
    - phone (str | null)
- entity_type (str): "LLC", "Corporation", "LP", etc.

IMPORTANT: Return ONLY the validated JSON object with no additional text \
or explanation.
"""


class CASOSParser:
    """Parse CA Secretary of State PDF documents using an LLM provider."""

    def __init__(self, llm_client: LLMProvider) -> None:
        """Inject the LLM client used for text extraction.

        Args:
            llm_client: An LLM provider instance.

        """
        self._llm = llm_client

    # ------------------------------------------------------------------
    # PDF extraction
    # ------------------------------------------------------------------

    @staticmethod
    def extract_text_from_pdf(pdf_path: str | Path) -> str | None:
        """Extract plain text from a PDF using ``pypdf``.

        Args:
            pdf_path: Path to the PDF file.

        Returns:
            Extracted text, or ``None`` on failure.

        """
        try:
            from pypdf import PdfReader  # noqa: PLC0415 — lazy import
        except ImportError:
            logger.exception("pypdf is not installed — cannot parse PDFs.")
            return None

        path = Path(pdf_path)
        if not path.exists():
            logger.error("PDF file not found: %s", path)
            return None

        try:
            reader = PdfReader(str(path))
            pages: list[str] = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
            full_text = "\n".join(pages)
            logger.info(
                "Extracted %d characters from %s", len(full_text), path.name,
            )
            return full_text
        except Exception as exc:
            logger.exception("Failed to extract text from PDF: %s", exc)
            return None

    # ------------------------------------------------------------------
    # LLM-based parsing
    # ------------------------------------------------------------------

    def parse_statement_of_information(
        self,
        pdf_path: str | Path,
    ) -> dict[str, Any]:
        """Extract structured entity information from a SoS PDF.

        Combines ``pypdf`` extraction with LLM-based structured JSON parsing.

        Args:
            pdf_path: Path to the PDF file.

        Returns:
            A dictionary with keys matching the JSON schema defined in the
            system prompt.  If extraction or parsing fails, error details
            are returned under an ``_error`` key.

        """
        text = self.extract_text_from_pdf(pdf_path)
        if not text:
            return {"_error": f"Could not extract text from {pdf_path}"}

        try:
            result: dict[str, Any] = self._llm.generate_structured_json(
                system_prompt=SOS_SYSTEM_PROMPT,
                user_prompt=f"Parse the following Statement of Information:\n\n{text}",
            )
            return result
        except RuntimeError as exc:
            logger.exception("LLM parsing of SoS PDF failed: %s", exc)
            return {"_error": str(exc), "raw_text_preview": text[:500]}


if __name__ == "__main__":
    import os

    # Smoke test — needs a real PDF and an LLM key
    sample = os.environ.get("SOS_PDF_PATH")
    if sample and os.environ.get("ANTHROPIC_API_KEY"):
        from src.llm.anthropic_provider import AnthropicProvider

        llm = AnthropicProvider(api_key=os.environ["ANTHROPIC_API_KEY"])
        parser = CASOSParser(llm)
        data = parser.parse_statement_of_information(sample)
    else:
        pass
