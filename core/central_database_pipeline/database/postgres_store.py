"""
Module: database/postgres_store.py
Description: Manages PostgreSQL storage (`job_ads` + `dropped_ads`) and JSONL handoff
files (`processed.jsonl`, `normalized_records.jsonl`, `vdb_payloads.jsonl`, `dropped.jsonl`).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from schema import JobAd

logger = logging.getLogger("fanoos.database")

try:
    import psycopg as pg_driver
except ImportError:
    try:
        import psycopg2 as pg_driver
    except ImportError:
        pg_driver = None


CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS job_ads (
    document_id VARCHAR(128) PRIMARY KEY,
    collector VARCHAR(64) NOT NULL,
    source_type VARCHAR(32) NOT NULL,
    source_url TEXT,
    is_expired BOOLEAN DEFAULT FALSE,
    organization TEXT,
    role_title TEXT NOT NULL,
    role_normalized TEXT NOT NULL,
    domain TEXT NOT NULL,
    seniority JSONB NOT NULL DEFAULT '[]'::jsonb,
    skills_required JSONB NOT NULL DEFAULT '[]'::jsonb,
    skills_preferred JSONB NOT NULL DEFAULT '[]'::jsonb,
    ai_skills JSONB NOT NULL DEFAULT '[]'::jsonb,
    tools JSONB NOT NULL DEFAULT '[]'::jsonb,
    soft_skills JSONB NOT NULL DEFAULT '[]'::jsonb,
    employment_type JSONB,
    work_mode JSONB NOT NULL DEFAULT '[]'::jsonb,
    location TEXT,
    experience_years_min INTEGER,
    language JSONB NOT NULL DEFAULT '[]'::jsonb,
    salary_min BIGINT,
    salary_max BIGINT,
    salary_currency VARCHAR(32),
    benefits JSONB NOT NULL DEFAULT '[]'::jsonb,
    education JSONB NOT NULL DEFAULT '[]'::jsonb,
    education_degree JSONB NOT NULL DEFAULT '[]'::jsonb,
    education_field JSONB NOT NULL DEFAULT '[]'::jsonb,
    military_service_requirement JSONB NOT NULL DEFAULT '[]'::jsonb,
    gender_requirement JSONB NOT NULL DEFAULT '[]'::jsonb,
    age_min INTEGER,
    age_max INTEGER,
    company_size_min INTEGER,
    company_size_max INTEGER,
    industry TEXT,
    compensation_type TEXT,
    internship_duration_months INTEGER,
    source_date DATE,
    collected_at DATE NOT NULL,
    text TEXT NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    evidence_notes JSONB NOT NULL DEFAULT '[]'::jsonb,
    candidate_new_skill JSONB NOT NULL DEFAULT '[]'::jsonb,
    version VARCHAR(32) NOT NULL,
    raw_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dropped_ads (
    document_id VARCHAR(128) PRIMARY KEY,
    collector VARCHAR(64),
    source_url TEXT,
    stage_failed VARCHAR(32) NOT NULL,
    rounds_attempted INTEGER NOT NULL,
    drop_reason TEXT NOT NULL,
    raw_text TEXT,
    last_candidate_json JSONB,
    dropped_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        f.flush()


def build_vdb_payload(job_ad: JobAd) -> dict[str, Any]:
    """Formats a normalized `JobAd` into the exact `VectorStorePayload` contract for Qdrant/RAG."""
    d = job_ad.model_dump(mode="json")
    return {
        "document_id": d["document_id"],
        "text": d["text"],
        "role_normalized": d["role_normalized"],
        "organization": d.get("organization") or "",
        "seniority": d.get("seniority") or [],
        "employment_type": d.get("employment_type") or [],
        "work_mode": d.get("work_mode") or [],
        "skills_required": d.get("skills_required") or [],
        "tools": d.get("tools") or [],
        "skills_preferred": d.get("skills_preferred") or [],
        "domain": d.get("domain"),
        "location": d.get("location"),
        "salary_currency": d.get("salary_currency"),
        "collected_at": d.get("collected_at"),
        "education": ", ".join(d.get("education") or []) or None,
        "industry": d.get("industry"),
        "experience_years_min": d.get("experience_years_min"),
        "salary_min": d.get("salary_min"),
        "salary_max": d.get("salary_max"),
        "internship_duration_months": d.get("internship_duration_months"),
    }


class FanoosDataStore:
    def __init__(self, data_dir: Path | None = None, pg_dsn: str | None = None) -> None:
        self.data_dir = Path(data_dir or (Path(__file__).resolve().parent / "artifacts"))
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.processed_jsonl = self.data_dir / "processed.jsonl"
        self.normalized_jsonl = self.data_dir / "normalized_records.jsonl"
        self.vdb_jsonl = self.data_dir / "vdb_payloads.jsonl"
        self.dropped_jsonl = self.data_dir / "dropped.jsonl"

        self.pg_dsn = pg_dsn or os.getenv("POSTGRES_DSN") or os.getenv("DATABASE_URL")
        self._conn = None

        if self.pg_dsn:
            if pg_driver is None:
                raise RuntimeError("POSTGRES_DSN is set, but `psycopg` / `psycopg2-binary` is not installed.")
            self._conn = pg_driver.connect(self.pg_dsn)
            with self._conn.cursor() as cur:
                cur.execute(CREATE_TABLES_SQL)
            self._conn.commit()
            logger.info("Connected to PostgreSQL (`job_ads` & `dropped_ads` ready).")
        else:
            logger.warning("POSTGRES_DSN not set in .env; saving records to JSONL artifacts in %s.", self.data_dir)

    def save_stage1_processed(self, job_ad: JobAd) -> None:
        _append_jsonl(self.processed_jsonl, job_ad.model_dump(mode="json"))

    def save_final_normalized(
        self,
        job_ad: JobAd,
        source_url: str | None = None,
        is_expired: bool = False,
    ) -> None:
        payload = job_ad.model_dump(mode="json")
        _append_jsonl(self.normalized_jsonl, payload)
        _append_jsonl(self.vdb_jsonl, build_vdb_payload(job_ad))

        if not self._conn:
            return

        sql = """
        INSERT INTO job_ads (
            document_id, collector, source_type, source_url, is_expired,
            organization, role_title, role_normalized, domain,
            seniority, skills_required, skills_preferred, ai_skills, tools, soft_skills,
            employment_type, work_mode, location, experience_years_min, language,
            salary_min, salary_max, salary_currency, benefits,
            education, education_degree, education_field,
            military_service_requirement, gender_requirement,
            age_min, age_max, company_size_min, company_size_max,
            industry, compensation_type, internship_duration_months,
            source_date, collected_at, text, content_hash,
            evidence_notes, candidate_new_skill, version, raw_json, updated_at
        ) VALUES (
            %(document_id)s, %(collector)s, %(source_type)s, %(source_url)s, %(is_expired)s,
            %(organization)s, %(role_title)s, %(role_normalized)s, %(domain)s,
            %(seniority)s, %(skills_required)s, %(skills_preferred)s, %(ai_skills)s, %(tools)s, %(soft_skills)s,
            %(employment_type)s, %(work_mode)s, %(location)s, %(experience_years_min)s, %(language)s,
            %(salary_min)s, %(salary_max)s, %(salary_currency)s, %(benefits)s,
            %(education)s, %(education_degree)s, %(education_field)s,
            %(military_service_requirement)s, %(gender_requirement)s,
            %(age_min)s, %(age_max)s, %(company_size_min)s, %(company_size_max)s,
            %(industry)s, %(compensation_type)s, %(internship_duration_months)s,
            %(source_date)s, %(collected_at)s, %(text)s, %(content_hash)s,
            %(evidence_notes)s, %(candidate_new_skill)s, %(version)s, %(raw_json)s, NOW()
        )
        ON CONFLICT (document_id) DO UPDATE SET
            role_normalized = EXCLUDED.role_normalized,
            domain = EXCLUDED.domain,
            skills_required = EXCLUDED.skills_required,
            skills_preferred = EXCLUDED.skills_preferred,
            ai_skills = EXCLUDED.ai_skills,
            tools = EXCLUDED.tools,
            soft_skills = EXCLUDED.soft_skills,
            salary_min = EXCLUDED.salary_min,
            salary_max = EXCLUDED.salary_max,
            salary_currency = EXCLUDED.salary_currency,
            raw_json = EXCLUDED.raw_json,
            updated_at = NOW();
        """

        def _j(val: Any) -> str | None:
            return json.dumps(val, ensure_ascii=False) if val is not None else None

        params = {
            **payload,
            "source_url": source_url,
            "is_expired": is_expired,
            "seniority": _j(payload["seniority"]),
            "skills_required": _j(payload["skills_required"]),
            "skills_preferred": _j(payload["skills_preferred"]),
            "ai_skills": _j(payload["ai_skills"]),
            "tools": _j(payload["tools"]),
            "soft_skills": _j(payload["soft_skills"]),
            "employment_type": _j(payload["employment_type"]),
            "work_mode": _j(payload["work_mode"]),
            "language": _j(payload["language"]),
            "benefits": _j(payload["benefits"]),
            "education": _j(payload["education"]),
            "education_degree": _j(payload["education_degree"]),
            "education_field": _j(payload["education_field"]),
            "military_service_requirement": _j(payload["military_service_requirement"]),
            "gender_requirement": _j(payload["gender_requirement"]),
            "evidence_notes": _j(payload["evidence_notes"]),
            "candidate_new_skill": _j(payload["candidate_new_skill"]),
            "raw_json": _j(payload),
        }

        with self._conn.cursor() as cur:
            cur.execute(sql, params)
        self._conn.commit()
        logger.info("Saved canonical JobAd '%s' to PostgreSQL.", job_ad.document_id)

    def save_dropped_ad(
        self,
        document_id: str,
        collector: str,
        stage_failed: str,
        rounds_attempted: int,
        drop_reason: list[str] | str,
        raw_text: str,
        source_url: str | None = None,
        last_candidate: dict | None = None,
    ) -> None:
        reason_str = "; ".join(drop_reason) if isinstance(drop_reason, list) else str(drop_reason)
        dropped_record = {
            "document_id": document_id,
            "collector": collector,
            "source_url": source_url,
            "stage_failed": stage_failed,
            "rounds_attempted": rounds_attempted,
            "drop_reason": reason_str,
            "raw_text": raw_text,
            "last_candidate": last_candidate,
            "dropped_at": datetime.now(timezone.utc).isoformat(),
        }
        _append_jsonl(self.dropped_jsonl, dropped_record)

        if not self._conn:
            return

        sql = """
        INSERT INTO dropped_ads (
            document_id, collector, source_url, stage_failed,
            rounds_attempted, drop_reason, raw_text, last_candidate_json, dropped_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (document_id) DO UPDATE SET
            stage_failed = EXCLUDED.stage_failed,
            rounds_attempted = EXCLUDED.rounds_attempted,
            drop_reason = EXCLUDED.drop_reason,
            last_candidate_json = EXCLUDED.last_candidate_json,
            dropped_at = NOW();
        """
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    document_id,
                    collector,
                    source_url,
                    stage_failed,
                    rounds_attempted,
                    reason_str,
                    raw_text,
                    json.dumps(last_candidate, ensure_ascii=False) if last_candidate else None,
                ),
            )
        self._conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()