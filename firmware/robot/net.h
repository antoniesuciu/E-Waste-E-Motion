// Wi-Fi, UDP command handling and telemetry. Wire format: firmware/README.md.
#pragma once

void netBegin();
void netReceive();       // handle at most one pending command packet
void netSendTelemetry(); // rate-limited to TELEMETRY_INTERVAL_MS
