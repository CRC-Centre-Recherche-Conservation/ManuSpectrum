import { describe, it, expect, beforeEach } from "vitest";
import {
    pickLanguage,
    pickNotice,
    readDismissed,
    rememberDismissal,
    STORAGE_KEY,
    stageOf,
    dismissKey,
    shouldShow,
    serverSkew,
    formatWhen,
    safeHref,
    readStorage,
    writeStorage,
} from "./core";

const START = Date.parse("2026-11-12T07:00:00Z");
const END = Date.parse("2026-11-12T09:00:00Z");
const notice = (over = {}) => ({
    id: 3,
    version: 100,
    kind: "maintenance",
    start: "2026-11-12T07:00:00Z",
    end: "2026-11-12T09:00:00Z",
    reminders: [604800, 86400, 3600, 600],
    ...over,
});
const labels = { until: "until {time}" };

describe("pickLanguage", () => {
    it("maps fr variants to fr and everything else to en", () => {
        expect(pickLanguage("fr")).toBe("fr");
        expect(pickLanguage("fr-CA")).toBe("fr");
        expect(pickLanguage("en-GB")).toBe("en");
        expect(pickLanguage("")).toBe("en");
        expect(pickLanguage(undefined)).toBe("en");
    });
});

describe("pickNotice", () => {
    const later = (over = {}) =>
        notice({
            id: 2,
            start: "2026-12-01T07:00:00Z",
            end: "2026-12-01T09:00:00Z",
            ...over,
        });
    const past = notice({
        id: 1,
        start: "2026-01-01T07:00:00Z",
        end: "2026-01-01T09:00:00Z",
    });

    it("returns the nearest notice not over, or null", () => {
        expect(pickNotice([later(), notice(), past], START - 1000).id).toBe(3);
        expect(pickNotice([later(), past], END)).toBeNull();
        expect(
            pickNotice([later(), past], Date.parse("2026-11-30T00:00:00Z")).id,
        ).toBe(2);
        expect(pickNotice([past], END)).toBeNull();
        expect(pickNotice(undefined, END)).toBeNull();
    });
    it("does not let a hidden earlier notice mask a later one", () => {
        const hidden = notice({
            id: 5,
            reminders: [600],
            start: "2026-12-01T07:00:00Z",
            end: "2026-12-01T09:00:00Z",
        });
        const visible = later({ start: "2026-12-02T07:00:00Z" });
        const now = Date.parse("2026-12-01T05:00:00Z");
        expect(pickNotice([hidden, visible], now).id).toBe(2);
    });
    it("prefers a notice in progress over an upcoming maintenance", () => {
        const long = notice({
            id: 7,
            kind: "important",
            start: "2026-11-01T00:00:00Z",
            end: "2026-12-31T00:00:00Z",
        });
        const upcoming = notice({ id: 8 });
        expect(pickNotice([upcoming, long], START - 1000).id).toBe(7);
    });
    it("skips a dismissed earlier notice for a later one", () => {
        const a = notice({ id: 1 });
        const b = notice({ id: 2, start: "2026-11-12T07:30:00Z" });
        const now = START - 300 * 1000;
        expect(pickNotice([a, b], now, {}).id).toBe(1);
        expect(pickNotice([a, b], now, { 1: "1:100:600" }).id).toBe(2);
        expect(
            pickNotice([a, b], now, { 1: "1:100:600", 2: "2:100:3600" }),
        ).toBeNull();
    });
});

describe("dismissed map", () => {
    beforeEach(() => window.localStorage.clear());
    it("keeps one key per id and prunes ids absent from the payload", () => {
        rememberDismissal(1, "a", [1, 2]);
        rememberDismissal(2, "b", [1, 2]);
        expect(readDismissed()).toEqual({ 1: "a", 2: "b" });
        rememberDismissal(2, "c", [2]);
        expect(readDismissed()).toEqual({ 2: "c" });
    });
    it("reads garbage as empty", () => {
        window.localStorage.setItem(STORAGE_KEY, "not json");
        expect(readDismissed()).toEqual({});
        window.localStorage.setItem(STORAGE_KEY, "[1]");
        expect(readDismissed()).toEqual({});
    });
});

describe("stageOf", () => {
    it("is hidden before the first reminder", () => {
        expect(stageOf(notice(), START - 604800 * 1000 - 1).phase).toBe(
            "hidden",
        );
    });
    it("fires each reminder exactly at its boundary", () => {
        expect(stageOf(notice(), START - 604800 * 1000)).toEqual({
            phase: "upcoming",
            reminder: 604800,
        });
        expect(stageOf(notice(), START - 86400 * 1000 - 1).reminder).toBe(
            604800,
        );
        expect(stageOf(notice(), START - 86400 * 1000).reminder).toBe(86400);
        expect(stageOf(notice(), START - 3600 * 1000).reminder).toBe(3600);
        expect(stageOf(notice(), START - 600 * 1000).reminder).toBe(600);
        expect(stageOf(notice(), START - 1).reminder).toBe(600);
    });
    it("is live from the start and over from the end", () => {
        expect(stageOf(notice(), START).phase).toBe("live");
        expect(stageOf(notice(), END - 1).phase).toBe("live");
        expect(stageOf(notice(), END).phase).toBe("over");
    });
});

describe("notice shown once", () => {
    const once = (over = {}) =>
        notice({ display: "once", reminders: [], ...over });
    it("is hidden before the start, shown until the end, then over", () => {
        expect(stageOf(once(), START - 1).phase).toBe("hidden");
        expect(stageOf(once(), START)).toEqual({
            phase: "shown",
            reminder: null,
        });
        expect(stageOf(once(), END - 1).phase).toBe("shown");
        expect(stageOf(once(), END).phase).toBe("over");
    });
    it("stays dismissed until a new version", () => {
        const stage = stageOf(once(), START + 1000);
        const key = dismissKey(once(), stage);
        expect(shouldShow(stage, null, key)).toBe(true);
        expect(shouldShow(stage, key, key)).toBe(false);
        expect(
            shouldShow(stage, key, dismissKey(once({ version: 101 }), stage)),
        ).toBe(true);
    });
    it("is picked after a live event only when the event is closed", () => {
        const event = notice({ id: 1 });
        const shown = once({ id: 2, start: "2026-11-01T00:00:00Z" });
        const now = START + 1000;
        expect(pickNotice([shown, event], now).id).toBe(1);
        const closed = dismissKey(event, stageOf(event, now));
        expect(pickNotice([shown, event], now, { 1: closed }).id).toBe(2);
    });
});

describe("dismissal", () => {
    it("shows an upcoming notice until its key is stored, then again at the next reminder", () => {
        const first = stageOf(notice(), START - 86400 * 1000 - 5);
        const key = dismissKey(notice(), first);
        expect(key).toBe("3:100:604800");
        expect(shouldShow(first, null, key)).toBe(true);
        expect(shouldShow(first, key, key)).toBe(false);
        const next = stageOf(notice(), START - 86400 * 1000);
        expect(shouldShow(next, key, dismissKey(notice(), next))).toBe(true);
    });
    it("shows an edited notice again", () => {
        const stage = stageOf(notice(), START - 5);
        const stored = dismissKey(notice(), stage);
        expect(
            shouldShow(
                stage,
                stored,
                dismissKey(notice({ version: 101 }), stage),
            ),
        ).toBe(true);
    });
    it("shows a live notice until its key is stored, and never a hidden or over one", () => {
        const live = { phase: "live", reminder: null };
        const key = dismissKey(notice(), live);
        expect(shouldShow(live, null, key)).toBe(true);
        expect(shouldShow(live, key, key)).toBe(false);
        expect(
            shouldShow(live, key, dismissKey(notice({ version: 101 }), live)),
        ).toBe(true);
        expect(shouldShow({ phase: "hidden", reminder: null }, null, "k")).toBe(
            false,
        );
        expect(shouldShow({ phase: "over", reminder: null }, null, "k")).toBe(
            false,
        );
    });
});

describe("serverSkew", () => {
    it("is the server minus the client clock, 0 without a usable header", () => {
        expect(
            serverSkew(
                "Thu, 12 Nov 2026 07:00:00 GMT",
                Date.parse("2026-11-12T06:59:00Z"),
            ),
        ).toBe(60000);
        expect(serverSkew(null, 5)).toBe(0);
        expect(serverSkew("nonsense", 5)).toBe(0);
    });
});

describe("formatWhen", () => {
    it("formats the upcoming range in the page language and zone", () => {
        const en = formatWhen(
            notice(),
            { phase: "upcoming" },
            "en",
            "Europe/Paris",
            labels,
        );
        expect(en).toContain("Thursday");
        expect(en).toContain("08:00");
        expect(en).toContain("10:00");
        const fr = formatWhen(
            notice(),
            { phase: "upcoming" },
            "fr",
            "Europe/Paris",
            labels,
        );
        expect(fr).toContain("jeudi");
        expect(fr).toContain("novembre");
    });
    it("falls back to two formatted sides without formatRange", () => {
        const original = Intl.DateTimeFormat.prototype.formatRange;
        Intl.DateTimeFormat.prototype.formatRange = undefined;
        try {
            const out = formatWhen(
                notice(),
                { phase: "upcoming" },
                "en",
                "Europe/Paris",
                labels,
            );
            expect(out).toContain(" – ");
            expect(out).toContain("08:00");
            expect(out).toContain("10:00");
        } finally {
            Intl.DateTimeFormat.prototype.formatRange = original;
        }
    });
    it("says until the end time for a live notice, with the day when it ends another day", () => {
        expect(
            formatWhen(
                notice(),
                { phase: "live" },
                "en",
                "Europe/Paris",
                labels,
            ),
        ).toBe("until 10:00");
        const long = notice({ end: "2026-11-14T09:00:00Z" });
        const out = formatWhen(
            long,
            { phase: "live" },
            "en",
            "Europe/Paris",
            labels,
        );
        expect(out).toContain("Saturday");
        expect(out).toContain("10:00");
    });
});

describe("safeHref", () => {
    it("accepts http(s) only", () => {
        expect(safeHref("https://example.org/a")).toBe("https://example.org/a");
        expect(safeHref("javascript:alert(1)")).toBeNull();
        expect(safeHref("data:text/html,x")).toBeNull();
        expect(safeHref("/relative")).toBeNull();
    });
});

describe("storage helpers", () => {
    it("round-trips and survives a blocked storage", () => {
        expect(writeStorage("k", "v")).toBe(true);
        expect(readStorage("k")).toBe("v");
        const original = Object.getOwnPropertyDescriptor(
            window,
            "localStorage",
        );
        Object.defineProperty(window, "localStorage", {
            configurable: true,
            get() {
                throw new Error("blocked");
            },
        });
        try {
            expect(readStorage("k")).toBeNull();
            expect(writeStorage("k", "v")).toBe(false);
        } finally {
            Object.defineProperty(window, "localStorage", original);
        }
    });
});
