# Greenfield ATAS historical export probe

This integration is an external-data probe, not an ATAS clone and not a
strategy. It uses the public custom-indicator API and keeps every accepted
export separate from exchange-native Bronze under `source=atas`.

## Current scope

- Windows ATAS custom indicator source for one unfiltered cumulative-trade
  request of at most seven days;
- JSONL envelope with explicit connector/instrument/time provenance, decimal
  strings, completion footer and SHA-256 sidecar;
- strict Greenfield importer with schema, ordering, count, checksum, UTC,
  positive-value and optional DOM integrity checks;
- content-addressed immutable landing path and manifest.

Historical market-depth export is deliberately not claimed yet. The ATAS API
advertises it, but availability depends on the selected connector/provider and
must be proven on an installed Bybit connector before the exporter writes DOM
records. A zero depth count means “not requested/proven”, never “complete L2”.

## Build and first probe

1. Install/launch ATAS on Windows and connect its Bybit market-data connector.
2. Install the .NET SDK matching ATAS (`net8.0` for this probe; add a net10
   target if the installed ATAS runtime requires it).
3. Build with the real ATAS installation directory:

   ```powershell
   dotnet build integrations/atas/Greenfield.AtasHistoryExporter/Greenfield.AtasHistoryExporter.csproj `
     -p:AtasInstallDir='C:\Program Files (x86)\ATAS Platform'
   ```

4. In ATAS, use **Add custom indicator** and select the built DLL. Attach it to
   a Bybit `BTCUSDT` chart. Set UTC `FromUtc`/`ToUtc` within one day for the
   first probe, keep `ConnectorName=Bybit`, and explicitly confirm the
   connector timestamps are UTC before leaving `SourceTimeZoneId=UTC`.
5. Verify the `.sha256` sidecar, then ingest without editing the export:

   ```powershell
   uv run python scripts/ingest_atas_history_export.py `
     --export-path 'C:\path\greenfield-atas-Bybit-BTCUSDT-....jsonl' `
     --data-dir data `
     --expected-sha256 '<lowercase sha256>'
   ```

The current workstation has `%APPDATA%\ATAS` cache/config remnants but no
discoverable installed ATAS program/SDK and no .NET SDK, so this cycle can
validate the Greenfield landing contract but cannot honestly claim a compiled
or provider-tested indicator. Do not parse ATAS proprietary cache `.dat` files.

Before bulk export, verify ATAS and connector licensing/redistribution terms.
