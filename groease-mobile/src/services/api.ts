// Adapted from web src/services/fastEcommerceAPI.ts
// Changes:
//   - Removed import.meta.env — uses config.ts
//   - Renamed class to GroeaseAPI for clarity
//   - Removed unused getProductDetails / checkAvailability stubs

import { Platform, LocationData, MatchedProduct } from '../types/product';
import { API_BASE_URL } from '../config';

export class GroeaseAPI {
  /**
   * Search products across all selected platforms.
   * Triggers backend scraping → comparison → returns MatchedProduct[]
   */
  static async searchProducts(
    query: string,
    location: LocationData,
    platforms: Platform[]
  ): Promise<MatchedProduct[]> {
    if (!query.trim()) return [];

    try {
      const products = await this.searchViaBackendAPI(query, location, platforms);

      if (products && products.length > 0) {
        // Filter to only the requested platforms within each matched product
        return products
          .map(matchedProduct => {
            const filteredPlatforms: Record<Platform, any> = {} as any;
            const filteredOriginalNames: Record<Platform, string> = {} as any;

            Object.keys(matchedProduct.platforms || {}).forEach(platform => {
              if (platforms.includes(platform as Platform)) {
                filteredPlatforms[platform as Platform] = matchedProduct.platforms[platform as Platform];
                if (matchedProduct.original_names?.[platform as Platform]) {
                  filteredOriginalNames[platform as Platform] = matchedProduct.original_names[platform as Platform];
                }
              }
            });

            return {
              ...matchedProduct,
              platforms: filteredPlatforms,
              original_names: filteredOriginalNames,
            };
          })
          .filter(p => Object.keys(p.platforms).length > 0);
      }

      return [];
    } catch (error) {
      console.error('[GroeaseAPI] Search error:', error);
      return [];
    }
  }

  private static async searchViaBackendAPI(
    query: string,
    location: LocationData,
    platforms: Platform[]
  ): Promise<MatchedProduct[]> {
    const url = `${API_BASE_URL}/api/search`;

    const payload = {
      query,
      location: {
        address: (location as any).address || `${location.city}, ${location.state}`,
        city: location.city,
        state: location.state,
        country: location.country || 'India',
        coordinates: location.coordinates,
      },
      platforms,
    };

    console.log(`[GroeaseAPI] Sending search POST to ${url}`);
    console.log(`[GroeaseAPI] Payload:`, JSON.stringify(payload, null, 2));

    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    console.log(`[GroeaseAPI] Received response status: ${response.status} ${response.statusText}`);

    if (!response.ok) {
      const errText = await response.text();
      console.error(`[GroeaseAPI] API Error details:`, errText);
      throw new Error(`API request failed: ${response.statusText}`);
    }

    const data = await response.json();
    console.log(`[GroeaseAPI] Successfully parsed JSON. Received ${data.products?.length || 0} products.`);
    return data.products || [];
  }
}
