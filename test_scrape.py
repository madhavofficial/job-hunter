import sys
from jobspy import scrape_jobs

def main():
    try:
        print("Testing jobspy...")
        jobs = scrape_jobs(
            site_name=["linkedin", "indeed"],
            search_term="software engineer intern",
            location="India",
            results_wanted=5,
            hours_old=72,
            country_indeed='india'
        )
        print(f"Scraped successfully! Found {len(jobs)} jobs.")
        print(jobs.head())
    except Exception as e:
        print("Error scraping:", e, file=sys.stderr)

if __name__ == "__main__":
    main()
