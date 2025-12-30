import React from 'react';
import MapComponent from './components/MapComponent';
import './App.css';

function App() {
  return (
    <div className="dashboard">
      <header>
        <h1>Favorable soil</h1>
        <p className="subtitle">Программа для анализа эффективности и плодородности почв</p>
      </header>

      <main>
        <MapComponent />
      </main>

      <footer style={{ marginTop: '2rem', textAlign: 'center', opacity: 0.5, fontSize: '0.8rem' }}>
        Данные предоставлены ESRI ArcGIS World Imagery. Анализ плодородности выполняется локально.
      </footer>
    </div>
  );
}

export default App;
