# Weather-Aware Truck Routing

A React and Django route-planning MVP that compares available road routes using
estimated checkpoint arrival times, hourly weather forecasts, payload-specific
risk rules, and estimated travel time.

## Run locally

Requirements: Node.js 20+, pnpm 10+, Python 3.13+, and uv.

```sh
pnpm install
uv sync
pnpm run dev
```

`pnpm run dev` starts both the Django API (`http://127.0.0.1:8000`) and the Vite React frontend (`http://localhost:5173`) concurrently. Vite automatically proxies `/api` requests to the Django backend.

Alternatively, you can run them in separate terminals:
- Backend: `pnpm run dev:api`
- Frontend: `pnpm run dev:web`

## API

- `GET /api/v1/health` — API health
- `POST /api/v1/route-plans` — geocode the trip, request up to three OSRM route
  alternatives, sample checkpoints every 10, 25, or 50 miles, retrieve hourly
  Open-Meteo forecasts, apply the assessment's risk/load thresholds, and rank
  the returned routes.

The API accepts `origin`, `destination`, an ISO 8601 `departure_at` with time
zone, `load_weight_lb`, and `sample_interval_miles`. A route request is limited
to eight per client IP per minute.

## Data providers and limits

- OpenStreetMap Nominatim: geocoding, cached in-process and requested no more
  than once per second.
- OSRM public routing service: up to three available driving alternatives.
- Open-Meteo: hourly wind, rain, snow, and temperature forecasts, cached for
  ten minutes.

The public services are suitable for an MVP and have their own usage policies
and availability limits. Set `GEOCODING_BASE_URL`, `ROUTING_BASE_URL`, and
`WEATHER_BASE_URL` to compatible hosted services for higher-volume production.
No API keys are needed for the default providers.

## Risk calculation

The API evaluates wind, rain, and snow at each checkpoint. It applies the
provided load overrides, weighs risk miles by the distance since the preceding
checkpoint, and ranks routes by no-travel miles, severe miles, high miles,
average risk, then estimated travel time. This puts no-travel exposure ahead of
all other ranking criteria.

The forecast slider displays each checkpoint's forecast from departure through
48 hours. Trip risk uses weather nearest the checkpoint's estimated arrival
time. Estimated travel time is the greater of the routing service duration and
a 55 mph trip average; stops and traffic changes are not modelled.

## Important limitation

The public routing service returns general driving routes, not truck-legal
routes. This app does not account for height, axle, bridge, hazardous-material,
or local truck restrictions. Weather scores are decision support only, not a
safety guarantee. Verify the route, current restrictions, and conditions with
appropriate fleet and official sources before dispatch.

## Tests

```sh
pnpm test
pnpm run typecheck
```
