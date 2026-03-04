// Location picker modal
// Two ways to set location:
//   1. "Use my current location" — GPS via expo-location + reverse geocode
//   2. Type to search — Geoapify autocomplete

import React, { useState, useEffect, useRef } from 'react';
import {
  Modal,
  View,
  Text,
  TextInput,
  TouchableOpacity,
  FlatList,
  ActivityIndicator,
  StyleSheet,
  KeyboardAvoidingView,
  Platform as RNPlatform,
} from 'react-native';
import { fetchAutocomplete, type GeoapifyResult } from '../services/geoapifyService';
import { LocationService } from '../services/locationService';

interface LocationModalProps {
  visible: boolean;
  onSelect: (location: {
    address: string;
    lat: number;
    lng: number;
    city?: string;
    state?: string;
    country?: string;
  }) => void;
  onClose?: () => void;
}

export function LocationModal({ visible, onSelect, onClose }: LocationModalProps) {
  const [query, setQuery] = useState('');
  const [suggestions, setSuggestions] = useState<GeoapifyResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [gpsLoading, setGpsLoading] = useState(false);
  const inputRef = useRef<TextInput>(null);

  // Debounced autocomplete
  useEffect(() => {
    console.log(`[LocationModal] Input query changed to: "${query}"`);
    if (!query.trim()) {
      setSuggestions([]);
      return;
    }

    const delay = setTimeout(() => {
      console.log(`[LocationModal] Triggering autocomplete fetch for exactly: "${query}"`);
      setLoading(true);
      fetchAutocomplete(query)
        .then(results => {
          console.log(`[LocationModal] Autocomplete returned ${results.length} suggestions.`);
          setSuggestions(results);
        })
        .catch(err => {
          console.warn('[LocationModal] Autocomplete error hit in Modal catch block:', err);
          setSuggestions([]);
        })
        .finally(() => {
          console.log('[LocationModal] Autocomplete finally block, stopping loading indicator.');
          setLoading(false);
        });
    }, 400);

    return () => clearTimeout(delay);
  }, [query]);

  const handleSelect = (result: GeoapifyResult) => {
    console.log('[LocationModal] User selected Geoapify suggestion:', result);
    const lat = result.lat ?? 0;
    const lon = result.lon ?? 0;
    const address =
      result.formatted ||
      [result.address_line1, result.address_line2].filter(Boolean).join(', ') ||
      `${result.city || ''}, ${result.state || ''}`.trim() ||
      'Unknown';

    console.log(`[LocationModal] Passing selected location to parent - Address: "${address}", Lat: ${lat}, Lng: ${lon}`);
    onSelect({ address, lat, lng: lon, city: result.city, state: result.state, country: result.country });
    setQuery('');
    setSuggestions([]);
  };

  const handleUseCurrentLocation = async () => {
    console.log('[LocationModal] handleUseCurrentLocation (GPS) button pressed');
    setGpsLoading(true);
    try {
      const loc = await LocationService.getCurrentLocation();
      console.log('[LocationModal] Successfully retrieved LocationData from LocationService:', loc);
      onSelect({
        address: `${loc.city}, ${loc.state}`,
        lat: loc.coordinates?.lat ?? 0,
        lng: loc.coordinates?.lng ?? 0,
        city: loc.city,
        state: loc.state,
        country: loc.country,
      });
      setQuery('');
      setSuggestions([]);
    } catch (e) {
      console.warn('[LocationModal] Final GPS error trapped in Modal catch block:', e);
    } finally {
      console.log('[LocationModal] GPS loading indicator turned off');
      setGpsLoading(false);
    }
  };

  return (
    <Modal
      visible={visible}
      animationType="slide"
      transparent
      statusBarTranslucent
      onShow={() => {
        setTimeout(() => inputRef.current?.focus(), 300);
      }}
    >
      <KeyboardAvoidingView
        style={styles.overlay}
        behavior={RNPlatform.OS === 'ios' ? 'padding' : 'height'}
        keyboardVerticalOffset={0}
      >
        <View style={styles.sheet}>
          {/* Header */}
          <View style={styles.header}>
            <View style={styles.headerRow}>
              <View style={{ flex: 1 }}>
                <Text style={styles.title}>Set Your Location</Text>
                <Text style={styles.subtitle}>
                  Provide your delivery location to see products
                </Text>
              </View>
              {onClose && (
                <TouchableOpacity onPress={onClose} style={styles.closeBtn} activeOpacity={0.7}>
                  <Text style={styles.closeBtnText}>✕</Text>
                </TouchableOpacity>
              )}
            </View>
          </View>

          {/* Use current location button */}
          <TouchableOpacity
            style={styles.gpsButton}
            onPress={handleUseCurrentLocation}
            activeOpacity={0.75}
            disabled={gpsLoading}
          >
            {gpsLoading ? (
              <ActivityIndicator size="small" color="#059669" />
            ) : (
              <Text style={styles.gpsIcon}>📍</Text>
            )}
            <Text style={styles.gpsText}>
              {gpsLoading ? 'Detecting location...' : 'Use my current location'}
            </Text>
          </TouchableOpacity>

          {/* Divider */}
          <View style={styles.dividerRow}>
            <View style={styles.dividerLine} />
            <Text style={styles.dividerText}>or search</Text>
            <View style={styles.dividerLine} />
          </View>

          {/* Search input */}
          <View style={styles.inputWrapper}>
            <TextInput
              ref={inputRef}
              style={styles.input}
              value={query}
              onChangeText={setQuery}
              placeholder="Search delivery location"
              placeholderTextColor="#93C5FD"
              autoCorrect={false}
              autoCapitalize="none"
              returnKeyType="search"
            />
            {loading && (
              <ActivityIndicator style={styles.spinner} size="small" color="#2563EB" />
            )}
          </View>

          {/* Suggestions */}
          <FlatList
            data={suggestions}
            keyExtractor={(item, idx) => `${item.lat}-${item.lon}-${idx}`}
            keyboardShouldPersistTaps="always"
            keyboardDismissMode="none"
            style={styles.list}
            contentContainerStyle={styles.listContent}
            renderItem={({ item }) => (
              <TouchableOpacity
                style={styles.suggestionItem}
                onPress={() => handleSelect(item)}
                activeOpacity={0.7}
              >
                <Text style={styles.suggestionMain}>
                  {item.address_line1 || item.city || item.formatted || 'Address'}
                </Text>
                <Text style={styles.suggestionSub}>
                  {[item.city, item.state, item.country].filter(Boolean).join(', ') || item.formatted}
                </Text>
              </TouchableOpacity>
            )}
            ListEmptyComponent={
              !loading && query.trim().length > 0 ? (
                <Text style={styles.emptyText}>No results found</Text>
              ) : null
            }
          />
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.5)',
    justifyContent: 'flex-end',
  },
  sheet: {
    backgroundColor: '#FFFFFF',
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    maxHeight: '90%',
    paddingBottom: RNPlatform.OS === 'android' ? 16 : 32,
    overflow: 'hidden',
  },
  header: {
    backgroundColor: '#1D4ED8',
    paddingHorizontal: 20,
    paddingTop: 24,
    paddingBottom: 20,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
  },
  closeBtn: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: 'rgba(255,255,255,0.2)',
    alignItems: 'center',
    justifyContent: 'center',
    marginLeft: 8,
    marginTop: 2,
  },
  closeBtnText: { fontSize: 16, color: '#FFFFFF', fontWeight: '700' },
  title: { fontSize: 20, fontWeight: '800', color: '#FFFFFF' },
  subtitle: { fontSize: 13, color: '#BFDBFE', marginTop: 4 },

  // GPS button
  gpsButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    marginHorizontal: 20,
    marginTop: 16,
    paddingHorizontal: 16,
    paddingVertical: 13,
    backgroundColor: '#ECFDF5',
    borderRadius: 12,
    borderWidth: 1.5,
    borderColor: '#6EE7B7',
  },
  gpsIcon: { fontSize: 18 },
  gpsText: {
    fontSize: 15,
    fontWeight: '700',
    color: '#059669',
  },

  // Divider
  dividerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginHorizontal: 20,
    marginTop: 16,
    gap: 10,
  },
  dividerLine: { flex: 1, height: 1, backgroundColor: '#E5E7EB' },
  dividerText: { fontSize: 12, fontWeight: '600', color: '#9CA3AF' },

  // Search input
  inputWrapper: {
    paddingHorizontal: 20,
    paddingTop: 12,
    paddingBottom: 8,
  },
  input: {
    height: 48,
    borderWidth: 2,
    borderColor: '#BFDBFE',
    borderRadius: 10,
    paddingHorizontal: 16,
    fontSize: 15,
    color: '#111827',
    backgroundColor: '#F8FAFF',
  },
  spinner: { position: 'absolute', right: 32, top: 24 },

  list: { flexGrow: 0, paddingHorizontal: 20, maxHeight: 260 },
  listContent: { paddingBottom: 8 },
  suggestionItem: {
    paddingVertical: 14,
    borderBottomWidth: 1,
    borderBottomColor: '#EFF6FF',
  },
  suggestionMain: { fontSize: 14, fontWeight: '600', color: '#111827' },
  suggestionSub: { fontSize: 12, color: '#2563EB', marginTop: 2 },
  emptyText: {
    textAlign: 'center',
    color: '#9CA3AF',
    fontSize: 14,
    paddingVertical: 20,
  },
});
