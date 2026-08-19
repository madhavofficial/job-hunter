import sys
import os
import webbrowser
import db
import tailor

def main():
    if len(sys.argv) < 2:
        print("Usage: python apply.py [job_id]", file=sys.stderr)
        sys.exit(1)
        
    job_id = sys.argv[1]
    db.init_db()
    
    # Get job details
    conn = db.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
    job = cursor.fetchone()
    conn.close()
    
    if not job:
        print(f"Error: Job ID '{job_id}' not found in database.", file=sys.stderr)
        sys.exit(1)
        
    title = job['title']
    company = job['company']
    location = job['location']
    
    # Fallback to job_url if job_url_direct is empty
    url = job['job_url_direct'] or job['job_url']
    
    print("====================================================")
    print("              INTERACTIVE APPLY PIPELINE            ")
    print("====================================================")
    print(f"Job: '{title}' at '{company}' ({location})")
    print(f"Target URL: {url}")
    print("====================================================")
    print("Step 1: Generating Tailored Resume & Cover Letter...")
    
    # Call tailor_materials to generate the files and update status
    resume_path, cl_path = tailor.tailor_materials(job_id)
    
    if not resume_path or not cl_path:
        print("Error: Failed to generate tailored materials. Aborting.", file=sys.stderr)
        sys.exit(1)
        
    print("\nStep 2: Review generated files:")
    print(f"-> Tailored Resume:      file://{resume_path}")
    print(f"-> Tailored Cover Letter: file://{cl_path}")
    print("====================================================")
    
    input("Press [Enter] to open the application form in your default browser and finalize tracking... ")
    
    if url:
        print(f"Opening browser to: {url}")
        webbrowser.open(url)
    else:
        print("Warning: No target URL available to open.")
        
    print("\n====================================================")
    print("🎉 Action Checklist:")
    print(f"1. A browser window was opened to apply for '{title}' at '{company}'.")
    print(f"2. Upload your tailored resume from:")
    print(f"   {resume_path}")
    print(f"3. Copy-paste your tailored cover letter from:")
    print(f"   {cl_path}")
    print(f"4. The job status has been updated to 'applied' in your SQLite DB.")
    print("====================================================")

if __name__ == "__main__":
    main()
