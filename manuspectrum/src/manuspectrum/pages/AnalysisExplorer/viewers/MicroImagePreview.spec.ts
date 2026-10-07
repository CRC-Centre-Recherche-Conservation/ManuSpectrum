import { flushPromises, mount } from "@vue/test-utils";
import L from "leaflet";
import { afterEach, describe, expect, it, vi } from "vitest";
import { nextTick, ref } from "vue";

import MicroImagePreview from "@/manuspectrum/pages/AnalysisExplorer/viewers/MicroImagePreview.vue";

import { WINDOW_RESIZE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
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
    vi.restoreAllMocks();
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

    it("shows a file of the Selection without the analysis record, and follows the size of its Compare window", async () => {
        const file = fileEntry({
            dataKind: "micro-imaging",
            role: "other",
            downloadUrl: "/files/micro.jpg",
            previewUrl: null,
        });
        const invalidate = vi.spyOn(L.Map.prototype, "invalidateSize");
        const images = recordImages();
        const tick = ref(0);
        const wrapper = mount(MicroImagePreview, {
            attachTo: sizedContainer(),
            props: { file },
            global: { provide: { [WINDOW_RESIZE_KEY as symbol]: tick } },
        });
        Object.defineProperty(images[0], "naturalWidth", { value: 1200 });
        Object.defineProperty(images[0], "naturalHeight", { value: 800 });
        images[0].dispatchEvent(new Event("load"));
        await flushPromises();
        expect(wrapper.find("img.micro-image").attributes("src")).toBe(
            file.downloadUrl,
        );
        invalidate.mockClear();
        tick.value += 1;
        await nextTick();
        expect(invalidate).toHaveBeenCalledTimes(1);
        wrapper.unmount();
    });

    async function mountInWindow(tick: ReturnType<typeof ref<number>>) {
        const images = recordImages();
        const wrapper = mount(MicroImagePreview, {
            attachTo: sizedContainer(),
            props: {
                file: fileEntry({
                    dataKind: "micro-imaging",
                    role: "other",
                    downloadUrl: "/files/micro.jpg",
                    previewUrl: null,
                }),
            },
            global: { provide: { [WINDOW_RESIZE_KEY as symbol]: tick } },
        });
        Object.defineProperty(images[0], "naturalWidth", { value: 1200 });
        Object.defineProperty(images[0], "naturalHeight", { value: 800 });
        images[0].dispatchEvent(new Event("load"));
        await flushPromises();
        return wrapper;
    }

    it("fits the whole image to its well again when the window changes size, until the reader zooms", async () => {
        const fit = vi.spyOn(L.Map.prototype, "fitBounds");
        const tick = ref(0);
        const wrapper = await mountInWindow(tick);
        expect(fit).toHaveBeenCalledTimes(1);
        tick.value = 1;
        await nextTick();
        expect(fit).toHaveBeenCalledTimes(2);
        wrapper.find(".leaflet-control-zoom-in").trigger("click");
        await nextTick();
        tick.value = 2;
        await nextTick();
        expect(fit).toHaveBeenCalledTimes(2);
        wrapper.unmount();
    });
});
