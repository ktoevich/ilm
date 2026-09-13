/**
 * Frontend smoke tests.
 *
 * There is no browser in CI, so the production bundle is executed in jsdom
 * with Leaflet and fetch stubbed. This covers the failures that actually
 * happened here: the entry point that shipped without a bundle, an init
 * handler that threw on a missing function and silently skipped everything
 * after it, API data interpolated into innerHTML unescaped, and `null` soil
 * readings rendering as the literal text "null".
 *
 * Run with:  npm run build && npm test
 */

import { JSDOM, VirtualConsole } from 'jsdom';
import fs from 'node:fs';
import path from 'node:path';


const ROOT = path.resolve(import.meta.dirname, '..');
const bundle = fs.readdirSync(path.join(ROOT, 'dist/assets')).find(f => f.endsWith('.js'));
const html = fs.readFileSync(path.join(ROOT, 'dist/index.html'), 'utf8')
  .replace(/<script[^>]*(cdnjs|unpkg)[^>]*>[\s\S]*?<\/script>/g, '')
  .replace(/<link[^>]*(cdnjs|unpkg|fonts)[^>]*>/g, '')
  .replace(/<script type="module"[^>]*><\/script>/, '');

const errors = [];
const vc = new VirtualConsole();
vc.on('jsdomError', e => errors.push(e.message));
vc.on('error', (...a) => errors.push(a.join(' ')));

const dom = new JSDOM(html, { url: 'http://localhost:5173/', runScripts: 'outside-only', pretendToBeVisual: true, virtualConsole: vc });
const { window } = dom;

const boundsStub = {
  getWest: () => 68.88, getSouth: () => 41.03, getEast: () => 68.92, getNorth: () => 41.07,
  getCenter: () => ({ lat: 41.05, lng: 68.90 }),
};
const layerStub = () => ({ addTo(){ return this; }, remove(){}, addLayer(){}, clearLayers(){}, getBounds: () => boundsStub });
window.L = {
  map: () => ({ setView(){ return this; }, on(){}, addLayer(){}, removeLayer(){}, getBounds: () => boundsStub, fitBounds(){}, addControl(){}, invalidateSize(){} }),
  tileLayer: layerStub, imageOverlay: layerStub,
  polygon: () => ({ getBounds: () => boundsStub, addTo: () => layerStub() }),
  FeatureGroup: function () { return { addTo(){ return this; }, addLayer(){}, clearLayers(){}, getBounds: () => boundsStub }; },
  Draw: { Event: { CREATED: 'draw:created' } },
  Control: { Draw: function () { return { addTo(){} }; } },
};

// A hostile field name, exactly as it would come back from the API.
const XSS = '<img src=x onerror="window.__pwned=true">';

let responder = (url) => String(url).includes('/session/')
  ? { authenticated: true, user_id: 1, fields_count: 0,
      capabilities: { sentinel2_ndvi: true, field_detection: true } }
  : { count: 0, results: [] };
window.fetch = async (url) => ({ ok: true, status: 200, json: async () => responder(String(url)) });
window.alert = () => {};

window.eval(fs.readFileSync(path.join(ROOT, 'dist/assets', bundle), 'utf8'));
window.document.dispatchEvent(new window.Event('DOMContentLoaded', { bubbles: true }));
await new Promise(r => setTimeout(r, 200));

const results = () => window.document.getElementById('results-container').innerHTML;
const checks = [];
const expect = (name, ok, detail = '') => checks.push({ name, ok, detail });

// ---- 1. fertility, full payload ---------------------------------------
responder = (url) => {
  if (url.includes('/analyze/')) return {
    overlay: { image: 'data:image/png;base64,AA', bounds: [[41, 68], [42, 69]] },
    stats: { very_high: 16.67, high: 16.6, moderate: 24.53, low: 34.0, mountains: 0, water: 0.07, desert: 8.13,
             analysis_method: 'Эвристика: индекс ExG + уклон по DEM + маска воды' },
    legend: { 'Очень высокое плодородие': 'rgba(0,100,0,0.7)' },
    method: 'Эвристика: индекс ExG + уклон по DEM + маска воды',
    caveats: ['Оценка построена по вегетационному покрову.', 'Дата съёмки неизвестна.'],
    imagery: { zoom: 13, metres_per_pixel: 14.41, tiles: '4/4', elevation_model: 'Copernicus GLO-90 (Open-Meteo)' },
    environment: {
      country: XSS, warnings: ['Страна определена приблизительно.'],
      weather: { temp: 30.7, humidity: 22, wind_speed: 2.4, condition: 'Ясно' },
      soil_chemistry: {
        ph: 7.4, nitrogen: 50.6, phosphorus: 30.3, potassium: 239.3, moisture: 12.6,
        texture: 'Суглинок тяжёлый', depth: '0-5cm', provider: 'ISRIC SoilGrids v2.0',
        sources: { ph: 'measured', nitrogen: 'derived', phosphorus: 'derived', potassium: 'derived', moisture: 'derived' },
      },
      recommendation: 'Низкая влажность почвы, требуется полив.',
      crops: [{ name: 'Пшеница', icon: '🌾', match_percent: 100, desc: 'Подходит.' }],
    },
  };
  return { count: 0, results: [] };
};
window.setAnalysisType('fertility');
await window.runAnalysis();
await new Promise(r => setTimeout(r, 200));

expect('плодородие: метод показан', results().includes('уклон по DEM'));
expect('плодородие: чекбокс сохранения существует и включён',
  window.document.getElementById('save-result-check')?.checked === true);
expect('плодородие: блок оговорок не рендерится', !results().includes('Как читать этот результат'));
expect('плодородие: разрешение снимка показано', results().includes('м/пиксель'));
expect('плодородие: источники значений показаны', results().includes('измерено') && results().includes('расчёт'));
expect('плодородие: pH из SoilGrids показан', results().includes('7.4'));
expect('плодородие: предупреждения не рендерятся', !results().includes('приблизительно'));
expect('XSS не выполнился', window.__pwned === undefined);
expect('XSS экранирован в разметке', !results().includes('<img src=x') && results().includes('&lt;img'));

// ---- 1b. composite fertility: components and soil ranges are rendered ----
responder = (url) => {
  if (url.includes('/analyze/')) return {
    overlay: { image: 'data:image/png;base64,AA', bounds: [[41, 68], [42, 69]] },
    stats: { very_high: 60, high: 10, moderate: 5, low: 2, mountains: 0, water: 1, desert: 2, built_up: 20 },
    legend: {}, method: 'NDVI Sentinel-2 за 3 сезона + почва SoilGrids + покров WorldCover + уклон DEM',
    imagery: { source: 'Sentinel-2 L2A', provider: 'Microsoft Planetary Computer', capture_date: '2026-09-05',
               metres_per_pixel: 13, elevation_model: 'Copernicus GLO-90', land_cover: 'ESA WorldCover 2021 v2.0.0' },
    components: {
      productivity: { source: 'Sentinel-2 L2A (Microsoft Planetary Computer)', years: [2026, 2025, 2024],
                      scenes_used: 18, peak_ndvi_mean: 0.822, season_ndvi_mean: 0.431, score_mean: 0.89, weight: 0.65 },
      soil: { source: 'ISRIC SoilGrids v2.0', resolution_m: 250, score: 0.988, weight: 0.35,
              factors: { ph: { value: 7.5, factor: 1, weight: 0.3 }, cec: { value: 23.8, factor: 0.95, weight: 0.25 } } },
      land_cover: { source: 'ESA WorldCover 2021 v2.0.0', percentages: { 'Пашня': 76.9, 'Застройка': 13.2 } },
      elevation: { source: 'Copernicus GLO-90 (Open-Meteo)', steep_threshold_percent: 15 },
    },
    environment: {
      country: 'Узбекистан', warnings: [],
      weather: { temp: 28, humidity: 30, wind_speed: 2, condition: 'Ясно' },
      soil_chemistry: {
        ph: 7.5, nitrogen: 40, phosphorus: 20, potassium: 200, moisture: 15, organic_carbon: 22.8, cec: 23.8,
        texture: 'Суглинок', depth: '0-5cm', provider: 'ISRIC SoilGrids v2.0',
        ranges: { ph: [6.0, 8.6], organic_carbon: [2.8, 82.5], cec: [5.0, 76.6] },
        sources: { ph: 'measured', nitrogen: 'derived', phosphorus: 'derived', potassium: 'derived', moisture: 'derived' },
      },
      recommendation: 'Показатели в пределах нормы.', crops: [],
    },
  };
  return { count: 0, results: [] };
};
window.setAnalysisType('fertility');
await window.runAnalysis();
await new Promise(r => setTimeout(r, 200));

expect('композит: блок «Из чего сложен индекс» показан', results().includes('Из чего сложен индекс'));
expect('композит: сезоны и число снимков показаны', results().includes('2024–2026') && results().includes('18'));
expect('композит: источник почвы и вес показаны', results().includes('ISRIC SoilGrids') && results().includes('вес 35%'));
expect('композит: покров WorldCover показан', results().includes('ESA WorldCover 2021'));
expect('композит: полоса «Застройка» показана', results().includes('Застройка') && results().includes('20.0%'));
expect('композит: диапазон pH SoilGrids показан', results().includes('6.0–8.6'));

// ---- 2. vegetation ------------------------------------------------------
responder = (url) => url.includes('/growth/analyze/') ? {
  vegetation: { index_type: 'ExG', index_label: 'Индекс зелёности (ExG)', index_mean: 0.0964,
                index_min: -0.04, index_max: 1.0, health_score: 56.12, growth_stage: 'vegetative' },
  overlay: { image: 'data:image/png;base64,AA', bounds: [[41, 68], [42, 69]] },
  method: 'Индекс зелёности (ExG) по RGB-подложке',
  caveats: ['Это индекс ExG, а не NDVI.'],
  imagery: { zoom: 13, metres_per_pixel: 14.4 },
} : { count: 0, results: [] };
window.setAnalysisType('ndvi');
await window.runAnalysis();
await new Promise(r => setTimeout(r, 200));

expect('зелёность: значение показано', results().includes('0.0964'));
expect('зелёность: стадия переведена', results().includes('Вегетация'));
expect('зелёность: блок оговорок не рендерится', !results().includes('Как читать этот результат'));
expect('зелёность: заголовок ExG, не NDVI', results().includes('ExG') && !/Показатели NDVI/.test(results()));

// ---- 3. missing soil data must not print "null" -------------------------
responder = (url) => url.includes('/analyze/') ? {
  overlay: { image: 'd', bounds: [[41, 68], [42, 69]] },
  stats: { very_high: 0, high: 0, moderate: 0, low: 0, mountains: 0, water: 100, desert: 0 },
  legend: {}, method: 'Эвристика', caveats: [], imagery: { zoom: 13, metres_per_pixel: 14 },
  environment: {
    country: 'Выбранная местность',
    warnings: ['Данные о почве для этой точки недоступны.'],
    weather: { temp: null, humidity: null, wind_speed: null, condition: null },
    soil_chemistry: { ph: null, nitrogen: null, phosphorus: null, potassium: null, moisture: null,
                      texture: null, provider: null, depth: null,
                      sources: { ph: 'unavailable', nitrogen: 'unavailable', phosphorus: 'unavailable',
                                 potassium: 'unavailable', moisture: 'unavailable' } },
    recommendation: 'Нет данных о pH для этой точки.', crops: [],
  },
} : { count: 0, results: [] };
window.setAnalysisType('fertility');
await window.runAnalysis();
await new Promise(r => setTimeout(r, 200));

expect('нет данных: не печатает null/undefined/NaN', !/null|undefined|NaN/.test(results()), results().match(/null|undefined|NaN/)?.[0]);
expect('нет данных: показан прочерк', results().includes('—'));
expect('нет данных: подпись «нет данных»', results().includes('нет данных'));
expect('нет данных: предупреждения не рендерятся', !results().includes('недоступны'));

// ---- 3b. Sentinel-2 provenance is shown; the basemap has none -----------
expect('кнопка автоопределения показана при наличии ключа',
  window.document.getElementById('detect-field-btn').hidden === false);

responder = (url) => url.includes('/growth/analyze/') ? {
  vegetation: { index_type: 'NDVI', index_label: 'NDVI (Sentinel-2)', index_mean: 0.52,
                index_min: 0.05, index_max: 0.88, health_score: 61.2, growth_stage: 'flowering',
                moisture_index: 0.0889, moisture_label: 'Умеренная влажность',
                reference_ndvi: 0.3879, reference_years: [2025, 2024],
                ndvi_anomaly: 0.0404, anomaly_label: 'Немного зеленее обычного' },
  overlay: { image: 'data:image/png;base64,AA', bounds: [[41, 68], [42, 69]] },
  method: 'NDVI по Sentinel-2 (ближний ИК), Google Earth Engine',
  imagery: { source: 'Sentinel-2 L2A', provider: 'Microsoft Planetary Computer',
             capture_date: '2026-08-21', cloud_percent: 3.1, metres_per_pixel: 10 },
} : { count: 0, results: [] };
window.setAnalysisType('ndvi');
await window.runAnalysis();
await new Promise(r => setTimeout(r, 200));

expect('NDVI: индекс подписан как NDVI', results().includes('NDVI'));
expect('NDVI: показана дата съёмки', results().includes('21 августа 2026'));
expect('NDVI: показан источник Sentinel-2', results().includes('Sentinel-2 L2A'));
expect('NDVI: показан провайдер', results().includes('Planetary Computer'));
expect('NDVI: показана облачность', results().includes('облачность'));
expect('NDVI: стадия — цветение', results().includes('Цветение'));
expect('NDVI: влажность NDMI показана', results().includes('NDMI') && results().includes('0.089'));
expect('NDVI: отклонение от нормы прошлых лет показано',
  results().includes('2025, 2024') && results().includes('+0.040') && results().includes('зеленее обычного'));

// ---- 4. server errors are surfaced, not replaced by a generic message ----
const httpCase = async (status, body, expected) => {
  window.fetch = async (url) => String(url).includes('/analyze/')
    ? { ok: false, status, json: async () => body }
    : { ok: true, status: 200, json: async () => ({ count: 0, results: [] }) };
  window.setAnalysisType('fertility');
  await window.runAnalysis();
  await new Promise(r => setTimeout(r, 50));
  const shown = window.document.getElementById('error-text').textContent;
  expect(`HTTP ${status}: показано «${expected}»`, shown.includes(expected), shown);
};

await httpCase(400, { bbox: 'Выбранная область слишком велика.' }, 'слишком велика');
await httpCase(502, { error: 'Не удалось загрузить спутниковые снимки' }, 'спутниковые снимки');
await httpCase(429, { detail: 'throttled' }, 'Слишком много анализов');
await httpCase(401, {}, 'не опознал это устройство');

expect('нет ошибок в консоли', errors.length === 0, errors.join(' | '));

for (const { name, ok, detail } of checks) {
  console.log(`${ok ? '  ok  ' : ' FAIL '} ${name}${ok || !detail ? '' : '  <-- ' + detail}`);
}
const failed = checks.filter(c => !c.ok).length;
console.log(`\n${checks.length - failed}/${checks.length} проверок пройдено`);
process.exit(failed ? 1 : 0);
