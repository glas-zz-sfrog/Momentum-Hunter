using System.Text.Json;
using MomentumHunter.EngineBridge;

namespace MomentumHunter.Integration.Tests;

public sealed class PythonEngineHostWireContractTests
{
    [Fact]
    public void ResponseContractAcceptsTheCurrentVersionedEnvelope()
    {
        using var document = JsonDocument.Parse(CurrentResponse());

        PythonEngineHostWireContract.ValidateResponse(document.RootElement);
    }

    [Theory]
    [InlineData("\"cycleCount\"", "\"cyclesCompleted\"")]
    [InlineData("\"capabilities\"", "\"capabilityNames\"")]
    [InlineData("\"summary\"", "\"message\"")]
    public void ResponseContractRejectsRenamedVariables(string current, string renamed)
    {
        using var document = JsonDocument.Parse(CurrentResponse().Replace(current, renamed));

        Assert.Throws<JsonException>(
            () => PythonEngineHostWireContract.ValidateResponse(document.RootElement));
    }

    [Fact]
    public void EndpointContractRejectsRenamedVariables()
    {
        const string endpoint = """
        {
          "schemaVersion": 1,
          "protocolVersion": "1.0",
          "hostInstanceId": "host-1",
          "processIdentifier": 123,
          "startedAtUtc": "2026-08-12T12:00:00Z",
          "address": "127.0.0.1",
          "port": 4567,
          "accessToken": "redacted-test-value",
          "runtimeBuildHash": "build-hash",
          "selectorArmSchemaVersion": 3
        }
        """;
        using var document = JsonDocument.Parse(endpoint);

        Assert.Throws<JsonException>(
            () => PythonEngineHostWireContract.ValidateEndpoint(document.RootElement));
    }

    private static string CurrentResponse() => """
    {
      "protocolVersion": "1.0",
      "requestId": "request-1",
      "accepted": true,
      "error": null,
      "result": {
        "code": "SNAPSHOT",
        "summary": "Current host snapshot.",
        "snapshot": {
          "schemaVersion": 1,
          "identity": {
            "protocolVersion": "1.0",
            "hostInstanceId": "host-1",
            "processId": 123,
            "startedAtUtc": "2026-08-12T12:00:00Z",
            "transport": "loopback-tcp",
            "runtimeBuildHash": "build-hash",
            "selectorArmSchemaVersion": 3
          },
          "health": {
            "state": "Healthy",
            "observedAtUtc": "2026-08-12T12:00:01Z",
            "detail": "Ready."
          },
          "collection": {
            "state": "Idle",
            "isPaused": false,
            "cycleInProgress": false,
            "cycleCount": 12,
            "monitoredSymbolCount": 3,
            "lastCompletedCycleAtUtc": "2026-08-12T11:59:59Z",
            "nextScheduledCycleAtUtc": "2026-08-12T12:00:05Z",
            "detail": "Waiting."
          },
          "activePositionMarking": {
            "state": "IDLE",
            "cadenceSeconds": 5.0,
            "cycleCount": 0,
            "providerRequestCount": 0,
            "lastCompletedAtUtc": null,
            "detail": "No active position.",
            "transport": "read-only Schwab quote transport",
            "orderTransmission": "UNAVAILABLE"
          },
          "capabilities": ["snapshot"]
        },
        "payload": null
      }
    }
    """;
}
