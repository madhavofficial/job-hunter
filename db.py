import sqlite3
import os
import pandas as pd

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jobs.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
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
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    conn.close()

def add_jobs(df: pd.DataFrame):
    if df.empty:
        return 0
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    inserted_count = 0
    
    for _, row in df.iterrows():
        job_id = str(row.get('id', ''))
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

        # 3. Check duplicate (title + company) posted within the active database to prevent repost duplicates
        if title and company and company.lower() not in ["none", ""]:
            cursor.execute("SELECT 1 FROM jobs WHERE lower(title) = lower(?) AND lower(company) = lower(?)", (title, company))
            if cursor.fetchone():
                continue
        
        # Insert
        try:
            cursor.execute("""
            INSERT INTO jobs (
                job_id, site, job_url, job_url_direct, title, company, location, 
                date_posted, job_type, description, is_remote, skills, experience_range,
                status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'scraped')
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
                int(row.get('is_remote', 0)) if pd.notna(row.get('is_remote')) else 0,
                row.get('skills', ''),
                row.get('experience_range', ''),
            ))
            inserted_count += 1
        except sqlite3.IntegrityError:
            # Safe fallback if concurrent operations or duplicate entry happens
            pass
            
    conn.commit()
    conn.close()
    return inserted_count

def get_unprocessed_jobs():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs WHERE status = 'scraped'")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_job_match(job_id: str, score: int, status: str, evidence: str, matching_notes: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE jobs 
    SET score = ?, status = ?, evidence = ?, matching_notes = ?
    WHERE job_id = ?
    """, (score, status, evidence, matching_notes, job_id))
    conn.commit()
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

def mark_as_applied(job_id: str, tailored_resume_path: str = None, tailored_cover_letter_path: str = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE jobs 
    SET status = 'applied', tailored_resume_path = ?, tailored_cover_letter_path = ?
    WHERE job_id = ?
    """, (tailored_resume_path, tailored_cover_letter_path, job_id))
    conn.commit()
    conn.close()

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
