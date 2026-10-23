import { describe, expect, it } from "vitest";

import { formatEventDate } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/event-format.ts";

const gettext = (msgid: string) => msgid;
const interpolate = (text: string, values: Record<string, string | number>) =>
    text.replace(/%\{(\w+)\}/g, (_, key: string) => String(values[key]));

const say = (start: number | null, end: number | null, approximate = false) =>
    formatEventDate({ start, end, approximate }, gettext, interpolate);

describe("formatEventDate", () => {
    it("writes the four formats", () => {
        expect(say(1301, 1400)).toBe("1301–1400");
        expect(say(1300, 1300, true)).toBe("c. 1300");
        expect(say(1290, 1310, true)).toBe("c. 1290–1310");
        expect(say(null, null)).toBe("undated");
    });

    it("lets a single bound stand for both", () => {
        expect(say(1300, null)).toBe("1300");
    });
});
