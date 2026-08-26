namespace Greenfield.AtasHistoryExporter;

using System.ComponentModel;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

using ATAS.Indicators;

[DisplayName("Greenfield ATAS History Export Probe")]
public sealed class GreenfieldAtasHistoryExporter : Indicator
{
    private readonly object _sync = new();
    private CumulativeTradesRequest? _request;
    private bool _started;

    public string FromUtc { get; set; } = DateTime.UtcNow.Date.AddDays(-1)
        .ToString("O", CultureInfo.InvariantCulture);

    public string ToUtc { get; set; } = DateTime.UtcNow.Date
        .ToString("O", CultureInfo.InvariantCulture);

    public string ConnectorName { get; set; } = "Bybit";

    public string SourceTimeZoneId { get; set; } = "UTC";

    public string ExportDirectory { get; set; } = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
        "Greenfield",
        "atas-exports");

    protected override void OnCalculate(int bar, decimal value)
    {
        // This probe only exports provider history; it does not create signals.
    }

    protected override void OnFinishRecalculate()
    {
        lock (_sync)
        {
            if (_started)
                return;

            var from = ParseUtc(FromUtc, nameof(FromUtc));
            var to = ParseUtc(ToUtc, nameof(ToUtc));

            if (to <= from || to - from > TimeSpan.FromDays(7))
                throw new InvalidOperationException("ATAS export range must be >0 and <=7 days.");

            if (string.IsNullOrWhiteSpace(ConnectorName))
                throw new InvalidOperationException("ConnectorName is required.");

            _request = new CumulativeTradesRequest(from, to, 0, 0);
            _started = true;
            RequestForCumulativeTrades(_request);
        }
    }

    protected override void OnCumulativeTradesResponse(
        CumulativeTradesRequest request,
        IEnumerable<CumulativeTrade> cumulativeTrades)
    {
        lock (_sync)
        {
            if (_request is null || request.RequestId != _request.RequestId)
                return;

            WriteExport(request, cumulativeTrades);
            _request = null;
        }
    }

    private void WriteExport(
        CumulativeTradesRequest request,
        IEnumerable<CumulativeTrade> cumulativeTrades)
    {
        Directory.CreateDirectory(ExportDirectory);
        var instrument = SafeFileComponent(InstrumentInfo.Instrument);
        var connector = SafeFileComponent(ConnectorName);
        var stamp = $"{request.BeginTime:yyyyMMddTHHmmssZ}_{request.EndTime:yyyyMMddTHHmmssZ}";
        var finalPath = Path.Combine(
            ExportDirectory,
            $"greenfield-atas-{connector}-{instrument}-{stamp}.jsonl");
        var temporaryPath = $"{finalPath}.{Guid.NewGuid():N}.tmp";
        var count = 0;

        try
        {
            using (var stream = new FileStream(
                temporaryPath, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            using (var writer = new StreamWriter(stream, new UTF8Encoding(false)))
            {
                WriteRecord(writer, new
                {
                    record_type = "header",
                    schema_version = 1,
                    source = "atas",
                    connector = ConnectorName,
                    instrument = InstrumentInfo.Instrument,
                    source_time_zone_id = SourceTimeZoneId,
                    requested_from_utc = IsoUtc(request.BeginTime),
                    requested_to_utc = IsoUtc(request.EndTime),
                    exported_at_utc = IsoUtc(DateTime.UtcNow),
                });

                foreach (var trade in cumulativeTrades.OrderBy(item => item.Time))
                {
                    WriteRecord(writer, new
                    {
                        record_type = "cumulative_trade",
                        timestamp_utc = IsoProviderTimeUtc(trade.Time),
                        first_price = trade.FirstPrice.ToString(CultureInfo.InvariantCulture),
                        last_price = trade.Lastprice.ToString(CultureInfo.InvariantCulture),
                        volume = trade.Volume.ToString(CultureInfo.InvariantCulture),
                        direction = trade.Direction.ToString().ToUpperInvariant(),
                        tick_count = trade.Ticks?.Count ?? 0,
                    });
                    count++;
                }

                WriteRecord(writer, new
                {
                    record_type = "footer",
                    complete = true,
                    cumulative_trade_count = count,
                    market_depth_snapshot_count = 0,
                });
                writer.Flush();
                stream.Flush(true);
            }

            File.Move(temporaryPath, finalPath, false);
            var digest = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(finalPath)))
                .ToLowerInvariant();
            using var sidecar = new FileStream(
                $"{finalPath}.sha256", FileMode.CreateNew, FileAccess.Write, FileShare.None);
            using var sidecarWriter = new StreamWriter(sidecar, new UTF8Encoding(false));
            sidecarWriter.Write($"{digest}  {Path.GetFileName(finalPath)}\n");
            sidecarWriter.Flush();
            sidecar.Flush(true);
        }
        finally
        {
            if (File.Exists(temporaryPath))
                File.Delete(temporaryPath);
        }
    }

    private static void WriteRecord(StreamWriter writer, object record) =>
        writer.WriteLine(JsonSerializer.Serialize(record));

    private static DateTime ParseUtc(string value, string name)
    {
        if (!DateTimeOffset.TryParse(
                value,
                CultureInfo.InvariantCulture,
                DateTimeStyles.AllowWhiteSpaces,
                out var parsed) || parsed.Offset != TimeSpan.Zero)
            throw new InvalidOperationException($"{name} must be ISO-8601 with a UTC offset.");

        return parsed.UtcDateTime;
    }

    private static string IsoUtc(DateTime value) =>
        (value.Kind == DateTimeKind.Utc ? value : value.ToUniversalTime())
            .ToString("O", CultureInfo.InvariantCulture);

    private string IsoProviderTimeUtc(DateTime value)
    {
        if (value.Kind == DateTimeKind.Utc)
            return IsoUtc(value);

        if (value.Kind == DateTimeKind.Local)
            return IsoUtc(value.ToUniversalTime());

        var sourceZone = TimeZoneInfo.FindSystemTimeZoneById(SourceTimeZoneId);
        return IsoUtc(TimeZoneInfo.ConvertTimeToUtc(value, sourceZone));
    }

    private static string SafeFileComponent(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
            throw new InvalidOperationException("ATAS instrument identity is missing.");

        var invalid = Path.GetInvalidFileNameChars();
        return new string(value.Select(ch => invalid.Contains(ch) ? '_' : ch).ToArray());
    }
}
