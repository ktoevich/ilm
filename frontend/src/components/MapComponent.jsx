import React, { useState, useEffect } from 'react';
import { MapContainer, TileLayer, Marker, Popup, useMapEvents, ImageOverlay } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';
import icon from 'leaflet/dist/images/marker-icon.png';
import iconShadow from 'leaflet/dist/images/marker-shadow.png';

let DefaultIcon = L.icon({
    iconUrl: icon,
    shadowUrl: iconShadow,
    iconSize: [25, 41],
    iconAnchor: [12, 41]
});
L.Marker.prototype.options.icon = DefaultIcon;

// Internal component to handle bounds and clicks
const MapController = ({ onBoundsChange }) => {
    const map = useMapEvents({
        moveend: () => {
            onBoundsChange(map.getBounds());
        }
    });

    useEffect(() => {
        onBoundsChange(map.getBounds());
    }, []);

    return null;
};

const MapComponent = () => {
    const [bounds, setBounds] = useState(null);
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState(null);
    const [error, setError] = useState(null);

    const handleAnalyze = async () => {
        if (!bounds) return;
        setLoading(true);
        setError(null);

        const bbox = [
            bounds.getWest(),
            bounds.getSouth(),
            bounds.getEast(),
            bounds.getNorth()
        ];

        try {
            const response = await fetch('http://localhost:8000/api/analyze/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ bbox }),
            });

            if (!response.ok) throw new Error('Backend error');

            const data = await response.json();
            setResult(data);
        } catch (err) {
            console.error("Analysis Error:", err);
            setError("Analysis failed. Try again.");
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="map-app">
            <div className="controls">
                <button onClick={handleAnalyze} disabled={loading || !bounds}>
                    {loading ? 'Анализ почвы...' : 'Анализировать текущий участок'}
                </button>
                {error && <span style={{ color: '#ff4b4b', marginLeft: '1rem' }}>{error}</span>}
            </div>

            <div className="map-wrapper">
                {loading && (
                    <div className="loading-overlay">
                        <div className="spinner"></div>
                        <p>Обработка спутниковых снимков...</p>
                    </div>
                )}

                <MapContainer
                    center={[41.3, 69.2]}
                    zoom={12}
                    style={{ width: '100%', aspectRatio: '1/1', maxHeight: '600px', borderRadius: '16px' }}
                >
                    <TileLayer
                        attribution='&copy; ESRI / ArcGIS'
                        url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
                    />

                    {result && result.overlay && (
                        <ImageOverlay
                            url={result.overlay.image}
                            bounds={result.overlay.bounds}
                            opacity={0.8}
                        />
                    )}

                    <MapController onBoundsChange={setBounds} />
                </MapContainer>
            </div>

            {result && result.legend && (
                <div className="legend-container">
                    <h3>Легенда</h3>
                    {Object.entries(result.legend).map(([label, color]) => (
                        <div key={label} className="legend-item">
                            <div className="legend-color" style={{ backgroundColor: color }}></div>
                            <span>{label}</span>
                        </div>
                    ))}

                    {result.stats && (
                        <div className="stats-container" style={{ marginTop: '1rem', borderTop: '1px solid #ccc', paddingTop: '0.5rem' }}>
                            <h3>Статистика участка</h3>
                            <div>Очень высокое: {result.stats.very_high.toFixed(1)}%</div>
                            <div>Высокое: {result.stats.high.toFixed(1)}%</div>
                            <div>Умеренное: {result.stats.moderate.toFixed(1)}%</div>
                            <div>Низкое: {result.stats.low.toFixed(1)}%</div>
                            <div>Неплодородная: {result.stats.non_fertile.toFixed(1)}%</div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

export default MapComponent;
