"""
Flask Backend API Server for Fast E-commerce Product Scraping

This is a Python/Flask server that handles scraping from various platforms
to avoid CORS issues. Run this separately and point VITE_API_BASE_URL to it.

Installation:
pip install flask flask-cors requests beautifulsoup4 lxml

Usage:
python app.py

Then set VITE_API_BASE_URL=http://localhost:3001 in your .env file
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from dotenv import load_dotenv
import json
import uuid
import os
from urllib.parse import quote
import threading
import time
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from ecommerce_platform.zepto import run_zepto_flow
from ecommerce_platform.blinkit import run_blinkit_flow
from ecommerce_platform.instamart import run_instamart_flow
from ecommerce_platform.dmart import run_dmart_flow
from ecommerce_platform.bigbasket import run_bigbasket_flow
from datetime import datetime
# Import comparison functions from compare.py
from compare import (
    find_matching_products,
    extract_quantity,
    normalize_product_name,
    normalize_product_data,
    compare_products_in_memory,
    save_comparison_to_json
)

# Configure logging - both to console and file
log_format = "%(asctime)s [%(process)d] [%(levelname)s] %(message)s"
log_file = os.path.join(os.path.dirname(__file__), 'server.log')

# Create file handler
file_handler = logging.FileHandler(log_file, encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter(log_format))

# Create console handler - ensure it flushes immediately
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter(log_format))
# Force immediate flushing
console_handler.stream = sys.stdout

# Configure root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.handlers = []  # Clear any existing handlers
root_logger.addHandler(console_handler)
root_logger.addHandler(file_handler)

# Also configure Flask's logger
flask_logger = logging.getLogger('werkzeug')
flask_logger.setLevel(logging.INFO)
flask_logger.addHandler(console_handler)
flask_logger.addHandler(file_handler)

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Configure Flask's logger to also output to console
app.logger.setLevel(logging.INFO)
app.logger.handlers = []  # Clear default handlers
app.logger.addHandler(console_handler)
app.logger.addHandler(file_handler)

PORT = int(os.environ.get('PORT', 8080))

# Load configuration from config.json
def load_config():
    """Load configuration from config.json file"""
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return config
    except FileNotFoundError:
        logging.warning(f'[Config] config.json not found at {config_path}, using defaults')
        return {}
    except json.JSONDecodeError as e:
        logging.error(f'[Config] Invalid JSON in config.json: {e}')
        return {}

# Load .env for Geoapify API key (optional)
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

# Load config on startup
CONFIG = load_config()
PLATFORM_CONFIG = CONFIG.get('platform', {})
GEOAPIFY_API_KEY = os.environ.get('GEOAPIFY_API_KEY', '')
SEARCH_DEBUG = CONFIG.get('search_debug', False)
MATCHING_CONFIG = CONFIG.get('matching', {})

def get_platform_config(platform_name):
    """Get configuration for a specific platform"""
    platform_config = PLATFORM_CONFIG.get(platform_name, {})
    return {
        'scrape': platform_config.get('scrape', True),  # Default to True if not specified
        'headless': platform_config.get('headless', True)  # Default to True if not specified
    }




@app.route('/api/search', methods=['POST'])
def search_all_platforms():
    """Search endpoint - searches across all platforms in parallel"""
    try:
        # Get request data
        if not request.is_json:
            return jsonify({'error': 'Request must be JSON'}), 400
        
        data = request.get_json() or {}
        query = data.get('query', '')
        location = data.get('location', {})
        platforms = data.get('platforms', ['zepto'])
        
        logging.info(f'[API] Received search request: query="{query}", platforms={platforms}, location={location}')
        
        if not query or not query.strip():
            return jsonify({'error': 'Query is required'}), 400
        
        # Generate shared parent folder for this search run
        # Format: run-2026-01-10_13-28-30 (consistent format)
        run_parent_folder = f"run-{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
        logging.info(f'[API] Using parent folder: {run_parent_folder}')
        
        all_products = []
        
        # Store products by platform for comparison
        products_by_platform = {}
        
        # Run all platforms in parallel using ThreadPoolExecutor
        logging.info(f'[API] Starting parallel search for {len(platforms)} platform(s)')
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=len(platforms)) as executor:
            # Submit all tasks with shared parent folder
            future_to_platform = {
                executor.submit(search_platform, platform, query, location, run_parent_folder): platform
                for platform in platforms
            }
            
            # Wait for all to complete and collect results
            for future in as_completed(future_to_platform):
                platform = future_to_platform[future]
                try:
                    products = future.result()  # This waits for the result
                    # Ensure products is a list before processing
                    if products is None:
                        products = []
                    logging.info(f'[API] [OK] Platform {platform} returned {len(products)} products')
                    
                    # Debug: Check if products have platform field set
                    if products:
                        sample_product = products[0]
                        product_platform = sample_product.get('platform', 'MISSING')
                        logging.debug(f'[API] Sample product from {platform} has platform field: "{product_platform}"')
                        if product_platform == 'MISSING' or product_platform != platform:
                            logging.warning(f'[API] Platform field mismatch! Expected "{platform}", got "{product_platform}"')
                            # Fix platform field if missing or incorrect
                            for p in products:
                                p['platform'] = platform
                    
                    all_products.extend(products)
                    products_by_platform[platform] = products
                except Exception as error:
                    logging.error(f'[API] [X] Error searching {platform}: {error}')
                    import traceback
                    logging.error(traceback.format_exc())
                    # Continue with other platforms even if one fails
                    continue
        
        elapsed = time.time() - start_time
        logging.info(f'[API] Total products found: {len(all_products)} (completed in {elapsed:.2f}s)')
        
        # Debug: Check platform distribution before comparison
        platform_distribution = {}
        for product in all_products:
            platform = product.get('platform', 'unknown')
            platform_distribution[platform] = platform_distribution.get(platform, 0) + 1
        logging.debug(f'[API] Platform distribution in all_products: {platform_distribution}')
        logging.debug(f'[API] Products by platform dict: {[(p, len(prods)) for p, prods in products_by_platform.items()]}')
        
        # Automatically run comparison after search
        matched_products = []
        if len(all_products) > 0:
            logging.info(f'[API] Running automatic comparison...')
            try:
                # Pass matching config to comparison function
                matching_config = CONFIG.get('matching', {})
                matched_products = compare_products_in_memory(all_products, query, location, config=matching_config)
                
                if matched_products:
                    # Save comparison results to compare.json
                    save_comparison_to_json(matched_products, query, location)
                    logging.info(f'[API] Comparison complete: {len(matched_products)} products compared')
                else:
                    logging.warning(f'[API] Comparison returned no products')
            except Exception as compare_error:
                logging.error(f'[API] Error during automatic comparison: {compare_error}')
                import traceback
                logging.error(traceback.format_exc())
                # Continue with returning all products even if comparison fails
        
        # If we have comparison results, return MatchedProduct[] format for frontend
        # Frontend expects products grouped by name with platforms object
        if matched_products and len(matched_products) > 0:
            # Filter platforms in each matched product to only include requested platforms
            filtered_matched_products = []
            for item in matched_products:
                # Filter platforms dict to only include requested platforms
                filtered_platforms = {
                    platform_name: platform_data 
                    for platform_name, platform_data in item.get('platforms', {}).items()
                    if platform_name in platforms
                }
                
                # Only include if there are platforms after filtering
                if filtered_platforms:
                    matched_product = {
                        'name': item.get('name', ''),
                        'image': item.get('image', ''),
                        'original_names': item.get('original_names', {}),
                        'platforms': filtered_platforms
                    }
                    filtered_matched_products.append(matched_product)
            
            if filtered_matched_products:
                logging.info(f'[API] Returning {len(filtered_matched_products)} matched products (MatchedProduct format)')
                return jsonify({'products': filtered_matched_products})
        
        # Fallback: return raw products if comparison failed or single platform
        logging.info(f'[API] Returning {len(all_products)} raw products')
        return jsonify({'products': all_products})
    except Exception as error:
        logging.error(f'[API] Search error: {error}')
        import traceback
        logging.error(traceback.format_exc())
        return jsonify({'error': f'Failed to search products: {str(error)}'}), 500


@app.route('/api/search/<platform>', methods=['POST'])
def search_platform_endpoint(platform):
    """Platform-specific search endpoint"""
    try:
        if not request.is_json:
            return jsonify({'error': 'Request must be JSON'}), 400
        
        data = request.get_json() or {}
        query = data.get('query', '')
        location = data.get('location', {})
        
        logging.info(f'[API] Platform-specific search: platform={platform}, query="{query}"')
        
        if not query or not query.strip():
            return jsonify({'error': 'Query is required'}), 400
        
        products = search_platform(platform, query, location)
        logging.info(f'[API] Platform {platform} returned {len(products)} products')
        return jsonify({'products': products})
    except Exception as error:
        logging.error(f'[API] Error searching {platform}: {error}')
        import traceback
        logging.error(traceback.format_exc())
        return jsonify({'error': f'Failed to search on {platform}: {str(error)}'}), 500




def search_platform(platform, query, location, run_parent_folder=None):
    """Search a specific platform"""
    # Check if platform scraping is enabled in config
    platform_config = get_platform_config(platform)
    if not platform_config['scrape']:
        logging.info(f'[API] Platform {platform} is disabled in config.json, skipping...')
        return []
    
    platform_map = {
        'zepto': scrape_zepto,
        'swiggy-instamart': scrape_instamart,
        'bigbasket': scrape_bigbasket,
        'blinkit': scrape_blinkit,
        'dmart': scrape_dmart
    }
    
    scraper = platform_map.get(platform)
    if scraper:
        logging.info(f'[API] Calling scraper for platform: {platform}')
        return scraper(query, location, platform_config, run_parent_folder=run_parent_folder, platform_name=platform)
    else:
        logging.warning(f'[API] No scraper found for platform: {platform}. Available platforms: {list(platform_map.keys())}')
    return []


def scrape_zepto(query, location, platform_config=None, run_parent_folder=None, platform_name='zepto'):
    """Zepto Scraper - Uses Playwright to scrape Zepto website"""
    try:
        if not query:
            logging.warning('[Zepto] Empty query, returning empty list')
            return []
        
        # Get headless setting from config
        if platform_config is None:
            platform_config = get_platform_config('zepto')
        headless = platform_config.get('headless', True)
        
        logging.info(f'[Zepto] Starting scrape for query: "{query}" (headless={headless})')
        
        # Use the Playwright-based scraper from zepto
        raw_products = run_zepto_flow(
            product_name=query,
            location=location,
            headless=headless,
            max_products=50,
            run_parent_folder=run_parent_folder,
            platform_name=platform_name
        )
        
        # Ensure products is a list
        if raw_products is None:
            raw_products = []
        
        # Normalize product data to standard format
        normalized_products = [normalize_product_data(p, platform_name) for p in raw_products]
        
        logging.info(f'[Zepto] Scrape completed: Found {len(normalized_products)} products for query "{query}"')
        return normalized_products
    except ImportError as error:
        logging.error(f'[Zepto] Import error - Playwright may not be installed: {error}')
        import traceback
        logging.error(traceback.format_exc())
        return []
    except Exception as error:
        logging.error(f'[Zepto] Scraping error: {error}')
        import traceback
        logging.error(traceback.format_exc())
        return []


def scrape_instamart(query, location, platform_config=None, run_parent_folder=None, platform_name='zepto'):
    """instamart Scraper - Uses Playwright to scrape instamart website"""
    logging.info(f"[instamart] entered instamart")
    try:
        if not query:
            logging.warning('[instamart] Empty query, returning empty list')
            return []
        
        # Get headless setting from config
        if platform_config is None:
            platform_config = get_platform_config('instamart')
        headless = platform_config.get('headless', True)
        
        logging.info(f'[instamart] Starting scrape for query: "{query}" (headless={headless})')
        
        # Use the Playwright-based scraper from instamart_itemlist
        # JSON saving is handled within run_instamart_flow
        raw_products = run_instamart_flow(
            product_name=query,
            location=location["city"],
            headless=headless,
            max_products=50,
            run_parent_folder=run_parent_folder,
            platform_name=platform_name
        )
        
        # Ensure products is a list
        if raw_products is None:
            raw_products = []
        
        normalized_products = [normalize_product_data(p, platform_name) for p in raw_products]

        logging.info(f'[instamart] Scrape completed: Found {len(normalized_products)} products for query "{query}"')
        return normalized_products
    except ImportError as error:
        logging.error(f'[instamart] Import error - Playwright may not be installed: {error}')
        import traceback
        logging.error(traceback.format_exc())
        return []
    except Exception as error:
        logging.error(f'[instamart] Scraping error: {error}')
        import traceback
        logging.error(traceback.format_exc())
        return []


def scrape_bigbasket(query, location, platform_config=None, run_parent_folder=None, platform_name='bigbasket'):
    """BigBasket Scraper - Uses Playwright to scrape BigBasket website"""
    try:
        if not query:
            logging.warning('[BigBasket] Empty query, returning empty list')
            return []
        
        # Get headless setting from config
        if platform_config is None:
            platform_config = get_platform_config('bigbasket')
        headless = platform_config.get('headless', True)
        
        logging.info(f'[BigBasket] Starting scrape for query: "{query}" (headless={headless})')
        
        # Use the Playwright-based scraper from bigbasket
        raw_products = run_bigbasket_flow(
            product_name=query,
            location=location["city"],
            headless=headless,
            max_products=50,
            run_parent_folder=run_parent_folder,
            platform_name=platform_name
        )
        
        # Ensure products is a list
        if raw_products is None:
            raw_products = []
        
        # Normalize product data to standard format
        normalized_products = [normalize_product_data(p, platform_name) for p in raw_products]
        
        logging.info(f'[BigBasket] Scrape completed: Found {len(normalized_products)} products for query "{query}"')
        return normalized_products
    except ImportError as error:
        logging.error(f'[BigBasket] Import error - Playwright may not be installed: {error}')
        import traceback
        logging.error(traceback.format_exc())
        return []
    except Exception as error:
        logging.error(f'[BigBasket] Scraping error: {error}')
        import traceback
        logging.error(traceback.format_exc())
        return []


def scrape_blinkit(query, location, platform_config=None, run_parent_folder=None, platform_name='blinkit'):
    """Blinkit Scraper - Uses Playwright to scrape Blinkit website"""
    try:
        if not query:
            logging.warning('[Blinkit] Empty query, returning empty list')
            return []
        
        # Get headless setting from config
        if platform_config is None:
            platform_config = get_platform_config('blinkit')
        headless = platform_config.get('headless', True)
        
        logging.info(f'[Blinkit] Starting scrape for query: "{query}" (headless={headless})')
        
        # Use the Playwright-based scraper from blinkit
        raw_products = run_blinkit_flow(
            product_name=query,
            location=location["city"],
            headless=headless,
            max_products=50,
            run_parent_folder=run_parent_folder,
            platform_name=platform_name
        )
        
        # Ensure products is a list
        if raw_products is None:
            raw_products = []
        
        # Normalize product data to standard format
        normalized_products = [normalize_product_data(p, platform_name) for p in raw_products]
        
        logging.info(f'[Blinkit] Scrape completed: Found {len(normalized_products)} products for query "{query}"')
        return normalized_products
    except ImportError as error:
        logging.error(f'[Blinkit] Import error - Playwright may not be installed: {error}')
        import traceback
        logging.error(traceback.format_exc())
        return []
    except Exception as error:
        logging.error(f'[Blinkit] Scraping error: {error}')
        import traceback
        logging.error(traceback.format_exc())
        return []


def scrape_dmart(query, location, platform_config=None, run_parent_folder=None, platform_name='dmart'):
    """Dmart Scraper - Uses Playwright to scrape Dmart website"""
    try:
        if not query:
            logging.warning('[Dmart] Empty query, returning empty list')
            return []
        
        # Get headless setting from config
        if platform_config is None:
            platform_config = get_platform_config('dmart')
        headless = platform_config.get('headless', True)
        
        logging.info(f'[Dmart] Starting scrape for query: "{query}" (headless={headless})')
        
        # Get location - handle both dict and string formats
        if isinstance(location, dict):
            location_name = location.get("city") or location.get("state") or str(location)
        else:
            location_name = str(location)
        
        logging.info(f'[Dmart] Using location: "{location_name}"')
        
        # Use the Playwright-based scraper from dmart
        raw_products = run_dmart_flow(
            product_name=query,
            location=location_name,
            headless=headless,
            max_products=50,
            run_parent_folder=run_parent_folder,
            platform_name=platform_name
        )
        
        # Ensure products is a list
        if raw_products is None:
            raw_products = []
        
        # Normalize product data to standard format
        normalized_products = [normalize_product_data(p, platform_name) for p in raw_products]
        
        logging.info(f'[Dmart] Scrape completed: Found {len(normalized_products)} products for query "{query}"')
        return normalized_products
    except ImportError as error:
        logging.error(f'[Dmart] Import error - Playwright may not be installed: {error}')
        import traceback
        logging.error(traceback.format_exc())
        return []
    except Exception as error:
        logging.error(f'[Dmart] Scraping error: {error}')
        import traceback
        logging.error(traceback.format_exc())
        return []



@app.route('/api/product/<platform>/<product_id>', methods=['GET'])
def get_product_details(platform, product_id):
    """Get product details"""
    # Implement product details fetching
    return jsonify({'product': None})


@app.route('/api/availability', methods=['POST'])
def check_availability():
    """Check availability"""
    data = request.get_json()
    # Implement availability checking
    return jsonify({'available': True})


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'message': 'Server is running'})


@app.route('/api/autocomplete', methods=['GET'])
def geoapify_autocomplete():
    """Proxy Geoapify autocomplete so API key stays on server (reference: server.js)"""
    text = (request.args.get('text') or '').strip()
    if not text:
        return jsonify([])
    if not GEOAPIFY_API_KEY:
        logging.warning('[Geoapify] GEOAPIFY_API_KEY not set')
        return jsonify({'error': 'GEOAPIFY_API_KEY not set. Add it to .env'}), 500
    url = f"https://api.geoapify.com/v1/geocode/autocomplete?text={quote(text)}&format=json&limit=8&filter=countrycode:in&apiKey={GEOAPIFY_API_KEY}"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        return jsonify(data.get('results', []))
    except requests.RequestException as e:
        logging.error(f'[Geoapify] Autocomplete request failed: {e}')
        return jsonify({'error': 'Autocomplete request failed'}), 502


@app.route('/api/geocode/reverse', methods=['GET'])
def geoapify_reverse():
    """Proxy Geoapify reverse geocode for lat/lon -> address (reference: server.js)"""
    lat = request.args.get('lat')
    lon = request.args.get('lon')
    if lat is None or lon is None:
        return jsonify({'error': 'lat and lon required'}), 400
    if not GEOAPIFY_API_KEY:
        return jsonify({'error': 'GEOAPIFY_API_KEY not set'}), 500
    url = f"https://api.geoapify.com/v1/geocode/reverse?lat={lat}&lon={lon}&format=json&apiKey={GEOAPIFY_API_KEY}"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        results = data.get('results', [])
        return jsonify(results[0] if results else {})
    except requests.RequestException as e:
        logging.error(f'[Geoapify] Reverse geocode failed: {e}')
        return jsonify({'error': 'Reverse geocode failed'}), 502


@app.route('/api/config', methods=['GET'])
def get_config():
    """Get current scraping configuration"""
    return jsonify({
        'platform_config': PLATFORM_CONFIG,
        'loaded': True
    })

@app.route('/api/compare', methods=['GET'])
def get_compare_data():
    """Get product comparison data from compare.json"""
    try:
        compare_path = os.path.join(os.path.dirname(__file__), 'compare.json')
        
        if not os.path.exists(compare_path):
            return jsonify({
                'error': 'compare.json not found',
                'message': 'Please run compare.py to generate comparison data'
            }), 404
        
        with open(compare_path, 'r', encoding='utf-8') as f:
            compare_data = json.load(f)
        
        # Return MatchedProduct[] format (same as /api/search endpoint)
        # compare.json already has the correct MatchedProduct format
        matched_products = compare_data.get('products', [])
        
        return jsonify({
            'products': matched_products,  # MatchedProduct[] format
            'search_query': compare_data.get('search_query', ''),
            'total_products': len(matched_products),
            'matched_products': compare_data.get('matched_products', 0),
            'location': compare_data.get('location', {})
        })
    except FileNotFoundError:
        return jsonify({
            'error': 'compare.json not found',
            'message': 'Please run compare.py to generate comparison data'
        }), 404
    except json.JSONDecodeError as e:
        return jsonify({
            'error': 'Invalid JSON in compare.json',
            'message': str(e)
        }), 500
    except Exception as error:
        logging.error(f'[API] Error loading compare.json: {error}')
        import traceback
        logging.error(traceback.format_exc())
        return jsonify({
            'error': 'Failed to load comparison data',
            'message': str(error)
        }), 500


@app.route('/', methods=['GET'])
def root():
    """Root endpoint - API information"""
    return jsonify({
        'message': 'Fast E-commerce API Server (Flask)',
        'version': '1.0.0',
        'endpoints': {
            'search_all': 'POST /api/search',
            'search_platform': 'POST /api/search/<platform>',
            'product_details': 'GET /api/product/<platform>/<product_id>',
            'availability': 'POST /api/availability',
            'health': 'GET /health'
        },
        'supported_platforms': ['zepto', 'swiggy-instamart', 'bigbasket', 'blinkit']
    })


@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    return jsonify({
        'error': 'Not Found',
        'message': 'The requested URL was not found on the server.',
        'available_endpoints': {
            'search_all': 'POST /api/search',
            'search_platform': 'POST /api/search/<platform>',
            'product_details': 'GET /api/product/<platform>/<product_id>',
            'availability': 'POST /api/availability',
            'health': 'GET /health',
            'root': 'GET /'
        }
    }), 404


if __name__ == '__main__':
    print(f'\n{"="*60}')
    print(f'Fast E-commerce API server (Flask)')
    print(f'{"="*60}')
    print(f'Server running on: http://0.0.0.0:{PORT}')
    print(f'Set VITE_API_BASE_URL=http://localhost:{PORT} in your .env file')
    print(f'Logs are being written to: {log_file}')
    print(f'{"="*60}\n')
    
    logging.info(f'Fast E-commerce API server (Flask) running on port {PORT}')
    logging.info(f'Logs are being written to: {log_file}')
    logging.info(f'Set VITE_API_BASE_URL=http://localhost:{PORT} in your .env file')
    logging.info(f'[Config] Search Debug: {"[OK] ENABLED (timestamped folders)" if SEARCH_DEBUG else "[X] DISABLED (overwrite mode)"}')
    logging.info('[Config] Platform scraping configuration:')
    for platform, config in PLATFORM_CONFIG.items():
        status = '[OK] ENABLED' if config.get('scrape', False) else '[X] DISABLED'
        headless = 'headless' if config.get('headless', True) else 'visible'
        logging.info(f'  {platform}: {status} ({headless})')
    # Ensure stdout is unbuffered for immediate log display
    sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None
    
    app.run(host='0.0.0.0', port=PORT, debug=True, use_reloader=False)


