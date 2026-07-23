using System.Text.Json;
using System.Text.Json.Nodes;
using MomentumHunter.Application;
using MomentumHunter.Contracts;
using MomentumHunter.EngineBridge;

namespace MomentumHunter.Presentation.Tests;

public sealed class PythonCandidateStoryWorkspaceClientTests
{
    [Fact]
    public void MapperPreservesCanonicalStatusProvenanceAndLaterAnnotation()
    {
        using var document = JsonDocument.Parse(PartialStoryJson());

        var snapshot = CandidateStorySnapshotMapper.Map(document.RootElement);

        Assert.Equal("CRWV", snapshot.Symbol);
        Assert.Equal(CandidateStoryEvidenceState.Partial, snapshot.State);
        Assert.Equal("Fading", snapshot.Status);
        Assert.Equal(1, snapshot.TrustedCaptureCount);
        var point = Assert.Single(snapshot.Points);
        Assert.Equal("raw capture", point.CaptureFactSource);
        Assert.Equal("later review/outcome annotation", point.LaterAnnotationSource);
        Assert.Equal("Post-capture outcome: complete", point.LaterAnnotation);
        Assert.True(point.Trusted);
        Assert.True(snapshot.ReadOnly);
    }

    [Fact]
    public void MapperRejectsWritableBoundaryUnknownStatusAndInconsistentCounts()
    {
        var writable = PartialStoryJson().Replace("\"readOnly\": true", "\"readOnly\": false");
        var unknown = PartialStoryJson().Replace("\"status\": \"Fading\"", "\"status\": \"Buy\"");
        var countMismatch = PartialStoryJson().Replace("\"displayedPointCount\": 1", "\"displayedPointCount\": 2");

        Assert.Throws<InvalidDataException>(() => Map(writable));
        Assert.Throws<InvalidDataException>(() => Map(unknown));
        Assert.Throws<InvalidDataException>(() => Map(countMismatch));
    }

    [Fact]
    public void MapperRejectsUntrustedDuplicateOrNonContiguousPoints()
    {
        var untrusted = PartialStoryJson().Replace("\"trusted\": true", "\"trusted\": false");
        var wrongSequence = PartialStoryJson().Replace("\"sequence\": 1", "\"sequence\": 2");
        var duplicateRoot = JsonNode.Parse(PartialStoryJson())!.AsObject();
        duplicateRoot["trustedCaptureCount"] = 2;
        duplicateRoot["totalPointCount"] = 2;
        duplicateRoot["displayedPointCount"] = 2;
        var points = duplicateRoot["points"]!.AsArray();
        var duplicate = points[0]!.DeepClone().AsObject();
        duplicate["sequence"] = 2;
        duplicate["capturedAt"] = "2026-06-18T07:00:00-05:00";
        duplicate["capturedAtLabel"] = "2026-06-18 07:00 AM CT";
        points.Add(duplicate);

        Assert.Throws<InvalidDataException>(() => Map(untrusted));
        Assert.Throws<InvalidDataException>(() => Map(wrongSequence));
        Assert.Throws<InvalidDataException>(() => Map(duplicateRoot.ToJsonString()));
    }

    [Fact]
    public void MapperAcceptsHonestEmptyStateWithoutPoints()
    {
        using var document = JsonDocument.Parse(EmptyStoryJson("CRWV"));

        var snapshot = CandidateStorySnapshotMapper.Map(document.RootElement);

        Assert.Equal(CandidateStoryEvidenceState.Empty, snapshot.State);
        Assert.Empty(snapshot.Points);
        Assert.Equal("Insufficient data", snapshot.Status);
    }

    [Fact]
    public async Task ClientNormalizesRequestAndRejectsResponseForDifferentSymbol()
    {
        var connection = new RecordingCandidateStoryConnection();
        var client = new PythonCandidateStoryWorkspaceClient(connection);
        var mismatch = new PythonCandidateStoryWorkspaceClient(
            new RecordingCandidateStoryConnection(responseSymbol: "EQX"));

        var snapshot = await client.GetSnapshotAsync(" crwv ");

        Assert.Equal("CRWV", connection.Symbol);
        Assert.Equal("CRWV", snapshot.Symbol);
        await Assert.ThrowsAsync<InvalidDataException>(() => mismatch.GetSnapshotAsync("CRWV"));
    }

    [Fact]
    public async Task ClientRejectsPathLikeSymbolBeforeCallingHost()
    {
        var connection = new RecordingCandidateStoryConnection();
        var client = new PythonCandidateStoryWorkspaceClient(connection);

        await Assert.ThrowsAsync<ArgumentException>(() => client.GetSnapshotAsync("../CRWV"));

        Assert.Null(connection.Symbol);
    }

    private static CandidateStorySnapshot Map(string json)
    {
        using var document = JsonDocument.Parse(json);
        return CandidateStorySnapshotMapper.Map(document.RootElement);
    }

    private static string PartialStoryJson() =>
        """
        {
          "schemaVersion": 1,
          "symbol": "CRWV",
          "state": "PARTIAL",
          "observedAt": "2026-07-23T12:00:00-05:00",
          "sourceAsOf": "2026-06-17T07:00:00-05:00",
          "sourceLabel": "Persisted trusted raw captures with labeled later annotations",
          "summary": "PARTIAL | Read-only Candidate Story evidence.",
          "company": "CoreWeave",
          "sector": "Technology",
          "industry": "Infrastructure Software",
          "status": "Fading",
          "statusDetail": "Score cooled and price fell below first seen.",
          "firstSeenLabel": "Jun 17, 2026 7:00 AM CT",
          "latestSeenLabel": "Jun 17, 2026 7:00 AM CT",
          "peakScoreLabel": "Jun 17, 2026 7:00 AM CT",
          "firstPrice": 100.0,
          "latestPrice": 100.0,
          "moveSinceFirstPct": 0.0,
          "firstScore": 80.0,
          "latestScore": 80.0,
          "peakScore": 80.0,
          "trustedCaptureCount": 1,
          "totalPointCount": 1,
          "displayedPointCount": 1,
          "points": [
            {
              "sequence": 1,
              "identityKey": "story-1",
              "captureId": "2026-06-17|morning|finviz|Base Momentum",
              "capturedAt": "2026-06-17T07:00:00-05:00",
              "capturedAtLabel": "2026-06-17 07:00 AM CT",
              "captureLabel": "Jun 17",
              "session": "morning",
              "sessionMarker": "AM",
              "provider": "finviz",
              "scanner": "Base Momentum",
              "mode": "PAPER",
              "calendarLabel": "Market session",
              "trustLabel": "Trusted active capture",
              "price": 100.0,
              "score": 80.0,
              "volume": 35000000,
              "relativeVolume": 2.2,
              "priceChangePreviousPct": null,
              "priceChangeFirstPct": 0.0,
              "scoreChangePrevious": null,
              "captureNote": "First seen, Latest capture",
              "laterAnnotation": "Post-capture outcome: complete",
              "captureFactSource": "raw capture",
              "laterAnnotationSource": "later review/outcome annotation",
              "warnings": ["Missing later review"],
              "trusted": true
            }
          ],
          "warnings": ["Only one capture is available."],
          "readOnly": true
        }
        """;

    private static string EmptyStoryJson(string symbol) =>
        $$"""
        {
          "schemaVersion": 1,
          "symbol": "{{symbol}}",
          "state": "EMPTY",
          "observedAt": "2026-07-23T12:00:00-05:00",
          "sourceAsOf": null,
          "sourceLabel": "Persisted trusted capture evidence",
          "summary": "EMPTY | No trusted captures.",
          "company": "",
          "sector": "",
          "industry": "",
          "status": "Insufficient data",
          "statusDetail": "No trusted captures found for this ticker.",
          "firstSeenLabel": "No trusted captures found",
          "latestSeenLabel": "No trusted captures found",
          "peakScoreLabel": "n/a",
          "firstPrice": null,
          "latestPrice": null,
          "moveSinceFirstPct": null,
          "firstScore": null,
          "latestScore": null,
          "peakScore": null,
          "trustedCaptureCount": 0,
          "totalPointCount": 0,
          "displayedPointCount": 0,
          "points": [],
          "warnings": ["No trusted captures found for this ticker."],
          "readOnly": true
        }
        """;

    private sealed class RecordingCandidateStoryConnection : IPythonEngineHostConnection
    {
        private readonly string? _responseSymbol;

        public RecordingCandidateStoryConnection(string? responseSymbol = null)
        {
            _responseSymbol = responseSymbol;
        }

        public string? Symbol { get; private set; }

        public Task<JsonElement> GetCandidateStorySnapshotAsync(
            string symbol,
            CancellationToken cancellationToken = default)
        {
            Symbol = symbol;
            using var document = JsonDocument.Parse(EmptyStoryJson(_responseSymbol ?? symbol));
            return Task.FromResult(document.RootElement.Clone());
        }

        public Task<PythonEngineHostSnapshot> EnsureConnectedAsync(CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<PythonEngineHostSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<PythonEngineHostCommandResult> SendCommandAsync(
            string command,
            string commandId,
            CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();
    }
}
