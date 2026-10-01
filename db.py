import sqlite3
import os
import json
import pandas as pd
from quality import canonical_company, canonical_title

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jobs.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS jobs (
        job_id TEXT PRIMARY KEY,
        site TEXT,
        job_url TEXT,
        job_url_direct TEXT,
        title TEXT,
        company TEXT,
        location TEXT,
        date_posted TEXT,
        job_type TEXT,
        description TEXT,
        is_remote BOOLEAN,
        skills TEXT,
        experience_range TEXT,
        score INTEGER DEFAULT 0,
        status TEXT DEFAULT 'scraped',
        evidence TEXT,
        matching_notes TEXT,
        tailored_resume_path TEXT,
        tailored_cover_letter_path TEXT,
        tailored_resume_pdf_path TEXT,
        tailored_cover_letter_pdf_path TEXT,
        role_fit_score INTEGER DEFAULT 0,
        company_quality_score INTEGER DEFAULT 0,
        evidence_quality_score INTEGER DEFAULT 0,
        freshness_score INTEGER DEFAULT 0,
        directness_score INTEGER DEFAULT 0,
        match_components TEXT DEFAULT '{}',
        recommendation_status TEXT DEFAULT 'discovered',
        canonical_job_id TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ats_boards (
        ats TEXT NOT NULL,
        board_slug TEXT NOT NULL,
        source TEXT DEFAULT 'discovered',
        last_scraped TIMESTAMP,
        job_count INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (ats, board_slug)
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ats_boards_active ON ats_boards (is_active)")

    # Add columns when upgrading an existing local database created by an older version.
    for column, definition in (
        ("tailored_resume_pdf_path", "TEXT"),
        ("tailored_cover_letter_pdf_path", "TEXT"),
        ("role_fit_score", "INTEGER DEFAULT 0"),
        ("company_quality_score", "INTEGER DEFAULT 0"),
        ("evidence_quality_score", "INTEGER DEFAULT 0"),
        ("freshness_score", "INTEGER DEFAULT 0"),
        ("directness_score", "INTEGER DEFAULT 0"),
        ("match_components", "TEXT DEFAULT '{}'"),
        ("recommendation_status", "TEXT DEFAULT 'discovered'"),
        ("canonical_job_id", "TEXT"),
    ):
        try:
            cursor.execute(f"ALTER TABLE jobs ADD COLUMN {column} {definition}")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise
    cursor.execute("SELECT job_id, company, title FROM jobs WHERE canonical_job_id IS NULL OR canonical_job_id = ''")
    for row in cursor.fetchall():
        cursor.execute(
            "UPDATE jobs SET canonical_job_id = ? WHERE job_id = ?",
            (f"{canonical_company(row['company'])}|{canonical_title(row['title'])}", row['job_id']),
        )
    sync_shortlisted_rankings(conn)
    conn.commit()
    conn.close()

def add_jobs(df: pd.DataFrame):
    if df.empty:
        return 0
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    inserted_count = 0
    
    for _, row in df.iterrows():
        job_id = str(row.get('job_id') or row.get('id') or '')
        if not job_id:
            continue
            
        # Clean direct URL or fallback to main job url
        job_url = row.get('job_url', '')
        job_url_direct = row.get('job_url_direct', '')
        title = str(row.get('title', '')).strip()
        company = str(row.get('company', '')).strip()
        
        # Deduplication checks
        # 1. Check by job_id first
        cursor.execute("SELECT 1 FROM jobs WHERE job_id = ?", (job_id,))
        if cursor.fetchone():
            continue
            
        # 2. Check by direct URL or job_url if available
        if job_url_direct:
            cursor.execute("SELECT 1 FROM jobs WHERE job_url_direct = ? OR job_url = ?", (job_url_direct, job_url_direct))
            if cursor.fetchone():
                continue
        if job_url:
            cursor.execute("SELECT 1 FROM jobs WHERE job_url = ?", (job_url,))
            if cursor.fetchone():
                continue

        # 3. Check duplicate (title + company) posted within the active database to prevent repost duplicates.
        # Prefer a direct ATS record over an aggregator record when both describe the
        # same role, so the pipeline keeps the canonical apply URL and description.
        if title and company and company.lower() not in ["none", ""]:
            cursor.execute(
                "SELECT job_id, site, status FROM jobs "
                "WHERE lower(title) = lower(?) AND lower(company) = lower(?) LIMIT 1",
                (title, company),
            )
            duplicate = cursor.fetchone()
            if not duplicate:
                cursor.execute(
                    "SELECT job_id, site, status FROM jobs WHERE canonical_job_id = ? LIMIT 1",
                    (f"{canonical_company(company)}|{canonical_title(title)}",),
                )
                duplicate = cursor.fetchone()
            if duplicate:
                incoming_site = str(row.get('site', ''))
                existing_site = str(duplicate['site'] or '')
                if incoming_site.startswith('ats:') and not existing_site.startswith('ats:'):
                    cursor.execute("""
                    UPDATE jobs
                    SET site = ?, job_url = ?, job_url_direct = ?, location = ?,
                        date_posted = ?, job_type = ?, description = ?, is_remote = ?,
                        skills = ?, experience_range = ?,
                        status = CASE WHEN status = 'applied' THEN status ELSE 'scraped' END,
                        score = CASE WHEN status = 'applied' THEN score ELSE 0 END,
                        evidence = CASE WHEN status = 'applied' THEN evidence ELSE '' END,
                        matching_notes = CASE WHEN status = 'applied' THEN matching_notes ELSE '' END,
                        canonical_job_id = ?
                    WHERE job_id = ?
                    """, (
                        incoming_site,
                        job_url,
                        job_url_direct,
                        row.get('location', ''),
                        str(row.get('date_posted', '')),
                        row.get('job_type', ''),
                        row.get('description', ''),
                        int(row.get('is_remote', 0)) if pd.notna(row.get('is_remote')) else 0,
                        row.get('skills', ''),
                        row.get('experience_range', ''),
                        f"{canonical_company(company)}|{canonical_title(title)}",
                        duplicate['job_id'],
                    ))
                continue
        
        # Strictly validate remote status to avoid false-positive on-site listings
        from screening import is_job_truly_remote
        is_remote_val = 1 if is_job_truly_remote(row) else 0

        # Insert
        try:
            cursor.execute("""
            INSERT INTO jobs (
                job_id, site, job_url, job_url_direct, title, company, location, 
                date_posted, job_type, description, is_remote, skills, experience_range,
                status, canonical_job_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'scraped', ?)
            """, (
                job_id,
                row.get('site', ''),
                job_url,
                job_url_direct,
                row.get('title', ''),
                row.get('company', ''),
                row.get('location', ''),
                str(row.get('date_posted', '')),
                row.get('job_type', ''),
                row.get('description', ''),
                is_remote_val,
                row.get('skills', ''),
                row.get('experience_range', ''),
                f"{canonical_company(company)}|{canonical_title(title)}",
            ))
            inserted_count += 1
        except sqlite3.IntegrityError:
            # Safe fallback if concurrent operations or duplicate entry happens
            pass
            
    conn.commit()
    conn.close()
    return inserted_count

def get_unprocessed_jobs(job_ids=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    if job_ids:
        placeholders = ", ".join("?" for _ in job_ids)
        cursor.execute(
            f"SELECT * FROM jobs WHERE status = 'scraped' AND job_id IN ({placeholders})",
            list(job_ids),
        )
    else:
        cursor.execute("SELECT * FROM jobs WHERE status = 'scraped'")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_job_match(job_id: str, score: int, status: str, evidence: str, matching_notes: str,
                     components: dict | None = None, recommendation_status: str | None = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    updates = ["score = ?", "status = ?", "evidence = ?", "matching_notes = ?"]
    values = [score, status, evidence, matching_notes]
    if components is not None:
        updates.extend([
            "role_fit_score = ?", "company_quality_score = ?", "evidence_quality_score = ?",
            "freshness_score = ?", "directness_score = ?", "match_components = ?",
        ])
        values.extend([
            components.get("role_fit", 0), components.get("company_quality", 0),
            components.get("evidence_quality", 0), components.get("freshness", 0),
            components.get("directness", 0), json.dumps(components, sort_keys=True),
        ])
    if recommendation_status is not None:
        updates.append("recommendation_status = ?")
        values.append(recommendation_status)
    values.append(job_id)
    cursor.execute(f"UPDATE jobs SET {', '.join(updates)} WHERE job_id = ?", values)
    conn.commit()
    conn.close()

def sync_shortlisted_rankings(conn: sqlite3.Connection | None = None) -> int:
    """Synchronize scores, components, and recommendation status for all shortlisted jobs in SQLite.

    Guarantees that database rankings match the evidence-based quality pipeline and company tiers.
    """
    from screening import classify_company_tier
    from quality import assess_listing_quality, quality_gate, weighted_match_score, is_recommended_role

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM jobs WHERE status = 'shortlisted'")
        rows = [dict(r) for r in cursor.fetchall()]
        if not rows:
            return 0

        updates = []
        for j in rows:
            company = j.get("company", "")
            tier = classify_company_tier(company, conn=conn)
            quality = assess_listing_quality(j, tier)
            passes, _ = quality_gate(j, tier, quality)
            role_fit = j.get("role_fit_score") or j.get("score") or 0
            if role_fit == 0:
                role_fit = j.get("score", 0)
            adj_score, components = weighted_match_score(role_fit, quality)

            rec_status = "recommended" if is_recommended_role(passes, tier, adj_score, quality) else "discovered"

            if (
                j.get("score") != adj_score
                or j.get("recommendation_status") != rec_status
                or j.get("role_fit_score") != role_fit
                or j.get("company_quality_score") != components.get("company_quality")
            ):
                updates.append((
                    adj_score,
                    role_fit,
                    components.get("company_quality", 0),
                    components.get("evidence_quality", 0),
                    components.get("freshness", 0),
                    components.get("directness", 0),
                    json.dumps(components, sort_keys=True),
                    rec_status,
                    j["job_id"],
                ))

        if updates:
            cursor.executemany("""
            UPDATE jobs SET
                score = ?,
                role_fit_score = ?,
                company_quality_score = ?,
                evidence_quality_score = ?,
                freshness_score = ?,
                directness_score = ?,
                match_components = ?,
                recommendation_status = ?
            WHERE job_id = ?
            """, updates)
            conn.commit()
        return len(updates)
    finally:
        if close_conn:
            conn.close()

def get_shortlisted_jobs():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs WHERE status = 'shortlisted' ORDER BY score DESC, created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_applied_jobs():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs WHERE status = 'applied' ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def store_tailored_materials(job_id: str, tailored_resume_path: str, tailored_cover_letter_path: str,
                             tailored_resume_pdf_path: str, tailored_cover_letter_pdf_path: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE jobs
    SET tailored_resume_path = ?, tailored_cover_letter_path = ?,
        tailored_resume_pdf_path = ?, tailored_cover_letter_pdf_path = ?
    WHERE job_id = ?
    """, (tailored_resume_path, tailored_cover_letter_path, tailored_resume_pdf_path,
          tailored_cover_letter_pdf_path, job_id))
    conn.commit()
    conn.close()


def mark_as_applied(job_id: str, tailored_resume_path: str = None, tailored_cover_letter_path: str = None,
                    tailored_resume_pdf_path: str = None, tailored_cover_letter_pdf_path: str = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE jobs 
    SET status = 'applied', tailored_resume_path = ?, tailored_cover_letter_path = ?,
        tailored_resume_pdf_path = ?, tailored_cover_letter_pdf_path = ?
    WHERE job_id = ?
    """, (tailored_resume_path, tailored_cover_letter_path, tailored_resume_pdf_path,
          tailored_cover_letter_pdf_path, job_id))
    conn.commit()
    conn.close()

    # Automatically sync to Notion tracker in background thread
    try:
        import threading
        import notion_sync
        threading.Thread(target=notion_sync.sync_applied_to_notion, args=(job_id,), daemon=True).start()
    except Exception as e:
        import sys
        print(f"Warning: Could not launch Notion sync thread for {job_id}: {e}", file=sys.stderr)

def mark_as_rejected(job_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE jobs 
    SET status = 'rejected'
    WHERE job_id = ?
    """, (job_id,))
    conn.commit()
    conn.close()


def mark_as_shortlisted(job_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE jobs SET status = 'shortlisted' WHERE job_id = ?", (job_id,))
    conn.commit()
    conn.close()


def add_ats_boards(boards: list[tuple[str, str]], source: str = "discovered") -> int:
    """Register dynamically discovered ATS boards into the persistent cache."""
    if not boards:
        return 0
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ats_boards (
        ats TEXT NOT NULL,
        board_slug TEXT NOT NULL,
        source TEXT DEFAULT 'discovered',
        last_scraped TIMESTAMP,
        job_count INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (ats, board_slug)
    )
    """)
    added = 0
    for ats, board_slug in boards:
        ats_clean = str(ats or "").strip().lower()
        slug_clean = str(board_slug or "").strip().lower()
        if not ats_clean or not slug_clean or len(slug_clean) > 80:
            continue
        try:
            cursor.execute("""
            INSERT OR IGNORE INTO ats_boards (ats, board_slug, source, is_active)
            VALUES (?, ?, ?, 1)
            """, (ats_clean, slug_clean, source))
            if cursor.rowcount > 0:
                added += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return added


def get_registered_ats_boards(active_only: bool = True, limit: int | None = None) -> list[tuple[str, str]]:
    """Retrieve registered ATS boards dynamically without hardcoding."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ats_boards (
        ats TEXT NOT NULL,
        board_slug TEXT NOT NULL,
        source TEXT DEFAULT 'discovered',
        last_scraped TIMESTAMP,
        job_count INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (ats, board_slug)
    )
    """)
    query = "SELECT ats, board_slug FROM ats_boards"
    params = []
    if active_only:
        query += " WHERE is_active = 1"
    query += " ORDER BY job_count DESC, created_at ASC"
    if limit:
        query += f" LIMIT {int(limit)}"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [(row["ats"], row["board_slug"]) for row in rows]


def update_ats_board_scraped(ats: str, board_slug: str, job_count: int, is_active: int = 1):
    """Update board scrape statistics and health."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE ats_boards
    SET last_scraped = datetime('now'),
        job_count = ?,
        is_active = ?
    WHERE ats = ? AND board_slug = ?
    """, (job_count, is_active, str(ats).lower(), str(board_slug).lower()))
    conn.commit()
    conn.close()


def get_dynamic_target_companies(limit: int = 50) -> list[str]:
    """Dynamically extract verified company names from active ATS boards and product postings."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ats_boards (
        ats TEXT NOT NULL,
        board_slug TEXT NOT NULL,
        source TEXT DEFAULT 'discovered',
        last_scraped TIMESTAMP,
        job_count INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (ats, board_slug)
    )
    """)
    # Extract clean company names from registered boards with postings
    cursor.execute("""
        SELECT DISTINCT board_slug FROM ats_boards 
        WHERE is_active = 1 AND job_count > 0
        ORDER BY job_count DESC
        LIMIT ?
    """, (limit,))
    board_slugs = [r["board_slug"].replace("-", " ").replace("_", " ").title() for r in cursor.fetchall()]
    
    # Also pull from high-scoring product companies already in jobs.db
    cursor.execute("""
        SELECT DISTINCT company FROM jobs
        WHERE (site LIKE 'ats:%' OR score >= 85)
          AND company NOT IN ('None', '', 'Custom Opportunity')
          AND company NOT LIKE '%Consultancy%'
          AND company NOT LIKE '%Staffing%'
        ORDER BY score DESC
        LIMIT ?
    """, (limit,))
    job_companies = [r["company"] for r in cursor.fetchall()]
    conn.close()

    # Deduplicate while preserving order
    seen = set()
    combined = []
    for c in board_slugs + job_companies:
        norm = c.strip().lower()
        if norm and norm not in seen and len(norm) > 2:
            seen.add(norm)
            combined.append(c.strip())
    return combined[:limit]

