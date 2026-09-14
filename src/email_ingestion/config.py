"""Configuration management for the Enterprise Email Ingestion Engine.

This module defines strongly-typed configuration models using Pydantic Settings.
Configuration is loaded from `config.yaml`, environment variables, or `.env` files.
"""

from pathlib import Path
from typing import List, Optional
import os
import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class StorageSettings(BaseModel):
    """Configuration for local storage and folder conventions."""
    download_dir: Path = Field(
        default=Path("Auto_download_email"),
        description="Root directory where organized attachments and context sidecars are saved."
    )
    quarantine_dir: Path = Field(
        default=Path("Auto_download_email/quarantine"),
        description="Directory where suspicious or mismatched files are isolated."
    )
    staging_dir: Path = Field(
        default=Path("Auto_download_email/.staging"),
        description="Temporary directory used for atomic two-phase streaming writes."
    )
    enable_content_addressable_storage: bool = Field(
        default=True,
        description="Store unique file blobs by SHA-256 hash and link to user directories."
    )


class SecuritySettings(BaseModel):
    """Configuration for security checks and MIME filtering."""
    filter_signatures: bool = Field(
        default=True,
        description="Filter out decorative signature logos and social media icons."
    )
    signature_max_size_bytes: int = Field(
        default=15360,  # 15 KB
        description="Maximum file size threshold for identifying inline signature images."
    )
    verify_magic_headers: bool = Field(
        default=True,
        description="Sniff real file magic bytes (using puremagic) to prevent extension spoofing."
    )
    quarantine_on_mismatch: bool = Field(
        default=True,
        description="Rename and isolate files if actual magic bytes differ from stated extension."
    )
    max_zip_decompression_ratio: float = Field(
        default=10.0,
        description="Maximum allowed uncompressed-to-compressed size ratio for zip bomb defense."
    )
    max_attachment_size_bytes: int = Field(
        default=104857600,  # 100 MB
        description="Maximum single attachment size allowed for processing."
    )


class IntelligenceSettings(BaseModel):
    """Configuration for context sidecars, similarity scoring, and duplicate anomaly detection."""
    generate_context_sidecars: bool = Field(
        default=True,
        description="Create email_context.md and context.json alongside each download."
    )
    fuzzy_similarity_threshold: float = Field(
        default=0.80,
        description="Similarity ratio (0.0 to 1.0) above which same-name files are deemed revisions (v2)."
    )
    duplicate_detection_mode: str = Field(
        default="interactive",
        description="Resolution strategy for duplicate attachments: 'interactive', 'auto_dedupe', or 'alert_only'."
    )


class DatabaseSettings(BaseModel):
    """Configuration for the ACID state ledger."""
    db_url: str = Field(
        default="sqlite:///email_ingestion_state.db",
        description="SQLAlchemy database connection URL (SQLite or PostgreSQL)."
    )


class ProviderCredentials(BaseModel):
    """Generic holder for provider-specific credentials."""
    enabled: bool = False
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    tenant_id: Optional[str] = None  # Microsoft only
    credentials_json: Optional[str] = None  # Google service account or client secret JSON
    user_email: Optional[str] = None


class IMAPCredentials(BaseModel):
    """Configuration for standard IMAP/IMAP-SSL mailbox connector."""
    enabled: bool = False
    host: Optional[str] = None
    port: int = 993
    username: Optional[str] = None
    password: Optional[str] = None
    mailbox: str = "INBOX"
    use_ssl: bool = True


class FilterSettings(BaseModel):
    """Configuration for email and sender filtering / exclusion rules."""
    enabled: bool = Field(default=True, description="Enable sender filtering and exclusion logic.")
    excluded_senders: List[str] = Field(
        default_factory=list,
        description="List of email addresses, domain wildcards (*@domain.com), or glob patterns to exclude."
    )
    exclude_file: Optional[str] = Field(
        default="excluded_senders.txt",
        description="Optional file path containing excluded senders or patterns, one per line."
    )


class EngineSettings(BaseSettings):
    """Master application configuration model."""
    environment: str = Field(default="development", description="Runtime environment: development or production")
    storage: StorageSettings = Field(default_factory=StorageSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    intelligence: IntelligenceSettings = Field(default_factory=IntelligenceSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    filters: FilterSettings = Field(default_factory=FilterSettings)
    
    # Providers
    mock_provider: ProviderCredentials = Field(default_factory=lambda: ProviderCredentials(enabled=True))
    gmail: ProviderCredentials = Field(default_factory=ProviderCredentials)
    microsoft: ProviderCredentials = Field(default_factory=ProviderCredentials)
    imap: IMAPCredentials = Field(default_factory=IMAPCredentials)
    
    # Enabled Plugins
    plugins: List[str] = Field(
        default_factory=lambda: ["ai_summarizer"],
        description="List of plugin identifiers to activate."
    )

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_nested_delimiter="__",
        extra="ignore"
    )

    @classmethod
    def load_from_yaml(cls, yaml_path: Path) -> "EngineSettings":
        """Load settings from a YAML file, with fallback to default values."""
        if not yaml_path.exists():
            return cls()
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls(**data)


# Global configuration loader helper
def get_settings(config_path: Optional[Path] = None) -> EngineSettings:
    """Retrieve engine settings from the preferred config path or default location."""
    if config_path and config_path.exists():
        return EngineSettings.load_from_yaml(config_path)
    
    default_path = Path("config.yaml")
    if default_path.exists():
        return EngineSettings.load_from_yaml(default_path)
    
    return EngineSettings()
