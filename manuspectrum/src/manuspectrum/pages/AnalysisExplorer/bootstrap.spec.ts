import { beforeEach, describe, expect, it, vi } from "vitest";

import {
    EXPLORER_CHUNK_MARKER,
    prefetchFirstScreen,
    startAnalysisExplorer,
} from "@/manuspectrum/pages/AnalysisExplorer/bootstrap.ts";
import { uuid } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

const mountPublicApp = vi.hoisted(() => vi.fn(async () => ({})));
const prefetchJson = vi.hoisted(() => vi.fn());

vi.mock("@/manuspectrum/public/mountPublicApp.ts", () => ({ mountPublicApp }));
vi.mock("@/manuspectrum/pages/AnalysisExplorer/api/http.ts", () => ({
    prefetchJson,
}));

beforeEach(() => {
    mountPublicApp.mockClear();
    prefetchJson.mockClear();
});

function prefetched(): string[] {
    return prefetchJson.mock.calls.map(
        ([route, request]) =>
            `${route} ${JSON.stringify(request.urlParameters ?? {})} ${request.query?.toString() ?? ""}`,
    );
}

describe("prefetchFirstScreen", () => {
    it("asks for the home of the reader's day", () => {
        vi.useFakeTimers({ toFake: ["Date"] });
        vi.setSystemTime(new Date(2026, 8, 25, 10));
        prefetchFirstScreen("");
        expect(prefetched()).toEqual([
            "manuspectrum:explorer-home {} day=2026-09-25",
        ]);
        vi.useRealTimers();
    });

    it("asks for the first page of the results the address filters", () => {
        prefetchFirstScreen("?screen=results&technique=t1&grain=analyses");
        expect(prefetched()).toEqual([
            "manuspectrum:explorer-search {} grain=analyses&technique=t1",
        ]);
    });

    it("asks for the document, its match and the analysis the address opens", () => {
        prefetchFirstScreen(
            `?doc=${uuid(1)}&focus=analysis:${uuid(2)}&technique=t1&grain=analyses`,
        );
        expect(prefetched()).toEqual([
            `manuspectrum:explorer-document {"resourceid":"${uuid(1)}"} `,
            `manuspectrum:explorer-document-match {"resourceid":"${uuid(1)}"} technique=t1`,
            `manuspectrum:explorer-analysis {"resourceid":"${uuid(2)}"} `,
        ]);
    });

    it("asks for nothing on another view", () => {
        prefetchFirstScreen("?view=compare");
        expect(prefetchJson).not.toHaveBeenCalled();
    });
});

describe("startAnalysisExplorer", () => {
    it("starts the first screen's requests before mounting", async () => {
        document.body.innerHTML = '<div id="ms-explorer-app"></div>';
        await startAnalysisExplorer();
        expect(prefetchJson.mock.invocationCallOrder[0]).toBeLessThan(
            mountPublicApp.mock.invocationCallOrder[0],
        );
    });

    it("mounts on the page's mount point with the server's connection flag", async () => {
        document.body.innerHTML =
            '<div id="ms-explorer-app" data-connected="true" data-mirador-url="https://viewer.example/"></div>';
        await startAnalysisExplorer();
        const mountPoint = document.getElementById(
            "ms-explorer-app",
        ) as HTMLElement;
        expect(mountPublicApp).toHaveBeenCalledWith(
            expect.objectContaining({
                mountPoint,
                initialProps: {
                    connected: true,
                    miradorUrl: "https://viewer.example/",
                },
            }),
        );
        expect(mountPoint.dataset.bundle).toBe(EXPLORER_CHUNK_MARKER);
    });

    it("reads a missing flag as a visitor and a missing viewer as none", async () => {
        document.body.innerHTML = '<div id="ms-explorer-app"></div>';
        await startAnalysisExplorer();
        expect(mountPublicApp).toHaveBeenCalledWith(
            expect.objectContaining({
                initialProps: { connected: false, miradorUrl: "" },
            }),
        );
    });

    it("does nothing without a mount point", async () => {
        document.body.innerHTML = "";
        await startAnalysisExplorer();
        expect(mountPublicApp).not.toHaveBeenCalled();
    });
});
