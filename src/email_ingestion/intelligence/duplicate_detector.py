"""Duplicate anomaly detection and user prompt resolution system.

Identifies:
1. Intra-Email Duplicates (accidental twin attachments in the same email message).
2. Cross-Email Duplicates (accidental resends or repeated attachments).
Provides both interactive CLI resolution prompts and automated daemon policies.
"""

from typing import List, Dict, Any, Optional
import click


class DuplicateAnomalyDetector:
    """Detects duplicate attachments and resolves them interactively or via policy."""

    def __init__(self, mode: str = "interactive"):
        self.mode = mode  # 'interactive', 'auto_dedupe', or 'alert_only'

    @staticmethod
    def detect_intra_message_duplicates(
        attachments: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Identify if a single email contains multiple attachments with identical hashes.
        
        Example: The sender intended to attach 'Invoice.pdf' and 'Spec.pdf',
        but mistakenly attached 'Invoice.pdf' twice.
        """
        seen_hashes: Dict[str, Dict[str, Any]] = {}
        duplicates: List[Dict[str, Any]] = []

        for att in attachments:
            sha256 = att.get("sha256")
            if not sha256:
                continue

            if sha256 in seen_hashes:
                first_att = seen_hashes[sha256]
                duplicates.append({
                    "original_slot": first_att["filename"],
                    "duplicate_slot": att["filename"],
                    "sha256": sha256,
                    "size_bytes": att.get("size_bytes", 0)
                })
            else:
                seen_hashes[sha256] = att

        return duplicates

    def resolve_duplicate_interactive(
        self,
        sender_email: str,
        subject: str,
        filename: str,
        sha256: str,
        is_intra_message: bool = False
    ) -> str:
        """Present an interactive prompt to the user to choose resolution action.
        
        Returns one of: 'KEEP_FIRST', 'KEEP_BOTH', or 'SKIP'
        """
        if self.mode != "interactive":
            return "KEEP_FIRST"  # Default policy for automated mode

        click.echo("")
        click.secho("=" * 70, fg="yellow", bold=True)
        if is_intra_message:
            click.secho("[!] ANOMALY: SENDER ATTACHED DUPLICATE FILE TWICE IN SAME EMAIL", fg="yellow", bold=True)
        else:
            click.secho("[!] NOTICE: RECENT RESEND / DUPLICATE ATTACHMENT DETECTED", fg="cyan", bold=True)
        
        click.echo(f"  From:     {sender_email}")
        click.echo(f"  Subject:  {subject}")
        click.echo(f"  File:     {filename}")
        click.echo(f"  SHA-256:  {sha256[:16]}...")
        click.echo("-" * 70)
        click.echo("What would you like to do with this duplicate attachment?")
        click.echo("  [1] Keep single copy & log warning in audit ledger (Recommended)")
        click.echo("  [2] Keep both copies with deduplication link")
        click.echo("  [3] Skip processing this duplicate file completely")
        
        choice = click.prompt(
            "Select action",
            type=click.Choice(["1", "2", "3"]),
            default="1",
            show_choices=True
        )

        resolution_map = {
            "1": "KEEP_FIRST",
            "2": "KEEP_BOTH",
            "3": "SKIP"
        }
        click.secho(f"-> Selected: {resolution_map[choice]}", fg="green")
        click.secho("=" * 70, fg="yellow")
        return resolution_map[choice]
