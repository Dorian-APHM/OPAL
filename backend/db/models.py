"""
SQLAlchemy models for the OPAL application database.
"""
from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, Float, JSON, UniqueConstraint
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class CdmConfig(Base):
    """Registered CDM database connections."""
    __tablename__ = "cdm_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
    db_host = Column(String(255), nullable=False)
    db_port = Column(Integer, nullable=False, default=5432)
    db_name = Column(String(255), nullable=False)
    db_user = Column(String(255), nullable=False)
    db_password_encrypted = Column(Text, nullable=False)
    omop_schema = Column(String(255), nullable=False, default="omop_cdm")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AnalysisSnapshot(Base):
    """Versioned analysis snapshots."""
    __tablename__ = "analysis_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cdm_name = Column(String(255), nullable=False, index=True)
    domain = Column(String(100), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    results = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class AnalysisSettings(Base):
    """Per-CDM analysis settings."""
    __tablename__ = "analysis_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cdm_name = Column(String(255), nullable=False, unique=True, index=True)
    omop_schema = Column(String(255), default="omop_cdm")
    top_unmapped_terms = Column(Integer, default=50)
    top_concepts = Column(Integer, default=50)
    max_records_per_person = Column(Integer, default=100)
    max_observation_months = Column(Integer, default=120)
    comparison_alert_threshold = Column(Float, default=5.0)


class Cohort(Base):
    """Saved cohort definitions."""
    __tablename__ = "cohorts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cdm_name = Column(String(255), nullable=False, index=True)
    name = Column(String(500), nullable=False)
    description = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CohortVersion(Base):
    """Versioned cohort criteria & results. Each edit creates a new version."""
    __tablename__ = "cohort_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cohort_id = Column(Integer, nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    criteria_json = Column(JSON, nullable=False)
    generated_sql = Column(Text, default="")
    patient_count = Column(Integer, nullable=True)
    characterization_json = Column(JSON, nullable=True)
    characterized_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class MappingDecision(Base):
    """
    Audit trail for mapping decisions.
    Each row records one decision: approve, modify, reject, or rollback.
    """
    __tablename__ = "mapping_decisions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cdm_name = Column(String(255), nullable=False, index=True)
    domain = Column(String(100), nullable=False, index=True)
    source_value = Column(String(1000), nullable=False)
    source_name = Column(String(1000), default="")
    action = Column(String(50), nullable=False)  # approved, modified, rejected, rolled_back
    target_concept_id = Column(Integer, nullable=True)
    target_concept_name = Column(String(500), default="")
    target_vocabulary_id = Column(String(100), default="")
    previous_concept_id = Column(Integer, nullable=True)
    suggestion_source = Column(String(50), default="")  # exact, relationship, fuzzy, contextual, manual
    confidence_score = Column(Float, nullable=True)
    user = Column(String(255), default="system")
    reason = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class ReferenceCodebook(Base):
    """
    Reference nomenclature entries (CCAM, CIM-10, etc.) loaded from CSV.
    Used to enrich mapping suggestions with descriptive text.
    """
    __tablename__ = "reference_codebooks"
    __table_args__ = (
        UniqueConstraint("name", "code", name="uq_ref_name_code"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, index=True)
    domain = Column(String(100), nullable=False, index=True)
    code = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow)


class SapbertMapping(Base):
    """
    Pre-computed SapBERT mapping suggestions.
    Loaded from sapbert_mapping.py output CSV.
    """
    __tablename__ = "sapbert_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    domain = Column(String(100), nullable=False, index=True)
    source_code = Column(String(255), nullable=False, index=True)
    source_name = Column(Text, default="")
    rank = Column(Integer, nullable=False)
    target_concept_id = Column(Integer, nullable=False)
    target_concept_code = Column(String(255), default="")
    target_concept_name = Column(String(500), default="")
    target_vocabulary_id = Column(String(100), default="")
    similarity = Column(Float, nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
