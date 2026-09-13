const API_URL = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' || window.location.protocol === 'file:'
  ? 'http://127.0.0.1:8000/api'
  : '/api';

const DEVICE_ID_KEY = 'favorable-soil-device-id';

/**
 * Stable anonymous identity for this browser.
 *
 * The backend maps this UUID to a user account, which is what keeps one
 * visitor's fields and analyses out of everyone else's. It is generated once
 * and kept in localStorage; clearing site data starts a new, empty account.
 */
function getDeviceId() {
  let deviceId = null;
  try {
    deviceId = localStorage.getItem(DEVICE_ID_KEY);
  } catch (err) {
    // Private mode or blocked storage: fall through to a per-session id.
  }

  if (!deviceId) {
    deviceId = (crypto.randomUUID && crypto.randomUUID()) || fallbackUuid();
    try {
      localStorage.setItem(DEVICE_ID_KEY, deviceId);
    } catch (err) {
      console.warn('Не удалось сохранить идентификатор устройства: данные не переживут перезагрузку');
    }
  }
  return deviceId;
}

function fallbackUuid() {
  // crypto.randomUUID needs a secure context; this keeps http:// dev working.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map(b => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function getAuthHeaders(extraHeaders = {}) {
  return {
    'Content-Type': 'application/json',
    'X-Device-Id': getDeviceId(),
    ...extraHeaders
  };
}

/**
 * Escape text before it goes into an innerHTML template.
 *
 * Field names, place names and API messages all end up in generated markup;
 * without this a name containing markup would execute in the page.
 */
function escapeHtml(value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** Format a number that may legitimately be missing. */
function formatNumber(value, digits = 1, suffix = '') {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return Number(value).toFixed(digits) + suffix;
}

/** Confirms the backend accepted our device identity. */
async function checkAuthSession() {
  try {
    const res = await fetch(`${API_URL}/session/`, { headers: getAuthHeaders() });
    if (!res.ok) {
      setError('Не удалось установить сессию с сервером. Данные не будут сохраняться.');
      return null;
    }
    const session = await res.json();
    if (session.capabilities) serverCapabilities = session.capabilities;
    applyCapabilities();
    return session;
  } catch (err) {
    console.error('Session check failed:', err);
    setError('Сервер недоступен. Проверьте, что бэкенд запущен.');
    return null;
  }
}

/** Reads a DRF list response, which is paginated: {count, results: [...]}. */
function readList(payload) {
  if (Array.isArray(payload)) return payload;
  return (payload && Array.isArray(payload.results)) ? payload.results : [];
}

let map;
let currentOverlay = null;
let currentBounds = null;
let currentAnalysisType = 'ndvi';
let drawnItems = null;
let currentDrawnLayer = null;
let allFields = [];
let serverCapabilities = { sentinel2_ndvi: false, field_detection: false };

/**
 * Indicative land prices per hectare, in USD.
 *
 * These are rough reference figures for orientation only -- they are not
 * market data, carry no date, and ignore irrigation, road access, soil quality
 * and ownership. Every place they are shown says so. Replace with a real
 * valuation source before treating any of it as a number to act on.
 */
const LAND_PRICES = {
  "Таджикистан": { priceUsdPerKm2: 350000, priceUsdPerHa: 3500, currency: "TJS", symbol: "TJS", flag: "🇹🇯" },
  "Узбекистан": { priceUsdPerKm2: 400000, priceUsdPerHa: 4000, currency: "UZS", symbol: "сум", flag: "🇺🇿" },
  "Казахстан": { priceUsdPerKm2: 100000, priceUsdPerHa: 1000, currency: "KZT", symbol: "₸", flag: "🇰🇿" },
  "Россия": { priceUsdPerKm2: 150000, priceUsdPerHa: 1500, currency: "RUB", symbol: "₽", flag: "🇷🇺" },
  "Киргизия": { priceUsdPerKm2: 250000, priceUsdPerHa: 2500, currency: "KGS", symbol: "сом", flag: "🇰🇬" },
  "default": { priceUsdPerKm2: 300000, priceUsdPerHa: 3000, currency: "USD", symbol: "$", flag: "🌍" }
};

function getLandPriceConfig(countryName) {
  if (!countryName) return LAND_PRICES["default"];
  const name = countryName.toLowerCase().trim();
  if (name.includes("таджик")) return LAND_PRICES["Таджикистан"];
  if (name.includes("узбек")) return LAND_PRICES["Узбекистан"];
  if (name.includes("казах")) return LAND_PRICES["Казахстан"];
  if (name.includes("росси")) return LAND_PRICES["Россия"];
  if (name.includes("кирг") || name.includes("кырг")) return LAND_PRICES["Киргизия"];
  return LAND_PRICES["default"];
}

const placeCache = new Map();

/**
 * Reverse-geocode for display purposes, cached by rounded coordinates.
 *
 * Nominatim's usage policy discourages bulk traffic, and this used to fire on
 * every dashboard refresh. Rounding to three decimals (~110 m) means panning
 * around the same field costs one request, not dozens.
 */
async function lookupPlace(lat, lon) {
  const key = `${lat.toFixed(3)},${lon.toFixed(3)}`;
  if (placeCache.has(key)) return placeCache.get(key);

  let result = { label: null, country: null };
  try {
    const res = await fetch(
      `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lon}&zoom=12&addressdetails=1`,
      { headers: { 'Accept-Language': 'ru' } }
    );
    if (res.ok) {
      const address = (await res.json()).address || {};
      result = {
        label: address.city || address.town || address.village || address.suburb
               || address.county || address.state || null,
        country: address.country || null
      };
    }
  } catch (err) {
    console.warn('Не удалось определить местоположение:', err);
  }

  placeCache.set(key, result);
  return result;
}

function formatMoney(amount, currencySymbol) {
  if (amount === 0) return "-";
  const fractionDigits = amount < 100 ? 2 : 0;
  return amount.toLocaleString('ru-RU', { maximumFractionDigits: fractionDigits }) + " " + currencySymbol;
}

window.changeTheme = function (theme) {
  const root = document.documentElement;
  if (theme === 'light') {
    root.style.setProperty('--bg-dark', '#f3f4f6');
    root.style.setProperty('--bg-darker', '#e5e7eb');
    root.style.setProperty('--card-bg', '#ffffff');
    root.style.setProperty('--card-bg-light', '#f9fafb');
    root.style.setProperty('--text-main', '#1f2937');
    root.style.setProperty('--text-muted', '#6b7280');
    root.style.setProperty('--border-color', 'rgba(0, 0, 0, 0.08)');
    root.style.setProperty('--glass-bg', 'rgba(0, 0, 0, 0.02)');
    root.style.setProperty('--glass-border', 'rgba(0, 0, 0, 0.05)');
    
    // Readability overrides for light theme:
    root.style.setProperty('--primary', '#4f46e5');
    root.style.setProperty('--primary-rgb', '79, 70, 229');
    root.style.setProperty('--primary-light', '#312e81');
    root.style.setProperty('--accent', '#0284c7');
    root.style.setProperty('--accent-green', '#059669');
    root.style.setProperty('--accent-orange', '#d97706');
    root.style.setProperty('--accent-red', '#dc2626');
    root.style.setProperty('--accent-purple', '#7c3aed');
    root.style.setProperty('--card-glass-bg', 'rgba(255, 255, 255, 0.6)');
    root.style.setProperty('--gradient-success', 'linear-gradient(135deg, #0284c7 0%, #059669 100%)');
    
    document.body.style.background = '#f3f4f6';
  } else { // dark / default
    root.style.setProperty('--bg-dark', '#0a0a0f');
    root.style.setProperty('--bg-darker', '#050508');
    root.style.setProperty('--card-bg', '#12121a');
    root.style.setProperty('--card-bg-light', '#1a1a25');
    root.style.setProperty('--text-main', '#e0e0e0');
    root.style.setProperty('--text-muted', '#888');
    root.style.setProperty('--border-color', 'rgba(255, 255, 255, 0.08)');
    root.style.setProperty('--glass-bg', 'rgba(255, 255, 255, 0.05)');
    root.style.setProperty('--glass-border', 'rgba(255, 255, 255, 0.1)');
    
    // Reset colors for dark theme:
    root.style.setProperty('--primary', '#646cff');
    root.style.setProperty('--primary-rgb', '100, 108, 255');
    root.style.setProperty('--primary-light', '#8b8fff');
    root.style.setProperty('--accent', '#00d2ff');
    root.style.setProperty('--accent-green', '#00ff88');
    root.style.setProperty('--accent-orange', '#ff9500');
    root.style.setProperty('--accent-red', '#ff4757');
    root.style.setProperty('--accent-purple', '#a855f7');
    root.style.setProperty('--card-glass-bg', 'rgba(30, 30, 30, 0.6)');
    root.style.setProperty('--gradient-success', 'linear-gradient(135deg, #00d2ff 0%, #00ff88 100%)');
    
    document.body.style.background = '#0a0a0f';
  }
  
  localStorage.setItem('favorable-soil-theme', theme);
};

let sessionStats = {
 startTime: Date.now(),
 analysisCount: 0,
 totalHealthScore: 0,
 healthScoreCount: 0,
 totalWeeds: 0,
 activities: []
};

setInterval(() => {
 const el = document.getElementById('stats-time');
 if (el) {
 const diff = Math.floor((Date.now() - sessionStats.startTime) / 1000);
 const m = Math.floor(diff / 60).toString().padStart(2, '0');
 const s = (diff % 60).toString().padStart(2, '0');
 el.textContent = `${m}:${s}`;
 }
}, 1000);

const pages = {
 dashboard: document.getElementById('page-dashboard'),
 analysis: document.getElementById('page-analysis')
};
const navItems = document.querySelectorAll('.sidebar-nav .nav-item');
const loadingOverlay = document.getElementById('loading-overlay');
const errorAlert = document.getElementById('error-alert');
const errorText = document.getElementById('error-text');
const resultsContainer = document.getElementById('results-container');
const legendItems = document.getElementById('legend-items');

document.addEventListener('DOMContentLoaded', () => {
  initMap();
  switchPage('analysis');
  checkAuthSession();
  loadFields();

  const savedTheme = localStorage.getItem('favorable-soil-theme') || 'dark';
  const themeSelect = document.getElementById('theme-select');
  if (themeSelect) themeSelect.value = savedTheme;
  changeTheme(savedTheme);

  const fieldSelect = document.getElementById('field-select');
  if (fieldSelect) {
    fieldSelect.addEventListener('change', (e) => {
      const fieldId = e.target.value;
      if (!fieldId) {
        if (drawnItems) drawnItems.clearLayers();
        currentDrawnLayer = null;
        currentBounds = map.getBounds();
        updateDashboard();
        return;
      }
      
      const field = allFields.find(f => f.id == fieldId);
      if (field && field.bounds_json) {
        try {
          const bounds = JSON.parse(field.bounds_json);
          if (drawnItems) drawnItems.clearLayers();
          
          const polygon = L.polygon(bounds, { color: '#00ff88', weight: 3, fillOpacity: 0.15 });
          if (drawnItems) drawnItems.addLayer(polygon);
          currentDrawnLayer = polygon;
          
          const polygonBounds = polygon.getBounds();
          map.fitBounds(polygonBounds);
          currentBounds = polygonBounds;
          
          updateDashboard();
        } catch (err) {
          console.error("Error parsing field bounds:", err);
        }
      }
    });
  }

  const printDateEl = document.getElementById('print-date');
  if (printDateEl) {
  printDateEl.textContent = new Date().toLocaleDateString('ru-RU', {
  weekday: 'long',
  year: 'numeric',
  month: 'long',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit'
  });
  }
});

async function loadFields() {
  try {
    const res = await fetch(`${API_URL}/fields/`, {
      headers: getAuthHeaders()
    });
    if (!res.ok) throw new Error('Failed to load fields');
    const fields = readList(await res.json());
    allFields = fields;

    const select = document.getElementById('field-select');
    if (select) {
      if (fields.length === 0) {
        select.innerHTML = '<option value="">Нет доступных полей</option>';
      } else {
        select.innerHTML = '<option value="">-- Выберите поле --</option>';
        fields.forEach(field => {
          const option = document.createElement('option');
          option.value = field.id;
          option.textContent = field.name;
          select.appendChild(option);
        });
      }
    }
  } catch (err) {
    console.error("Error loading fields:", err);
  }
}

window.toggleNewFieldForm = function () {
  const form = document.getElementById('save-field-form');
  if (form) {
    form.style.display = form.style.display === 'none' ? 'block' : 'none';
  }
};

window.saveFieldFromMap = async function () {
  if (!currentBounds) {
    alert('Сначала выберите область на карте');
    return;
  }

  const nameInput = document.getElementById('new-field-name');
  const name = nameInput ? nameInput.value.trim() : '';
  if (!name) {
    alert('Введите название поля');
    return;
  }

  const bounds = currentBounds;
  const centerLat = (bounds.getSouth() + bounds.getNorth()) / 2;
  const centerLon = (bounds.getWest() + bounds.getEast()) / 2;

  const boundsArray = [
    [bounds.getSouth(), bounds.getWest()],
    [bounds.getSouth(), bounds.getEast()],
    [bounds.getNorth(), bounds.getEast()],
    [bounds.getNorth(), bounds.getWest()]
  ];

  const latDiff = bounds.getNorth() - bounds.getSouth();
  const lonDiff = bounds.getEast() - bounds.getWest();
  const areaKm2 = latDiff * 111.32 * lonDiff * 111.32 * Math.cos(centerLat * Math.PI / 180);
  const areaHa = areaKm2 * 100;

  try {
    const res = await fetch(`${API_URL}/fields/`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        name: name,
        bounds_json: JSON.stringify(boundsArray),
        center_lat: centerLat,
        center_lon: centerLon,
        area_hectares: Math.round(areaHa * 100) / 100
      })
    });

 if (!res.ok) {
 const err = await res.json();
 throw new Error(err.detail || 'Ошибка сохранения');
 }

 const saved = await res.json();
 alert(` Поле "${saved.name}" сохранено!`);

 if (nameInput) nameInput.value = '';
 document.getElementById('save-field-form').style.display = 'none';

 await loadFields();

 const select = document.getElementById('field-select');
 if (select) select.value = saved.id;

 } catch (err) {
 alert(` Ошибка: ${err.message}`);
 console.error('Save field error:', err);
 }
};

window.switchPage = function (pageId) {
 Object.values(pages).forEach(el => {
 if (el) el.classList.add('hidden')
 });
 if (pages[pageId]) {
 pages[pageId].classList.remove('hidden');
 }
 navItems.forEach(item => {
 if (item.dataset.page === pageId) item.classList.add('active');
 else item.classList.remove('active');
 });

 if (pageId === 'analysis' && map) {
 setTimeout(() => map.invalidateSize(), 100);
 const select = document.getElementById('analysis-type-select');
 if (select) select.value = currentAnalysisType;

 if (!currentOverlay) {
 updateLegend(null);
 }
 }

 if (pageId === 'dashboard') {
 updateDashboard();
 }
}

window.setAnalysisType = function (type) {
 currentAnalysisType = type;
 switchPage('analysis');
 ['fertility', 'ndvi', 'weeds'].forEach(t => {
 const btn = document.getElementById(`tab-${t}`);
 if (btn) {
 if (t === type) btn.classList.add('active');
 else btn.classList.remove('active');
 }
 });

 const select = document.getElementById('analysis-type-select');
 if (select) {
 select.value = type;
 }
 const titles = {
 fertility: '️ Анализ плодородия',
 ndvi: ' Мониторинг роста',
 weeds: ' Обнаружение сорняков',
 infrastructure: 'Анализ инфраструктуры',
 prediction: 'Динамика застройки',
 urban_filter: 'Покров земли'
 };
 const titleEl = document.getElementById('analysis-title');
 if (titleEl) titleEl.textContent = titles[type] || titles['fertility'];
 if (currentOverlay) {
 map.removeLayer(currentOverlay);
 currentOverlay = null;
 }
 clearMarkers();
 updateLegend(null);
 if (resultsContainer) resultsContainer.innerHTML = '';
 const bottomCrops = document.getElementById('map-bottom-crops-container');
 if (bottomCrops) bottomCrops.innerHTML = '';
}

let markers = [];
function clearMarkers() {
 markers.forEach(m => map.removeLayer(m));
 markers = [];
}


function initMap() {
  if (document.getElementById('map')) {
    map = L.map('map').setView([38.55, 68.78], 12);

    const satellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
      attribution: '&copy; ESRI',
      maxZoom: 19
    });

    satellite.addTo(map);

    drawnItems = new L.FeatureGroup();
    map.addLayer(drawnItems);

    // `draw: false` here meant nobody could ever draw an area: the CREATED
    // event never fired and every analysis silently used the whole viewport.
    const drawControl = new L.Control.Draw({
      edit: {
        featureGroup: drawnItems
      },
      draw: {
        rectangle: { shapeOptions: { color: '#00ff88', weight: 3, fillOpacity: 0.1 } },
        polygon: { shapeOptions: { color: '#00ff88', weight: 3, fillOpacity: 0.1 }, allowIntersection: false },
        polyline: false, circle: false, circlemarker: false, marker: false
      }
    });
    map.addControl(drawControl);

    map.on(L.Draw.Event.CREATED, function (e) {
      const layer = e.layer;
      drawnItems.clearLayers();
      
      const fieldSelect = document.getElementById('field-select');
      if (fieldSelect) fieldSelect.value = '';
      
      drawnItems.addLayer(layer);
      currentDrawnLayer = layer;
      currentBounds = layer.getBounds();
      
      updateDashboard();
    });

    map.on('moveend', () => {
      if (!currentDrawnLayer) {
        currentBounds = map.getBounds();
      }
    });
    currentBounds = map.getBounds();
  }
}


window.runAnalysis = async function () {
  if (!currentBounds) {
    alert("Карта еще не загрузилась");
    return;
  }

  setLoading(true);
  setError(null);
  clearMarkers();

  const bbox = [
    currentBounds.getWest(),
    currentBounds.getSouth(),
    currentBounds.getEast(),
    currentBounds.getNorth()
  ];

  let endpoint = '/growth/analyze/';
  if (currentAnalysisType === 'fertility') endpoint = '/analyze/';
  if (currentAnalysisType === 'weeds') endpoint = '/weeds/detect/';
  if (['infrastructure', 'prediction', 'urban_filter'].includes(currentAnalysisType)) endpoint = '/urban/analyze/';

  const fieldSelect = document.getElementById('field-select');
  const saveCheck = document.getElementById('save-result-check');
  
  const fieldId = fieldSelect ? fieldSelect.value : null;
  const saveResult = saveCheck ? saveCheck.checked : false;

  try {
    const res = await fetch(`${API_URL}${endpoint}`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        bbox,
        field_id: fieldId || null,
        save_result: saveResult,
        analysis_type: currentAnalysisType
      })
    });

    if (!res.ok) {
      setError(await describeHttpError(res));
      return;
    }

    renderResult(await res.json());
  } catch (err) {
    // Reaching here means the request never completed: DNS, TLS, offline or
    // CORS. An HTTP error status is handled above, with the server's own text.
    console.error('Analysis request failed:', err);
    setError(navigator.onLine
      ? 'Не удалось связаться с сервером. Проверьте, что бэкенд запущен и доступен.'
      : 'Нет подключения к интернету.');
  } finally {
    setLoading(false);
  }
}

/**
 * Turn a failed response into a message worth showing.
 *
 * The backend already sends a specific, user-facing reason -- a bbox that is
 * too large, a rate limit, an unreachable tile server. Repeating it beats the
 * generic "Ошибка связи с сервером" that used to hide all three.
 */
async function describeHttpError(res) {
  if (res.status === 401) {
    return 'Сервер не опознал это устройство. Обновите страницу.';
  }
  if (res.status === 429) {
    return 'Слишком много анализов за короткое время. Подождите и повторите.';
  }

  let payload = null;
  try {
    payload = await res.json();
  } catch (err) {
    return `Сервер вернул ошибку ${res.status}.`;
  }

  const detail = payload.error
    || payload.detail
    || (payload.bbox && [].concat(payload.bbox)[0])
    || Object.values(payload).flat()[0];

  if (res.status === 502) {
    return detail || 'Не удалось получить спутниковые снимки для этой области.';
  }
  return detail ? String(detail) : `Сервер вернул ошибку ${res.status}.`;
}

async function updateDashboard() {
  const countEl = document.getElementById('stats-count');
  const healthEl = document.getElementById('stats-health');
  const weedsEl = document.getElementById('stats-weeds');
  const activityList = document.getElementById('activity-list');
  const summaryEl = document.getElementById('dashboard-summary');

  if (countEl) countEl.textContent = sessionStats.analysisCount;

  if (healthEl) {
    const avg = sessionStats.healthScoreCount > 0
      ? (sessionStats.totalHealthScore / sessionStats.healthScoreCount).toFixed(1)
      : '-';
    healthEl.textContent = avg + (avg !== '-' ? '%' : '');
  }

  if (weedsEl) weedsEl.textContent = sessionStats.totalWeeds;

  if (activityList) {
    if (sessionStats.activities.length === 0) {
      activityList.innerHTML = '<div style="color: var(--text-muted); text-align: center; margin-top: 2rem;">Здесь появится история ваших действий</div>';
    } else {
      activityList.innerHTML = sessionStats.activities.map(a => `
        <div class="activity-item">
          <div class="activity-icon" style="background: rgba(var(--primary-rgb), 0.1); color: var(--primary);">
            ${getIconForType(a.type)}
          </div>
          <div class="activity-details">
            <div class="activity-title">${escapeHtml(a.text)}</div>
            <div class="activity-time">${escapeHtml(a.time)}</div>
          </div>
        </div>
      `).join('');
    }
  }

  if (summaryEl) {
    let rates = { TJS: 10.93, RUB: 89.5, UZS: 12600, KZT: 450, KGS: 87.5 };
    let exchangeHtml = '';
    try {
      const rateRes = await fetch('https://api.exchangerate-api.com/v4/latest/USD');
      const rateData = await rateRes.json();
      if (rateData && rateData.rates) {
        rates = rateData.rates;
      }
      const tjsRate = rates.TJS || 10.93;
      const rubRate = rates.RUB || 89.5;

      exchangeHtml = `
        <div style="display: flex; gap: 1rem;">
          <div class="market-item" style="flex: 1;">
            <div class="market-name"> USD → TJS</div>
            <div class="market-price" style="font-size: 1.2rem; color: #00ff88;">1$ = ${tjsRate.toFixed(2)} TJS</div>
            <div class="market-change up">Нац. банк Таджикистана</div>
          </div>
          <div class="market-item" style="flex: 1;">
            <div class="market-name"> USD → RUB</div>
            <div class="market-price" style="font-size: 1.2rem; color: #4facfe;">1$ = ${rubRate.toFixed(2)} ₽</div>
            <div class="market-change">ЦБ РФ</div>
          </div>
        </div>
      `;
    } catch (e) {
      console.error('Exchange rate API error:', e);
      const tjsRate = rates.TJS || 10.93;
      exchangeHtml = `
        <div class="market-item">
          <div class="market-name"> USD → TJS</div>
          <div class="market-price" style="font-size: 1.2rem; color: #00ff88;">1$ ≈ ${tjsRate.toFixed(2)} TJS</div>
          <div class="market-change" style="color: var(--text-muted);">Оффлайн данные</div>
        </div>
      `;
    }

    let lat = 38.56;
    let lon = 68.77;
    let locationLabel = 'Душанбе';
    let areaHa = 0;
    let areaKm2 = 0;

    const fieldSelect = document.getElementById('field-select');
    if (fieldSelect && fieldSelect.value) {
      const field = allFields.find(f => f.id == fieldSelect.value);
      if (field) {
        lat = parseFloat(field.center_lat) || 38.56;
        lon = parseFloat(field.center_lon) || 68.77;
        locationLabel = field.name;
        areaHa = parseFloat(field.area_hectares) || 0;
        areaKm2 = areaHa / 100;
      }
    } else if (currentBounds) {
      const center = currentBounds.getCenter();
      lat = parseFloat(center.lat.toFixed(4));
      lon = parseFloat(center.lng.toFixed(4));
      locationLabel = `Шир: ${lat}, Долг: ${lon}`;

      const latDiff = currentBounds.getNorth() - currentBounds.getSouth();
      const lonDiff = currentBounds.getEast() - currentBounds.getWest();
      areaKm2 = latDiff * 111.32 * lonDiff * 111.32 * Math.cos(lat * Math.PI / 180);
      areaHa = areaKm2 * 100;
    }

    const place = await lookupPlace(lat, lon);
    let countryName = place.country || 'Выбранная местность';
    if (place.label) locationLabel = place.label;

    // Calculate land price
    const landPriceConfig = getLandPriceConfig(countryName);
    const totalCostUsd = areaHa * landPriceConfig.priceUsdPerHa;
    const localRate = rates[landPriceConfig.currency] || 1.0;
    const totalCostLocal = totalCostUsd * localRate;

    // Update dashboard stat card
    const priceEl = document.getElementById('stats-land-price');
    if (priceEl) {
      if (totalCostUsd > 0) {
        if (landPriceConfig.currency !== 'USD') {
          priceEl.innerHTML = `<span style="font-size: 1.5rem; font-weight: 700;">${formatMoney(totalCostUsd, "$")}</span><div style="font-size: 0.8rem; color: var(--accent-orange); font-weight: 500; margin-top: 2px;">≈ ${formatMoney(totalCostLocal, landPriceConfig.symbol)}</div>`;
        } else {
          priceEl.textContent = formatMoney(totalCostUsd, "$");
        }
      } else {
        priceEl.textContent = "-";
      }
    }

    let valuationHtml = '';
    if (areaHa > 0) {
      const usdPerHaFormatted = formatMoney(landPriceConfig.priceUsdPerHa, "$");
      const totalUsdFormatted = formatMoney(totalCostUsd, "$");
      const totalLocalFormatted = formatMoney(totalCostLocal, landPriceConfig.symbol);

      valuationHtml = `
        <div style="margin-bottom: 1.5rem; background: var(--card-bg-light); border: 1px solid var(--border-color); padding: 1.2rem; border-radius: 16px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
            <h4 style="margin: 0; font-size: 0.95rem; color: var(--text-main); font-weight: 600;">💰 Справочная стоимость земли</h4>
            <span style="font-size: 1.2rem;" title="${escapeHtml(countryName)}">${landPriceConfig.flag}</span>
          </div>
          <div style="display: flex; flex-direction: column; gap: 0.6rem; font-size: 0.85rem;">
            <div style="display: flex; justify-content: space-between;">
              <span style="color: var(--text-muted);">Регион/Страна:</span>
              <span style="font-weight: 500; color: var(--text-main);">${escapeHtml(countryName)}</span>
            </div>
            <div style="display: flex; justify-content: space-between;">
              <span style="color: var(--text-muted);">Площадь:</span>
              <span style="font-weight: 500; color: var(--text-main);">${areaKm2.toFixed(3)} км² (${areaHa.toFixed(2)} га)</span>
            </div>
            <div style="display: flex; justify-content: space-between;">
              <span style="color: var(--text-muted);">Справочная цена:</span>
              <span style="font-weight: 500; color: var(--accent-green);">${usdPerHaFormatted} / га</span>
            </div>
            <div style="border-top: 1px solid var(--border-color); margin-top: 0.4rem; padding-top: 0.6rem; display: flex; justify-content: space-between; align-items: baseline;">
              <span style="color: var(--text-main); font-weight: 600;">Ориентировочно:</span>
              <div style="text-align: right;">
                <div style="font-size: 1.15rem; font-weight: 700; color: #00ff88;">${totalUsdFormatted}</div>
                ${landPriceConfig.currency !== 'USD' ? `<div style="font-size: 0.85rem; color: var(--accent-orange); font-weight: 500; margin-top: 2px;">≈ ${totalLocalFormatted}</div>` : ''}
              </div>
            </div>
            <div style="font-size: 0.7rem; color: var(--text-muted); border-top: 1px solid var(--border-color); padding-top: 0.5rem; line-height: 1.4;">
              Справочные средние по стране, без учёта орошения, доступа к дорогам и качества почвы.
              Это ориентир, а не рыночная оценка участка.
            </div>
          </div>
        </div>
      `;
    }

    let forecastHtml = '';
    try {
      const weatherRes = await fetch(`https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}&daily=temperature_2m_max,weathercode&timezone=auto&forecast_days=4`);
      const weatherData = await weatherRes.json();

      const weatherIcons = {
        0: '☀️', 1: '🌤️', 2: '⛅', 3: '☁️',
        45: '🌫️', 48: '🌫️',
        51: '🌧️', 53: '🌧️', 55: '🌧️',
        61: '🌧️', 63: '🌧️', 65: '🌧️',
        71: '🌨️', 73: '🌨️', 75: '🌨️',
        80: '🌧️', 81: '🌧️', 82: '🌧️',
        95: '⛈️', 96: '⛈️', 99: '⛈️'
      };

      // The upstream shape is not guaranteed: a rate-limited or errored
      // response still parses as JSON, just without `daily`.
      const daily = (weatherData && weatherData.daily) || {};
      const days = Array.isArray(daily.time) ? daily.time : [];

      forecastHtml = [1, 2, 3]
        .filter(i => days[i] !== undefined)
        .map(i => {
          const date = new Date(days[i]);
          const temp = Math.round(daily.temperature_2m_max?.[i]);
          const icon = weatherIcons[daily.weathercode?.[i]] || '☀️';
          if (Number.isNaN(temp)) return '';
          return `
          <div class="forecast-day">
            <div class="forecast-date">${escapeHtml(date.toLocaleDateString('ru-RU', { weekday: 'short' }))}</div>
            <div class="forecast-icon">${icon}</div>
            <div class="forecast-temp">${temp > 0 ? '+' : ''}${temp}°</div>
          </div>
        `;
        }).join('');
    } catch (e) {
      console.error('Weather API error:', e);
      forecastHtml = '<div style="color: var(--text-muted);">Ошибка загрузки погоды</div>';
    }

    let content = `
      ${valuationHtml}
      
      <div style="margin-bottom: 1.5rem;">
        <h4 style="margin: 0 0 0.5rem 0; font-size: 0.9rem; color: var(--text-muted);">Курс валют</h4>
        ${exchangeHtml}
      </div>
      
      <div style="margin-bottom: 1.5rem; background: var(--bg-darker); padding: 1rem; border-radius: 12px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
          <h4 style="margin: 0; font-size: 0.9rem; color: var(--text-muted);">Прогноз погоды</h4>
          <a href="https://www.google.com/search?q=${encodeURIComponent('погода ' + locationLabel)}" target="_blank" style="font-size: 0.75rem; color: var(--accent); text-decoration: underline;" title="Открыть в Google Weather">
            ${locationLabel} 🔍
          </a>
        </div>
        <div class="forecast-grid">
          ${forecastHtml}
        </div>
      </div>
    `;

    if (sessionStats.activities.length > 0) {
      const last = sessionStats.activities[0];
      content += `
        <div style="padding: 1rem; background: rgba(100, 108, 255, 0.1); border-radius: 12px; border: 1px solid rgba(100, 108, 255, 0.2);">
          <h4 style="margin: 0 0 0.5rem 0; font-size: 1rem; color: var(--primary-light);">Последняя активность</h4>
          <p style="margin: 0; font-size: 0.9rem; color: var(--text-main);">${last.text}</p>
          <div style="margin-top: 1rem; display: flex; gap: 8px;">
            <span class="badge badge-info">${last.type}</span>
            <span class="badge badge-warning">${last.time}</span>
          </div>
        </div>
      `;
    } else {
      content += `
        <div style="padding: 2rem; text-align: center; border: 2px dashed var(--border-color); border-radius: 12px; color: var(--text-muted);">
          Нет недавней активности. Начните с анализа карты!
        </div>
      `;
    }

    summaryEl.innerHTML = content;
  }
}

function getIconForType(type) {
 if (type === 'weeds') return '';
 if (type === 'fertility') return '️';
 if (type === 'infrastructure') return '️';
 if (type === 'prediction') return '️';
 if (type === 'urban_filter') return '️';
 return '';
}

function renderResult(data) {
 sessionStats.analysisCount++;

 let activityText = `Анализ: ${currentAnalysisType}`;

 const resData = data.data || data;

 if (data.vegetation && typeof data.vegetation.health_score === 'number') {
 sessionStats.totalHealthScore += data.vegetation.health_score;
 sessionStats.healthScoreCount++;
 activityText += ` (Зелёность: ${data.vegetation.health_score.toFixed(1)}%)`;
 }

 if (data.detections) {
 const count = data.detections.length;
 sessionStats.totalWeeds += count;
 if (currentAnalysisType === 'weeds') {
 activityText += ` (Найдено: ${count} объектов)`;
 }
 }

 if (currentAnalysisType === 'infrastructure' && resData.district_type) {
 activityText += ` (${resData.district_type})`;
 }

 if (currentAnalysisType === 'prediction' && resData.growth_status) {
 activityText += ` (${resData.growth_status})`;
 }

 sessionStats.activities.unshift({
 time: new Date().toLocaleTimeString(),
 text: activityText,
 type: currentAnalysisType
 });

 if (sessionStats.activities.length > 20) sessionStats.activities.pop();
 updateDashboard();

 if (currentOverlay) {
 map.removeLayer(currentOverlay);
 }
 if (data.overlay) {
 currentOverlay = L.imageOverlay(data.overlay.image, data.overlay.bounds, { opacity: 0.8 }).addTo(map);
 }

 updateLegend(data);

 let html = '';

 if (data.vegetation) {
 const veg = data.vegetation;
 const stages = {
 'bare_soil': 'Голая почва',
 'emergence': 'Всходы',
 'vegetative': 'Вегетация',
 'flowering': 'Цветение',
 'maturation': 'Созревание'
 };

 const scoreClass = veg.health_score > 70 ? 'badge-success' :
 (veg.health_score > 40 ? 'badge-warning' : 'badge-danger');

 html += `
 <div class="stats-panel">
 <h3 class="stats-panel-title">${escapeHtml(veg.index_label || 'Вегетационный индекс')}</h3>
 <div style="display: grid; gap: 1rem;">
 <div style="display: flex; justify-content: space-between;">
 <span style="color: var(--text-muted)">Средний ${escapeHtml(veg.index_type || 'индекс')}</span>
 <span style="font-weight: 600">${formatNumber(veg.index_mean, 4)}</span>
 </div>
 <div style="display: flex; justify-content: space-between;">
 <span style="color: var(--text-muted)">Оценка зелёности</span>
 <span class="badge ${scoreClass}">${formatNumber(veg.health_score, 1, '%')}</span>
 </div>
 <div style="display: flex; justify-content: space-between;">
 <span style="color: var(--text-muted)">Стадия роста</span>
 <span style="font-weight: 600">${escapeHtml(stages[veg.growth_stage] || veg.growth_stage)}</span>
 </div>
 ${typeof veg.moisture_index === 'number' ? `
 <div style="display: flex; justify-content: space-between;">
 <span style="color: var(--text-muted)">Влажность покрова (NDMI)</span>
 <span style="font-weight: 600" title="${escapeHtml(veg.moisture_label || '')}">${formatNumber(veg.moisture_index, 3)}</span>
 </div>
 ${veg.moisture_label ? `<div style="font-size: 0.8rem; color: var(--text-muted);">${escapeHtml(veg.moisture_label)}</div>` : ''}` : ''}
 ${typeof veg.ndvi_anomaly === 'number' ? `
 <div style="display: flex; justify-content: space-between;">
 <span style="color: var(--text-muted)">Отклонение от нормы ${(veg.reference_years || []).length ? '(' + escapeHtml(veg.reference_years.join(', ')) + ')' : ''}</span>
 <span style="font-weight: 600; color: ${veg.ndvi_anomaly >= 0 ? 'var(--accent-green)' : 'var(--accent-orange)'};">${veg.ndvi_anomaly >= 0 ? '+' : ''}${formatNumber(veg.ndvi_anomaly, 3)}</span>
 </div>
 ${veg.anomaly_label ? `<div style="font-size: 0.8rem; color: var(--text-muted);">${escapeHtml(veg.anomaly_label)}</div>` : ''}` : ''}
 </div>
 ${renderImageryNote(data.imagery)}
 </div>`;
 } else if (currentAnalysisType === 'urban_filter' && resData.stats) {
 const d = resData.stats;
 html += `
 <div class="stats-panel">
 <h3 class="stats-panel-title">Степень урбанизации</h3>
 <div class="stats-bars">
 ${renderBar('Застройка (асфальт/бетон)', d.urban_percent, '#555')}
 ${renderBar('Растительность', d.veg_percent, '#00ff88')}
 ${renderBar('Вода', d.water_percent, '#4a90d9')}
 </div>
 ${d.classes ? `<div style="margin-top: 0.6rem; font-size: 0.8rem; color: var(--text-muted); display: flex; flex-wrap: wrap; gap: 0.4rem 0.8rem;">
 ${Object.entries(d.classes).sort((a, b) => b[1] - a[1]).map(([label, share]) => `<span>${escapeHtml(label)}: ${formatNumber(share, 1, '%')}</span>`).join('')}
 </div>` : ''}
 ${renderSourceNotes(data.method || resData.method, resData.sources, resData.notes)}
 </div>
 `;
 }

 if (data.stats && currentAnalysisType === 'fertility') {
 const method = data.method || data.stats.analysis_method || 'Эвристика';
 html += `
 <div class="stats-panel">
 <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem; gap: 0.5rem;">
 <h3 class="stats-panel-title" style="margin: 0;">Плодородие по площади</h3>
 <span class="badge badge-info" style="font-size: 0.7rem;">${escapeHtml(method)}</span>
 </div>
 <div class="stats-bars">
 ${renderBar('Очень высокое', data.stats.very_high, '#006400')}
 ${renderBar('Высокое', data.stats.high, '#00C800')}
 ${renderBar('Умеренное', data.stats.moderate, '#00FFFF')}
 ${renderBar('Низкое', data.stats.low, '#00A5FF')}
 ${renderBar('Крутой склон (>15%)', data.stats.mountains, '#644632')}
 ${renderBar('Без растительного покрова', data.stats.desert, '#969696')}
 ${renderBar('Вода', data.stats.water, '#0000FF')}
 ${typeof data.stats.built_up === 'number' ? renderBar('Застройка', data.stats.built_up, '#C80000') : ''}
 </div>
 ${renderImageryNote(data.imagery)}
 </div>
 ${renderFertilityComponents(data.components)}`;
 }

 if (data.detections && currentAnalysisType === 'weeds') {
 const severityLabels = {
 low: 'низкая', medium: 'средняя', high: 'высокая', critical: 'критическая'
 };

 html += `
 <div class="stats-panel">
 <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem; gap: 0.5rem;">
 <h3 class="stats-panel-title" style="margin: 0;">Аномалии растительности</h3>
 <span class="badge badge-info" style="font-size: 0.7rem;">${escapeHtml(data.method || 'Текстурный анализ')}</span>
 </div>
 <div style="display: grid; gap: 1rem;">
 <div style="display: flex; justify-content: space-between;">
 <span style="color: var(--text-muted)">Покрытие</span>
 <span style="font-weight: 600; color: #dc3545;">${formatNumber(data.weed_coverage_percent, 2, '%')}</span>
 </div>
 <div style="display: flex; justify-content: space-between;">
 <span style="color: var(--text-muted)">Обнаружено очагов</span>
 <span style="font-weight: 600">${data.detections.length}</span>
 </div>
 <div style="display: flex; justify-content: space-between;">
 <span style="color: var(--text-muted)">Суммарная площадь</span>
 <span style="font-weight: 600">${formatNumber(data.total_weed_area_sqm, 0, ' м²')}</span>
 </div>
 ${typeof data.field_median_ndvi === 'number' ? `
 <div style="display: flex; justify-content: space-between;">
 <span style="color: var(--text-muted)">Медиана NDVI поля</span>
 <span style="font-weight: 600">${formatNumber(data.field_median_ndvi, 3)}</span>
 </div>` : ''}
 </div>
 ${data.note ? `<div style="margin-top: 0.6rem; font-size: 0.78rem; color: var(--accent-orange);">${escapeHtml(data.note)}</div>` : ''}
 ${renderImageryNote(data.imagery)}
 </div>`;

 if (data.detections.length > 0) {
 html += `<div class="stats-panel" style="margin-top: 1rem;">
 <h4 class="stats-panel-title" style="font-size: 0.9rem;">Очаги (по убыванию площади)</h4>
 <div style="max-height: 240px; overflow-y: auto; display: flex; flex-direction: column; gap: 0.5rem;">`;

 data.detections.slice(0, 50).forEach((d, i) => {
 const severe = d.severity === 'critical' || d.severity === 'high';
 html += `
 <div style="background: rgba(255, 255, 255, 0.05); padding: 8px; border-radius: 6px; font-size: 0.85rem;">
 <div style="display: flex; justify-content: space-between; margin-bottom: 4px; gap: 0.5rem;">
 <span style="color: #dc3545; font-weight: 600;">#${i + 1} ${escapeHtml(d.name)}</span>
 <span class="badge badge-${severe ? 'danger' : 'warning'}">${escapeHtml(severityLabels[d.severity] || d.severity)}</span>
 </div>
 <div style="color: var(--text-muted); margin-bottom: 4px;">
 ${formatNumber(d.area, 0, ' м²')} · ${escapeHtml(d.lat)}, ${escapeHtml(d.lon)}
 ${d.direction === 'greener' ? ' · зеленее поля' : d.direction === 'paler' ? ' · бледнее поля' : ''}
 </div>
 <div style="color: var(--text-muted);">${escapeHtml(d.recommendations)}</div>
 </div>`;
 });

 html += `</div></div>`;
 }
 }

 if (currentAnalysisType === 'infrastructure' && resData) {
 html += `
 <div class="stats-panel">
 <h3 class="stats-panel-title">️ Анализ застройки</h3>
 <div style="display: grid; gap: 1rem;">
 <div style="padding: 1rem; background: rgba(255, 255, 255, 0.05); border-radius: 8px;">
 <div style="font-size: 0.85rem; color: var(--text-muted);">Тип района</div>
 <div style="font-size: 1.1rem; font-weight: 600; margin-top: 4px;">${escapeHtml(resData.district_type)}</div>
 </div>
 
 <div style="display: flex; justify-content: space-between;">
 <span style="color: var(--text-muted)">Плотность застройки</span>
 <span style="font-weight: 600">${formatNumber(resData.building_density, 1, '%')}</span>
 </div>
 ${typeof resData.buildings_detected === 'number' ? `
 <div style="display: flex; justify-content: space-between;">
 <span style="color: var(--text-muted)">Зданий в OpenStreetMap</span>
 <span style="font-weight: 600">${resData.buildings_detected}${typeof resData.buildings_total_area_sqm === 'number' && resData.buildings_total_area_sqm > 0 ? ` · ${formatNumber(resData.buildings_total_area_sqm, 0, ' м²')}` : ''}</span>
 </div>` : ''}
 </div>
 ${renderSourceNotes(data.method || resData.method, resData.sources, resData.notes)}
 </div>
 `;
 }

 if (currentAnalysisType === 'prediction' && resData) {
 html += `
 <div class="stats-panel">
 <h3 class="stats-panel-title">️ Потенциал развития</h3>
 <div style="display: grid; gap: 1rem;">
 <div style="padding: 1rem; background: rgba(255, 215, 0, 0.1); border-radius: 8px; border: 1px solid rgba(255, 215, 0, 0.3);">
 <div style="font-size: 0.85rem; color: var(--text-muted);">Статус</div>
 <div style="font-size: 1.1rem; font-weight: 600; margin-top: 4px; color: #ffca2c;">${resData.growth_status}</div>
 </div>
 
 <div style="display: flex; justify-content: space-between;">
 <span style="color: var(--text-muted)">Свободной земли рядом с застройкой</span>
 <span style="font-weight: 600">${formatNumber(resData.growth_potential_percent, 1, '%')}</span>
 </div>
 ${typeof resData.built_up_percent_2021 === 'number' ? `
 <div style="display: flex; justify-content: space-between;">
 <span style="color: var(--text-muted)">Застройка в 2021 (WorldCover)</span>
 <span style="font-weight: 600">${formatNumber(resData.built_up_percent_2021, 1, '%')}</span>
 </div>` : ''}
 ${typeof resData.built_up_change_pp === 'number' ? `
 <div style="display: flex; justify-content: space-between;">
 <span style="color: var(--text-muted)">Изменение 2020→2021</span>
 <span style="font-weight: 600; color: ${resData.built_up_change_pp > 0 ? 'var(--accent-red)' : 'var(--text-main)'};">${resData.built_up_change_pp > 0 ? '+' : ''}${formatNumber(resData.built_up_change_pp, 1, ' п.п.')}</span>
 </div>` : ''}
 </div>
 ${renderSourceNotes(null, resData.sources, resData.notes)}
 
 <div style="margin-top: 1rem;">
 <h4 class="stats-panel-title" style="font-size: 0.9rem;">Рекомендации</h4>
 <ul style="padding-left: 1.2rem; margin: 0; color: var(--text-muted); font-size: 0.9rem;">
 ${(resData.recommendations || []).map(r => `<li>${escapeHtml(r)}</li>`).join('')}
 </ul>
 </div>
 </div>
 `;
 }

  if (resData.environment || data.environment) {
    const env = resData.environment || data.environment;
    const w = env.weather || {};
    const soil = env.soil_chemistry || {};
    const sources = soil.sources || {};

    // Which numbers are measured, which are derived, and which are missing --
    // showing this is the whole point of replacing the old random values.
    const sourceLabels = {
      measured: { text: 'измерено', color: 'var(--accent-green)' },
      derived: { text: 'расчёт', color: 'var(--accent-orange)' },
      unavailable: { text: 'нет данных', color: 'var(--text-muted)' }
    };

    const sourceBadge = (key) => {
      const meta = sourceLabels[sources[key]] || sourceLabels.unavailable;
      return `<span style="font-size: 0.65rem; color: ${meta.color};">${meta.text}</span>`;
    };

    const nutrient = (label, value, key, color) => `
      <div style="display: flex; flex-direction: column; gap: 2px;">
        <span style="color: ${color};">${label}: ${formatNumber(value, 0)}</span>
        ${sourceBadge(key)}
      </div>`;

    html += `
    <div class="stats-panel" style="margin-top: 1rem;">
      <div style="display: flex; justify-content: space-between; align-items: baseline; gap: 0.5rem; margin-bottom: 0.5rem;">
        <h3 class="stats-panel-title" style="margin: 0;">Агроклиматические условия</h3>
        <span style="font-size: 0.7rem; color: var(--text-muted);">${escapeHtml(env.country || '')}</span>
      </div>

      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.8rem; margin-bottom: 1rem;">
        <div class="env-card">
          <div class="env-val">${formatNumber(w.temp, 1, '°C')}</div>
          <div class="env-label">Температура</div>
        </div>
        <div class="env-card">
          <div class="env-val">${formatNumber(w.humidity, 0, '%')}</div>
          <div class="env-label">Влажность воздуха</div>
        </div>
        <div class="env-card">
          <div class="env-val">${formatNumber(w.wind_speed, 1, ' м/с')}</div>
          <div class="env-label">Ветер</div>
        </div>
        <div class="env-card">
          <div class="env-val">${formatNumber(soil.ph, 1)}</div>
          <div class="env-label">pH почвы · ${escapeHtml((sourceLabels[sources.ph] || sourceLabels.unavailable).text)}${renderRange((soil.ranges || {}).ph, 1)}</div>
        </div>
      </div>
      ${(typeof soil.organic_carbon === 'number' || typeof soil.cec === 'number') ? `
      <div style="display: flex; justify-content: space-between; font-size: 0.8rem; color: var(--text-muted); margin-bottom: 0.8rem; gap: 0.5rem; flex-wrap: wrap;">
        <span>Орг. углерод: ${formatNumber(soil.organic_carbon, 1, ' г/кг')}${renderRange((soil.ranges || {}).organic_carbon, 1)}</span>
        <span>ЁКО: ${formatNumber(soil.cec, 1)}${renderRange((soil.ranges || {}).cec, 1)}</span>
      </div>` : ''}

      <div style="background: rgba(255, 255, 255, 0.03); padding: 10px; border-radius: 8px;">
        <div style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 6px;">
          Питательные вещества (мг/кг), слой ${escapeHtml(soil.depth || '0-5 см')}
        </div>
        <div style="display: flex; justify-content: space-between; font-size: 0.85rem;">
          ${nutrient('N', soil.nitrogen, 'nitrogen', '#4facfe')}
          ${nutrient('P', soil.phosphorus, 'phosphorus', '#00f2fe')}
          ${nutrient('K', soil.potassium, 'potassium', '#a8edea')}
        </div>
        <div style="display: flex; justify-content: space-between; font-size: 0.8rem; margin-top: 8px; color: var(--text-muted);">
          <span>Влажность почвы: ${formatNumber(soil.moisture, 1, '%')}</span>
          <span>${escapeHtml(soil.texture || '')}</span>
        </div>
        ${soil.provider ? `<div style="margin-top: 6px; font-size: 0.7rem; color: var(--text-muted);">Источник: ${escapeHtml(soil.provider)}</div>` : ''}
      </div>

      <div style="margin-top: 10px; font-size: 0.85rem; color: var(--primary-light); background: rgba(var(--primary-rgb), 0.1); padding: 8px; border-radius: 6px;">
        ${escapeHtml(env.recommendation || '')}
      </div>

    </div>
    `;
  }

 if (resultsContainer) resultsContainer.innerHTML = html;

 const bottomCrops = document.getElementById('map-bottom-crops-container');
 if (bottomCrops) {
  const env = resData ? (resData.environment || data.environment) : (data ? data.environment : null);
  if (env && env.crops) {
    bottomCrops.innerHTML = renderCropsBottom(env.crops, env.country);
  } else {
 bottomCrops.innerHTML = '';
 }
 }
}

/**
 * What the fertility index is made of.
 *
 * The number is a blend of multi-season productivity (Sentinel-2), a soil
 * score (SoilGrids), a land-cover mask (WorldCover) and slope (DEM). Showing
 * each part with its source is what separates a grounded estimate from a
 * coloured picture.
 */
function renderFertilityComponents(components) {
  if (!components || (!components.productivity && !components.soil && !components.note)) return '';

  if (components.note && !components.productivity) {
    return `<div class="stats-panel" style="margin-top: 1rem; font-size: 0.85rem; color: var(--text-muted);">${escapeHtml(components.note)}</div>`;
  }

  const p = components.productivity || {};
  const s = components.soil || {};
  const lc = components.land_cover || {};
  const el = components.elevation || {};

  const factorLabels = { ph: 'pH', organic_carbon: 'Орг. углерод', cec: 'ЁКО', texture: 'Текстура' };
  const factorRows = Object.entries(s.factors || {}).map(([key, f]) => `
    <div style="display: flex; justify-content: space-between; font-size: 0.8rem;">
      <span style="color: var(--text-muted);">${escapeHtml(factorLabels[key] || key)}: ${escapeHtml(f.value)}</span>
      <span>${formatNumber(f.factor * 100, 0, '%')} · вес ${formatNumber(f.weight * 100, 0, '%')}</span>
    </div>`).join('');

  const coverRows = Object.entries(lc.percentages || {})
    .sort((a, b) => b[1] - a[1]).slice(0, 5)
    .map(([label, share]) => `<span style="margin-right: 0.6rem;">${escapeHtml(label)} ${formatNumber(share, 0, '%')}</span>`)
    .join('');

  const row = (label, value) => `
    <div style="display: flex; justify-content: space-between; font-size: 0.85rem;">
      <span style="color: var(--text-muted);">${label}</span>
      <span style="font-weight: 600;">${value}</span>
    </div>`;

  return `
  <div class="stats-panel" style="margin-top: 1rem;">
    <h4 class="stats-panel-title" style="font-size: 0.9rem;">Из чего сложен индекс</h4>

    <div style="margin-bottom: 0.8rem;">
      <div style="font-size: 0.85rem; font-weight: 600; margin-bottom: 4px;">
        Продуктивность · вес ${formatNumber((p.weight || 0) * 100, 0, '%')}
      </div>
      ${row('Сезонов Sentinel-2', (p.years || []).length ? `${p.years.length} (${Math.min(...p.years)}–${Math.max(...p.years)})` : '—')}
      ${row('Снимков использовано', p.scenes_used ?? '—')}
      ${row('Пиковый NDVI (среднее по земле)', formatNumber(p.peak_ndvi_mean, 3))}
      ${row('Средний NDVI за сезон', formatNumber(p.season_ndvi_mean, 3))}
      ${p.source ? `<div style="font-size: 0.7rem; color: var(--text-muted);">Источник: ${escapeHtml(p.source)}</div>` : ''}
    </div>

    <div style="margin-bottom: 0.8rem;">
      <div style="font-size: 0.85rem; font-weight: 600; margin-bottom: 4px;">
        Почва · вес ${formatNumber((s.weight || 0) * 100, 0, '%')}
        ${typeof s.score === 'number' ? `<span class="badge badge-info" style="margin-left: 6px;">${formatNumber(s.score * 100, 0, '%')}</span>` : ''}
      </div>
      ${factorRows || `<div style="font-size: 0.8rem; color: var(--text-muted);">${escapeHtml(s.note || 'нет данных')}</div>`}
      ${s.source ? `<div style="font-size: 0.7rem; color: var(--text-muted);">Источник: ${escapeHtml(s.source)}${s.resolution_m ? `, ${s.resolution_m} м` : ''}</div>` : ''}
    </div>

    <div style="font-size: 0.8rem; color: var(--text-muted);">
      ${lc.source ? `Покров: ${escapeHtml(lc.source)}. ${coverRows}` : escapeHtml(lc.note || '')}
      ${el.source ? `<div>Рельеф: ${escapeHtml(el.source)}, порог склона ${el.steep_threshold_percent}%</div>` : ''}
    </div>
  </div>`;
}

function renderCropsBottom(crops, country) {
  if (!crops || crops.length === 0) return '';

  const title = country
    ? `Рекомендуемые культуры (${escapeHtml(country)})`
    : 'Рекомендуемые культуры';

  let html = `
  <div style="padding: 1rem; border-top: 1px solid var(--border-color); background: rgba(0,0,0,0.2);">
  <h4 style="margin: 0 0 1rem 0; font-size: 0.95rem; display: flex; align-items: center; gap: 8px;">
  ${title}
  </h4>
 <div style="display: flex; gap: 1rem; overflow-x: auto; padding-bottom: 5px;">
 `;

 crops.forEach(c => {
 html += `
 <div style="min-width: 140px; background: rgba(0, 255, 136, 0.05); border: 1px solid rgba(0, 255, 136, 0.2); border-radius: 12px; padding: 12px; flex: 1;">
 <div style="font-weight: 600; text-align: center; margin-bottom: 4px;">${escapeHtml(c.icon || '')} ${escapeHtml(c.name)}</div>
 <div style="display: flex; justify-content: center; margin-bottom: 6px;">
 <span class="badge badge-success">${escapeHtml(c.match_percent)}% совпадение</span>
 </div>
 <div style="font-size: 0.75rem; color: var(--text-muted); text-align: center; line-height: 1.3;">
 ${escapeHtml(c.desc)}
 </div>
 </div>
 `;
 });

 html += `</div></div>`;
 return html;
}

/** "(5.9–7.1)" for a SoilGrids uncertainty band, or nothing when absent. */
function renderRange(range, digits = 1) {
  if (!Array.isArray(range) || range.length !== 2) return '';
  if (typeof range[0] !== 'number' || typeof range[1] !== 'number') return '';
  return ` <span style="opacity: 0.75;">(${formatNumber(range[0], digits)}–${formatNumber(range[1], digits)})</span>`;
}

/** Method, named data sources and caveats for the urban results. */
function renderSourceNotes(method, sources, notes) {
  const parts = [];
  if (method) parts.push(`<div>${escapeHtml(method)}</div>`);
  if (Array.isArray(sources) && sources.length) {
    parts.push(`<div>Источники: ${sources.map(escapeHtml).join(', ')}</div>`);
  }
  if (Array.isArray(notes) && notes.length) {
    parts.push(notes.map(n => `<div style="color: var(--accent-orange);">${escapeHtml(n)}</div>`).join(''));
  }
  if (!parts.length) return '';
  return `<div style="margin-top: 0.6rem; font-size: 0.75rem; color: var(--text-muted);">${parts.join('')}</div>`;
}

/**
 * Provenance of the imagery behind a result.
 *
 * With Sentinel-2 there is a real acquisition date and cloud percentage to
 * show; the RGB basemap has neither, so those parts are simply omitted.
 */
function renderImageryNote(imagery) {
  if (!imagery) return '';

  const parts = [];
  if (imagery.source) parts.push(escapeHtml(imagery.source));
  if (imagery.capture_date) parts.push(`съёмка ${formatDate(imagery.capture_date)}`);
  if (imagery.provider) parts.push(escapeHtml(imagery.provider));
  if (imagery.metres_per_pixel) parts.push(`${formatNumber(imagery.metres_per_pixel, 1)} м/пиксель`);
  if (typeof imagery.cloud_percent === 'number') {
    parts.push(`облачность ${formatNumber(imagery.cloud_percent, 0, '%')}`);
  }
  if (imagery.elevation_model) parts.push(escapeHtml(imagery.elevation_model));

  if (parts.length === 0) return '';
  return `<div style="margin-top: 0.6rem; font-size: 0.75rem; color: var(--text-muted);">${parts.join(' · ')}</div>`;
}

function formatDate(iso) {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return escapeHtml(iso);
  return parsed.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' });
}

/** Show or hide features that depend on server-side credentials. */
function applyCapabilities() {
  const detectButton = document.getElementById('detect-field-btn');
  if (detectButton) {
    detectButton.hidden = !serverCapabilities.field_detection;
  }
}

/**
 * Draw the mapped field boundary under the map centre.
 *
 * Beats dragging a rectangle by hand: the polygon follows the real parcel, so
 * the analysed area matches what is actually farmed. Boundaries come from
 * OpenStreetMap, so a location nobody has mapped yet answers 404 and the user
 * keeps drawing by hand.
 */
window.detectField = async function () {
  if (!currentBounds) {
    alert('Карта ещё не загрузилась');
    return;
  }

  const centre = currentBounds.getCenter();
  setLoading(true);
  setError(null);

  try {
    const res = await fetch(`${API_URL}/fields/detect/`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ lat: centre.lat, lon: centre.lng })
    });

    if (!res.ok) {
      setError(await describeHttpError(res));
      return;
    }

    const { features } = await res.json();
    const field = features.find(f => f.type === 'field') || features[0];

    if (!field || !field.bounds || field.bounds.length < 3) {
      setError('Границы участка не найдены для этой точки.');
      return;
    }

    if (drawnItems) drawnItems.clearLayers();
    const polygon = L.polygon(field.bounds, { color: '#00ff88', weight: 3, fillOpacity: 0.15 });
    if (drawnItems) drawnItems.addLayer(polygon);
    currentDrawnLayer = polygon;
    currentBounds = polygon.getBounds();
    map.fitBounds(currentBounds);

    updateDashboard();
  } catch (err) {
    console.error('Field detection failed:', err);
    setError('Не удалось определить границы участка.');
  } finally {
    setLoading(false);
  }
};

function renderBar(label, value, color) {
 if (!value) value = 0;
 return `
 <div class="stat-bar-item">
 <div class="stat-bar-label">
 <span>${label}</span>
 <span>${value.toFixed(1)}%</span>
 </div>
 <div class="stat-bar">
 <div class="stat-bar-fill" style="width: ${value}%; background-color: ${color}"></div>
 </div>
 </div>
 `;
}

function updateLegend(data) {
 if (!legendItems) return;

 if (!data) {
 legendItems.innerHTML = '<div style="color: var(--text-muted); font-size: 0.875rem;">Сделайте анализ для отображения легенды</div>';
 return;
 }

 let legend = data.legend;

 if (!legend && currentAnalysisType === 'ndvi') {
 legend = {
 "Здоровая растительность": "rgba(0, 128, 0, 0.7)",
 "Умеренная растительность": "rgba(144, 238, 144, 0.7)",
 "Слабая растительность": "rgba(255, 255, 0, 0.7)",
 "Голая почва": "rgba(139, 69, 19, 0.7)",
 "Вода/Тень": "rgba(0, 0, 139, 0.7)"
 };
 }

 if (!legend && currentAnalysisType === 'weeds') {
 legend = {
 "Аномалии растительности": "rgba(255, 0, 0, 0.8)",
 "Обычная растительность": "rgba(0, 0, 0, 0.0)"
 };
 }

 if (legend) {
 let html = '';
 for (const [label, color] of Object.entries(legend)) {
 html += `
 <div class="legend-item">
 <div class="legend-color" style="background-color: ${escapeHtml(color)}"></div>
 <span>${escapeHtml(label)}</span>
 </div>`;
 }
 legendItems.innerHTML = html;
 }
}

function setLoading(isLoading) {
 const btn = document.getElementById('btn-analyze');
 if (isLoading) {
 if (loadingOverlay) loadingOverlay.classList.remove('hidden');
 if (btn) {
 btn.disabled = true;
 btn.textContent = ' Анализ...';
 }
 } else {
 if (loadingOverlay) loadingOverlay.classList.add('hidden');
 if (btn) {
 btn.disabled = false;
 btn.textContent = ' Анализировать состояние';
 }
 }
}

function setError(msg) {
 if (msg) {
 if (errorText) errorText.textContent = msg;
 if (errorAlert) errorAlert.classList.remove('hidden');
 } else {
 if (errorAlert) errorAlert.classList.add('hidden');
 }
}
