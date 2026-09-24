import { describe, expect, it, vi } from "vitest";
import { effectScope, nextTick, ref } from "vue";
import { flushPromises } from "@vue/test-utils";

import {
    ServiceError,
    UnavailableError,
} from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { useRequest } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

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
