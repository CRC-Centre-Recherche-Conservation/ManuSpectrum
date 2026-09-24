import { afterEach, describe, expect, it } from "vitest";

import {
    createMemoryStorage,
    guardLocalStorage,
    readStorage,
    writeStorage,
} from "@/manuspectrum/public/safe-storage.ts";

const ORIGINAL = Object.getOwnPropertyDescriptor(window, "localStorage");

function blockLocalStorage(): void {
    Object.defineProperty(window, "localStorage", {
        configurable: true,
        get() {
            throw new DOMException("blocked", "SecurityError");
        },
    });
}

afterEach(() => {
    if (ORIGINAL) {
        Object.defineProperty(window, "localStorage", ORIGINAL);
    } else {
        Reflect.deleteProperty(window, "localStorage");
    }
    window.localStorage.clear();
});

describe("safe storage", () => {
    it("reads and writes through localStorage when it works", () => {
        expect(writeStorage("k", "v")).toBe(true);
        expect(readStorage("k")).toBe("v");
    });

    it("answers null and false when access throws", () => {
        blockLocalStorage();
        expect(readStorage("k")).toBeNull();
        expect(writeStorage("k", "v")).toBe(false);
    });

    it("installs a memory storage when reading localStorage throws", () => {
        blockLocalStorage();
        guardLocalStorage();
        expect(window.localStorage.getItem("x")).toBeNull();
        window.localStorage.setItem("x", "1");
        expect(window.localStorage.getItem("x")).toBe("1");
    });

    it("leaves a working localStorage in place", () => {
        const before = window.localStorage;
        guardLocalStorage();
        expect(window.localStorage).toBe(before);
    });

    it("implements the Storage interface in memory", () => {
        const storage = createMemoryStorage();
        storage.setItem("a", "1");
        storage.setItem("b", "2");
        expect(storage.length).toBe(2);
        expect(storage.key(0)).toBe("a");
        storage.removeItem("a");
        expect(storage.getItem("a")).toBeNull();
        storage.clear();
        expect(storage.length).toBe(0);
    });
});
