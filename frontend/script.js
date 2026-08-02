const API_URL = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' || window.location.protocol === 'file:'
  ? 'http://127.0.0.1:8000/api'
  : '/api';

// --- AUTHENTICATION STATE ---
let authToken = localStorage.getItem('auth_token') || null;
let currentUser = null;
try {
  const savedUser = localStorage.getItem('auth_user');
  if (savedUser) currentUser = JSON.parse(savedUser);
} catch (e) {
  currentUser = null;
}

function getAuthHeaders(extraHeaders = {}) {
  const headers = {
    'Content-Type': 'application/json',
    ...extraHeaders
  };
  if (authToken) {
    headers['Authorization'] = `Token ${authToken}`;
  }
  return headers;
}

function updateAuthUI() {
  const nameEl = document.getElementById('user-name-text');
  const emailEl = document.getElementById('user-email-text');
  const btnEl = document.getElementById('btn-auth-action');
  const avatarEl = document.getElementById('user-avatar');

  if (authToken && currentUser) {
    if (nameEl) nameEl.textContent = currentUser.first_name || currentUser.username || 'Пользователь';
    if (emailEl) emailEl.textContent = currentUser.email || '';
    if (btnEl) btnEl.innerHTML = '🚪 Выйти';
    if (avatarEl) {
      const char = (currentUser.first_name || currentUser.email || 'U')[0].toUpperCase();
      avatarEl.textContent = char;
    }
    hideAuthModal();
  } else {
    if (nameEl) nameEl.textContent = 'Гость';
    if (emailEl) emailEl.textContent = 'Требуется вход';
    if (btnEl) btnEl.innerHTML = '🔐 Войти';
    if (avatarEl) avatarEl.textContent = '👤';
  }
}

function showAuthModal(defaultTab = 'login') {
  const modal = document.getElementById('auth-modal');
  if (modal) {
    modal.classList.remove('hidden');
    switchAuthTab(defaultTab);
  }
}

function hideAuthModal() {
  const modal = document.getElementById('auth-modal');
  if (modal) {
    modal.classList.add('hidden');
  }
}

function switchAuthTab(tab) {}

function handleAuthAction() {}

function requireAuth() {
  return true;
}

async function handleLoginSubmit(event) {
  event.preventDefault();
  const emailInput = document.getElementById('login-email');
  const errBox = document.getElementById('auth-login-error');
  const btnSubmit = document.getElementById('btn-login-submit');

  const email = emailInput ? emailInput.value.trim() : '';

  if (!email) {
    showAuthError(errBox, 'Заполните поле email');
    return;
  }

  if (btnSubmit) btnSubmit.disabled = true;
  if (errBox) errBox.classList.add('hidden');

  try {
    const res = await fetch(`${API_URL}/auth/email/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email })
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Ошибка входа');
    }

    authToken = data.token;
    currentUser = data.user;
    localStorage.setItem('auth_token', authToken);
    localStorage.setItem('auth_user', JSON.stringify(currentUser));

    updateAuthUI();
    loadFields();
  } catch (err) {
    showAuthError(errBox, err.message);
  } finally {
    if (btnSubmit) btnSubmit.disabled = false;
  }
}

async function handleRegisterSubmit(event) {
  event.preventDefault();
  const nameInput = document.getElementById('reg-name');
  const emailInput = document.getElementById('reg-email');
  const passInput = document.getElementById('reg-password');
  const errBox = document.getElementById('auth-reg-error');
  const btnSubmit = document.getElementById('btn-reg-submit');

  const first_name = nameInput ? nameInput.value.trim() : '';
  const email = emailInput ? emailInput.value.trim() : '';
  const password = passInput ? passInput.value : '';

  if (!email || !password) {
    showAuthError(errBox, 'Заполните обязательные поля');
    return;
  }

  if (btnSubmit) btnSubmit.disabled = true;
  if (errBox) errBox.classList.add('hidden');

  try {
    const res = await fetch(`${API_URL}/auth/register/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, first_name })
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Ошибка регистрации');
    }

    authToken = data.token;
    currentUser = data.user;
    localStorage.setItem('auth_token', authToken);
    localStorage.setItem('auth_user', JSON.stringify(currentUser));

    updateAuthUI();
    loadFields();
  } catch (err) {
    showAuthError(errBox, err.message);
  } finally {
    if (btnSubmit) btnSubmit.disabled = false;
  }
}

async function logout() {
  if (authToken) {
    try {
      await fetch(`${API_URL}/auth/logout/`, {
        method: 'POST',
        headers: getAuthHeaders()
      });
    } catch (e) {
      console.warn('Logout request failed:', e);
    }
  }

  authToken = null;
  currentUser = null;
  localStorage.removeItem('auth_token');
  localStorage.removeItem('auth_user');

  updateAuthUI();
  showAuthModal('login');
}

function showAuthError(element, message) {
  if (element) {
    element.textContent = message;
    element.classList.remove('hidden');
  }
}

async function checkAuthSession() {
  hideAuthModal();
}

window.switchAuthTab = switchAuthTab;
window.handleAuthAction = handleAuthAction;
window.handleLoginSubmit = handleLoginSubmit;
window.handleRegisterSubmit = handleRegisterSubmit;

let map;
let currentOverlay = null;
let currentBounds = null;
let currentAnalysisType = 'ndvi';
let drawnItems = null;
let currentDrawnLayer = null;
let allFields = [];

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

function getCountryByCoords(lat, lon) {
  if (37.0 <= lat && lat <= 46.0 && 59.0 <= lon && lon <= 74.0) {
    return "Узбекистан";
  } else if (45.0 <= lat && lat <= 56.0 && 50.0 <= lon && lon <= 88.0) {
    return "Казахстан";
  } else if (41.0 <= lat && lat <= 82.0 && 19.0 <= lon && lon <= 170.0) {
    return "Россия";
  } else if (36.0 <= lat && lat <= 41.0 && 67.0 <= lon && lon <= 75.0) {
    return "Таджикистан";
  } else if (39.0 <= lat && lat <= 44.0 && 69.0 <= lon && lon <= 80.0) {
    return "Киргизия";
  }
  return "Выбранная местность";
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
    const fields = await res.json();
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
  if (!requireAuth()) return;

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
 infrastructure: '️ Анализ инфраструктуры',
 prediction: '️ Предсказание застройки',
 urban_filter: '️ Фильтр застройки'
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

    const drawControl = new L.Control.Draw({
      edit: {
        featureGroup: drawnItems
      },
      draw: false
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
  if (!requireAuth()) return;

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

 if (!res.ok) throw new Error('Ошибка связи с сервером');

 const data = await res.json();
 renderResult(data);

 } catch (err) {
 console.error(err);
 if (err.message.includes('fetch')) {
 setError("Ошибка подключения к серверу. Убедитесь, что бэкенд запущен (python manage.py runserver)");
 } else {
 setError("Ошибка анализа: " + err.message);
 }
 } finally {
 setLoading(false);
 }
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
            <div class="activity-title">${a.text}</div>
            <div class="activity-time">${a.time}</div>
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

    let countryName = getCountryByCoords(lat, lon);

    try {
      const geoRes = await fetch(`https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lon}&zoom=12&addressdetails=1`, {
        headers: { 'Accept-Language': 'ru' }
      });
      if (geoRes.ok) {
        const geoData = await geoRes.json();
        const address = geoData.address || {};
        const placeName = address.city || address.town || address.village || address.suburb || address.county || address.state || '';
        if (placeName) {
          locationLabel = placeName;
        }
        if (address.country) {
          countryName = address.country;
        }
      }
    } catch (e) {
      console.error("Geocoding error:", e);
    }

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
            <h4 style="margin: 0; font-size: 0.95rem; color: var(--text-main); font-weight: 600;">💰 Оценка стоимости земли</h4>
            <span style="font-size: 1.2rem;" title="${countryName}">${landPriceConfig.flag}</span>
          </div>
          <div style="display: flex; flex-direction: column; gap: 0.6rem; font-size: 0.85rem;">
            <div style="display: flex; justify-content: space-between;">
              <span style="color: var(--text-muted);">Регион/Страна:</span>
              <span style="font-weight: 500; color: var(--text-main);">${countryName}</span>
            </div>
            <div style="display: flex; justify-content: space-between;">
              <span style="color: var(--text-muted);">Площадь:</span>
              <span style="font-weight: 500; color: var(--text-main);">${areaKm2.toFixed(3)} км² (${areaHa.toFixed(2)} га)</span>
            </div>
            <div style="display: flex; justify-content: space-between;">
              <span style="color: var(--text-muted);">Средняя цена:</span>
              <span style="font-weight: 500; color: var(--accent-green);">${usdPerHaFormatted} / га</span>
            </div>
            <div style="border-top: 1px solid var(--border-color); margin-top: 0.4rem; padding-top: 0.6rem; display: flex; justify-content: space-between; align-items: baseline;">
              <span style="color: var(--text-main); font-weight: 600;">Итоговая оценка:</span>
              <div style="text-align: right;">
                <div style="font-size: 1.15rem; font-weight: 700; color: #00ff88;">${totalUsdFormatted}</div>
                ${landPriceConfig.currency !== 'USD' ? `<div style="font-size: 0.85rem; color: var(--accent-orange); font-weight: 500; margin-top: 2px;">≈ ${totalLocalFormatted}</div>` : ''}
              </div>
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

      forecastHtml = [1, 2, 3].map(i => {
        const date = new Date(weatherData.daily.time[i]);
        const temp = Math.round(weatherData.daily.temperature_2m_max[i]);
        const code = weatherData.daily.weathercode[i];
        const icon = weatherIcons[code] || '☀️';
        return `
          <div class="forecast-day">
            <div class="forecast-date">${date.toLocaleDateString('ru-RU', { weekday: 'short' })}</div>
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

 if (data.ndvi && data.ndvi.health_score) {
 sessionStats.totalHealthScore += data.ndvi.health_score;
 sessionStats.healthScoreCount++;
 activityText += ` (Здоровье: ${data.ndvi.health_score.toFixed(1)}%)`;
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

 if (data.stats && data.stats.context === 'urban') {
 const d = data.stats;
 html += `
 <div class="stats-panel">
 <h3 class="stats-panel-title">️ Среда: Город (Авто-обнаружение)</h3>
 <div class="alert alert-info" style="margin-bottom: 1rem; font-size: 0.85rem; padding: 0.5rem;">
 ℹ️ Система определила городскую застройку. Режим анализа плодородия заменен на фильтр урбанизации.
 </div>
 <div class="stats-bars">
 ${renderBar('Застройка (здания/дороги)', d.urban_percent, '#504646')}
 ${renderBar('Растительность', d.veg_percent, '#00ff88')}
 </div>
 <div style="margin-top: 15px; padding: 10px; background: rgba(255,255,255,0.05); border-radius: 8px;">
 <strong>Статус:</strong> ${d.status}
 </div>
 </div>
 `;
 updateLegend({
 legend: {
 "Городская среда (Авто)": "rgba(80, 70, 70, 0.8)",
 "Зеленые зоны": "rgba(0,0,0,0)"
 }
 });

 } else if (data.ndvi) {
 const stages = {
 'bare_soil': 'Голая почва',
 'emergence': 'Всходы',
 'vegetative': 'Вегетация',
 'flowering': 'Цветение',
 'maturation': 'Созревание'
 };

 const scoreClass = data.ndvi.health_score > 70 ? 'badge-success' :
 (data.ndvi.health_score > 40 ? 'badge-warning' : 'badge-danger');

 html += `
 <div class="stats-panel">
 <h3 class="stats-panel-title"> Показатели NDVI</h3>
 <div style="display: grid; gap: 1rem;">
 <div style="display: flex; justify-content: space-between;">
 <span style="color: var(--text-muted)">Средний NDVI</span>
 <span style="font-weight: 600">${data.ndvi.ndvi_mean?.toFixed(4)}</span>
 </div>
 <div style="display: flex; justify-content: space-between;">
 <span style="color: var(--text-muted)">Оценка здоровья</span>
 <span class="badge ${scoreClass}">
 ${data.ndvi.health_score?.toFixed(1)}%
 </span>
 </div>
 <div style="display: flex; justify-content: space-between;">
 <span style="color: var(--text-muted)">Стадия роста</span>
 <span style="font-weight: 600">
 ${stages[data.ndvi.growth_stage] || data.ndvi.growth_stage}
 </span>
 </div>
 </div>
 </div>`;
 } else if (currentAnalysisType === 'urban_filter') {
 const d = resData.data;
 html += `
 <div class="stats-panel">
 <h3 class="stats-panel-title">️ Степень урбанизации</h3>
 <div class="stats-bars">
 ${renderBar('Только город (асфальт/бетон)', d.urban_percent, '#555')}
 ${renderBar('Растительность (фильтр)', d.veg_percent, '#00ff88')}
 </div>
 <div style="margin-top: 15px; padding: 10px; background: rgba(255,255,255,0.05); border-radius: 8px;">
 <strong>Статус:</strong> ${d.status}
 </div>
 </div>
 `;
 }

 if (data.stats && currentAnalysisType === 'fertility') {
 const method = data.stats.analysis_method || 'Heuristic';
 const isAI = method.includes('Groq');
 html += `
 <div class="stats-panel">
 <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
 <h3 class="stats-panel-title" style="margin: 0;">️ Состав почвы</h3>
 <span class="badge ${isAI ? 'badge-success' : 'badge-info'}" style="font-size: 0.7rem;">
 ${isAI ? ' ' : '️ '}${method}
 </span>
 </div>
 ${data.stats.ai_description ? `
 <div style="margin-bottom: 0.75rem; padding: 8px 12px; background: rgba(0, 255, 136, 0.08); border-left: 3px solid #00ff88; border-radius: 4px; font-size: 0.85rem; color: #b0ffb0;">
 <strong>ИИ:</strong> ${data.stats.ai_description}
 </div>
 ` : ''}
 ${data.stats.ai_confidence ? `
 <div style="margin-bottom: 0.75rem; display: flex; justify-content: space-between; font-size: 0.85rem;">
 <span style="color: var(--text-muted)">Уверенность ИИ</span>
 <span style="font-weight: 600; color: #00ff88;">${(data.stats.ai_confidence * 100).toFixed(0)}%</span>
 </div>
 ` : ''}
 <div class="stats-bars">
 ${renderBar('Очень высокое', data.stats.very_high, '#006400')}
 ${renderBar('Высокое', data.stats.high, '#00C800')}
 ${renderBar('Умеренное', data.stats.moderate, '#00FFFF')}
 ${renderBar('Низкое', data.stats.low, '#00A5FF')}
 ${renderBar('Горы / Скалы', data.stats.mountains, '#644632')}
 ${renderBar('Пустыня / Застройка', data.stats.desert, '#969696')}
 ${renderBar('Вода / Тени', data.stats.water, '#0000FF')}
 </div>
 </div>`;
 }

 if (data.detections && currentAnalysisType === 'weeds') {
 const weedMethod = data.analysis_method || 'Heuristic';
 const weedIsAI = weedMethod.includes('Groq');
 html += `
 <div class="stats-panel">
 <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
 <h3 class="stats-panel-title" style="margin: 0;"> Отчет по сорнякам</h3>
 <span class="badge ${weedIsAI ? 'badge-success' : 'badge-info'}" style="font-size: 0.7rem;">
 ${weedIsAI ? ' ' : '️ '}${weedMethod}
 </span>
 </div>
 ${data.ai_analysis ? `
 <div style="margin-bottom: 0.75rem; padding: 8px 12px; background: rgba(0, 255, 136, 0.08); border-left: 3px solid #00ff88; border-radius: 4px; font-size: 0.85rem; color: #b0ffb0;">
 <strong>ИИ:</strong> ${data.ai_analysis.description}
 </div>
 <div style="margin-bottom: 0.75rem; padding: 8px 12px; background: rgba(255, 200, 0, 0.08); border-left: 3px solid #ffca2c; border-radius: 4px; font-size: 0.85rem; color: #ffe0a0;">
 <strong>Рекомендация ИИ:</strong> ${data.ai_analysis.recommendations}
 </div>
 ` : ''}
 <div style="display: grid; gap: 1rem;">
 <div style="display: flex; justify-content: space-between;">
 <span style="color: var(--text-muted)">Покрытие</span>
 <span style="font-weight: 600; color: #dc3545;">${data.weed_coverage_percent?.toFixed(2)}%</span>
 </div>
 <div style="display: flex; justify-content: space-between;">
 <span style="color: var(--text-muted)">Обнаружено очагов</span>
 <span style="font-weight: 600">${data.detections.length}</span>
 </div>
 <div style="display: flex; justify-content: space-between;">
 <span style="color: var(--text-muted)">Площадь поражения</span>
 <span style="font-weight: 600">${data.total_weed_area_sqm?.toFixed(0)} м²</span>
 </div>
 ${data.ai_analysis ? `
 <div style="display: flex; justify-content: space-between;">
 <span style="color: var(--text-muted)">Уверенность ИИ</span>
 <span style="font-weight: 600; color: #00ff88;">${(data.ai_analysis.confidence * 100).toFixed(0)}%</span>
 </div>
 ` : ''}
 </div>
 </div>`;

 if (data.detections.length > 0) {
 html += `<div class="stats-panel" style="margin-top: 1rem;">
 <h4 class="stats-panel-title" style="font-size: 0.9rem;">Обнаруженные объекты</h4>
 <div style="max-height: 200px; overflow-y: auto; display: flex; flex-direction: column; gap: 0.5rem;">`;

 data.detections.forEach((d, i) => {
 html += `
 <div style="background: rgba(255, 255, 255, 0.05); padding: 8px; border-radius: 6px; font-size: 0.85rem;">
 <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
 <span style="color: #dc3545; font-weight: 600;">#${i + 1} ${d.name}</span>
 <span class="badge badge-${d.severity === 'critical' || d.severity === 'high' ? 'danger' : 'warning'}">
 ${d.severity}
 </span>
 </div>
 <div style="color: var(--text-muted);">${d.recommendations}</div>
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
 <div style="font-size: 1.1rem; font-weight: 600; margin-top: 4px;">${resData.district_type}</div>
 </div>
 
 <div style="display: flex; justify-content: space-between;">
 <span style="color: var(--text-muted)">Плотность застройки</span>
 <span style="font-weight: 600">${resData.building_density}%</span>
 </div>
 </div>
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
 <span style="color: var(--text-muted)">Свободной земли (доступной)</span>
 <span style="font-weight: 600">${resData.growth_potential_percent}%</span>
 </div>
 </div>
 
 <div style="margin-top: 1rem;">
 <h4 class="stats-panel-title" style="font-size: 0.9rem;">Рекомендации</h4>
 <ul style="padding-left: 1.2rem; margin: 0; color: var(--text-muted); font-size: 0.9rem;">
 ${resData.recommendations.map(r => `<li>${r}</li>`).join('')}
 </ul>
 </div>
 </div>
 `;
 }

 if (resData.environment || data.environment) {
 const env = resData.environment || data.environment;
 const w = env.weather;
 const s = env.soil_chemistry;

 html += `
 <div class="stats-panel" style="margin-top: 1rem;">
 <h3 class="stats-panel-title">️ Агроклиматические условия</h3>
 
 <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.8rem; margin-bottom: 1rem;">
 <div class="env-card">
 <div class="env-icon">️</div>
 <div class="env-val">${w.temp}°C</div>
 <div class="env-label">Температура</div>
 </div>
 <div class="env-card">
 <div class="env-icon"></div>
 <div class="env-val">${w.humidity}%</div>
 <div class="env-label">Влажность</div>
 </div>
 <div class="env-card">
 <div class="env-icon"></div>
 <div class="env-val">${w.wind_speed} м/с</div>
 <div class="env-label">Ветер</div>
 </div>
 <div class="env-card">
 <div class="env-icon"></div>
 <div class="env-val">${s.ph}</div>
 <div class="env-label">pH Почвы</div>
 </div>
 </div>
 
 <div style="background: rgba(255, 255, 255, 0.03); padding: 10px; border-radius: 8px;">
 <div style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 6px;">Состав почвы (мг/кг)</div>
 <div style="display: flex; justify-content: space-between; font-size: 0.85rem;">
 <span style="color: #4facfe;">N: ${s.nitrogen}</span>
 <span style="color: #00f2fe;">P: ${s.phosphorus}</span>
 <span style="color: #a8edea;">K: ${s.potassium}</span>
 </div>
 <div class="progress-multi" style="margin-top: 5px; height: 6px; display: flex; border-radius: 3px; overflow: hidden;">
 <div style="width: 33%; background: #4facfe;"></div>
 <div style="width: 33%; background: #00f2fe;"></div>
 <div style="width: 34%; background: #a8edea;"></div>
 </div>
 </div>

 <div style="margin-top: 10px; font-size: 0.85rem; color: var(--primary-light); background: rgba(var(--primary-rgb), 0.1); padding: 8px; border-radius: 6px;">
 ${env.recommendation}
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

function renderCropsBottom(crops, country) {
  if (!crops || crops.length === 0) return '';

  const title = country ? `Рекомендуемые культуры (${country})` : 'Рекомендуемые культуры';

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
 <div style="font-weight: 600; text-align: center; margin-bottom: 4px;">${c.name}</div>
 <div style="display: flex; justify-content: center; margin-bottom: 6px;">
 <span class="badge badge-success">${c.match_percent}% Совп.</span>
 </div>
 <div style="font-size: 0.75rem; color: var(--text-muted); text-align: center; line-height: 1.3;">
 ${c.desc}
 </div>
 </div>
 `;
 });

 html += `</div></div>`;
 return html;
}

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
 "Сорняки / Аномалии": "rgba(255, 0, 0, 0.8)",
 "Обычная растительность": "rgba(0, 0, 0, 0.0)"
 };
 }

 if (legend) {
 let html = '';
 for (const [label, color] of Object.entries(legend)) {
 html += `
 <div class="legend-item">
 <div class="legend-color" style="background-color: ${color}"></div>
 <span>${label}</span>
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
