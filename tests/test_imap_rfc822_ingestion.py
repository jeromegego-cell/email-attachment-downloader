"""Unit and integration tests for IMAP RFC 822 email payload parsing and streaming."""

from email.message import EmailMessage
from unittest.mock import MagicMock
import pytest

from email_ingestion.connectors.imap_connector import IMAPConnector


def create_synthetic_rfc822_email() -> bytes:
    """Create a fully compliant RFC 822 multipart email with headers and attachments."""
    msg = EmailMessage()
    msg["From"] = "Acme Supplies <orders@acme-supplies.com>"
    msg["To"] = "Finance <finance@mycompany.com>"
    msg["Subject"] = "Invoice – September 2026 Order #8821"
    msg["Message-ID"] = "<acme_order_8821@acme-supplies.com>"
    msg["Date"] = "Fri, 11 Sep 2026 12:30:00 +0000"

    # Plain text body
    msg.set_content("Please find attached the official purchase invoice and item list.")

    # HTML alternative
    msg.add_alternative(
        "<p>Please find attached the official purchase invoice and item list.</p>"
        "<img src='cid:signature_logo_99' alt='Logo'>",
        subtype="html"
    )

    # Real PDF attachment
    pdf_bytes = b"%PDF-1.5\n1 0 obj<</Type/Catalog>>endobj\nxref\n0 1\ntrailer<</Root 1 0 R>>\n%%EOF"
    msg.add_attachment(
        pdf_bytes,
        maintype="application",
        subtype="pdf",
        filename="Purchase_Invoice_8821.pdf"
    )

    # Real CSV attachment
    csv_bytes = b"Sku,Quantity,UnitCost,Total\nSKU-100,5,12.50,62.50\n"
    msg.add_attachment(
        csv_bytes,
        maintype="text",
        subtype="csv",
        filename="line_items.csv"
    )

    return msg.as_bytes()


def test_imap_connector_rfc822_multipart_parsing():
    """Verify that IMAPConnector accurately parses RFC 822 bytes and provides streaming."""
    raw_email_bytes = create_synthetic_rfc822_email()

    connector = IMAPConnector(
        host="imap.acme-corp.com",
        username="finance@mycompany.com",
        password="secret_password"
    )

    # Mock the internal IMAP4 client
    mock_client = MagicMock()
    mock_client.search.return_value = ("OK", [b"2"])
    mock_client.fetch.return_value = ("OK", [(b"2 (RFC822 {1234})", raw_email_bytes)])

    connector._client = mock_client

    envelopes = connector.fetch_new_messages(max_messages=10)
    assert len(envelopes) == 1

    env = envelopes[0]
    assert env.id == "acme_order_8821@acme-supplies.com"
    assert "acme" in env.sender_email.lower()
    assert "Invoice – September 2026" in env.subject
    assert len(env.attachments) == 2

    # Check first attachment (PDF)
    att_pdf = next(a for a in env.attachments if a.filename == "Purchase_Invoice_8821.pdf")
    assert att_pdf.content_type == "application/pdf"
    assert att_pdf.size_bytes > 20

    # Stream download test
    stream = connector.download_attachment_stream(env.id, att_pdf.id)
    downloaded_bytes = stream.read()
    assert downloaded_bytes.startswith(b"%PDF-1.5")

    # Check second attachment (CSV)
    att_csv = next(a for a in env.attachments if a.filename == "line_items.csv")
    csv_stream = connector.download_attachment_stream(env.id, att_csv.id)
    assert b"SKU-100" in csv_stream.read()

    # Verify acknowledgement flags Seen
    connector.acknowledge_processed(env.id)
    mock_client.store.assert_called_with("2", "+FLAGS", "\\Seen")

    # Verify clean disconnect
    connector.disconnect()
    mock_client.close.assert_called_once()
    mock_client.logout.assert_called_once()
    assert connector._client is None
