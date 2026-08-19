import requests
from bs4 import BeautifulSoup
import sys

def main():
    url = "https://www.linkedin.com/jobs/view/4454504697"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    
    print(f"Fetching LinkedIn URL: {url}...")
    try:
        response = requests.get(url, headers=headers, timeout=10)
        print(f"Status Code: {response.status_code}")
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Public LinkedIn job view has description inside specific classes
        # Let's try common classes: 'show-more-less-html__markup' or 'description__text'
        desc_div = soup.find(class_="show-more-less-html__markup")
        if not desc_div:
            desc_div = soup.find(class_="description__text")
            
        if desc_div:
            desc_text = desc_div.get_text(separator="\n").strip()
            print("\nFound Description (first 200 chars):")
            print(desc_text[:200])
            print(f"Total length: {len(desc_text)}")
        else:
            print("\nDescription element not found in HTML.")
            # Let's save a snippet of the body to see what we got
            body_text = soup.body.get_text().strip() if soup.body else ""
            print("Body snippet (first 300 chars):")
            print(body_text[:300])
            
    except Exception as e:
        print("Error fetching:", e, file=sys.stderr)

if __name__ == "__main__":
    main()
