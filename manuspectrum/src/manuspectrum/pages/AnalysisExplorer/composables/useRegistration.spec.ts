import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { effectScope } from "vue";

import {
    reloadRegistrations,
    useRegistration,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useRegistration.ts";
import { REGISTRATION_STORAGE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/folio/registration-store.ts";

const box = { x: 1, y: 2, w: 30, h: 40 };
const capture = {
    url: "https://img.example/iiif/p/0,0,10,10/10,10/0/default.jpg",
    width: 10,
    height: 10,
    canvas: "c1",
    at: 7,
};

beforeEach(() => {
    window.localStorage.clear();
    reloadRegistrations();
});
afterEach(() => {
    vi.restoreAllMocks();
});

describe("useRegistration", () => {
    it("writes a place through to the storage and shares it", () => {
        const a = useRegistration();
        const b = useRegistration();
        a.setPlace("an1", "c1", box, 2);
        expect(b.get("an1")).toMatchObject({
            canvas: "c1",
            box,
            quarter: 2,
            capture: null,
        });
        const stored = JSON.parse(
            window.localStorage.getItem(REGISTRATION_STORAGE_KEY) ?? "{}",
        );
        expect(stored.entries.an1.quarter).toBe(2);
        expect(a.get("nope")).toBeNull();
    });

    it("keeps the same 100 entries in memory as in the storage", () => {
        const r = useRegistration();
        let nowTick = 0;
        vi.spyOn(Date, "now").mockImplementation(() => nowTick);
        for (let index = 0; index < 101; index += 1) {
            nowTick = index + 1;
            r.setPlace(`an${index}`, "c1", box, 0);
        }
        expect(Object.keys(r.entries.value)).toHaveLength(100);
        expect(r.get("an0")).toBeNull();
        expect(r.get("an100")).not.toBeNull();
    });

    it("reset keeps a capture and drops an entry without one", () => {
        const r = useRegistration();
        r.setPlace("an1", "c1", box, 1);
        r.reset("an1");
        expect(r.get("an1")).toBeNull();

        r.setPlace("an2", "c1", box, 1);
        r.setCapture("an2", capture);
        r.reset("an2");
        expect(r.get("an2")?.capture).toEqual(capture);
        expect(r.get("an2")?.quarter).toBe(0);
        r.clearCapture("an2");
        expect(r.get("an2")).toBeNull();
    });

    it("clearing a capture keeps a laid place", () => {
        const r = useRegistration();
        r.setPlace("an3", "c1", box, 1);
        r.setCapture("an3", capture);
        r.clearCapture("an3");
        expect(r.get("an3")).toMatchObject({ box, quarter: 1, capture: null });
    });

    it("re-reads when another tab writes", () => {
        const r = useRegistration();
        const scope = effectScope();
        scope.run(() => useRegistration());
        window.localStorage.setItem(
            REGISTRATION_STORAGE_KEY,
            JSON.stringify({
                version: 1,
                entries: {
                    z: {
                        canvas: "c9",
                        box,
                        quarter: 3,
                        capture: null,
                        touched: 1,
                    },
                },
            }),
        );
        window.dispatchEvent(
            new StorageEvent("storage", { key: REGISTRATION_STORAGE_KEY }),
        );
        expect(r.get("z")?.quarter).toBe(3);
        scope.stop();
    });

    it("removes the listener once the last scope is disposed", () => {
        const add = vi.spyOn(window, "addEventListener");
        const remove = vi.spyOn(window, "removeEventListener");
        const one = effectScope();
        const two = effectScope();
        one.run(() => useRegistration());
        two.run(() => useRegistration());
        expect(
            add.mock.calls.filter(([type]) => type === "storage"),
        ).toHaveLength(1);
        one.stop();
        expect(remove).not.toHaveBeenCalledWith("storage", expect.anything());
        two.stop();
        expect(
            remove.mock.calls.filter(([type]) => type === "storage"),
        ).toHaveLength(1);
    });
});
