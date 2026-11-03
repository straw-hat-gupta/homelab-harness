import { formatBytes, formatDuration, formatValue, statusTone } from "@/lib/format";

describe("format", () => {
  it.each([
    [0, "0 B"],
    [1023, "1023 B"],
    [1536, "1.5 KiB"],
    [68719476736, "64.0 GiB"],
    [1000204886016, "932 GiB"],
  ])("formats %i bytes as %s", (bytes, text) => {
    expect(formatBytes(bytes)).toBe(text);
  });

  it.each([
    [0, "0s"],
    [45, "45s"],
    [3725, "1h 2m"],
    [1209600, "14d"],
    [1213200, "14d 1h"],
  ])("formats %i seconds as %s", (seconds, text) => {
    expect(formatDuration(seconds)).toBe(text);
  });

  it("formats by unit and shows unknown values as a dash", () => {
    expect(formatValue(null, "bytes")).toBe("—");
    expect(formatValue(8, "percent")).toBe("8.0 %");
    expect(formatValue(1234, "count")).toBe("1,234");
    expect(formatValue("n/a")).toBe("n/a");
  });

  it("reads statuses without alarming on unknown ones", () => {
    expect(statusTone("running")).toBe("ok");
    expect(statusTone("Offline")).toBe("bad");
    expect(statusTone("stopped")).toBe("neutral");
    expect(statusTone(null)).toBe("neutral");
  });
});
