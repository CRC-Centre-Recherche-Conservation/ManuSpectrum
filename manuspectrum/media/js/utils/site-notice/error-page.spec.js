/* global __dirname */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const TEMPLATE = readFileSync(
    resolve(__dirname, "../../../../templates/errors/500.htm"),
    "utf-8",
);
const SCRIPT = TEMPLATE.match(/<script>([\s\S]*?)<\/script>/)[1];
const BODY = TEMPLATE.match(/<body>([\s\S]*?)<script>/)[1];

const START = Date.parse("2026-11-12T07:00:00Z");

function notice(over = {}) {
    return {
        id: 1,
        kind: "maintenance",
        start: "2026-11-12T07:00:00Z",
        end: "2026-11-12T09:00:00Z",
        text: { en: "Down for maintenance.", fr: "En maintenance." },
        ...over,
    };
}

function respond(body, { ok = true, date = START + 60 * 1000 } = {}) {
    return vi.fn(async () => ({
        ok,
        headers: { get: () => new Date(date).toUTCString() },
        json: async () => {
            if (body === "not json") throw new SyntaxError("bad");
            return body;
        },
    }));
}

async function run(fetchMock) {
    window.fetch = fetchMock;
    window.eval(SCRIPT);
    for (let i = 0; i < 5; i += 1) await Promise.resolve();
    await new Promise((done) => setTimeout(done, 0));
}

const hidden = (id) => document.getElementById(id).hidden;

beforeEach(() => {
    document.body.innerHTML = BODY;
});

afterEach(() => {
    delete window.fetch;
});

describe("errors/500.htm announcement", () => {
    it("shows an announcement in progress above the error, which stays", async () => {
        await run(respond({ timeZone: "Europe/Paris", notices: [notice()] }));
        const box = document.getElementById("ms-notice");
        expect(box.hidden).toBe(false);
        expect(box.querySelector("h2").textContent).toBe("Maintenance");
        expect(box.textContent).toContain("Down for maintenance.");
        expect(box.textContent).toContain("En maintenance.");
        expect(box.textContent).toContain("until 10:00 / jusqu’à 10:00");
        expect(hidden("ms-code")).toBe(false);
        expect(hidden("ms-error")).toBe(false);
        expect(document.getElementById("ms-code").textContent).not.toContain(
            "Maintenance",
        );
        expect(document.getElementById("ms-error").textContent).toContain(
            "Instrument malfunction",
        );
        const order = [
            ...document.querySelectorAll("#ms-code, #ms-notice, #ms-error"),
        ];
        expect(order.map((node) => node.id)).toEqual([
            "ms-code",
            "ms-notice",
            "ms-error",
        ]);
    });

    it("leaves out the end line for a notice shown once", async () => {
        await run(
            respond({
                notices: [notice({ display: "once", kind: "info" })],
            }),
        );
        const box = document.getElementById("ms-notice");
        expect(box.hidden).toBe(false);
        expect(box.textContent).toContain("Down for maintenance.");
        expect(box.textContent).not.toContain("until");
    });

    it("titles the other kinds", async () => {
        for (const [kind, title] of [
            ["important", "Important"],
            ["info", "Information"],
        ]) {
            document.body.innerHTML = BODY;
            await run(respond({ notices: [notice({ kind })] }));
            expect(document.querySelector("#ms-notice h2").textContent).toBe(
                title,
            );
        }
    });

    it("adds the weekday and date when the end is on another day", async () => {
        await run(
            respond({
                timeZone: "Europe/Paris",
                notices: [notice({ end: "2026-11-14T09:00:00Z" })],
            }),
        );
        const text = document.getElementById("ms-notice").textContent;
        expect(text).toContain("Saturday");
        expect(text).toContain("samedi");
        expect(text).toContain("10:00");
    });

    it("writes payload text as text, never as markup", async () => {
        await run(
            respond({
                notices: [
                    notice({
                        text: { en: "<img src=x onerror=alert(1)>", fr: "" },
                    }),
                ],
            }),
        );
        expect(document.querySelector("#ms-notice img")).toBeNull();
    });

    it("leaves the page unchanged outside the window", async () => {
        await run(respond({ notices: [notice()] }, { date: START - 3600000 }));
        expect(hidden("ms-notice")).toBe(true);
        expect(hidden("ms-code")).toBe(false);
        expect(hidden("ms-error")).toBe(false);
    });

    it("leaves the page unchanged on a non-ok or non-JSON answer", async () => {
        await run(respond({ notices: [notice()] }, { ok: false }));
        expect(hidden("ms-notice")).toBe(true);
        expect(hidden("ms-code")).toBe(false);
        await run(respond("not json"));
        expect(hidden("ms-notice")).toBe(true);
        expect(hidden("ms-error")).toBe(false);
    });
});
