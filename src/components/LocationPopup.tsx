import { useEffect, useState } from "react";
import { fetchAutocomplete, reverseGeocode, type GeoapifyResult } from "../services/geoapifyService";

interface LocationResult {
  address: string;
  lat: number;
  lng: number;
  city?: string;
  state?: string;
  country?: string;
}

interface LocationPopupProps {
  onClose: (location: LocationResult) => void;
  onDismiss?: () => void; // Optional: only provided when user already has a location
}

export const LocationPopup = ({ onClose, onDismiss }: LocationPopupProps) => {
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState<GeoapifyResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [gpsLoading, setGpsLoading] = useState(false);
  const [gpsError, setGpsError] = useState("");

  // Fetch suggestions when query changes (Geoapify autocomplete via backend)
  useEffect(() => {
    if (!query.trim()) {
      setSuggestions([]);
      return;
    }

    const delay = setTimeout(() => {
      fetchAutocomplete(query)
        .then(setSuggestions)
        .catch((err) => {
          console.warn("[LocationPopup] Autocomplete error:", err);
          setSuggestions([]);
        });
    }, 400);

    return () => clearTimeout(delay);
  }, [query]);

  const handleSelect = (result: GeoapifyResult) => {
    setLoading(true);
    const lat = result.lat ?? 0;
    const lon = result.lon ?? 0;
    const address = result.formatted || [result.address_line1, result.address_line2].filter(Boolean).join(", ") || `${result.city || ""}, ${result.state || ""}`.trim() || "Unknown";
    onClose({
      address,
      lat,
      lng: lon,
      city: result.city,
      state: result.state,
      country: result.country,
    });
    setLoading(false);
  };

  const handleUseCurrentLocation = () => {
    if (!navigator.geolocation) {
      setGpsError("Geolocation is not supported by your browser.");
      return;
    }
    setGpsLoading(true);
    setGpsError("");
    navigator.geolocation.getCurrentPosition(
      async (position) => {
        const { latitude, longitude } = position.coords;
        try {
          const result = await reverseGeocode(latitude, longitude);
          if (result) {
            const address = result.formatted ||
              [result.address_line1, result.address_line2].filter(Boolean).join(", ") ||
              `${result.city || ""}, ${result.state || ""}`.trim() ||
              "Current Location";
            onClose({
              address,
              lat: latitude,
              lng: longitude,
              city: result.city,
              state: result.state,
              country: result.country,
            });
          } else {
            onClose({
              address: "Current Location",
              lat: latitude,
              lng: longitude,
            });
          }
        } catch (e) {
          console.warn("[LocationPopup] Reverse geocode failed:", e);
          onClose({
            address: "Current Location",
            lat: latitude,
            lng: longitude,
          });
        } finally {
          setGpsLoading(false);
        }
      },
      (error) => {
        setGpsLoading(false);
        if (error.code === error.PERMISSION_DENIED) {
          setGpsError("Location access denied. Please allow location access and try again.");
        } else {
          setGpsError("Could not get your location. Please search manually.");
        }
      },
      { timeout: 10000 }
    );
  };

  return (
    <div
      className="fixed inset-0 flex items-center justify-center p-4"
      style={{
        zIndex: 9999,
        backgroundColor: "rgba(0,0,0,0.4)",
      }}
    >
      <div
        className="bg-white w-full max-w-[420px] rounded-lg shadow-xl border border-blue-100 overflow-hidden"
        style={{ position: "relative", zIndex: 10000 }}
      >
        <div className="bg-gradient-to-r from-blue-600 to-blue-700 px-6 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-xl font-bold text-white">Set Your Location</h2>
              <p className="text-sm text-blue-100 mt-1">
                Provide your delivery location to see products
              </p>
            </div>
            {/* Close button — only shown when user already has a location */}
            {onDismiss && (
              <button
                onClick={onDismiss}
                className="ml-4 text-white/80 hover:text-white transition-colors p-1 rounded hover:bg-white/20"
                aria-label="Close"
              >
                <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                </svg>
              </button>
            )}
          </div>
        </div>

        <div className="p-6">
          {/* GPS Button */}
          <button
            onClick={handleUseCurrentLocation}
            disabled={gpsLoading || loading}
            className="w-full flex items-center justify-center gap-2 mb-4 px-4 py-3 bg-blue-50 hover:bg-blue-100 border-2 border-blue-200 hover:border-blue-400 rounded-lg text-blue-700 font-medium text-sm transition-all disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {gpsLoading ? (
              <>
                <div className="h-4 w-4 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
                <span>Getting location...</span>
              </>
            ) : (
              <>
                <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M5.05 4.05a7 7 0 119.9 9.9L10 18.9l-4.95-4.95a7 7 0 010-9.9zM10 11a2 2 0 100-4 2 2 0 000 4z" clipRule="evenodd" />
                </svg>
                <span>Use my current location</span>
              </>
            )}
          </button>

          {gpsError && (
            <p className="text-xs text-red-600 mb-3 text-center">{gpsError}</p>
          )}

          <div className="relative flex items-center gap-2 mb-1">
            <div className="flex-1 border-t border-gray-200" />
            <span className="text-xs text-gray-400 px-2">or search manually</span>
            <div className="flex-1 border-t border-gray-200" />
          </div>

          <div className="relative mt-3">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search delivery location"
              className="w-full border-2 border-blue-200 focus:border-blue-500 focus:ring-2 focus:ring-blue-200 px-4 py-3 rounded-lg text-sm transition-colors outline-none"
              disabled={loading || gpsLoading}
            />
            {loading && (
              <div className="absolute right-3 top-1/2 -translate-y-1/2">
                <div className="h-4 w-4 border-2 border-blue-600 border-t-transparent rounded-full animate-spin"></div>
              </div>
            )}
          </div>

          {suggestions.length > 0 && (
            <div className="border-2 border-blue-100 rounded-lg mt-3 max-h-60 overflow-y-auto bg-white shadow-lg">
              {suggestions.map((item, idx) => (
                <div
                  key={`${item.lat}-${item.lon}-${idx}`}
                  onClick={() => handleSelect(item)}
                  className="px-4 py-3 cursor-pointer hover:bg-blue-50 border-b border-blue-50 last:border-b-0 transition-colors"
                >
                  <p className="font-medium text-sm text-gray-900">
                    {item.address_line1 || item.city || item.formatted || "Address"}
                  </p>
                  <p className="text-xs text-blue-600 mt-0.5">
                    {[item.city, item.state, item.country].filter(Boolean).join(", ") || item.formatted}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
