// Adapted from web src/services/locationService.ts
// Key change: navigator.geolocation replaced with expo-location
// Everything else (address parsing, Geoapify integration) is identical

import * as ExpoLocation from 'expo-location';
import { Alert, Linking } from 'react-native';
import { LocationData } from '../types/product';
import { reverseGeocode, type GeoapifyResult } from './geoapifyService';

export class LocationService {
  /**
   * Request location permission from the OS
   */
  static async requestPermission(): Promise<boolean> {
    console.log('[LocationService] Requesting foreground permissions...');
    const { status, canAskAgain } = await ExpoLocation.requestForegroundPermissionsAsync();
    console.log(`[LocationService] Permission status: ${status}, canAskAgain: ${canAskAgain}`);

    if (status !== 'granted') {
      if (!canAskAgain) {
        Alert.alert(
          'Location Permission Required',
          'Please enable location access in your phone settings to use this feature.',
          [
            { text: 'Cancel', style: 'cancel' },
            { text: 'Open Settings', onPress: () => Linking.openSettings() }
          ]
        );
      }
      return false;
    }
    return true;
  }

  /**
   * Get current device location (uses expo-location instead of navigator.geolocation)
   */
  static async getCurrentLocation(): Promise<LocationData> {
    console.log('[LocationService] getCurrentLocation called');
    try {
      const hasPermission = await this.requestPermission();
      if (!hasPermission) {
        console.warn('[LocationService] Permission denied. Falling back to default location.');
        return this.getDefaultLocation();
      }

      console.log('[LocationService] Permission granted. Fetching GPS coordinates via ExpoLocation...');
      const position = await ExpoLocation.getCurrentPositionAsync({
        accuracy: ExpoLocation.Accuracy.Balanced,
      });

      const { latitude, longitude } = position.coords;
      console.log(`[LocationService] Received raw coordinates - Lat: ${latitude}, Lng: ${longitude}`);

      try {
        console.log(`[LocationService] Attempting to reverse geocode Lat: ${latitude}, Lng: ${longitude}...`);
        const result = await reverseGeocode(latitude, longitude);
        if (result) {
          console.log('[LocationService] Reverse geocode successful:', result);
          const city = result.city || 'Mumbai';
          const area = result.address_line1 || '';
          const displayName = area && area !== city
            ? `${area}, ${city}`
            : city;
          const finalLocData = {
            city,
            state: result.state || 'Maharashtra',
            country: result.country || 'India',
            displayName,
            coordinates: { lat: latitude, lng: longitude },
          };
          console.log('[LocationService] Returning formatted LocationData:', finalLocData);
          return finalLocData;
        } else {
          console.log('[LocationService] Reverse geocode returned null/empty.');
        }
      } catch (e) {
        console.warn('[LocationService] Reverse geocode threw an error:', e);
      }

      console.log('[LocationService] Falling back to coordinate-based mapping (No exact geocode match).');
      const fallbackResult = {
        ...this.getCoordBasedLocation(latitude, longitude),
        coordinates: { lat: latitude, lng: longitude },
      };
      console.log('[LocationService] Returning fallback result:', fallbackResult);
      return fallbackResult;
    } catch (error) {
      console.warn('[LocationService] Location error catch block hit:', error);
      return this.getDefaultLocation();
    }
  }

  /**
   * Convert a selected Geoapify address to LocationData
   * Identical logic to web version
   */
  static async convertAddressToLocationData(
    address: string,
    lat: number,
    lng: number,
    options?: { city?: string; state?: string; country?: string }
  ): Promise<LocationData> {
    if (options?.city || options?.state || options?.country) {
      // Build a displayName from the raw address + city
      const city = options.city || 'Mumbai';
      const addressLine = address.split(',')[0]?.trim() || '';
      const displayName = addressLine && addressLine !== city
        ? `${addressLine}, ${city}`
        : city;
      return {
        city,
        state: options.state || 'Maharashtra',
        country: options.country || 'India',
        displayName,
        coordinates: { lat, lng },
      };
    }
    try {
      const result = await reverseGeocode(lat, lng);
      if (result) {
        const city = result.city || 'Mumbai';
        const area = result.address_line1 || '';
        const displayName = area && area !== city ? `${area}, ${city}` : city;
        return {
          city,
          state: result.state || 'Maharashtra',
          country: result.country || 'India',
          displayName,
          coordinates: { lat, lng },
        };
      }
    } catch (e) {
      console.warn('[LocationService] Reverse geocode failed:', e);
    }
    const parsed = this.parseLocationFromAddress(address);
    return { ...parsed, displayName: address.split(',')[0]?.trim() || parsed.city, coordinates: { lat, lng } };
  }

  static getLocationString(location: LocationData): string {
    return location.displayName || `${location.city}, ${location.state}`;
  }

  private static getDefaultLocation(): LocationData {
    return { city: 'Mumbai', state: 'Maharashtra', country: 'India' };
  }

  private static parseLocationFromAddress(address: string): LocationData {
    const parts = address.split(',').map(p => p.trim());
    if (parts.length >= 2) {
      return {
        city: parts[parts.length - 3] || parts[parts.length - 2] || 'Mumbai',
        state: parts[parts.length - 2] || 'Maharashtra',
        country: parts[parts.length - 1] || 'India',
      };
    }
    return { city: parts[0] || 'Mumbai', state: 'Maharashtra', country: 'India' };
  }

  // Fallback coordinate-based city detection (same as web)
  private static getCoordBasedLocation(lat: number, lng: number): LocationData {
    if (lat > 19 && lat < 20 && lng > 72 && lng < 73) return { city: 'Mumbai', state: 'Maharashtra', country: 'India' };
    if (lat > 28 && lat < 29 && lng > 76 && lng < 78) return { city: 'Delhi', state: 'Delhi', country: 'India' };
    if (lat > 12 && lat < 13 && lng > 77 && lng < 78) return { city: 'Bangalore', state: 'Karnataka', country: 'India' };
    if (lat > 17 && lat < 19 && lng > 73 && lng < 74) return { city: 'Pune', state: 'Maharashtra', country: 'India' };
    return { city: 'Mumbai', state: 'Maharashtra', country: 'India' };
  }
}
