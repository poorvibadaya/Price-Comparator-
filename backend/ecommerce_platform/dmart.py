import os
import json
import time
import requests
from urllib.parse import quote
from datetime import datetime
from playwright.sync_api import sync_playwright

# Storage folder for product data
STORAGE_FOLDER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "product_data")
os.makedirs(STORAGE_FOLDER, exist_ok=True)

def search_dmart_api(query, page=1, size=40, store_id=10706):
    print("DMart API called...")
    """Make API call to DMart search endpoint"""
    url = f"https://digital.dmart.in/api/v3/search/{quote(query)}?page={page}&size={size}&channel=web&searchTerm={quote(query)}&storeId={store_id}"
    
    headers = {
        "X-REQUEST-ID": "ODdkN2I4MDAtMzU0Ni00Mjk0LThhZjgtODA0YjE2NWE2NjI4fHxTLTIwMjYwMTA2XzE1NDgyMnx8LTEwMDI=",
        "storeId": str(store_id),
        "d_info": "w-20260106_154822",
        "Content-Type": "application/json;charset=UTF-8",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"DMart API error: {e}")
        return None
    
def handle_popups(page):
    """Closes the Download App modal if it appears."""
    try:
        # Looking for the partial class of the Download App Modal
        modal_close_btn = page.locator('[class*="DownloadAppModal__Image"], [class*="modal-close"]')
        if modal_close_btn.is_visible():
            print("Closing Download App Modal...")
            modal_close_btn.click()
    except:
        pass

def set_dmart_location(page, location_name):
    handle_popups(page)

    print("Waiting for DMart location input...")

    # 1. Type location
    search_input = page.locator('#pincodeInput')
    search_input.wait_for(state="visible", timeout=15000)
    search_input.click()
    search_input.fill("")
    search_input.press_sequentially(location_name, delay=120)

    # 2. Select first suggestion
    print("Selecting first location result...")
    suggestions_container = page.locator('.pinCodeScrollBar')
    suggestions_container.wait_for(state="visible", timeout=15000)

    first_result = suggestions_container.locator('li button').first
    first_result.wait_for(state="visible", timeout=15000)
    first_result.click()

    # 3. Decide based on popup button
    print("Checking location serviceability...")

    confirm_btn = page.locator('button:has-text("CONFIRM LOCATION")')
    reject_btn  = page.locator('button:has-text("SELECT DIFFERENT LOCATION")')

    # give UI time to render
    page.wait_for_timeout(1500)

    if reject_btn.is_visible():
        print("[FAIL] Location not serviceable by DMart. Aborting scraping.")
        raise Exception("Pincode not serviceable")

    elif confirm_btn.is_visible():
        print("[OK] Location serviceable. Confirming...")
        confirm_btn.click()
        print("DMart location fully set.")
        time.sleep(3)

    else:
        raise Exception("No location confirmation button appeared (DOM changed)")


def search_dmart_products(page, query):
    handle_popups(page)

    print(f"Searching DMart for: {query}")

    # 1. Focus and type in search input
    search_input = page.locator('#scrInput')
    search_input.wait_for(state="visible", timeout=15000)
    search_input.click()
    search_input.fill("")
    search_input.press_sequentially(query, delay=100)

    # Small wait so UI registers text
    page.wait_for_timeout(500)

    # 2. Click SEARCH button
    print("Clicking SEARCH button...")
    search_button = page.locator('button:has-text("SEARCH")')
    search_button.wait_for(state="visible", timeout=15000)
    search_button.click()

    # 3. Wait for search results to load
    page.wait_for_load_state("domcontentloaded")
    time.sleep(3)

    # 4. Scroll to load more products
    for i in range(1):
        print(f"Scrolling DMart... ({i+1}/1)")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(3)

def split_product_name(full_name):
    """Split product name into name and description based on common patterns"""
    if not full_name or full_name == "N/A":
        return full_name, "N/A"
    
    # Common patterns to split on
    patterns = [
        r'\s*\(.*?\)\s*:\s*',  # Split on parentheses followed by colon
        r'\s*:\s*',  # Split on colon (e.g., "Product : 500 ml")
        r'\s*-\s*\d+',  # Split before dash followed by number
    ]
    
    for pattern in patterns:
        import re
        match = re.search(pattern, full_name)
        if match:
            split_point = match.start()
            name = full_name[:split_point].strip()
            description = full_name[split_point:].strip()
            # Clean up description by removing leading colons/dashes
            description = re.sub(r'^[:\-\s]+', '', description)
            return name, description
    
    # If no pattern matches, return original name with empty description
    return full_name, "N/A"

def extract_dmart_data(page):
    extraction_script = """
    () => {
        const items = document.querySelectorAll(
            'div.w-\\\\[265px\\\\].h-\\\\[390px\\\\].bg-appWhite'
        );

        return Array.from(items).map(item => {
            // PRODUCT NAME
            const nameEl = item.querySelector("div.text-primaryColor.min-h-10");
            const productName = nameEl ? nameEl.innerText.trim() : "N/A";

            // PRICES
            let dmartPrice = "N/A";
            const priceTexts = Array.from(item.querySelectorAll('p'))
                .map(p => p.innerText.trim())
                .filter(t => t.startsWith("₹"));

            if (priceTexts.length >= 2) {
                dmartPrice = priceTexts[1];
            } else if (priceTexts.length === 1) {
                dmartPrice = priceTexts[0];
            }

            // IMAGE
            let image = "N/A";
            const imgDiv = item.querySelector('div[style*="background-image"]');

            if (imgDiv) {
                const bg = imgDiv.style.backgroundImage;
                // Extract first URL from: url("..."), url("...")
                const match = bg.match(/url\(["']?(.*?)["']?\)/);
                if (match && match[1]) {
                    image = match[1];
                }
            }

            return {
                "product_name": productName,
                "price": dmartPrice,
                "delivery_time": "N/A",
                "product_link": 'N/A',
                "image_url": image
            };
        });
    }
    """
    return page.evaluate(extraction_script)

def remove_duplicate_products(product_list):
    """
    Removes exact duplicate dictionaries from a list while preserving order.
    """
    seen = set()
    unique_products = []
    
    for product in product_list:
        # Convert dict to a sorted tuple of items so it can be hashed/tracked
        # sorting keys ensures {'a':1, 'b':2} and {'b':2, 'a':1} are seen as same
        product_tuple = tuple(sorted(product.items()))
        
        if product_tuple not in seen:
            unique_products.append(product)
            seen.add(product_tuple)
            
    return unique_products

def save_to_timestamped_folder(data, platform_name, run_parent_folder=None):
    # If parent folder is provided, use it; otherwise create a new one
    if run_parent_folder:
        # Use the shared parent folder: product_data/run-2026-01-10_20-10-15/
        run_folder = os.path.join(STORAGE_FOLDER, run_parent_folder)
        os.makedirs(run_folder, exist_ok=True)
    else:
        # Fallback: Create a unique timestamp (e.g., 2026-01-10_01-30-45)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        run_folder = os.path.join(STORAGE_FOLDER, f"run-{timestamp}-{platform_name.lower()}")
        os.makedirs(run_folder, exist_ok=True)
    
    # Define file path: run_folder/zepto.json (directly in parent folder)
    json_filename = f"{platform_name.lower()}.json"
    json_path = os.path.join(run_folder, json_filename)
    
    # Save the data
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)
        
    print(f"--- Data Saved Successfully ---")
    print(f"Folder: {run_folder}")
    print(f"File: {json_filename}")
    return json_path


# --- MAIN EXECUTION ---
def run_dmart_flow(product_name, location, headless=True, max_products=50, run_parent_folder=None, platform_name='dmart'):
    start_time = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        # Use a standard Chrome User-Agent
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        context = browser.new_context(user_agent=user_agent)
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = context.new_page()
        
        try:
            page.goto("https://www.dmart.in/", wait_until="domcontentloaded")
            
            set_dmart_location(page, location)
            search_dmart_products(page, product_name)
            
            raw_list = extract_dmart_data(page)
            
            # Process each product to split name and description
            final_list = []
            for product in raw_list:
                name, description = split_product_name(product['product_name'])
                processed_product = product.copy()
                processed_product['product_name'] = name
                processed_product['description'] = description
                final_list.append(processed_product)

            final_data_list = remove_duplicate_products(final_list)
            
            final_saved_path = save_to_timestamped_folder(final_data_list, platform_name, run_parent_folder=run_parent_folder)

            time_end = time.time()
            print(f"--- Dmart Total Time Taken: {time_end - start_time:.2f}) seconds ---")
            return final_data_list
            
        except Exception as e:
            print(f"[Dmart] Error during scraping: {e}")
            import traceback
            traceback.print_exc()
            return [] 
        finally:
            browser.close()

if __name__ == "__main__":
    run_dmart_flow(product_name="atta", location="Mumbai", headless=False, max_products=50)
