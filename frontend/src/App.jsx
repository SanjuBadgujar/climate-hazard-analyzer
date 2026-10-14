import { useState } from "react";
import {
  Chart as ChartJS, CategoryScale, LinearScale, BarElement, BarController, LineController,
  LineElement, PointElement, Tooltip, Legend, Title,
} from "chart.js";
import { Chart } from "react-chartjs-2";
import MapPicker from "./MapPicker.jsx";
import { analyze, csvUrl, geocode } from "./api.js";

ChartJS.register(CategoryScale, LinearScale, BarElement, BarController, LineController,
  LineElement, PointElement, Tooltip, Legend, Title);

const LAST_YEAR = new Date().getFullYear() - 1;

export default function App() {
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState([]);
  const [place, setPlace] = useState("Pune, India");
  const [pos, setPos] = useState({ lat: 18.52, lon: 73.86 });
  const [boxDeg, setBoxDeg] = useState(0);
  const [hazard, setHazard] = useState("heatwave");
  const [floor, setFloor] = useState(0);
  const [start, setStart] = useState(1990);
  const [end, setEnd] = useState(Math.min(2020, LAST_YEAR));
  const [state, setState] = useState({ loading: false, error: "", data: null, params: null });

  async function search(e) {
    e.preventDefault();
    if (query.trim().length < 2) return;
    try {
      setMatches((await geocode(query.trim())).results);
    } catch (err) {
      setState((s) => ({ ...s, error: err.message }));
    }
  }

  function choose(m) {
    setPos({ lat: m.lat, lon: m.lon });
    setPlace([m.name, m.admin1, m.country].filter(Boolean).join(", "));
    setMatches([]);
    setQuery("");
  }

  function buildParams() {
    const p = { hazard, start_year: start, end_year: end };
    if (floor > 0) p.min_tmax_c = floor;
    if (boxDeg > 0) {
      const h = boxDeg / 2;
      Object.assign(p, { min_lat: pos.lat - h, max_lat: pos.lat + h, min_lon: pos.lon - h, max_lon: pos.lon + h });
    } else Object.assign(p, { lat: pos.lat, lon: pos.lon });
    return p;
  }

  async function run() {
    const params = buildParams();
    setState({ loading: true, error: "", data: null, params });
    try {
      setState({ loading: false, error: "", data: await analyze(params), params });
    } catch (err) {
      setState({ loading: false, error: err.message, data: null, params });
    }
  }

  const { data, loading, error, params } = state;

  return (
    <div className="page">
      <header>
        <h1>Climate Hazard Trend Analyzer</h1>
        <p>Historical heatwave frequency, duration and trend for any region (ERA5 reanalysis via Open-Meteo).</p>
      </header>

      <section className="panel controls">
        <div className="left">
          <form onSubmit={search} className="row">
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search a city or state..." maxLength={80} />
            <button type="submit">Search</button>
          </form>
          {matches.length > 0 && (
            <ul className="matches">
              {matches.map((m, i) => (
                <li key={i}><button type="button" onClick={() => choose(m)}>
                  {[m.name, m.admin1, m.country].filter(Boolean).join(", ")}
                </button></li>
              ))}
            </ul>
          )}
          <p className="muted">Selected: <b>{place}</b> ({pos.lat}, {pos.lon}) - or click the map</p>

          <div className="grid">
            <label>Hazard
              <select value={hazard} onChange={(e) => setHazard(e.target.value)}>
                <option value="heatwave">Heatwave</option>
                <option disabled>Drought (planned)</option>
                <option disabled>Heavy rainfall (planned)</option>
              </select>
            </label>
            <label>Region size
              <select value={boxDeg} onChange={(e) => setBoxDeg(+e.target.value)}>
                <option value={0}>Point (city)</option>
                <option value={1}>1&deg; box</option>
                <option value={2}>2&deg; box</option>
                <option value={5}>5&deg; box</option>
              </select>
            </label>
            <label>Minimum Tmax
              <select value={floor} onChange={(e) => setFloor(+e.target.value)}>
                <option value={0}>None (percentile only)</option>
                <option value={35}>&ge; 35&deg;C</option>
                <option value={40}>&ge; 40&deg;C</option>
              </select>
            </label>
            <label>From
              <input type="number" min={1950} max={LAST_YEAR} value={start} onChange={(e) => setStart(+e.target.value)} />
            </label>
            <label>To
              <input type="number" min={1950} max={LAST_YEAR} value={end} onChange={(e) => setEnd(+e.target.value)} />
            </label>
          </div>
          <button className="primary" onClick={run} disabled={loading}>
            {loading ? "Analyzing... (first run fetches data)" : "Analyze"}
          </button>
          {error && <div className="error" role="alert">{error}</div>}
        </div>
        <MapPicker lat={pos.lat} lon={pos.lon} boxDeg={boxDeg} onPick={(lat, lon) => { setPos({ lat, lon }); setPlace("Custom location"); }} />
      </section>

      {data && <Results data={data} params={params} />}
    </div>
  );
}

function Results({ data, params }) {
  const y = data.yearly;
  const labels = y.map((r) => r.year);
  const mk = data.trends.heatwave_days.mann_kendall;
  const lin = data.trends.heatwave_days.linear;

  const daysChart = {
    labels,
    datasets: [
      { type: "bar", label: "Heatwave days", data: y.map((r) => r.heatwave_days), backgroundColor: "rgba(217,72,15,0.65)" },
      { type: "line", label: "5-yr rolling mean", data: y.map((r) => r.rolling5_days), borderColor: "#1c3d5a", pointRadius: 0, tension: 0.3 },
      { type: "line", label: "Linear trend", data: y.map((r) => r.trend_days), borderColor: "#111", borderDash: [6, 4], pointRadius: 0 },
    ],
  };
  const eventsChart = {
    labels,
    datasets: [
      { type: "bar", label: "Events", data: y.map((r) => r.events), backgroundColor: "rgba(28,61,90,0.6)", yAxisID: "y" },
      { type: "line", label: "Longest event (days)", data: y.map((r) => r.max_duration_days), borderColor: "#b42318", yAxisID: "y1", tension: 0.2 },
    ],
  };
  const base = { responsive: true, plugins: { legend: { position: "bottom" } }, interaction: { mode: "index", intersect: false } };
  const top = [...data.events].sort((a, b) => b.duration_days - a.duration_days || b.mean_excess_c - a.mean_excess_c).slice(0, 8);
  const q = data.data_quality;

  return (
    <>
      <section className="panel insight">
        <h2>{data.insights.headline}</h2>
        {data.insights.details.map((d, i) => <p key={i}>{d}</p>)}
        <span className={`badge ${data.insights.significant ? "sig" : "nosig"}`}>
          {data.insights.significant ? "Statistically significant trend" : "No significant trend"}
        </span>
        <a className="csv" href={csvUrl(params)}>Download CSV</a>
      </section>

      <section className="cards">
        <Stat label="Total events" value={y.reduce((a, r) => a + r.events, 0)} />
        <Stat label="Longest event (days)" value={Math.max(...y.map((r) => r.max_duration_days))} />
        <Stat label="Trend (days/decade)" value={lin.slope_per_decade} />
        <Stat label="Mann-Kendall p" value={mk.p_value < 0.001 ? "<0.001" : mk.p_value} />
      </section>

      <section className="panel">
        <h3>Heatwave days per year</h3>
        <Chart type="bar" data={daysChart} options={base} />
      </section>
      <section className="panel">
        <h3>Events per year and longest duration</h3>
        <Chart type="bar" data={eventsChart} options={{ ...base, scales: { y: { beginAtZero: true, ticks: { precision: 0 } }, y1: { position: "right", beginAtZero: true, grid: { drawOnChartArea: false } } } }} />
      </section>

      <section className="panel">
        <h3>Most intense / longest events</h3>
        <table>
          <thead><tr><th>Start</th><th>End</th><th>Days</th><th>Peak Tmax (&deg;C)</th><th>Avg excess (&deg;C)</th></tr></thead>
          <tbody>
            {top.length === 0 && <tr><td colSpan={5}>No events detected.</td></tr>}
            {top.map((e) => <tr key={e.start}><td>{e.start}</td><td>{e.end}</td><td>{e.duration_days}</td><td>{e.peak_tmax_c}</td><td>{e.mean_excess_c}</td></tr>)}
          </tbody>
        </table>
      </section>

      <section className="panel two">
        <div>
          <h3>Definition</h3>
          <p>Tmax above the {data.definition.percentile}th percentile of each calendar day (&plusmn;7 day window) for at least {data.definition.min_consecutive_days} consecutive days. Threshold range {data.threshold_summary.min_c}&ndash;{data.threshold_summary.max_c}&deg;C.</p>
          <p className="muted">Grid cell {data.region.grid_lat}, {data.region.grid_lon} &middot; {data.source}</p>
        </div>
        <div>
          <h3>Data quality</h3>
          <p>{q.total_days.toLocaleString()} days &middot; {q.missing_days_raw} missing &middot; {q.invalid_values_removed} invalid removed &middot; {q.gaps_interpolated_days} interpolated &middot; coverage {(q.valid_fraction * 100).toFixed(1)}%</p>
        </div>
      </section>

      <section className="panel caveats">
        <h3>Read this before quoting the numbers</h3>
        <ul>{data.insights.caveats.map((c, i) => <li key={i}>{c}</li>)}</ul>
      </section>
    </>
  );
}

const Stat = ({ label, value }) => (
  <div className="card"><div className="val">{value ?? "-"}</div><div className="muted">{label}</div></div>
);
