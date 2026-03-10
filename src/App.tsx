import { useState, useEffect } from 'react';
import { SearchBar } from './components/SearchBar';
import { ProductComparisonTable } from './components/ProductComparisonTable';
import { LocationDisplay } from './components/LocationDisplay';
import { LocationPopup } from './components/LocationPopup';
import { Footer } from './components/Footer';
import { LocationService } from './services/locationService';
import { ProductService } from './services/productService';
import { LocationData, ComparisonFilters, MatchedProduct, Platform } from './types/product';
import { Loader2, Sparkles, ShoppingCart, Clock, Banknote, Package, Search, GitCompare, SlidersHorizontal } from 'lucide-react';
import { Badge } from './components/ui/badge';
import { Button } from './components/ui/button';

type SortOption = 'best-match' | 'price-low' | 'price-high';
import groeaseLogo from './images/groease_logo_crop.jpg';
import groeaseCenter from './images/groease.jpeg';
import groeaseBanner from './images/Groease_banner.png';
import groeaseBanner2 from './images/Groease_banner_2 .png';
import groeaseBanner3 from './images/Groease_banner_3.png';
import groeaseBanner4 from './images/Groease_banner_4.png';

const BANNER_SLIDES = [
  { src: groeaseBanner, alt: 'Groease — As seen on Ideabaaz. One app, endless ease.' },
  { src: groeaseBanner2, alt: 'Groease — As seen on Ideabaaz. Youngest contestant.' },
  { src: groeaseBanner3, alt: 'Groease — As seen on Ideabaaz. Real titans, real solution.' },
  { src: groeaseBanner4, alt: 'Groease — As seen on Ideabaaz. One app, endless ease.' },
];

const BANNER_INTERVAL_MS = 5000;

function App() {
  const [location, setLocation] = useState<LocationData | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [products, setProducts] = useState<MatchedProduct[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchProgress, setSearchProgress] = useState(0);
  const [showLocationPopup, setShowLocationPopup] = useState(true); // Show popup by default
  const [bannerIndex, setBannerIndex] = useState(0);
  const [sortBy, setSortBy] = useState<SortOption>('best-match');
  const [minPrice, setMinPrice] = useState('');
  const [maxPrice, setMaxPrice] = useState('');

  // Default platforms to search (no filters panel, so hardcoded)
  const defaultPlatforms: Platform[] = ['zepto', 'blinkit', 'swiggy-instamart', 'bigbasket', 'dmart'];

  // Progress bar animation effect - uses easing curve that progresses over 40s then stops at 90%
  useEffect(() => {
    if (!loading) {
      setSearchProgress(0);
      return;
    }

    const startTime = Date.now();
    // Progress over 40 seconds to reach 90%
    const durationTo90 = 20000; // 40 seconds to reach 90%
    
    // Easing function: ease-in-out cubic for realistic progress
    const easeInOutCubic = (t: number): number => {
      return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
    };

    const interval = setInterval(() => {
      const elapsed = Date.now() - startTime;
      const progress = Math.min(elapsed / durationTo90, 1); // Progress over 40s
      const easedProgress = easeInOutCubic(progress);
      // Cap at 90% and hold there until search completes
      setSearchProgress(Math.min(easedProgress * 90, 90));
    }, 100); // Update every 100ms for smooth animation

    return () => clearInterval(interval);
  }, [loading]);

  useEffect(() => {
    if (location) {
      // Search products whenever location, query, or filters change
      const searchProducts = async () => {
        console.log('[App] useEffect triggered - searching:', {
          searchQuery,
          location,
          platforms: defaultPlatforms,
        });
        
        // Don't search if query is empty
        if (!searchQuery.trim()) {
          console.log('[App] Empty query, skipping search');
          setProducts([]);
          setLoading(false);
          setSearchProgress(0);
          return;
        }
        
        setLoading(true);
        setSearchProgress(0);
        try {
          // Use default filters with hardcoded platforms
          const defaultFilters: ComparisonFilters = {
            platforms: defaultPlatforms,
            sortBy: 'price-low',
          };
          const results = await ProductService.searchProducts(searchQuery, location, defaultFilters);
          console.log('[App] Search results:', results.length, 'products');
          setProducts(results);
          setSearchProgress(100); // Complete the progress bar
          // Wait a moment to show 100% before hiding
          setTimeout(() => {
            setLoading(false);
            setSearchProgress(0);
          }, 500);
        } catch (error) {
          console.error('[App] Error searching products:', error);
          setProducts([]);
          setLoading(false);
          setSearchProgress(0);
        }
      };
      searchProducts();
    }
  }, [location, searchQuery]);

  // Banner slideshow auto-advance
  useEffect(() => {
    const id = setInterval(() => {
      setBannerIndex((i) => (i + 1) % BANNER_SLIDES.length);
    }, BANNER_INTERVAL_MS);
    return () => clearInterval(id);
  }, []);

  const handleSearch = (query: string) => {
    console.log('[App] handleSearch called with query:', query);
    setSearchQuery(query);
  };

  const handleRefreshLocation = () => {
    setShowLocationPopup(true);
  };

  const handleLocationSet = async (locationData: { address: string; lat: number; lng: number; city?: string; state?: string; country?: string }) => {
    // Location is mandatory - don't allow closing without setting location
    if (!locationData.address || locationData.lat === 0 || locationData.lng === 0) {
      return; // Don't close popup if location is not set
    }

    setLoading(true);
    try {
      // Convert address + optional Geoapify city/state/country to LocationData format
      const locationDataFormatted = await LocationService.convertAddressToLocationData(
        locationData.address,
        locationData.lat,
        locationData.lng,
        locationData.city != null || locationData.state != null || locationData.country != null
          ? { city: locationData.city, state: locationData.state, country: locationData.country }
          : undefined
      );
      
      setLocation(locationDataFormatted);
      localStorage.setItem('userLocation', JSON.stringify(locationDataFormatted));
      setShowLocationPopup(false);
    } catch (error) {
      console.error('Error setting location:', error);
    } finally {
      setLoading(false);
    }
  };

  // Apply client-side price filter
  const filteredProducts = products.filter((p) => {
    const prices = Object.values(p.platforms || {}).map((pd) => pd.price);
    const lowestPrice = prices.length > 0 ? Math.min(...prices) : 0;
    if (minPrice && lowestPrice < Number(minPrice)) return false;
    if (maxPrice && lowestPrice > Number(maxPrice)) return false;
    return true;
  });

  if (loading && !location) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-white via-blue-50/30 to-white">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 animate-spin text-blue-600" />
          <p className="text-blue-700 font-medium">Loading your location...</p>
        </div>
      </div>
    );
  }

  // Debug: Log popup state
  console.log('[App] Render - showLocationPopup:', showLocationPopup, 'location:', location);

  return (
    <div className="min-h-screen flex flex-col bg-gradient-to-br from-white via-blue-50/30 to-white">
      {/* Location Popup - Must render first */}
      {showLocationPopup && (
        <LocationPopup
          onClose={handleLocationSet}
          onDismiss={location ? () => setShowLocationPopup(false) : undefined}
        />
      )}

      {/* GROEASE Header with Logo */}
      <header id="search-area" className="bg-gradient-to-r from-white via-blue-50/40 to-white border-b border-blue-100 shadow-sm sticky top-0 z-40 backdrop-blur-sm">
        <div className="container mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6">
            <div className="flex flex-col sm:flex-row items-start sm:items-center gap-3 sm:gap-4">
              <img 
                src={groeaseLogo} 
                alt="GROEASE Logo" 
                className="h-24 w-auto object-contain"
              />
              <Badge variant="outline" className="bg-yellow-50 border-yellow-300 text-yellow-700 text-[10px] sm:text-xs font-medium whitespace-nowrap">
                Beta
              </Badge>
            </div>
            {location && <LocationDisplay location={location} onRefresh={handleRefreshLocation} />}
          </div>
          <SearchBar onSearch={handleSearch} />
        </div>
      </header>

      {/* Main Content */}
      <main className="container mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {loading && searchQuery && location && (
          <div className="mb-8 py-8">
            <div className="max-w-2xl mx-auto">
              <div className="mb-4">
                <div className="flex items-center justify-between mb-2">
                  <p className="text-blue-700 font-medium">Searching for products...</p>
                  <span className="text-blue-600 text-sm font-medium">{Math.round(searchProgress)}%</span>
                </div>
                <div className="w-full bg-blue-100 rounded-full h-2.5 overflow-hidden">
                  <div
                    className="bg-gradient-to-r from-blue-500 to-blue-600 h-2.5 rounded-full transition-all duration-300 ease-out"
                    style={{ width: `${searchProgress}%` }}
                  />
                </div>
              </div>
            </div>
          </div>
        )}
        
        {!loading && searchQuery && (
          <div className="mb-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-3">
              <p className="text-blue-700 text-sm">
                Found <span className="font-semibold text-blue-900">{filteredProducts.length}</span>
                {products.length !== filteredProducts.length && (
                  <span className="text-blue-500"> (of {products.length})</span>
                )}
                {' '}product{filteredProducts.length !== 1 ? 's' : ''} for <span className="font-medium">"{searchQuery}"</span>
              </p>
            </div>

            {/* Filter bar */}
            {products.length > 0 && (
              <div className="flex flex-wrap items-center gap-3 p-3 bg-blue-50/60 border border-blue-100 rounded-lg">
                <div className="flex items-center gap-1.5 text-blue-700 text-xs font-semibold">
                  <SlidersHorizontal className="h-3.5 w-3.5" />
                  <span>Filters</span>
                </div>

                {/* Sort */}
                <div className="flex items-center gap-2">
                  <label className="text-xs text-gray-600 font-medium whitespace-nowrap">Sort by:</label>
                  <select
                    value={sortBy}
                    onChange={(e) => setSortBy(e.target.value as SortOption)}
                    className="text-xs border border-blue-200 rounded-md px-2 py-1.5 bg-white text-gray-800 focus:outline-none focus:border-blue-400"
                  >
                    <option value="best-match">Best Match</option>
                    <option value="price-low">Price: Low to High</option>
                    <option value="price-high">Price: High to Low</option>
                  </select>
                </div>

                {/* Price range */}
                <div className="flex items-center gap-1.5">
                  <label className="text-xs text-gray-600 font-medium whitespace-nowrap">Price ₹:</label>
                  <input
                    type="number"
                    placeholder="Min"
                    value={minPrice}
                    onChange={(e) => setMinPrice(e.target.value)}
                    className="w-16 text-xs border border-blue-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:border-blue-400"
                  />
                  <span className="text-gray-400 text-xs">–</span>
                  <input
                    type="number"
                    placeholder="Max"
                    value={maxPrice}
                    onChange={(e) => setMaxPrice(e.target.value)}
                    className="w-16 text-xs border border-blue-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:border-blue-400"
                  />
                </div>

                {/* Clear filters */}
                {(minPrice || maxPrice || sortBy !== 'best-match') && (
                  <button
                    onClick={() => { setMinPrice(''); setMaxPrice(''); setSortBy('best-match'); }}
                    className="text-xs text-blue-600 hover:text-blue-800 underline"
                  >
                    Clear
                  </button>
                )}
              </div>
            )}
          </div>
        )}

        {!loading && filteredProducts.length === 0 && !searchQuery ? (
          /* Landing Page */
          <div className="max-w-4xl mx-auto space-y-16 md:space-y-24">
            {/* Hero */}
            <div className="text-center space-y-6">
              <div className="flex justify-center mb-6">
                <div className="p-4 bg-gradient-to-br from-blue-50 to-blue-100 rounded-2xl shadow-lg border border-blue-200">
                  <img src={groeaseCenter} alt="GROEASE Logo" className="h-20 w-20 object-contain mx-auto" />
                </div>
              </div>
              <p className="text-3xl md:text-4xl font-bold leading-tight bg-gradient-to-r from-blue-600 to-blue-700 bg-clip-text text-transparent">
                India&apos;s first quick commerce comparison app.
              </p>
              <div className="text-lg text-blue-700 font-medium space-y-1">
                <p>Search once.</p>
                <p>Compare across multiple quick-commerce platforms.</p>
                <p>Choose the best option.</p>
              </div>
            </div>

            {/* Banner slideshow */}
            <section className="w-screen relative left-1/2 -translate-x-1/2">
              <div className="w-full rounded-none overflow-hidden shadow-md border-0 border-y border-blue-100 bg-blue-50/30">
                {BANNER_SLIDES.map((slide, i) => (
                  <div
                    key={i}
                    className={`transition-opacity duration-500 ${i === bannerIndex ? 'opacity-100' : 'opacity-0 absolute inset-0 pointer-events-none invisible'}`}
                    aria-hidden={i !== bannerIndex}
                  >
                    <img src={slide.src} alt={slide.alt} className="w-full h-auto block" />
                  </div>
                ))}
              </div>
              <div className="flex justify-center gap-2 py-3">
                {BANNER_SLIDES.map((_, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => setBannerIndex(i)}
                    className={`h-2 rounded-full transition-all ${i === bannerIndex ? 'w-6 bg-blue-600' : 'w-2 bg-blue-200 hover:bg-blue-300'}`}
                    aria-label={`Go to slide ${i + 1}`}
                  />
                ))}
              </div>
            </section>

            {/* WHY GROEASE? */}
            <section>
              <h2 className="text-2xl md:text-3xl font-bold text-blue-900 mb-8 text-center">WHY GROEASE?</h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
                <div className="p-5 bg-white rounded-xl border border-blue-100 shadow-sm hover:shadow-md transition-shadow">
                  <div className="p-3 bg-blue-50 rounded-xl w-fit mb-3">
                    <ShoppingCart className="h-6 w-6 text-blue-600" />
                  </div>
                  <h3 className="font-semibold text-blue-900 mb-1">One Search</h3>
                  <p className="text-sm text-blue-700">Multiple apps, one screen.</p>
                </div>
                <div className="p-5 bg-white rounded-xl border border-blue-100 shadow-sm hover:shadow-md transition-shadow">
                  <div className="p-3 bg-blue-50 rounded-xl w-fit mb-3">
                    <Clock className="h-6 w-6 text-blue-600" />
                  </div>
                  <h3 className="font-semibold text-blue-900 mb-1">Delivery Clarity</h3>
                  <p className="text-sm text-blue-700">Know who&apos;s faster.</p>
                </div>
                <div className="p-5 bg-white rounded-xl border border-blue-100 shadow-sm hover:shadow-md transition-shadow">
                  <div className="p-3 bg-blue-50 rounded-xl w-fit mb-3">
                    <Banknote className="h-6 w-6 text-blue-600" />
                  </div>
                  <h3 className="font-semibold text-blue-900 mb-1">Price Visibility</h3>
                  <p className="text-sm text-blue-700">See the best deal.</p>
                </div>
                <div className="p-5 bg-white rounded-xl border border-blue-100 shadow-sm hover:shadow-md transition-shadow">
                  <div className="p-3 bg-blue-50 rounded-xl w-fit mb-3">
                    <Package className="h-6 w-6 text-blue-600" />
                  </div>
                  <h3 className="font-semibold text-blue-900 mb-1">Live Availability</h3>
                  <p className="text-sm text-blue-700">Only what&apos;s in stock.</p>
                </div>
              </div>
            </section>

            {/* HOW IT WORKS */}
            <section className="bg-white/60 rounded-2xl border border-blue-100 p-6 md:p-8">
              <h2 className="text-2xl md:text-3xl font-bold text-blue-900 mb-6 text-center">HOW IT WORKS</h2>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6 md:gap-4">
                <div className="relative flex flex-col items-center p-5 rounded-xl bg-blue-50/80 border border-blue-100">
                  <div className="w-12 h-12 rounded-full bg-blue-600 text-white flex items-center justify-center font-bold text-lg mb-3">1</div>
                  <Search className="h-7 w-7 text-blue-600 mb-2" />
                  <p className="font-semibold text-blue-900 text-center">Search a product</p>
                  <div className="hidden md:block absolute top-1/2 -right-3 -translate-y-1/2 text-blue-300 text-xl">→</div>
                </div>
                <div className="relative flex flex-col items-center p-5 rounded-xl bg-blue-50/80 border border-blue-100">
                  <div className="w-12 h-12 rounded-full bg-blue-600 text-white flex items-center justify-center font-bold text-lg mb-3">2</div>
                  <GitCompare className="h-7 w-7 text-blue-600 mb-2" />
                  <p className="font-semibold text-blue-900 text-center">Compare options</p>
                  <div className="hidden md:block absolute top-1/2 -right-3 -translate-y-1/2 text-blue-300 text-xl">→</div>
                </div>
                <div className="flex flex-col items-center p-5 rounded-xl bg-blue-50/80 border border-blue-100">
                  <div className="w-12 h-12 rounded-full bg-blue-600 text-white flex items-center justify-center font-bold text-lg mb-3">3</div>
                  <ShoppingCart className="h-7 w-7 text-blue-600 mb-2" />
                  <p className="font-semibold text-blue-900 text-center">Order smart</p>
                </div>
              </div>
              <p className="text-center text-blue-600 font-semibold mt-4 text-sm uppercase tracking-wide">Simple. Quick. Efficient.</p>
            </section>

            {/* WHO IT'S FOR + WHY WE BUILT GROEASE — side-by-side layout */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
              {/* WHO IT'S FOR */}
              <section className="bg-white rounded-2xl border border-blue-100 shadow-sm p-6 md:p-8">
                <h2 className="text-xl md:text-2xl font-bold text-blue-900 mb-6">WHO IT&apos;S FOR</h2>
                <div className="space-y-4 mb-6">
                  <div className="flex items-center gap-3 p-3 rounded-lg bg-blue-50/50 border border-blue-50">
                    <span className="w-2 h-2 rounded-full bg-blue-500 shrink-0" />
                    <span className="text-blue-800 font-medium">Urban shoppers</span>
                  </div>
                  <div className="flex items-center gap-3 p-3 rounded-lg bg-blue-50/50 border border-blue-50">
                    <span className="w-2 h-2 rounded-full bg-blue-500 shrink-0" />
                    <span className="text-blue-800 font-medium">College students & Gen Z</span>
                  </div>
                  <div className="flex items-center gap-3 p-3 rounded-lg bg-blue-50/50 border border-blue-50">
                    <span className="w-2 h-2 rounded-full bg-blue-500 shrink-0" />
                    <span className="text-blue-800 font-medium">Working professionals</span>
                  </div>
                  <div className="flex items-center gap-3 p-3 rounded-lg bg-blue-50/50 border border-blue-50">
                    <span className="w-2 h-2 rounded-full bg-blue-500 shrink-0" />
                    <span className="text-blue-800 font-medium">Families</span>
                  </div>
                </div>
                <p className="text-blue-700 font-medium text-sm">If you shop groceries online, Groease works for you.</p>
              </section>

              {/* WHY WE BUILT GROEASE */}
              <section className="bg-gradient-to-br from-blue-50 to-blue-100/50 rounded-2xl border border-blue-100 shadow-sm p-6 md:p-8">
                <h2 className="text-xl md:text-2xl font-bold text-blue-900 mb-6">WHY WE BUILT GROEASE</h2>
                <div className="space-y-4">
                  <p className="text-blue-800 font-medium">Too many apps.</p>
                  <p className="text-blue-800 font-medium">Too many decisions.</p>
                  <p className="text-blue-900 font-semibold pt-2 border-t border-blue-200">
                    Groease simplifies grocery shopping by giving you clarity first.
                  </p>
                </div>
              </section>
            </div>

            {/* FOUNDER'S NOTE */}
            <section className="bg-white rounded-2xl border border-blue-100 shadow-md p-6 md:p-8">
              <h2 className="text-2xl md:text-3xl font-bold text-blue-900 mb-6 text-center">FOUNDER&apos;S NOTE</h2>
              <blockquote className="text-blue-800 space-y-4 max-w-3xl mx-auto">
                <p>During exam season, I found myself juggling multiple grocery apps, checking prices, delivery slots, and availability, all while short on time.</p>
                <p>That frustration turned into an idea. An idea that became Groease.</p>
                <p>I later pitched this on Ideabaaz, where the problem instantly resonated. Arjun Vaidya showed strong interest, calling it a solution he&apos;d personally use.</p>
                <p>Groease is built by a user, for users. What started as a daily inconvenience is now designed to make everyday shopping easier for everyone.</p>
                <footer className="pt-4 border-t border-blue-100 text-blue-700 font-medium italic">
                  — Aliza Saifi, Founder, Groease
                </footer>
              </blockquote>
            </section>

            {/* FINAL CTA */}
            <section className="text-center py-8">
              <p className="text-2xl font-bold text-blue-900 mb-2">Less switching.</p>
              <p className="text-2xl font-bold text-blue-900 mb-6">More ease.</p>
              <Button
                size="lg"
                className="bg-blue-600 hover:bg-blue-700 text-white px-8 py-6 text-lg rounded-xl"
                onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
              >
                Try Groease
              </Button>
            </section>
          </div>
        ) : !loading && filteredProducts.length === 0 && searchQuery ? (
          <div className="text-center py-16">
            <div className="max-w-md mx-auto">
              <div className="mb-4 p-4 bg-blue-50 rounded-full w-16 h-16 mx-auto flex items-center justify-center border border-blue-100">
                <Sparkles className="h-8 w-8 text-blue-400" />
              </div>
              <p className="text-blue-700 text-lg mb-2 font-medium">
                No products found with matching quantities across platforms.
              </p>
              <p className="text-blue-600 text-sm mt-2">Try a different search term</p>
            </div>
          </div>
        ) : !loading ? (
          <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6 gap-4">
            {filteredProducts
              .slice()
              .sort((a, b) => {
                // Get lowest price across platforms for each product
                const pricesA = Object.values(a.platforms || {}).map((pd) => pd.price);
                const pricesB = Object.values(b.platforms || {}).map((pd) => pd.price);
                const lowestA = pricesA.length > 0 ? Math.min(...pricesA) : Infinity;
                const lowestB = pricesB.length > 0 ? Math.min(...pricesB) : Infinity;

                if (sortBy === 'price-low') return lowestA - lowestB;
                if (sortBy === 'price-high') return lowestB - lowestA;

                // Default: best-match — sort by platform match count desc, then alphabetically
                const matchCountA = Object.keys(a.platforms || {}).length;
                const matchCountB = Object.keys(b.platforms || {}).length;
                if (matchCountA !== matchCountB) return matchCountB - matchCountA;

                const nameA = a.name;
                const nameB = b.name;
                const startsWithLetterA = /^[a-zA-Z]/.test(nameA);
                const startsWithLetterB = /^[a-zA-Z]/.test(nameB);
                if (startsWithLetterA && !startsWithLetterB) return -1;
                if (!startsWithLetterA && startsWithLetterB) return 1;
                return nameA.localeCompare(nameB, undefined, { sensitivity: 'base', numeric: true });
              })
              .map((matchedProduct) => (
                <ProductComparisonTable
                  key={matchedProduct.name}
                  matchedProduct={matchedProduct}
                />
              ))}
          </div>
        ) : null}
      </main>
      <Footer />
    </div>
  );
}

export default App;

