import { beforeEach, describe, expect, it, vi } from "vitest";

import {
    EXPLORER_CHUNK_MARKER,
    startAnalysisExplorer,
} from "@/manuspectrum/pages/AnalysisExplorer/bootstrap.ts";

const mountPublicApp = vi.hoisted(() => vi.fn(async () => ({})));

vi.mock("@/manuspectrum/public/mountPublicApp.ts", () => ({ mountPublicApp }));

beforeEach(() => mountPublicApp.mockClear());

describe("startAnalysisExplorer", () => {
    it("mounts on the page's mount point with the server's connection flag", async () => {
        document.body.innerHTML =
            '<div id="ms-explorer-app" data-connected="true"></div>';
        await startAnalysisExplorer();
        const mountPoint = document.getElementById(
            "ms-explorer-app",
        ) as HTMLElement;
        expect(mountPublicApp).toHaveBeenCalledWith(
            expect.objectContaining({
                mountPoint,
                initialProps: { connected: true },
            }),
        );
        expect(mountPoint.dataset.bundle).toBe(EXPLORER_CHUNK_MARKER);
    });

    it("reads a missing flag as a visitor", async () => {
        document.body.innerHTML = '<div id="ms-explorer-app"></div>';
        await startAnalysisExplorer();
        expect(mountPublicApp).toHaveBeenCalledWith(
            expect.objectContaining({ initialProps: { connected: false } }),
        );
    });

    it("does nothing without a mount point", async () => {
        document.body.innerHTML = "";
        await startAnalysisExplorer();
        expect(mountPublicApp).not.toHaveBeenCalled();
    });
});
