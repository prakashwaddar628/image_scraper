import pandas as pd
import requests
import os
import re
import time
import json
import urllib.parse
from bs4 import BeautifulSoup

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configuration
EXCEL_FILE = 'Item_List_Categorized.xlsx'
IMAGE_DIR = 'Product_Images'
SHEET_NAME = 'All Items - Categorized'

# Authorized retail domains to accept images from
AUTHORIZED_RETAILERS = ['amazon', 'flipkart', 'bigbasket', 'jiomart', 'blinkit', 'swiggy', 'zeptonow']

def clean_filename(name):
    """Remove characters that are invalid in Windows/Mac filenames."""
    return re.sub(r'[\\/*?:"<>|]', "", str(name)).strip()

def download_image(url, save_path):
    """Download the image from a URL and save it."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers, stream=True, timeout=10)
        
        content_type = response.headers.get('Content-Type', '')
        if response.status_code == 200 and 'image' in content_type:
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
            return True
    except Exception:
        pass
    return False

def is_authorized_source(page_url):
    """Check if the webpage hosting the image is an authorized retailer."""
    if not page_url:
        return False
    page_url_lower = page_url.lower()
    for retailer in AUTHORIZED_RETAILERS:
        if retailer in page_url_lower:
            return True
    return False

def main():
    if not os.path.exists(IMAGE_DIR):
        os.makedirs(IMAGE_DIR)

    print(f"Reading data from {EXCEL_FILE}...")
    df = pd.read_excel(EXCEL_FILE, sheet_name=SHEET_NAME)
    
    for index, row in df.iterrows():
        product_name = row['Item Description']
        barcode = row['Barcode'] # We can pass this to the query for better accuracy
        
        if pd.isna(product_name):
            continue

        safe_name = clean_filename(product_name)
        file_path = os.path.join(IMAGE_DIR, f"{safe_name}.jpg")

        if os.path.exists(file_path):
            print(f"[SKIP] {safe_name}.jpg already exists.")
            continue

        print(f"Searching for: {product_name}...")
        
        # Add 'buy online india grocery' context to force e-commerce results
        query = urllib.parse.quote(f"{product_name} grocery buy online india")
        search_url = f"https://www.bing.com/images/search?q={query}"
        
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            res = requests.get(search_url, headers=headers, timeout=10)
            soup = BeautifulSoup(res.text, 'html.parser')
            
            image_tags = soup.find_all('a', class_='iusc')
            success = False
            
            # Scan through the top 10 image results
            for a_tag in image_tags[:10]:
                if 'm' in a_tag.attrs:
                    m_data = json.loads(a_tag['m'])
                    image_url = m_data.get('murl')
                    page_url = m_data.get('purl') # The website where the image was found
                    
                    # STRICT FILTER: Only proceed if the image is on a recognized retail site
                    if is_authorized_source(page_url):
                        if image_url and download_image(image_url, file_path):
                            domain = urllib.parse.urlparse(page_url).netloc
                            print(f"[SUCCESS] Saved {safe_name}.jpg (Source: {domain})")
                            success = True
                            break # Move to the next product in the excel sheet
            
            if not success:
                print(f"[ERROR] No authorized retail image found for {product_name}. Skipping to maintain accuracy.")

        except Exception as e:
            print(f"[ERROR] Search failed for {product_name}: {e}")

        time.sleep(2)

if __name__ == "__main__":
    main()