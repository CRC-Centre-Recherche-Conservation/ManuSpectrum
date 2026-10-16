import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { init } from "./banner";
import { STORAGE_KEY } from "./core";

const START = Date.parse("2026-11-12T07:00:00Z");
const LABELS = {
    region: "Site announcement",
    dismiss: "Dismiss this announcement",
    until: "until {time}",
    upcoming: "Upcoming",
    live: "In progress",
    kind: {
        info: "Information",
        maintenance: "Maintenance",
        important: "Important",
    },
};

function notice(over = {}) {
    return {
        id: 3,
        version: 100,
        kind: "maintenance",
        start: "2026-11-12T07:00:00Z",
        end: "2026-11-12T09:00:00Z",
        reminders: [604800, 86400, 3600, 600],
        text: {
            en: "The site will be unavailable.",
            fr: "Le site sera indisponible.",
        },
        link: {
            url: "https://example.org/details",
            label: { en: "Details", fr: "Détails" },
        },
        ...over,
    };
}

function payload(notices, extra = {}) {
    return {
        timeZone: "Europe/Paris",
        notices,
        labels: {
            en: LABELS,
            fr: { ...LABELS, region: "Annonce du site", dismiss: "Fermer" },
        },
        ...extra,
    };
}

function fakeFetch(
    body,
    dateHeader = new Date(START - 3600 * 1000).toUTCString(),
) {
    return vi.fn(async () => ({
        ok: true,
        headers: { get: (name) => (name === "Date" ? dateHeader : null) },
        json: async () => body,
    }));
}

let script;
let instance;

async function start(body, options = {}) {
    instance = init(script, {
        fetch: options.fetch || fakeFetch(body, options.date),
    });
    await instance.ready;
    return document.querySelector(".ms-notice");
}

beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    vi.setSystemTime(START - 3600 * 1000);
    document.documentElement.lang = "en";
    document.body.innerHTML =
        '<p id="page">page</p><script id="ms-site-notice" data-url="/api/site-notice"></script>';
    script = document.getElementById("ms-site-notice");
    window.localStorage.clear();
    window.history.replaceState({}, "", "/");
});

afterEach(() => {
    if (instance) instance.destroy();
    instance = null;
    vi.useRealTimers();
    document.documentElement.style.removeProperty("--ms-notice-h");
});

describe("site notice banner", () => {
    it("renders the notice as the first child of body with labels from the payload", async () => {
        const banner = await start(payload([notice()]));
        expect(document.body.firstElementChild).toBe(banner);
        expect(banner.getAttribute("role")).toBe("region");
        expect(banner.getAttribute("aria-label")).toBe("Site announcement");
        expect(banner.classList.contains("ms-notice--maintenance")).toBe(true);
        expect(banner.querySelector(".ms-notice__kind").textContent).toBe(
            "Maintenance · Upcoming",
        );
        expect(banner.querySelector(".ms-notice__text").textContent).toBe(
            "The site will be unavailable.",
        );
        expect(banner.querySelector(".ms-notice__when").textContent).toContain(
            "08:00",
        );
        expect(
            banner.querySelector(".ms-notice__link").getAttribute("href"),
        ).toBe("https://example.org/details");
        expect(
            banner
                .querySelector(".ms-notice__dismiss")
                .getAttribute("aria-label"),
        ).toBe("Dismiss this announcement");
    });

    it("renders each kind and uses the page language", async () => {
        document.documentElement.lang = "fr";
        const banner = await start(payload([notice({ kind: "important" })]));
        expect(banner.classList.contains("ms-notice--important")).toBe(true);
        expect(banner.getAttribute("aria-label")).toBe("Annonce du site");
        expect(banner.querySelector(".ms-notice__text").textContent).toBe(
            "Le site sera indisponible.",
        );
        expect(banner.querySelector(".ms-notice__link").textContent).toBe(
            "Détails",
        );
    });

    it("inserts payload text as text, and drops a non-http link", async () => {
        const hostile = notice({
            kind: "info",
            text: { en: '<img src=x onerror="alert(1)">', fr: "" },
            link: { url: "javascript:alert(1)", label: { en: "x", fr: "x" } },
        });
        const banner = await start(payload([hostile]));
        expect(banner.querySelector("img")).toBeNull();
        expect(banner.querySelector(".ms-notice__text").textContent).toBe(
            '<img src=x onerror="alert(1)">',
        );
        expect(banner.querySelector(".ms-notice__link")).toBeNull();
    });

    it("shows nothing before the first reminder, on a failed fetch and with no notice", async () => {
        const early = Date.UTC(2026, 10, 1);
        expect(
            await start(payload([notice()]), {
                date: new Date(early).toUTCString(),
            }),
        ).toBeNull();
        instance.destroy();
        const failing = vi.fn(async () => ({
            ok: false,
            headers: { get: () => null },
            json: async () => ({}),
        }));
        expect(await start(null, { fetch: failing })).toBeNull();
        instance.destroy();
        const broken = vi.fn(async () => {
            throw new Error("network");
        });
        expect(await start(null, { fetch: broken })).toBeNull();
        instance.destroy();
        expect(await start(payload([]))).toBeNull();
    });

    it("dismisses on click, stores the key, and stays away on the next load", async () => {
        const banner = await start(payload([notice()]));
        banner.querySelector(".ms-notice__dismiss").click();
        expect(document.querySelector(".ms-notice")).toBeNull();
        expect(document.body.classList.contains("ms-has-notice")).toBe(false);
        expect(window.localStorage.getItem(STORAGE_KEY)).toBe(
            JSON.stringify({ 3: "3:100:3600" }),
        );
        instance.destroy();
        expect(await start(payload([notice()]))).toBeNull();
    });

    it("dismisses on Escape from inside the banner", async () => {
        const banner = await start(payload([notice()]));
        banner.querySelector(".ms-notice__dismiss").focus();
        banner.dispatchEvent(
            new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
        );
        expect(document.querySelector(".ms-notice")).toBeNull();
        expect(window.localStorage.getItem(STORAGE_KEY)).toBe(
            JSON.stringify({ 3: "3:100:3600" }),
        );
    });

    it("shows a dismissed notice again at the next reminder", async () => {
        window.localStorage.setItem(
            STORAGE_KEY,
            JSON.stringify({ 3: "3:100:3600" }),
        );
        expect(await start(payload([notice()]))).toBeNull();
        vi.setSystemTime(START - 600 * 1000);
        vi.advanceTimersByTime(30 * 1000);
        expect(document.querySelector(".ms-notice")).not.toBeNull();
    });

    it("re-evaluates on a storage event", async () => {
        await start(payload([notice()]));
        window.localStorage.setItem(
            STORAGE_KEY,
            JSON.stringify({ 3: "3:100:3600" }),
        );
        window.dispatchEvent(new StorageEvent("storage", { key: STORAGE_KEY }));
        expect(document.querySelector(".ms-notice")).toBeNull();
    });

    it("labels a live notice with its kind and the live label", async () => {
        vi.setSystemTime(START + 60 * 1000);
        const banner = await start(payload([notice()]), {
            date: new Date(START + 60 * 1000).toUTCString(),
        });
        expect(banner.querySelector(".ms-notice__kind").textContent).toBe(
            "Maintenance · In progress",
        );
    });

    it("fetches with revalidation so the Date header is fresh", async () => {
        const fetchMock = fakeFetch(payload([notice()]));
        await start(null, { fetch: fetchMock });
        expect(fetchMock.mock.calls[0][1].cache).toBe("no-cache");
    });

    it("dismissing one notice does not bring back another dismissed one", async () => {
        const a = notice({ id: 1 });
        const b = notice({ id: 2 });
        const both = payload([a, b]);
        window.localStorage.setItem(
            STORAGE_KEY,
            JSON.stringify({ 1: "1:100:3600" }),
        );
        const banner = await start(both);
        banner.querySelector(".ms-notice__dismiss").click();
        expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY))).toEqual({
            1: "1:100:3600",
            2: "2:100:3600",
        });
        instance.destroy();
        expect(await start(both)).toBeNull();
    });

    it("is live with a close button, and disappears at the end", async () => {
        vi.setSystemTime(START + 60 * 1000);
        const banner = await start(payload([notice()]), {
            date: new Date(START + 60 * 1000).toUTCString(),
        });
        expect(banner.classList.contains("ms-notice--live")).toBe(true);
        expect(banner.querySelector(".ms-notice__dismiss")).not.toBeNull();
        expect(banner.querySelector(".ms-notice__when").textContent).toBe(
            "until 10:00",
        );
        vi.setSystemTime(START + 2 * 3600 * 1000);
        vi.advanceTimersByTime(30 * 1000);
        expect(document.querySelector(".ms-notice")).toBeNull();
    });

    it("keeps a closed live notice hidden until a new version", async () => {
        vi.setSystemTime(START + 60 * 1000);
        const date = new Date(START + 60 * 1000).toUTCString();
        const banner = await start(payload([notice()]), { date });
        banner.querySelector(".ms-notice__dismiss").click();
        expect(document.querySelector(".ms-notice")).toBeNull();
        expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY))).toEqual({
            3: "3:100:null",
        });
        instance.destroy();
        expect(await start(payload([notice()]), { date })).toBeNull();
        instance.destroy();
        expect(
            await start(payload([notice({ version: 101 })]), { date }),
        ).not.toBeNull();
    });

    it("closes a live notice on Escape", async () => {
        vi.setSystemTime(START + 60 * 1000);
        const banner = await start(payload([notice()]), {
            date: new Date(START + 60 * 1000).toUTCString(),
        });
        banner.dispatchEvent(
            new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
        );
        expect(document.querySelector(".ms-notice")).toBeNull();
    });

    it("renders a notice shown once with no date line or live styling, closed for good", async () => {
        const once = notice({
            display: "once",
            reminders: [],
            start: "2026-11-01T00:00:00Z",
        });
        const banner = await start(payload([once]));
        expect(banner.querySelector(".ms-notice__when")).toBeNull();
        expect(banner.classList.contains("ms-notice--live")).toBe(false);
        expect(banner.querySelector(".ms-notice__kind").textContent).toBe(
            "Maintenance",
        );
        expect(banner.querySelector(".ms-notice__text").textContent).toBe(
            "The site will be unavailable.",
        );
        banner.querySelector(".ms-notice__dismiss").click();
        instance.destroy();
        expect(await start(payload([once]))).toBeNull();
        vi.advanceTimersByTime(30 * 1000);
        expect(document.querySelector(".ms-notice")).toBeNull();
        instance.destroy();
        expect(
            await start(payload([{ ...once, version: 101 }])),
        ).not.toBeNull();
    });

    it("promotes an upcoming notice to live when the start passes", async () => {
        await start(payload([notice()]));
        expect(document.querySelector(".ms-notice--live")).toBeNull();
        vi.setSystemTime(START + 1000);
        vi.advanceTimersByTime(30 * 1000);
        expect(document.querySelector(".ms-notice--live")).not.toBeNull();
    });

    it("corrects the client clock with the Date header", async () => {
        vi.setSystemTime(START - 30 * 86400 * 1000);
        const banner = await start(payload([notice()]), {
            date: new Date(START - 3600 * 1000).toUTCString(),
        });
        expect(banner).not.toBeNull();
    });

    it("previews with ?preview=<id>, even outside the dates, and never writes storage", async () => {
        window.history.replaceState({}, "", "/?ms-notice-preview=3");
        vi.setSystemTime(START - 40 * 86400 * 1000);
        const fetchMock = fakeFetch(
            payload([notice()], { preview: true }),
            new Date(START - 40 * 86400 * 1000).toUTCString(),
        );
        const banner = await start(null, { fetch: fetchMock });
        expect(fetchMock.mock.calls[0][0]).toBe("/api/site-notice?preview=3");
        expect(banner).not.toBeNull();
        banner.querySelector(".ms-notice__dismiss").click();
        expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
        vi.advanceTimersByTime(30 * 1000);
        expect(document.querySelector(".ms-notice")).toBeNull();
    });
});

describe("site notice height", () => {
    it("publishes the measured height and clears it on removal", async () => {
        const rect = vi
            .spyOn(Element.prototype, "getBoundingClientRect")
            .mockReturnValue({ height: 44 });
        try {
            const banner = await start(payload([notice()]));
            expect(
                document.documentElement.style.getPropertyValue(
                    "--ms-notice-h",
                ),
            ).toBe("44px");
            expect(document.body.classList.contains("ms-has-notice")).toBe(
                true,
            );
            banner.querySelector(".ms-notice__dismiss").click();
            expect(
                document.documentElement.style.getPropertyValue(
                    "--ms-notice-h",
                ),
            ).toBe("");
            expect(document.body.classList.contains("ms-has-notice")).toBe(
                false,
            );
        } finally {
            rect.mockRestore();
        }
    });
});
