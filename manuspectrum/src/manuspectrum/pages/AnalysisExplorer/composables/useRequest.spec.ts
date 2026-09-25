import { afterEach, describe, expect, it, vi } from "vitest";
import { effectScope, nextTick, ref } from "vue";

import type { Ref } from "vue";
import { flushPromises } from "@vue/test-utils";

import {
    ServiceError,
    UnavailableError,
} from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import {
    DEBOUNCE_MS,
    useRequest,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

function deferred<T>(): {
    promise: Promise<T>;
    resolve: (value: T) => void;
    reject: (error: unknown) => void;
} {
    let resolve!: (value: T) => void;
    let reject!: (error: unknown) => void;
    const promise = new Promise<T>((ok, fail) => {
        resolve = ok;
        reject = fail;
    });
    return { promise, resolve, reject };
}

afterEach(() => vi.useRealTimers());

describe("useRequest", () => {
    it("is idle while the source is null", () => {
        const scope = effectScope();
        const handle = scope.run(() => useRequest(() => null, vi.fn()))!;
        expect(handle.status.value).toBe("idle");
        scope.stop();
    });

    it("aborts the previous request and ignores its late answer", async () => {
        const argument = ref("a");
        const first = deferred<string>();
        const second = deferred<string>();
        const signals: AbortSignal[] = [];
        const load = vi.fn((value: string, signal: AbortSignal) => {
            signals.push(signal);
            return value === "a" ? first.promise : second.promise;
        });
        const scope = effectScope();
        const handle = scope.run(() => useRequest(() => argument.value, load))!;
        argument.value = "b";
        await nextTick();
        expect(signals[0].aborted).toBe(true);
        second.resolve("B");
        await flushPromises();
        first.resolve("A");
        await flushPromises();
        expect(handle.data.value).toBe("B");
        expect(handle.status.value).toBe("ready");
        scope.stop();
        expect(signals[1].aborted).toBe(false);
    });

    it("reports unavailable on 404 and error on 429", async () => {
        const scope = effectScope();
        const unavailable = scope.run(() =>
            useRequest(
                () => "x",
                async () => {
                    throw new UnavailableError();
                },
            ),
        )!;
        const failing = scope.run(() =>
            useRequest(
                () => "x",
                async () => {
                    throw new ServiceError(429);
                },
            ),
        )!;
        await flushPromises();
        expect(unavailable.status.value).toBe("unavailable");
        expect(failing.status.value).toBe("error");
        scope.stop();
    });

    it("reloads on retry", async () => {
        const load = vi
            .fn()
            .mockRejectedValueOnce(new ServiceError(503))
            .mockResolvedValueOnce("ok");
        const scope = effectScope();
        const handle = scope.run(() => useRequest(() => "x", load))!;
        await flushPromises();
        expect(handle.status.value).toBe("error");
        handle.retry();
        await flushPromises();
        expect(handle.status.value).toBe("ready");
        expect(handle.data.value).toBe("ok");
        scope.stop();
    });

    it("reloads on retry past the tab memo", async () => {
        const load = vi.fn().mockResolvedValue("ok");
        const scope = effectScope();
        const handle = scope.run(() => useRequest(() => "x", load))!;
        await flushPromises();
        handle.retry();
        await flushPromises();
        expect(load.mock.calls.map((call) => call[2])).toEqual([false, true]);
        scope.stop();
    });

    it("records the source its data answers", async () => {
        const argument = ref("a");
        const scope = effectScope();
        const handle = scope.run(() =>
            useRequest(
                () => argument.value,
                async (value) => value.toUpperCase(),
            ),
        )!;
        await flushPromises();
        expect([handle.data.value, handle.loaded.value]).toEqual(["A", "a"]);
        scope.stop();
    });

    it("takes a cached payload at once, with no request", async () => {
        const load = vi.fn();
        const scope = effectScope();
        const handle = scope.run(() =>
            useRequest(() => "x", load, { cached: () => "held" }),
        )!;
        expect(handle.data.value).toBe("held");
        expect(handle.status.value).toBe("ready");
        expect(load).not.toHaveBeenCalled();
        scope.stop();
    });

    describe("debounced", () => {
        function debounced(argument: Ref<string>) {
            const load = vi.fn(async (value: string) => value.toUpperCase());
            const scope = effectScope();
            const handle = scope.run(() =>
                useRequest(() => argument.value, load, {
                    debounce: (next) => !next.startsWith("page"),
                }),
            )!;
            return { load, scope, handle };
        }

        it("starts the first load at once", () => {
            vi.useFakeTimers();
            const { load, scope } = debounced(ref("a"));
            expect(load).toHaveBeenCalledTimes(1);
            scope.stop();
        });

        it("shows loading at once and asks only for the last of quick changes", async () => {
            vi.useFakeTimers();
            const argument = ref("a");
            const { load, scope, handle } = debounced(argument);
            await flushPromises();
            argument.value = "b";
            await nextTick();
            expect(handle.status.value).toBe("loading");
            expect(handle.data.value).toBe("A");
            vi.advanceTimersByTime(DEBOUNCE_MS - 1);
            argument.value = "c";
            await nextTick();
            vi.advanceTimersByTime(DEBOUNCE_MS - 1);
            expect(load).toHaveBeenCalledTimes(1);
            vi.advanceTimersByTime(1);
            await flushPromises();
            expect(load.mock.calls.map((call) => call[0])).toEqual(["a", "c"]);
            expect(handle.data.value).toBe("C");
            expect(handle.status.value).toBe("ready");
            scope.stop();
        });

        it("asks at once for a change the predicate does not debounce, and on retry", async () => {
            vi.useFakeTimers();
            const argument = ref("a");
            const { load, scope, handle } = debounced(argument);
            argument.value = "page2";
            await nextTick();
            expect(load).toHaveBeenCalledTimes(2);
            argument.value = "d";
            await nextTick();
            handle.retry();
            expect(load.mock.calls.map((call) => call[0])).toEqual([
                "a",
                "page2",
                "d",
            ]);
            scope.stop();
        });

        it("drops a waiting change when the scope stops", async () => {
            vi.useFakeTimers();
            const argument = ref("a");
            const { load, scope } = debounced(argument);
            argument.value = "b";
            await nextTick();
            scope.stop();
            vi.advanceTimersByTime(DEBOUNCE_MS);
            expect(load).toHaveBeenCalledTimes(1);
        });
    });

    it("aborts the pending request when the scope stops", () => {
        let signal: AbortSignal | undefined;
        const scope = effectScope();
        scope.run(() =>
            useRequest(
                () => "x",
                (_value, abort) => {
                    signal = abort;
                    return new Promise(() => undefined);
                },
            ),
        );
        scope.stop();
        expect(signal?.aborted).toBe(true);
    });
});
