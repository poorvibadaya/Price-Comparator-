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

def set_blinkit_location(page, location_name):
    handle_popups(page)
    
    # 1. Click on Location Bar auto appear hence commented
    # print("Opening location bar...")
    # page.locator('[class^="LocationBar__Title"]').click()
    
    # 2. Focus and Click the input specifically
    # Waiting for the container and then locating the 'input' within it
    search_input_container = page.locator('.modal-right__input-wrapper')
    search_input_container.wait_for(state="visible")
    
    search_input = search_input_container.locator('input')
    
    # EXPLICIT CLICK before filling
    search_input.click() 
    
    # Use press_sequentially to ensure React triggers its search results correctly
    search_input.press_sequentially(location_name, delay=100) 
    
    # 3. Click first result
    print("Selecting location result...")
    # Use a more specific locator for the result items
    first_result = page.locator('.address-container-v1 [class*="LocationSearchList__LocationListContainer"]').first
    
    # Ensure it's ready for interaction
    first_result.wait_for(state="visible", timeout=10000)
    first_result.click()
    
    # 4. Final stabilizing wait
    print("Location set. Refreshing catalog...")
    # page.wait_for_load_state("domcontentloaded")
    time.sleep(2)

def search_blinkit_products(page, query):
    handle_popups(page)
    
    # 1. Search Bar Interaction
    search_container = page.locator('[class^="SearchBar__PlaceholderContainer"]')
    search_container.click()
    
    # Fill the input that appears
    time.sleep(2)
    page.keyboard.type(query)
    page.keyboard.press("Enter")
    page.evaluate("document.body.style.zoom = '50%'")
    # page.wait_for_load_state("networkidle")
    time.sleep(3)
    
    for i in range(1):
        handle_popups(page)
        print(f"Scrolling Blinkit... ({i+1}/5)")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(3)

def extract_blinkit_data(page):
    """Fast extraction using JS evaluate for React structure."""
    extraction_script = """
        () => {
        const items = document.querySelectorAll('.tw-relative.tw-flex');
        
        return Array.from(items).map(item => {
            const roleBtn = item.querySelector('[role="button"]');
            const anyWithId = item.querySelector('[id]');
            const parentId = item.id;

            const productId = (roleBtn && roleBtn.id) || (anyWithId && anyWithId.id) || parentId || null;
            
            const nameEl = item.querySelector('.tw-text-300.tw-font-semibold');
            const productName = nameEl ? nameEl.innerText.trim() : "";

            const imgEl = item.querySelector('img.tw-opacity-100');
            const imageUrl = imgEl ? imgEl.getAttribute('src') : "N/A";

            const slug = productName
                .toLowerCase()
                .replace(/[^a-z0-9]+/g, '-')
                .replace(/^-+|-+$/g, '');

            const productLink = productId 
                .toLowerCase()
                ? `https://blinkit.com/prn/${slug}/prid/${productId}` 
                : "N/A";

            const priceEl = item.querySelector('.tw-text-200.tw-font-semibold');
            const descEl = item.querySelector('.tw-text-200.tw-font-medium.tw-line-clamp-1');
            const timeEl = item.querySelector('.tw-text-050.tw-font-bold.tw-uppercase');

            return {
                "product_name": productName || "N/A",
                "price": priceEl ? priceEl.innerText.trim() : "N/A",
                "description": descEl ? descEl.innerText.trim() : "N/A",
                "delivery_time": timeEl ? timeEl.innerText.trim() : "N/A",
                "product_link": productLink,
                "image_url": imageUrl
            };
        }).filter(p => p.product_name !== "N/A");
    }
    """
    return page.evaluate(extraction_script)




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
    
    # Define file path: run_folder/blinkit.json (directly in parent folder)
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
def run_blinkit_flow(product_name, location, headless=True, max_products=50, run_parent_folder=None, platform_name='blinkit'):
    start_time = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        # Use a standard Chrome User-Agent
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        context = browser.new_context(user_agent=user_agent)
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = context.new_page()
        
        try:
            page.goto("https://blinkit.com/", wait_until="domcontentloaded")
            
            set_blinkit_location(page, location)
            search_blinkit_products(page, product_name)
            
            final_list = extract_blinkit_data(page)

            # Remove Duplicates
            final_list = remove_duplicate_products(final_list)

            save_to_timestamped_folder(final_list, platform_name, run_parent_folder=run_parent_folder)
            
            # Return the products list so server.py can use them
            time_end = time.time()
            print(f"--- Blinkit Total Time Taken: {time_end - start_time:.2f}) seconds ---")
            return final_list
            
        except Exception as e:
            print(f"[Blinkit] Error during scraping: {e}")
            import traceback
            traceback.print_exc()
            return []  # Return empty list on error
        finally:
            browser.close()

if __name__ == "__main__":
    run_blinkit_flow(product_name="atta", location="Mumbai", headless=False, max_products=50)