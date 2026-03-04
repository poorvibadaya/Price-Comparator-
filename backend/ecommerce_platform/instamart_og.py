import os
import json
import time
from datetime import datetime
from playwright.sync_api import sync_playwright

# Storage folder for product data
STORAGE_FOLDER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "product_data")
os.makedirs(STORAGE_FOLDER, exist_ok=True)

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

def setup_automatic_handlers(page):
    # Defining the complex locator exactly as you requested
    try_again_button = page.locator('button.sc-iGgWBj.gVfwdV.hIVl0').filter(
        has=page.locator('span.sc-gEvEer.jvMXGN div.sc-gEvEer.eMfGmB', has_text="Try Again")
    )
    
    def recover_from_error():
        try:
            print("--- Error Interceptor Triggered ---")
            # Force a small wait to ensure the button is actually clickable
            try_again_button.wait_for(state="visible", timeout=5000)
            try_again_button.click()
            print("Successfully clicked 'Try Again'")
            
            # Wait for the page to actually start loading content again
            page.wait_for_load_state("domcontentloaded")
        except Exception as e:
            print(f"Handler failed to click button: {e}")

    # Register the handler
    page.add_locator_handler(try_again_button, recover_from_error)



def set_location(page, location_name):
    
    print(f"Setting location to: {location_name}")
    # this is commented for automation browser popup already opens location selector
    # address_header = page.get_by_test_id("address-line")
    # address_header.wait_for(state="visible")
    # address_header.click()

    # Select the container by test-id
    search_container = page.get_by_test_id("search-location")
    page.wait_for_timeout(2000)

    # 1. Click it to trigger the real input field
    search_container.click()

    # 2. Now look for the input (it might be global or inside the container now)
    # We use a generic locator since the DOM probably updated
    page.locator("input[placeholder*='Search']").fill(location_name)

    first_result = page.locator("._11n32").first
    first_result.wait_for(state="visible")
    page.wait_for_timeout(2000)
    first_result.click()
    # Wait for catalog to transition
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(3000)
    page.locator(".sc-gEvEer.jvMXGN").click()

def search_and_scroll(page, product_query):
    page.wait_for_timeout(2000)
    
    print(f"Searching for: {product_query}")
    
    # 1. Click search and type
    page.wait_for_timeout(2000)
    page.get_by_test_id("search-container").click()
    page.locator("input._18fRo").click()
    page.wait_for_timeout(2000)
    page.locator("input._18fRo").fill(product_query)
    page.wait_for_timeout(3000)
    page.keyboard.press("Enter")
    
    page.wait_for_load_state("domcontentloaded")
    
    page.wait_for_timeout(5000)
    page.evaluate("document.body.style.zoom = '10%'")
    
    # 2. Scroll Loop (5 iterations is usually enough for Instamart's lazy load)
    for i in range(5):
        print(f"Scrolling Instamart... ({i+1}/5)")
        page.evaluate("""
            (selector) => {
                const container = document.querySelector(selector);
                if (container) {
                    // Scroll to the bottom of this specific element
                    container.scrollTop = container.scrollHeight;
                }
            }
        """, "._2_95H")
        page.wait_for_timeout(5000)

def extract_product_list(page):
    print("Extracting Instamart items...")
    
    extraction_script = """
    () => {
        const items = document.querySelectorAll('div._3Rr1X');

        return Array.from(items).map(item => {
            const timeEl = item.querySelector('.sc-gEvEer.ePxHTM.GOJ8s._1y_Uf');
            const deliveryTime = timeEl ? timeEl.innerText.trim() : "N/A";
            const nameEl = item.querySelector('.sc-gEvEer.iPErou._1lbNR');
            const productName = nameEl ? nameEl.innerText.trim() : "N/A";
            const imgEl = item.querySelector('img._16I1D');
            const imageUrl = imgEl ? imgEl.getAttribute('src') : "N/A";
            const descEl = item.querySelector('.sc-gEvEer.bCqPoH._3wq_F');
            let description = "N/A";
            if (descEl) {
                description = Array.from(descEl.childNodes)
                    .filter(node => node.nodeType === Node.TEXT_NODE)
                    .map(node => node.textContent.trim())
                    .join(' ') || descEl.firstChild?.textContent?.trim() || "N/A";
            }

            const priceEl = item.querySelector('.sc-gEvEer.iQcBUp._2jn41');
            const price = priceEl ? priceEl.innerText.trim() : "N/A";

            const linkEl = item.closest('a') || item.querySelector('a');
            let productLink = "N/A";
            
            if (linkEl) {
                const href = linkEl.getAttribute('href');
                productLink = href ? (href.startsWith('http') ? href : `https://www.swiggy.com${href}`) : "N/A";
            }

            return {
                "product_name": productName,
                "price": price,
                "description": description,
                "delivery_time": deliveryTime,
                "product_link": productLink,
                "image_url": imageUrl
            };
        }).filter(p => p.product_name !== "N/A");
    }
    """
    products = page.evaluate(extraction_script)
    return [p for p in products if p['product_name'] != "N/A"]

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

def run_instamart_flow(product_name, location, headless=True, max_products=50, run_parent_folder=None, platform_name='instamart'):
    start_time = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        # Using a mobile-friendly or standard desktop context
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        context = browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent=user_agent
        )
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = context.new_page()
        setup_automatic_handlers(page)

        try:
            # Set a more reasonable timeout
            page.goto("https://www.swiggy.com/instamart/", wait_until="domcontentloaded", timeout=10000)
            # 
            
            set_location(page, location)
            search_and_scroll(page, product_name)
            
            final_data_list = extract_product_list(page)

            # Remove Duplicates
            final_data_list = remove_duplicate_products(final_data_list)

            save_to_timestamped_folder(final_data_list, platform_name, run_parent_folder=run_parent_folder)
            time_end = time.time()
            print(f"--- Instamart Total Time Taken: {time_end - start_time:.2f}) seconds ---")
            return final_data_list

        except Exception as e:
            print(f"Extraction Error: {e}")
        finally:
            brow
            ser.close()

# For standalone script execution
if __name__ == "__main__":
    run_instamart_flow(product_name="cookie", location="Mumbai", headless=False, max_products=50)