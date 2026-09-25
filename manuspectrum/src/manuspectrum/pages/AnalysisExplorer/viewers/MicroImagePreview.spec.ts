import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import MicroImagePreview from "@/manuspectrum/pages/AnalysisExplorer/viewers/MicroImagePreview.vue";

import {
    analysisPayload,
    fileEntry,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { sizedContainer } from "@/manuspectrum/pages/AnalysisExplorer/testing/leaflet.ts";

function recordImages(): HTMLImageElement[] {
    const images: HTMLImageElement[] = [];
    vi.stubGlobal(
        "Image",
        class extends window.Image {
            constructor() {
                super();
                images.push(this);
            }
        },
    );
    return images;
}

afterEach(() => {
    vi.unstubAllGlobals();
});

describe("MicroImagePreview", () => {
    it("shows the image once its size is known, with a download link", async () => {
        const file = fileEntry({
            dataKind: "micro-imaging",
            role: "other",
            name: "micro.jpg",
            downloadUrl: "/files/micro.jpg",
            previewUrl: null,
        });
        const images = recordImages();
        const wrapper = mount(MicroImagePreview, {
            attachTo: sizedContainer(),
            props: { file, analysis: analysisPayload() },
        });
        Object.defineProperty(images[0], "naturalWidth", { value: 1200 });
        Object.defineProperty(images[0], "naturalHeight", { value: 800 });
        images[0].dispatchEvent(new Event("load"));
        await flushPromises();
        expect(wrapper.find("img.micro-image").attributes("src")).toBe(
            file.downloadUrl,
        );
        expect(wrapper.find("a.download").attributes("href")).toBe(
            file.downloadUrl,
        );
        wrapper.unmount();
    });

    it("says when the image cannot be shown", async () => {
        const images = recordImages();
        const wrapper = mount(MicroImagePreview, {
            attachTo: sizedContainer(),
            props: {
                file: fileEntry({ dataKind: "micro-imaging" }),
                analysis: analysisPayload(),
            },
        });
        images[0].dispatchEvent(new Event("error"));
        await flushPromises();
        expect(wrapper.text()).toContain("This image cannot be shown here.");
        wrapper.unmount();
    });

    it("offers no download link for an address that is not http or https", () => {
        recordImages();
        const wrapper = mount(MicroImagePreview, {
            attachTo: sizedContainer(),
            props: {
                file: fileEntry({
                    dataKind: "micro-imaging",
                    downloadUrl: "javascript:alert(1)",
                }),
                analysis: analysisPayload(),
            },
        });
        expect(wrapper.find("a.download").exists()).toBe(false);
        wrapper.unmount();
    });
});
