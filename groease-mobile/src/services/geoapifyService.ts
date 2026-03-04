// Adapted from web src/services/geoapifyService.ts
// Change: removed import.meta.env — uses config.ts instead

import { API_BASE_URL } from '../config';

export interface GeoapifyResult {
  lat: number;
  lon: number;
  formatted?: string;
  address_line1?: string;
  address_line2?: string;
  city?: string;
  state?: string;
  postcode?: string;
  country?: string;
  [key: string]: unknown;
}

/**
 * Fetch location autocomplete suggestions (proxied through Flask backend)
 */
export async function fetchAutocomplete(text: string): Promise<GeoapifyResult[]> {
  console.log(`[GeoapifyService] fetchAutocomplete called with text: "${text}"`);
  const url = `${API_BASE_URL}/api/autocomplete?text=${encodeURIComponent(text.trim())}`;
  console.log(`[GeoapifyService] Sending GET request to: ${url}`);
  try {
    const res = await fetch(url, { method: 'GET' });
    console.log(`[GeoapifyService] Received response status: ${res.status} ${res.statusText}`);

    if (!res.ok) {
      console.error(`[GeoapifyService] Request failed with status code ${res.status}`);
      if (res.status === 500) {
        const err = await res.json().catch(() => ({}));
        console.error(`[GeoapifyService] Extracted 500 error body:`, err);
        throw new Error((err as any)?.error || 'Geoapify autocomplete not configured');
      }
      throw new Error(`Autocomplete failed: ${res.statusText}`);
    }
    const data = await res.json();
    console.log(`[GeoapifyService] Successfully parsed JSON. Found ${Array.isArray(data) ? data.length : 'unknown'} results.`);
    return Array.isArray(data) ? data : [];
  } catch (error) {
    console.error(`[GeoapifyService] Exception during autocomplete fetch:`, error);
    throw error;
  }
}

/**
 * Reverse geocode: lat/lon -> address (proxied through Flask backend)
 */
export async function reverseGeocode(lat: number, lon: number): Promise<GeoapifyResult | null> {
  console.log(`[GeoapifyService] reverseGeocode called with lat: ${lat}, lon: ${lon}`);
  const url = `${API_BASE_URL}/api/geocode/reverse?lat=${lat}&lon=${lon}`;
  console.log(`[GeoapifyService] Sending GET request to: ${url}`);
  try {
    const res = await fetch(url, { method: 'GET' });
    console.log(`[GeoapifyService] Received reverse geocode response status: ${res.status} ${res.statusText}`);

    if (!res.ok) {
      console.error(`[GeoapifyService] Reverse geocode request failed with status code ${res.status}`);
      return null;
    }
    const data = await res.json();
    console.log(`[GeoapifyService] Successfully parsed reverse geocode JSON:`, data);
    return data && (data.lat != null || data.lon != null) ? (data as GeoapifyResult) : null;
  } catch (error) {
    console.error(`[GeoapifyService] Exception during reverse geocode fetch:`, error);
    return null;
  }
}
