# Heat Watch

72-hour heat stress and rain outlook for a single CMC site (default: Marlborough, QLD).

**Live page:** https://soheilheydari25.github.io/heat-watch/

- Hourly forecast map with a time-lapse of the next 72 hours (trigger level, air temp, feels like, rain)
- Rainfall in mm per hour and daily totals
- Queensland construction heat triggers: Caution (feels like 32°C+), Stop-work (air 35°C+, or 29°C+ with 75%+ humidity), Extreme (air 40°C+)
- Trigger log with date, duration, start and finish
- Search any Australian address, or pick the site on the map

Forecast guidance only. Work decisions follow CMC's heat management plan, the project's EBA and on-site checks such as the WHSQ heat stress calculator.

## Forecast data

1. **MET Norway** Locationforecast API (main source). Free for any use under CC BY 4.0, no key needed.
2. **Open-Meteo** (automatic backup if MET Norway doesn't answer).
3. **Saved copy**: the last good forecast is kept in each browser and shown (clearly marked) for up to 24 hours if both services are down. Within 30 minutes of a fetch, reloading the page reuses the saved copy instead of calling the services again.

Weather data from MET Norway (CC BY 4.0) and Open-Meteo.com (CC BY 4.0). Address search © OpenStreetMap contributors. Map tiles © Esri.
