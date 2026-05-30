"""
api/models/db.py — Modèles SQLAlchemy conformes RGPD — Waterflow 2

Deux mondes d'authentification séparés :
  ┌─────────────────────────────────────────────────────────────┐
  │ CLIENTS (collectivités)  →  clé API uniquement             │
  │   - id_client, denomination, adresse_postale, api_key       │
  │   - Périmètre : leurs propres prélèvements & résultats      │
  ├─────────────────────────────────────────────────────────────┤
  │ EXPERTS (analystes / responsable d'exploitation)           │
  │   →  login technique (EXPERT_TOKEN dans env)               │
  │   - Rôle ANALYSTE  : tous prélèvements, dashboards         │
  │   - Rôle EXPLOIT   : supervision, métriques, logs, clés    │
  └─────────────────────────────────────────────────────────────┘

Tables :
  clients          — comptes collectivités
  prelevements     — fiches de prélèvement
  mesures          — valeurs physico-chimiques
  predictions      — résultats modèle ML
  audit_logs       — journal accès RGPD (immuable)
  request_metrics  — métriques performance par route
"""

import os
import uuid
import hashlib
from datetime import datetime, timezone

from sqlalchemy import (
    create_engine, Column, String, Float, Integer,
    Boolean, DateTime, Text, ForeignKey, Index, Enum
)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker
import enum

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///waterflow2.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    echo=False,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── Base ────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


# ── Enums ───────────────────────────────────────────────────────────────────

class ExpertRole(str, enum.Enum):
    """Rôles internes — ne concernent pas les clients."""
    ANALYSTE = "analyste"   # accès données, dashboards, prédictions
    EXPLOIT  = "exploit"    # supervision : métriques, logs, gestion clés


class IngestionSource(str, enum.Enum):
    MANUAL = "manual"   # saisie JSON directe
    OCR    = "ocr"      # extraction fiche PDF/image
    API    = "api"      # dépôt programmatique sans OCR


# ── Clients (collectivités) ──────────────────────────────────────────────────

class Client(Base):
    """
    Compte d'une collectivité cliente.

    Champs visibles / modifiables par les experts :
      - id_client     : identifiant métier lisible (ex: COMM-042)
      - denomination  : nom officiel de la structure
      - adresse       : adresse postale complète
      - actif         : désactivation sans suppression

    Sécurité :
      - La clé API brute n'est JAMAIS stockée : uniquement son hash SHA-256.
      - key_hint (4 premiers chars) permet l'identification dans les logs.
      - Une seule clé active à la fois par client (simplification MVP).
    """
    __tablename__ = "clients"

    id            = Column(String(36),  primary_key=True,
                           default=lambda: str(uuid.uuid4()))
    id_client     = Column(String(64),  unique=True, nullable=False, index=True)
    denomination  = Column(String(256), nullable=False)
    adresse       = Column(Text,        nullable=False)
    actif         = Column(Boolean,     default=True,  nullable=False)
    created_at    = Column(DateTime,    default=utcnow)
    created_by    = Column(String(64),  nullable=True)   # login expert créateur

    # Clé API — une seule active par client
    api_key_hash  = Column(String(64),  unique=True,  nullable=True, index=True)
    api_key_hint  = Column(String(8),   nullable=True)
    key_generated_at = Column(DateTime, nullable=True)

    # RGPD
    rgpd_consent    = Column(Boolean,  default=False)
    rgpd_consent_at = Column(DateTime, nullable=True)
    anonymised_at   = Column(DateTime, nullable=True)

    prelevements = relationship("Prelevement", back_populates="client",
                                cascade="all, delete-orphan")

    @staticmethod
    def hash_key(raw_key: str) -> str:
        return hashlib.sha256(raw_key.encode()).hexdigest()

    def set_api_key(self, raw_key: str) -> None:
        """Hash et stocke une nouvelle clé — l'ancienne est révoquée."""
        self.api_key_hash    = self.hash_key(raw_key)
        self.api_key_hint    = raw_key[:4]
        self.key_generated_at = utcnow()

    def verify_key(self, raw_key: str) -> bool:
        if not self.api_key_hash or not self.actif:
            return False
        candidate = self.hash_key(raw_key)
        return hashlib.compare_digest(candidate, self.api_key_hash)


# ── Prélèvements ─────────────────────────────────────────────────────────────

class Prelevement(Base):
    """Fiche de prélèvement — liée à un client."""
    __tablename__ = "prelevements"

    id               = Column(String(36), primary_key=True,
                               default=lambda: str(uuid.uuid4()))
    client_id        = Column(String(36), ForeignKey("clients.id", ondelete="CASCADE"),
                               nullable=False, index=True)
    date_prelevement = Column(DateTime,  nullable=True)
    lieu             = Column(String(256), nullable=True)
    source           = Column(Enum(IngestionSource), default=IngestionSource.API)
    fichier_nom      = Column(String(256), nullable=True)
    fichier_type     = Column(String(64),  nullable=True)
    ocr_raw_text     = Column(Text,        nullable=True)
    ocr_warnings     = Column(Text,        nullable=True)   # JSON list
    observations     = Column(Text,        nullable=True)
    created_at       = Column(DateTime,    default=utcnow)

    client     = relationship("Client",     back_populates="prelevements")
    mesures    = relationship("Mesure",     back_populates="prelevement",
                               uselist=False, cascade="all, delete-orphan")
    predictions = relationship("Prediction", back_populates="prelevement",
                                cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_prev_client_date", "client_id", "date_prelevement"),
    )


class Mesure(Base):
    """Valeurs physico-chimiques normalisées."""
    __tablename__ = "mesures"

    id              = Column(String(36), primary_key=True,
                              default=lambda: str(uuid.uuid4()))
    prelevement_id  = Column(String(36), ForeignKey("prelevements.id", ondelete="CASCADE"),
                              nullable=False, unique=True, index=True)
    ph              = Column(Float, nullable=True)
    hardness        = Column(Float, nullable=True)
    solids          = Column(Float, nullable=True)
    chloramines     = Column(Float, nullable=True)
    sulfate         = Column(Float, nullable=True)
    conductivity    = Column(Float, nullable=True)
    organic_carbon  = Column(Float, nullable=True)
    trihalomethanes = Column(Float, nullable=True)
    turbidity       = Column(Float, nullable=True)

    prelevement = relationship("Prelevement", back_populates="mesures")

    def to_feature_dict(self) -> dict:
        return {
            "ph":              self.ph,
            "Hardness":        self.hardness,
            "Solids":          self.solids,
            "Chloramines":     self.chloramines,
            "Sulfate":         self.sulfate,
            "Conductivity":    self.conductivity,
            "Organic_carbon":  self.organic_carbon,
            "Trihalomethanes": self.trihalomethanes,
            "Turbidity":       self.turbidity,
        }


class Prediction(Base):
    """Résultat du modèle ML — version tracée pour auditabilité."""
    __tablename__ = "predictions"

    id             = Column(String(36), primary_key=True,
                             default=lambda: str(uuid.uuid4()))
    prelevement_id = Column(String(36), ForeignKey("prelevements.id", ondelete="CASCADE"),
                             nullable=False, index=True)
    potable        = Column(Integer, nullable=False)        # 0 ou 1
    probability    = Column(Float,   nullable=False)
    model_version  = Column(String(64), nullable=True)
    created_at     = Column(DateTime, default=utcnow)

    prelevement = relationship("Prelevement", back_populates="predictions")


# ── Audit & Métriques ────────────────────────────────────────────────────────

class AuditLog(Base):
    """
    Journal d'accès RGPD — immuable par convention.
    actor_type : 'client' | 'expert'
    actor_id   : id_client ou login expert
    """
    __tablename__ = "audit_logs"

    id          = Column(String(36), primary_key=True,
                          default=lambda: str(uuid.uuid4()))
    timestamp   = Column(DateTime,  default=utcnow, index=True)
    actor_type  = Column(String(16), nullable=False)     # 'client' | 'expert'
    actor_id    = Column(String(64), nullable=True,  index=True)
    actor_role  = Column(String(32), nullable=True)      # rôle expert ou 'client'
    ip_address  = Column(String(45), nullable=True)      # pseudonymisée /24
    action      = Column(String(64), nullable=False)
    resource_id = Column(String(36), nullable=True)
    status_code = Column(Integer,    nullable=True)
    detail      = Column(Text,       nullable=True)

    __table_args__ = (Index("ix_audit_actor", "actor_type", "actor_id"),)


class RequestMetric(Base):
    """Métriques de performance brutes — purgées périodiquement."""
    __tablename__ = "request_metrics"

    id          = Column(String(36), primary_key=True,
                          default=lambda: str(uuid.uuid4()))
    timestamp   = Column(DateTime,   default=utcnow, index=True)
    route       = Column(String(128), nullable=False, index=True)
    method      = Column(String(8),   nullable=False)
    status_code = Column(Integer,     nullable=False)
    duration_ms = Column(Float,       nullable=False)
    actor_type  = Column(String(16),  nullable=True)   # 'client' | 'expert'
    actor_hint  = Column(String(16),  nullable=True)   # key_hint ou login expert


def init_db():
    """Crée toutes les tables si elles n'existent pas."""
    Base.metadata.create_all(bind=engine)
