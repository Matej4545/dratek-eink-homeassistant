// Minimal weather - a Script Template for the DRATEK eInk panel.
//
// The current temperature is the headline; one `weatherChart` row carries the
// next 24 hours: the temperature curve, a few "22h 15°" labels inside the plot
// and a rain band under the curve whenever any precipitation is forecast. On a
// landscape panel the reading takes the left column and the chart the right
// one; on a portrait panel the chart stacks full-width under the reading.
//
// Data sources (paste into the editor's "Data sources" field):
//
// [
//   { "id": "current", "type": "entity", "entity_id": "weather.forecast_home", "entity_attribute": "temperature" },
//   { "id": "condition", "type": "entity", "entity_id": "weather.forecast_home" },
//   { "id": "hourly", "type": "entity", "entity_id": "sensor.eink_hourly_weather", "entity_attribute": "forecast" }
// ]
//
// `sensor.eink_hourly_weather` is a trigger-based template sensor that keeps
// the hourly forecast in its `forecast` attribute (configuration.yaml):
//
// template:
//   - triggers:
//       - trigger: time_pattern
//         hours: "/1"
//       - trigger: homeassistant
//         event: start
//     actions:
//       - action: weather.get_forecasts
//         target:
//           entity_id: weather.forecast_home
//         data:
//           type: hourly
//         response_variable: hourly
//     sensor:
//       - name: eInk Hourly Weather
//         unique_id: eink_hourly_weather
//         state: "{{ hourly['weather.forecast_home'].forecast | count }}"
//         attributes:
//           forecast: "{{ hourly['weather.forecast_home'].forecast }}"
//
// An automatic refresh updates the current reading; the chart is redrawn on
// the next manual send (a list-valued source is never rebound as text).

const CONDITIONS = {
  "clear-night": "Jasno",
  cloudy: "Zataženo",
  fog: "Mlha",
  hail: "Kroupy",
  lightning: "Bouřky",
  "lightning-rainy": "Bouřky",
  partlycloudy: "Polojasno",
  pouring: "Liják",
  rainy: "Déšť",
  snowy: "Sníh",
  "snowy-rainy": "Déšť se sněhem",
  sunny: "Slunečno",
  windy: "Větrno",
  "windy-variant": "Větrno",
  exceptional: "Výstraha",
};

const hourly = (Array.isArray(data.hourly) ? data.hourly : [])
  .filter((entry) => entry && Number.isFinite(Number(entry.temperature)))
  .slice(0, 24);
const temperatures = hourly.map((entry) => Number(entry.temperature));
const rain = hourly.map((entry) => Math.max(0, Number(entry.precipitation) || 0));
const current = Number(data.current);
const reading = Number.isFinite(current)
  ? String(Math.round(current * 10) / 10).replace(".", ",")
  : (temperatures.length ? String(Math.round(temperatures[0])) : "–");

const rows = [
  { text: CONDITIONS[String(data.condition || "")] || "Počasí", size: 0.1, h: 0.14, bold: true },
  { stat: { value: reading, unit: "°C" }, h: 0.3 },
];

if (temperatures.length >= 2) {
  const low = Math.round(Math.min(...temperatures));
  const high = Math.round(Math.max(...temperatures));
  // Landscape panels give the chart roughly half their width, so it fits
  // fewer labels than a portrait panel's full-width row.
  const landscape = width / height >= 1.35;
  const chartWidth = landscape ? width * 0.55 : width;
  const every = chartWidth < 220 ? 6 : 4;
  const labels = hourly.map((entry, index) => {
    if (index % every !== Math.floor(every / 2)) return "";
    const hour = new Date(entry.datetime).getHours();
    return Number.isFinite(hour) ? `${hour}h ${Math.round(temperatures[index])}°` : "";
  });
  rows.push({
    weatherChart: {
      values: temperatures,
      labels,
      // Only when something actually falls - no empty band on a dry day.
      ...(rain.some((amount) => amount > 0) ? { rain } : {}),
      color: "red",
      caption: `${temperatures.length} H · ${low}°–${high}°`,
    },
    h: 0.5,
    compact: height <= 128,
  });
} else {
  rows.push({ text: "Hodinová předpověď není k dispozici", size: 0.07, h: 0.2 });
}

return rows;
