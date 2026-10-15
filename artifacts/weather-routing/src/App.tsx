import { Fragment, useMemo, useState, useEffect, type FormEvent } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useCreateRoutePlan, useWeatherRoutingHealth } from '@workspace/api-client-react';
import type { RoutePlanInput, RoutePlanResult, RouteOption, RouteCheckpoint } from '@workspace/api-client-react';
import { MapContainer, TileLayer, Polyline, CircleMarker, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import { AlertTriangle, ArrowDown, ArrowRight, Check, ChevronDown, Clock3, CloudRain, Compass, Gauge, MapPin, Navigation, RefreshCw, Route as RouteIcon, Truck, Wind } from 'lucide-react';

const queryClient = new QueryClient();

const riskText: Record<string, string> = { low: 'Low', moderate: 'Moderate', high: 'High', severe: 'Severe', no_travel: 'No travel' };
const riskColor: Record<string, string> = { low: '#4d806b', moderate: '#d2a34a', high: '#d27a42', severe: '#bd5148', no_travel: '#772f31' };

function stamp(value?: string) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(date);
}
function duration(seconds: number) {
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.round((seconds % 3600) / 60);
  return `${hrs}h ${String(mins).padStart(2, '0')}m`;
}
function riskAtForecastOffset(point: RouteCheckpoint, offset: number) {
  if (!point.forecast.length) return point.risk_level;
  return point.forecast.reduce((nearest, candidate) =>
    Math.abs(candidate.forecast_offset_hours - offset) <
    Math.abs(nearest.forecast_offset_hours - offset)
      ? candidate
      : nearest,
  ).risk_level;
}
function FitRoutes({ routes }: { routes: RouteOption[] }) {
  const map = useMap();
  useEffect(() => {
    const points = routes.flatMap(route => route.coordinates.map(point => [point.latitude, point.longitude] as [number, number]));
    if (points.length > 1) map.fitBounds(points, { padding: [38, 38], maxZoom: 7 });
  }, [map, routes]);
  return null;
}

function RouteMap({ routes, selected, activeRoute, forecastOffset, selectedCheckpoint, onSelectCheckpoint }: { routes: RouteOption[]; selected: string; activeRoute: RouteOption; forecastOffset: number; selectedCheckpoint: number | null; onSelectCheckpoint: (routeId: string, index: number) => void }) {
  const focus = activeRoute.coordinates[0];
  const center: [number, number] = focus ? [focus.latitude, focus.longitude] : [39.5, -98.35];
  return (
    <div className="map-frame" data-testid="map-route-display">
      <MapContainer center={center} zoom={5} scrollWheelZoom className="route-map">
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
          url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"
          subdomains="abcd"
          maxZoom={20}
        />
        <FitRoutes routes={routes} />
        {routes.map((route, index) => {
          const isSelected = route.route_id === selected;
          const color = isSelected ? '#bd7735' : ['#536c7a', '#8c9a98', '#9c8068'][index % 3];
          return <Fragment key={route.route_id}>
            {route.coordinates.length > 1 && <Polyline positions={route.coordinates.map(p => [p.latitude, p.longitude] as [number, number])} pathOptions={{ color, weight: isSelected ? 5 : 3, opacity: isSelected ? 0.94 : 0.62, dashArray: isSelected ? undefined : '7 8' }} />}
            {route.checkpoints.map((point) => {
              const risk = riskAtForecastOffset(point, forecastOffset);
              const activeCheckpoint = isSelected && point.index === selectedCheckpoint;
              return <CircleMarker
                key={point.index}
                center={[point.latitude, point.longitude]}
                radius={activeCheckpoint ? 7 : isSelected ? 5 : 3.5}
                eventHandlers={{ click: () => onSelectCheckpoint(route.route_id, point.index) }}
                pathOptions={{ color: activeCheckpoint ? '#293c46' : '#f9f5eb', weight: activeCheckpoint ? 3 : 1.5, fillColor: riskColor[risk] || '#81908a', fillOpacity: isSelected ? 1 : 0.72 }}
              />;
            })}
          </Fragment>;
        })}
      </MapContainer>
      <div className="map-legend"><span><i className="legend-line chosen" /> Selected route</span><span><i className="legend-line other" /> Alternative</span></div>
      <div className="heat-legend" data-testid="legend-forecast-risk">
        {(['low', 'moderate', 'high', 'severe', 'no_travel'] as const).map(level => <span key={level}><i style={{ backgroundColor: riskColor[level] }} />{riskText[level]}</span>)}
        <small>FORECAST +{String(forecastOffset).padStart(2, '0')}H</small>
      </div>
      <div className="map-attribution">Route geometry supplied by routing service</div>
    </div>
  );
}

function App() {
  const createPlan = useCreateRoutePlan();
  const apiHealth = useWeatherRoutingHealth();
  const [origin, setOrigin] = useState('');
  const [destination, setDestination] = useState('');
  const [departure, setDeparture] = useState(() => {
    const d = new Date();
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
    return d.toISOString().slice(0, 16);
  });
  const [loadWeight, setLoadWeight] = useState('38000');
  const [interval, setInterval] = useState<10 | 25 | 50>(25);
  const [result, setResult] = useState<RoutePlanResult | null>(null);
  const [selectedId, setSelectedId] = useState('');
  const [offset, setOffset] = useState(0);
  const [selectedCheckpoint, setSelectedCheckpoint] = useState<number | null>(null);
  const [formError, setFormError] = useState('');

  const routes = result?.routes ?? [];
  const rankedRoutes = useMemo(() => [...routes].sort((a, b) =>
    a.no_travel_miles - b.no_travel_miles ||
    a.severe_miles - b.severe_miles ||
    a.high_miles - b.high_miles ||
    a.average_risk_score - b.average_risk_score ||
    a.duration_seconds - b.duration_seconds
  ), [routes]);
  const selectedRoute = routes.find(route => route.route_id === selectedId) ?? routes.find(route => route.route_id === result?.best_route_id) ?? routes[0];
  const bestRoute = routes.find(route => route.route_id === result?.best_route_id);
  const maxHours = result?.forecast_hours_available ?? 48;
  const checkpoint = selectedRoute?.checkpoints.find(point => point.index === selectedCheckpoint) ?? selectedRoute?.checkpoints[0];
  const selectedForecast = checkpoint?.forecast.length ? checkpoint.forecast.reduce((best, point) => Math.abs(point.forecast_offset_hours - offset) < Math.abs(best.forecast_offset_hours - offset) ? point : best) : undefined;
  const nearestForecastOffset = selectedForecast?.forecast_offset_hours;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError('');
    if (origin.trim().length < 2 || destination.trim().length < 2) {
      setFormError('Enter an origin and destination with at least two characters.');
      return;
    }
    const weight = Number(loadWeight);
    if (!Number.isFinite(weight) || weight < 0 || weight > 200000) {
      setFormError('Load weight must be between 0 and 200,000 lb.');
      return;
    }
    if (!departure || Number.isNaN(new Date(departure).getTime())) {
      setFormError('Choose a valid departure date and time.');
      return;
    }
    const input: RoutePlanInput = {
      origin: origin.trim(),
      destination: destination.trim(),
      departure_at: new Date(departure).toISOString(),
      load_weight_lb: weight,
      sample_interval_miles: interval,
    };
    createPlan.mutate({ data: input }, {
      onSuccess: response => {
        setResult(response);
        setSelectedId(response.best_route_id);
        setOffset(0);
        setSelectedCheckpoint(response.routes.find(route => route.route_id === response.best_route_id)?.checkpoints[0]?.index ?? null);
      },
      onError: error => setFormError(error instanceof Error ? error.message : 'Route comparison could not be completed. Please try again.'),
    });
  }

  function chooseRoute(routeId: string) {
    setSelectedId(routeId);
    setSelectedCheckpoint(routes.find(route => route.route_id === routeId)?.checkpoints[0]?.index ?? null);
  }
  function chooseMapCheckpoint(routeId: string, checkpointIndex: number) {
    setSelectedId(routeId);
    setSelectedCheckpoint(checkpointIndex);
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="/" data-testid="link-home">
          <span className="brand-mark"><RouteIcon size={19} strokeWidth={2.2} /></span>
          <span className="brand-name">WAYPOINT<span>/</span>WX</span>
          <span className="brand-divider" />
          <span className="brand-caption">FLEET WEATHER DESK</span>
        </a>
        <div className="top-status">
          <span className={`service-state ${apiHealth.isError ? 'offline' : ''}`} data-testid="status-routing-api">
            <i /> {apiHealth.isLoading ? 'Checking services' : apiHealth.data?.status === 'ok' ? 'Routing service online' : apiHealth.data?.status || (apiHealth.isError ? 'Routing service unavailable' : 'Routing service')}
          </span>
          <span className="status-divider" />
          <span className="status-time" data-testid="text-current-time"><Clock3 size={14} /> DISPATCH CONSOLE</span>
        </div>
      </header>
      <main className="workspace">
        <section className="intro-row">
          <div>
            <div className="eyebrow"><span className="eyebrow-rule" /> WEATHER-INTELLIGENT DISPATCH</div>
            <h1>Plan the miles<br /><em>the weather allows.</em></h1>
            <p className="intro-copy">Compare route exposure against forecast conditions at your departure time, with risk adjusted for the load you carry.</p>
          </div>
          <div className="desk-stamp"><span>OPERATIONS</span><strong>ROUTE<br />ASSESSMENT</strong><small>WEATHER WINDOW · 00—48H</small></div>
        </section>
        <div className="main-grid">
          <aside className="trip-panel panel" aria-label="Trip details">
            <div className="panel-heading"><div><span className="section-index">01 / TRIP SETUP</span><h2>Trip parameters</h2></div><Compass size={18} /></div>
            <form onSubmit={submit} noValidate data-testid="form-route-plan">
              <label className="field-label" htmlFor="origin">ORIGIN</label>
              <div className="input-wrap"><MapPin size={16} /><input id="origin" data-testid="input-origin" value={origin} onChange={e => setOrigin(e.target.value)} placeholder="City, state or ZIP" autoComplete="off" /></div>
              <div className="route-connector"><span /></div>
              <label className="field-label" htmlFor="destination">DESTINATION</label>
              <div className="input-wrap"><Navigation size={16} /><input id="destination" data-testid="input-destination" value={destination} onChange={e => setDestination(e.target.value)} placeholder="City, state or ZIP" autoComplete="off" /></div>
              <label className="field-label field-spaced" htmlFor="departure">DEPARTURE TIME</label>
              <div className="input-wrap date-input"><Clock3 size={16} /><input id="departure" type="datetime-local" data-testid="input-departure" value={departure} onChange={e => setDeparture(e.target.value)} /></div>
              <div className="field-row">
                <div className="field-block"><label className="field-label" htmlFor="weight">LOAD WEIGHT</label><div className="weight-wrap"><Truck size={16} /><input id="weight" type="number" min="0" max="200000" step="100" data-testid="input-load-weight" value={loadWeight} onChange={e => setLoadWeight(e.target.value)} /><span>LB</span></div></div>
                <div className="field-block"><label className="field-label" htmlFor="interval">CHECKPOINTS</label><div className="select-wrap"><select id="interval" data-testid="select-sample-interval" value={interval} onChange={e => setInterval(Number(e.target.value) as 10 | 25 | 50)}><option value={10}>Every 10 mi</option><option value={25}>Every 25 mi</option><option value={50}>Every 50 mi</option></select><ChevronDown size={14} /></div></div>
              </div>
              <p className="input-note">Payload is factored into weather-risk thresholds.</p>
              {formError && <div className="form-error" role="alert" data-testid="text-form-error"><AlertTriangle size={15} />{formError}</div>}
              <button className="submit-button" type="submit" disabled={createPlan.isPending} data-testid="button-compare-routes">
                {createPlan.isPending ? <><span className="button-pulse" /> Comparing conditions…</> : <>Compare route conditions <ArrowRight size={17} /></>}
              </button>
            </form>
            <div className="service-foot"><span className={`health-dot ${apiHealth.data?.status === 'ok' ? 'healthy' : ''}`} /> ROUTING API {apiHealth.isLoading ? 'CHECKING' : apiHealth.data?.status?.toUpperCase() ?? (apiHealth.isError ? 'UNAVAILABLE' : 'STATUS UNKNOWN')}</div>
          </aside>

          <section className="results-column">
            {!result && !createPlan.isPending && <div className="empty-state panel" data-testid="empty-route-results">
              <div className="empty-illustration"><div className="empty-orbit orbit-a" /><div className="empty-orbit orbit-b" /><RouteIcon size={32} strokeWidth={1.2} /></div>
              <span className="section-index">AWAITING ROUTE INPUT</span>
              <h2>Your forecast briefing<br />starts with a trip.</h2>
              <p>Enter a lane and departure window. We’ll return available route options with checkpoint-level conditions and payload-aware risk indicators.</p>
              <div className="empty-foot"><span>NO ROUTES LOADED</span><span>—</span><span>NO WEATHER ASSUMED</span></div>
            </div>}
            {createPlan.isPending && <div className="loading-state panel" data-testid="loading-route-results"><div className="skeleton skeleton-map" /><div className="skeleton-line wide" /><div className="skeleton-line" /><p>Requesting route geometry and departure-time forecast…</p></div>}
            {result && selectedRoute && <>
              <div className="route-summary panel" data-testid="section-route-summary">
                <div className="summary-top"><div><span className="section-index">02 / ROUTE COMPARISON</span><div className="lane-title">{result.origin}<ArrowRight size={17} />{result.destination}</div></div><span className="plan-chip"><Check size={13} /> PLAN READY</span></div>
                <div className="summary-metrics">
                  <div><span>DEPARTURE</span><strong>{stamp(result.departure_at)}</strong></div>
                  <div><span>LOAD WEIGHT</span><strong>{result.load_weight_lb.toLocaleString()} <small>lb</small></strong></div>
                  <div><span>CHECKPOINT SPACING</span><strong>{result.sample_interval_miles} <small>mi</small></strong></div>
                  <div><span>FORECAST WINDOW</span><strong>0—{result.forecast_hours_available} <small>hours</small></strong></div>
                </div>
              </div>

              <div className="analysis-layout">
                <div className="map-column">
                  <div className="map-heading"><div><span className="section-index">03 / ROUTE GEOMETRY</span><h2>Weather across the lane</h2></div><span className="small-mono"><i /> {routes.length} AVAILABLE {routes.length === 1 ? 'ROUTE' : 'ROUTES'}</span></div>
                  <RouteMap
                    routes={routes}
                    selected={selectedRoute.route_id}
                    activeRoute={selectedRoute}
                    forecastOffset={offset}
                    selectedCheckpoint={selectedCheckpoint}
                    onSelectCheckpoint={chooseMapCheckpoint}
                  />
                  <div className="forecast-panel panel" data-testid="section-forecast-scrubber">
                    <div className="forecast-head"><div><span className="section-index">04 / FORECAST SCRUBBER</span><h3>Conditions along the route</h3></div><div className="forecast-clock"><span>FORECAST OFFSET</span><strong>+{String(offset).padStart(2, '0')} <small>HRS</small></strong></div></div>
                    <input aria-label="Forecast offset in hours" type="range" min={0} max={maxHours} step={1} value={offset} onChange={e => setOffset(Number(e.target.value))} className="forecast-range" data-testid="input-forecast-offset" />
                    <div className="range-labels"><span>DEPARTURE · 0H</span><span>+24H</span><span>+{maxHours}H</span></div>
                    <div className="forecast-condition" data-testid="text-scrubbed-condition">
                      {selectedForecast ? <><div className={`risk-pill risk-${selectedForecast.risk_level}`}><i />{riskText[selectedForecast.risk_level] || selectedForecast.risk_level}</div><span>Checkpoint {checkpoint?.index} · {checkpoint?.distance_miles.toLocaleString()} mi</span><b>{selectedForecast.wind_mph} mph wind</b><span>{selectedForecast.rain_in_per_hour.toFixed(2)} in/hr rain · {selectedForecast.snow_in_per_hour.toFixed(2)} in/hr snow</span><span>{selectedForecast.temperature_f == null ? 'Temperature unavailable' : `${selectedForecast.temperature_f}°F`}</span>{nearestForecastOffset !== offset && <small>Nearest available forecast: +{nearestForecastOffset}h</small>}</> : <span>No forecast points are available for this checkpoint.</span>}
                    </div>
                  </div>
                </div>
                <aside className="route-list-panel panel" data-testid="section-route-rankings">
                  <div className="panel-heading"><div><span className="section-index">05 / RISK RANKING</span><h2>Route alternatives</h2></div><Gauge size={18} /></div>
                  <p className="ranking-note">Fewest no-travel, severe, and high miles; then average risk and travel time. The service recommendation is marked separately.</p>
                  <div className="route-cards">
                    {rankedRoutes.map((route, index) => {
                      const recommended = route.route_id === result.best_route_id;
                      const isActive = route.route_id === selectedRoute.route_id;
                      return <button key={route.route_id} className={`route-card ${isActive ? 'active' : ''}`} onClick={() => chooseRoute(route.route_id)} data-testid={`button-select-route-${route.route_id}`}>
                        <div className="route-card-top"><span className="route-rank">0{index + 1}</span><span className="route-card-title">{route.label}</span>{recommended && <span className="recommend-badge">RECOMMENDED</span>}</div>
                        <p className="route-summary-copy">{route.summary}</p>
                        <div className="route-stats"><span><b>{route.distance_miles.toLocaleString()}</b> mi</span><span><b>{duration(route.duration_seconds)}</b></span><span><b>{stamp(route.estimated_arrival)}</b> ETA</span></div>
                        <div className="risk-meter-row"><span>AVERAGE RISK SCORE</span><strong>{route.average_risk_score}</strong></div>
                        <div className="risk-meter" aria-label={`Rank position ${index + 1} of ${rankedRoutes.length}`}><i style={{ width: `${Math.round(((rankedRoutes.length - index) / rankedRoutes.length) * 100)}%`, backgroundColor: riskColor[index === 0 ? 'low' : index === rankedRoutes.length - 1 ? 'high' : 'moderate'] }} /></div>
                        <div className="exposure-row"><span><i className="exposure high" />{route.high_miles.toLocaleString()} high mi</span><span><i className="exposure severe" />{route.severe_miles.toLocaleString()} severe mi</span><span><i className="exposure closed" />{route.no_travel_miles.toLocaleString()} no-travel mi</span></div>
                      </button>;
                    })}
                  </div>
                  <div className="ranking-legend"><span><Check size={13} /> API recommendation</span><span><ArrowDown size={13} /> Rank from average score</span></div>
                </aside>
              </div>

              <section className="checkpoint-section panel" data-testid="section-checkpoints">
                <div className="checkpoint-head"><div><span className="section-index">06 / SEGMENT CONDITIONS</span><h2>Checkpoint exposure</h2><p>Selected route: <strong>{selectedRoute.label}</strong> · {selectedRoute.checkpoints.length} reported checkpoints</p></div><span className="small-mono">AT DEPARTURE</span></div>
                {selectedRoute.checkpoints.length ? <div className="checkpoint-table-wrap"><table className="checkpoint-table">
                  <thead><tr><th>CHECKPOINT</th><th>DISTANCE</th><th>ARRIVAL</th><th>CONDITIONS</th><th>RISK</th><th>REASONS</th></tr></thead>
                  <tbody>{selectedRoute.checkpoints.map(point => <tr key={`${selectedRoute.route_id}-${point.index}`} className={point.index === checkpoint?.index ? 'selected-row' : ''} onClick={() => setSelectedCheckpoint(point.index)} data-testid={`row-checkpoint-${point.index}`}>
                    <td><button className="checkpoint-select" onClick={() => setSelectedCheckpoint(point.index)} data-testid={`button-checkpoint-${point.index}`}><span className="checkpoint-number">{String(point.index).padStart(2, '0')}</span><span>Segment {point.index}</span></button></td>
                    <td><strong>{point.distance_miles.toLocaleString()} mi</strong><small>+{point.segment_miles} mi segment</small></td>
                    <td>{stamp(point.estimated_arrival)}</td>
                    <td className="weather-cell"><Wind size={13} />{Math.round(point.weather.wind_mph)} mph <CloudRain size={13} />{point.weather.rain_in_per_hour.toFixed(2)} rain{point.weather.snow_in_per_hour > 0 && <> · {point.weather.snow_in_per_hour.toFixed(2)} snow</>}{point.weather.temperature_f != null && <> · {point.weather.temperature_f}°F</>}</td>
                    <td><span className={`risk-pill risk-${point.risk_level}`}><i />{riskText[point.risk_level] || point.risk_level}</span></td>
                    <td className="reason-cell">{point.risk_reasons.length ? point.risk_reasons.join(' · ') : 'No risk factors reported'}</td>
                  </tr>)}</tbody>
                </table></div> : <div className="checkpoint-empty"><AlertTriangle size={17} /> The routing service returned no checkpoint samples for this route.</div>}
                <div className="checkpoint-detail">
                  <div className="detail-label"><span className="section-index">SELECTED CHECKPOINT DETAIL</span><strong>{checkpoint ? `Segment ${checkpoint.index} · mile ${checkpoint.distance_miles}` : 'No checkpoint selected'}</strong></div>
                  {checkpoint && <><div className="detail-conditions"><span>WIND <b>{checkpoint.weather.wind_mph} mph</b></span><span>RAIN <b>{checkpoint.weather.rain_in_per_hour.toFixed(2)} in/hr</b></span><span>SNOW <b>{checkpoint.weather.snow_in_per_hour.toFixed(2)} in/hr</b></span><span>TEMP <b>{checkpoint.weather.temperature_f == null ? '—' : `${checkpoint.weather.temperature_f}°F`}</b></span><span>LOCATION <b>{checkpoint.latitude.toFixed(3)}, {checkpoint.longitude.toFixed(3)}</b></span></div><div className="risk-reasons"><strong>RISK FACTORS</strong>{checkpoint.risk_reasons.length ? checkpoint.risk_reasons.map((reason, i) => <span key={`${checkpoint.index}-${i}`}>{reason}</span>) : <span>No specific risk reasons provided.</span>}</div></>}
                </div>
              </section>

              <div className="recommendation panel" data-testid="section-recommendation">
                <div className="recommend-icon"><Check size={19} /></div>
                <div className="recommend-copy"><span className="section-index">SERVICE RECOMMENDATION</span><h2>{bestRoute ? bestRoute.label : 'No recommended route returned'}</h2><p>{bestRoute?.summary ?? 'The service did not identify a preferred route.'}</p></div>
                {bestRoute && <div className="recommend-metrics"><span>AVG RISK SCORE</span><strong>{bestRoute.average_risk_score}</strong><span>{bestRoute.severe_miles.toLocaleString()} severe mi · {bestRoute.no_travel_miles.toLocaleString()} no-travel mi</span></div>}
              </div>
              <div className="source-bar" data-testid="text-data-sources"><span>DATA SOURCES</span>{result.data_sources.length ? result.data_sources.map((source, i) => <span className="source-chip" key={`${source}-${i}`}>{source}</span>) : <span className="source-none">No source details returned</span>}<button className="refresh-button" onClick={() => { setResult(null); setSelectedId(''); setOffset(0); }} data-testid="button-new-comparison"><RefreshCw size={13} /> NEW COMPARISON</button></div>
            </>}
          </section>
        </div>
        <footer className="safety-banner" data-testid="notice-safety-warning"><AlertTriangle size={17} /><p><strong>Operational decision support only.</strong> Routing data is not truck-restriction-aware and does not account for all vehicle, road, or operating constraints. Forecasts can change. Verify current conditions and restrictions before dispatch; this is not a safety guarantee.</p></footer>
        <footer className="page-footer"><span>WAYPOINT/WX · WEATHER-AWARE TRUCK ROUTING</span><span>CONDITIONS INFORM THE CALL. THE DRIVER MAKES IT.</span></footer>
      </main>
    </div>
  );
}

function Root() {
  return <QueryClientProvider client={queryClient}><App /></QueryClientProvider>;
}

export default Root;
