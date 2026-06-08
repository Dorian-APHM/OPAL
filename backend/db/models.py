"""
SQLAlchemy models for the OPAL application database.
"""
from datetime import datetime, timezone


def _utcnow():
    return datetime.now(timezone.utc)

from sqlalchemy import Boolean, Column, ForeignKey, Index, Integer, String, Text, DateTime, Float, JSON, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship

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
    # Optional per-category schema overrides: {category_key: schema_name}.
    # Categories without an entry fall back to omop_schema.
    schema_categories = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class AnalysisSnapshot(Base):
    """Versioned analysis snapshots."""
    __tablename__ = "analysis_snapshots"
    __table_args__ = (
        Index("ix_snapshots_cdm_domain", "cdm_name", "domain"),
        Index("ix_snapshots_cdm_domain_version", "cdm_name", "domain", "version"),
        UniqueConstraint("cdm_name", "domain", "version", name="uq_snapshot_cdm_domain_version"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    cdm_name = Column(String(255), nullable=False, index=True)
    domain = Column(String(100), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    results = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class AnalysisSettings(Base):
    """Per-CDM analysis settings."""
    __tablename__ = "analysis_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cdm_name = Column(String(255), nullable=False, unique=True, index=True)
    omop_schema = Column(String(255), default="omop_cdm")
    # Optional per-category schema overrides: {category_key: schema_name}.
    # Overrides the matching entries on CdmConfig.schema_categories.
    schema_categories = Column(JSON, nullable=True)
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
    created_by = Column(String(255), nullable=False, default="system", index=True)
    shared_with_all = Column(Integer, default=0)  # 0=private, 1=public (Integer for SQLite compat)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    # Cascade relationships
    versions = relationship("CohortVersion", cascade="all, delete-orphan", passive_deletes=True,
                            primaryjoin="Cohort.id == foreign(CohortVersion.cohort_id)")
    shares = relationship("CohortShare", cascade="all, delete-orphan", passive_deletes=True,
                          primaryjoin="Cohort.id == foreign(CohortShare.cohort_id)")


class CohortVersion(Base):
    """Versioned cohort criteria & results. Each edit creates a new version."""
    __tablename__ = "cohort_versions"
    __table_args__ = (
        Index("ix_cohort_versions_cohort_version", "cohort_id", "version"),
        UniqueConstraint("cohort_id", "version", name="uq_cohort_version"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    cohort_id = Column(Integer, ForeignKey("cohorts.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    criteria_json = Column(JSON, nullable=False)
    generated_sql = Column(Text, default="")
    patient_count = Column(Integer, nullable=True)
    characterization_json = Column(JSON, nullable=True)
    characterized_at = Column(DateTime, nullable=True)
    pathways_json = Column(JSON, nullable=True)
    pathways_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class MappingDecision(Base):
    """
    Audit trail for mapping decisions.
    Each row records one decision: approve, modify, reject, or rollback.
    """
    __tablename__ = "mapping_decisions"
    __table_args__ = (
        Index("ix_mapping_decisions_cdm_domain", "cdm_name", "domain"),
        Index("ix_mapping_decisions_cdm_domain_sv", "cdm_name", "domain", "source_value"),
    )

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
    created_at = Column(DateTime, default=_utcnow)


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
    uploaded_at = Column(DateTime, default=_utcnow)


class SapbertMapping(Base):
    """
    Pre-computed SapBERT mapping suggestions.

    Generated in-app by the opal-sapbert service at Source Value Cache build time
    (keyed per CDM). Legacy rows loaded from the sapbert_mapping.py output CSV have
    cdm_name = NULL.
    """
    __tablename__ = "sapbert_mappings"
    __table_args__ = (
        # Per-CDM suggestion lookup; the (cdm_name, domain) prefix also serves
        # per-domain queries. Covers the legacy NULL-cdm_name rows too.
        Index("ix_sapbert_lookup", "cdm_name", "domain", "source_code"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    # NULL for legacy CSV-uploaded rows; set per CDM for in-app builds.
    cdm_name = Column(String(255), nullable=True)
    domain = Column(String(100), nullable=False, index=True)
    source_code = Column(String(255), nullable=False, index=True)
    source_name = Column(Text, default="")
    rank = Column(Integer, nullable=False)
    target_concept_id = Column(Integer, nullable=False)
    target_concept_code = Column(String(255), default="")
    target_concept_name = Column(String(500), default="")
    target_vocabulary_id = Column(String(100), default="")
    similarity = Column(Float, nullable=False)
    uploaded_at = Column(DateTime, default=_utcnow)


class SapbertDomainState(Base):
    """Per-(CDM, domain) SapBERT build status + the persistent suggestion toggle.

    Tracks which (cdm, domain) have SapBERT mappings built (`status`/`row_count`)
    and whether SapBERT suggestions are enabled for that domain (`enabled`). Drives
    the Settings build progress and the per-domain on/off toggle in mapping
    suggestions. A domain is "available" to toggle once it has been built here.
    """
    __tablename__ = "sapbert_domain_state"
    __table_args__ = (
        UniqueConstraint("cdm_name", "domain", name="uq_sapbert_domain_state_cdm_domain"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    cdm_name = Column(String(255), nullable=False, index=True)
    domain = Column(String(100), nullable=False)
    row_count = Column(Integer, default=0)
    status = Column(String(50), nullable=False, default="pending")  # pending|running|done|error
    enabled = Column(Boolean, nullable=False, default=True)
    error_message = Column(Text, nullable=True)
    built_at = Column(DateTime, nullable=True)


class ConceptSet(Base):
    """Reusable concept sets (groups of concepts)."""
    __tablename__ = "concept_sets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(500), nullable=False)
    cdm_name = Column(String(255), nullable=False, index=True)
    domain = Column(String(100), nullable=True)
    description = Column(Text, default="")
    concepts_json = Column(Text, nullable=False)
    created_by = Column(String(255), default="system")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class IncidenceAnalysis(Base):
    """Saved incidence rate analyses."""
    __tablename__ = "incidence_analyses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cdm_name = Column(String(255), nullable=False, index=True)
    name = Column(String(500), nullable=False)
    target_cohort_id = Column(Integer, nullable=False)
    outcome_cohort_id = Column(Integer, nullable=False)
    parameters_json = Column(Text, default="{}")
    results_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class EstimationAnalysis(Base):
    """Saved estimation analyses (Kaplan-Meier, etc.)."""
    __tablename__ = "estimation_analyses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cdm_name = Column(String(255), nullable=False, index=True)
    name = Column(String(500), nullable=False)
    analysis_type = Column(String(50), nullable=False, default="kaplan_meier")
    target_cohort_id = Column(Integer, nullable=False)
    outcome_cohort_id = Column(Integer, nullable=False)
    parameters_json = Column(Text, default="{}")
    results_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class CdmAccess(Base):
    """Per-user CDM access control. When no rows exist for a CDM, it's open to all."""
    __tablename__ = "cdm_access"
    __table_args__ = (
        UniqueConstraint("cdm_name", "username", name="uq_cdm_access"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    cdm_name = Column(String(255), nullable=False, index=True)
    username = Column(String(255), nullable=False, index=True)
    granted_by = Column(String(255), default="admin")
    created_at = Column(DateTime, default=_utcnow)


class CdmGroupAccess(Base):
    """Per-group CDM access control. Grants all members of a user group access to a CDM."""
    __tablename__ = "cdm_group_access"
    __table_args__ = (
        UniqueConstraint("cdm_name", "group_name", name="uq_cdm_group_access"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    cdm_name = Column(String(255), nullable=False, index=True)
    group_name = Column(String(255), nullable=False, index=True)
    granted_by = Column(String(255), default="admin")
    created_at = Column(DateTime, default=_utcnow)


class UserFavorite(Base):
    """User favorites (cohorts, concepts, queries, etc.)."""
    __tablename__ = "user_favorites"
    __table_args__ = (
        UniqueConstraint("username", "item_type", "item_id", name="uq_user_fav"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(255), nullable=False, index=True)
    item_type = Column(String(50), nullable=False)  # cohort, concept, query, cdm
    item_id = Column(String(500), nullable=False)  # id or identifier
    item_label = Column(String(500), default="")
    item_meta = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class SavedQuery(Base):
    """Saved SQL queries for the SQL Editor."""
    __tablename__ = "saved_queries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cdm_name = Column(String(255), nullable=False, index=True)
    name = Column(String(500), nullable=False)
    sql = Column(Text, nullable=False)
    description = Column(Text, default="")
    created_by = Column(String(255), default="system")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class Notification(Base):
    """In-app notifications."""
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_read", "username", "read"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(255), nullable=False, index=True)
    type = Column(String(50), nullable=False)  # mapping_review, quality_done, cohort_shared, access_request
    title = Column(String(500), nullable=False)
    message = Column(Text, default="")
    link = Column(String(500), default="")  # frontend route to navigate to
    item_id = Column(String(500), nullable=True, index=True)  # identifies the specific element (domain name, cohort id, etc.)
    read = Column(Integer, default=0)  # 0=unread, 1=read (using Integer for SQLite compat)
    target_role = Column(String(50), nullable=True, index=True)  # if set, visible to all users with this role
    created_at = Column(DateTime, default=_utcnow)


class NotificationPreference(Base):
    """Per-user notification preferences. Users can mute specific notification types."""
    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint("username", "notif_type", name="uq_notif_pref"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(255), nullable=False, index=True)
    notif_type = Column(String(50), nullable=False)  # e.g. "quality_done", "cohort_shared"
    enabled = Column(Integer, default=1)  # 1=enabled, 0=muted
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class CohortTemplate(Base):
    """Pre-defined cohort templates."""
    __tablename__ = "cohort_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(500), nullable=False)
    category = Column(String(100), nullable=False, default="General")  # e.g. Cardiology, Endocrinology
    description = Column(Text, default="")
    criteria_json = Column(JSON, nullable=False)
    author = Column(String(255), default="system")
    created_at = Column(DateTime, default=_utcnow)


class CohortShare(Base):
    """Tracks who a cohort is shared with (individual user or group)."""
    __tablename__ = "cohort_shares"
    __table_args__ = (
        UniqueConstraint("cohort_id", "share_type", "share_target", name="uq_cohort_share"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    cohort_id = Column(Integer, ForeignKey("cohorts.id", ondelete="CASCADE"), nullable=False, index=True)
    share_type = Column(String(20), nullable=False)  # "user" or "group"
    share_target = Column(String(255), nullable=False)  # username or group name
    shared_by = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class UserGroup(Base):
    """Custom user groups for sharing."""
    __tablename__ = "user_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
    description = Column(Text, default="")
    created_by = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=_utcnow)

    members = relationship("UserGroupMember", cascade="all, delete-orphan", passive_deletes=True,
                           primaryjoin="UserGroup.name == foreign(UserGroupMember.group_name)")


class UserGroupMember(Base):
    """Members of a user group."""
    __tablename__ = "user_group_members"
    __table_args__ = (
        UniqueConstraint("group_name", "username", name="uq_group_member"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_name = Column(String(255), nullable=False, index=True)
    username = Column(String(255), nullable=False, index=True)
    added_by = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class SourceValueCache(Base):
    """Cached distinct source values with counts, stored in app DB for fast search."""
    __tablename__ = "source_value_cache"
    __table_args__ = (
        Index("ix_svc_cdm_domain", "cdm_name", "domain"),
        Index("ix_svc_search", "cdm_name", "domain", "source_value"),
        Index("ix_svc_search_atc", "cdm_name", "domain", "source_atc"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    cdm_name = Column(String(255), nullable=False)
    domain = Column(String(100), nullable=False)
    source_value = Column(String(1000), nullable=False)
    source_name = Column(String(1000), nullable=True, default="")
    source_atc = Column(String(255), nullable=True, default="")
    n_records = Column(Integer, nullable=False, default=0)
    n_persons = Column(Integer, nullable=False, default=0)
    mapped_concept_id = Column(Integer, nullable=True)
    mapped_concept_name = Column(String(500), nullable=True, default="")
    mapped_vocabulary_id = Column(String(100), nullable=True, default="")
    mapped_standard_concept = Column(String(1), nullable=True)


class AtcLabel(Base):
    """ATC code -> class name, per CDM, for DISPLAY only (cohort-LLM group titles).

    A Drug concept-set group is keyed by its ATC code (e.g. B01AA). Showing a random
    member's product label as the group title is confusing ("WARFARINE…" for the whole
    vitamin-K-antagonist class). This flat map (harvested from the CDM's own OMOP
    `concept` ATC vocabulary, names often English) lets the retriever title each group
    with its class name. Display only — NOT used for embedding or matching, so the
    language of the label has no impact on retrieval quality.
    """
    __tablename__ = "atc_labels"
    __table_args__ = (
        UniqueConstraint("cdm_name", "atc_code", name="uq_atc_label_cdm_code"),
        Index("ix_atc_label_cdm", "cdm_name"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    cdm_name = Column(String(255), nullable=False)
    atc_code = Column(String(16), nullable=False)
    label = Column(String(512), nullable=False)


class SourceValueCacheStatus(Base):
    """Tracks cache population status per CDM/domain."""
    __tablename__ = "source_value_cache_status"
    __table_args__ = (
        UniqueConstraint("cdm_name", "domain", name="uq_svc_status_cdm_domain"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    cdm_name = Column(String(255), nullable=False, index=True)
    domain = Column(String(100), nullable=False)
    row_count = Column(Integer, default=0)
    status = Column(String(50), nullable=False, default="pending")
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)


class AccessRequest(Base):
    """
    Self-service sign-up requests awaiting admin approval.
    """
    __tablename__ = "access_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(255), nullable=False, index=True)
    email = Column(String(500), nullable=True, default="")
    first_name = Column(String(255), nullable=True, default="")
    last_name = Column(String(255), nullable=True, default="")
    requested_role = Column(String(100), nullable=False)  # admin, data-manager, chercheur, medecin
    status = Column(String(50), nullable=False, default="pending")  # pending, approved, rejected
    reviewed_by = Column(String(255), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class LineageDoc(Base):
    """Parsed ETL lineage documentation per CDM."""
    __tablename__ = "lineage_docs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cdm_name = Column(String(255), nullable=False, unique=True, index=True)
    filename = Column(String(500), nullable=False)
    lineage_json = Column(JSON, nullable=False)
    uploaded_by = Column(String(255), default="system")
    uploaded_at = Column(DateTime, default=_utcnow)


class MappingApplyLog(Base):
    """
    Tracks each mapping application (UPDATE) on a CDM clinical table.
    Allows rollback by batch_id.
    """
    __tablename__ = "mapping_apply_log"
    __table_args__ = (
        Index("ix_mapping_apply_batch", "batch_id"),
        Index("ix_mapping_apply_cdm_domain", "target_cdm_name", "domain"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(String(64), nullable=False, index=True)
    source_cdm_name = Column(String(255), nullable=False)
    target_cdm_name = Column(String(255), nullable=False)
    domain = Column(String(100), nullable=False)
    table_name = Column(String(100), nullable=False)
    column_name = Column(String(100), nullable=False)
    source_value = Column(String(1000), nullable=False)
    previous_concept_id = Column(Integer, nullable=True)
    new_concept_id = Column(Integer, nullable=False)
    row_count = Column(Integer, nullable=False, default=0)
    applied_by = Column(String(255), nullable=False, default="system")
    applied_at = Column(DateTime, default=_utcnow)
    rolled_back = Column(Integer, nullable=False, default=0)  # 0=active, 1=rolled back


class CohortLlmConfig(Base):
    """Instance-wide cohort-LLM connection (singleton row, id=1).

    Used in 'on-premise' mode: the admin enters their OpenAI-compatible LLM endpoint
    in the Settings UI. The API key is stored Fernet-encrypted (utils/crypto) and is
    never returned in clear by the API. Empty/absent -> the embedded model is used.
    """
    __tablename__ = "cohort_llm_config"

    id = Column(Integer, primary_key=True, default=1)
    base_url = Column(String(1000), nullable=True)
    model = Column(String(255), nullable=True)
    api_key_encrypted = Column(Text, nullable=True)
    updated_by = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
