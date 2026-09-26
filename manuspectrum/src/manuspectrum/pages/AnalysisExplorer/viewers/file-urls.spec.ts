import { flushPromises, mount } from "@vue/test-utils";
import L from "leaflet";
import { createPinia, setActivePinia } from "pinia";
import PrimeVue from "primevue/config";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ref, shallowRef } from "vue";

import AnalysisCard from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/AnalysisCard.vue";

import { folioOverlays } from "@/manuspectrum/pages/AnalysisExplorer/folio/overlays.ts";
import {
    CURTAIN_KEY,
    FOLIO_ZONES_KEY,
    MIRADOR_URL_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import {
    analysisPayload,
    annotation,
    fileEntry,
    imagingEntry,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { sizedContainer } from "@/manuspectrum/pages/AnalysisExplorer/testing/leaflet.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";
import { viewerFor } from "@/manuspectrum/pages/AnalysisExplorer/viewers/registry.ts";

import type { MockInstance } from "vitest";

import type { RequestStatus } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";
import type {
    DataKind,
    FileEntry,
    ImageRef,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

vi.mock("@/manuspectrum/pages/AnalysisExplorer/xy/plotly.ts", () => ({
    loadPlotly: async () => ({
        react: async () => undefined,
        relayout: async () => undefined,
        purge: () => undefined,
    }),
}));

const UNSAFE = [
    "javascript:alert(1)",
    "data:image/svg+xml,<svg onload=alert(1)>",
    "//evil.example/x.png",
    "/\\evil.example/x.png",
];
const UNSAFE_MARK = /javascript:|data:|evil\.example/i;
const KINDS: DataKind[] = ["xy", "chemical-imaging", "micro-imaging", "file"];

/** Every `href` and `src` in the document, with the `src` of images built in script. */
function boundUrls(images: HTMLImageElement[]): string[] {
    const attributes = [...document.querySelectorAll("[href], [src]")].flatMap(
        (element) =>
            ["href", "src"]
                .map((name) => element.getAttribute(name))
                .filter((value): value is string => value !== null),
    );
    return [
        ...attributes,
        ...images.map((image) => image.getAttribute("src") ?? ""),
    ];
}

function hostileFile(kind: DataKind, url: string, image: ImageRef): FileEntry {
    const base = kind === "chemical-imaging" ? imagingEntry() : fileEntry();
    return {
        ...base,
        dataKind: kind,
        downloadUrl: url,
        previewUrl: url,
        layers: base.layers.map((layer) => ({ ...layer, image })),
    };
}

let images: HTMLImageElement[];
let overlay: MockInstance<typeof L.imageOverlay>;

beforeEach(() => {
    images = [];
    vi.stubGlobal(
        "Image",
        class extends window.Image {
            constructor() {
                super();
                images.push(this);
            }
        },
    );
    vi.stubGlobal(
        "fetch",
        vi.fn(async () => jsonResponse({}, 404)),
    );
    overlay = vi.spyOn(L, "imageOverlay");
});

afterEach(() => {
    overlay.mockRestore();
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
});

describe("file URLs", () => {
    for (const kind of KINDS) {
        for (const url of UNSAFE) {
            for (const image of [
                { service: null, url, width: 10, height: 10 },
                { service: url, url: null, width: 10, height: 10 },
            ]) {
                it(`binds no ${url} of a ${kind} file (image ${image.url ? "url" : "service"})`, async () => {
                    const pinia = createPinia();
                    setActivePinia(pinia);
                    const file = hostileFile(kind, url, image);
                    const preview = await viewerFor(kind).preview();
                    const wrapper = mount(preview, {
                        attachTo: sizedContainer(),
                        props: {
                            file,
                            analysis: analysisPayload({ files: [file] }),
                        },
                        global: {
                            plugins: [pinia, PrimeVue],
                            provide: {
                                [CURTAIN_KEY as symbol]: ref(null),
                                [FOLIO_ZONES_KEY as symbol]: ref(
                                    new Set([uuid(101)]),
                                ),
                            },
                        },
                    });
                    await flushPromises();
                    for (const probe of images)
                        probe.dispatchEvent(new Event("load"));
                    await flushPromises();

                    for (const bound of boundUrls(images)) {
                        expect(bound).not.toMatch(UNSAFE_MARK);
                    }
                    for (const [bound] of overlay.mock.calls) {
                        expect(String(bound)).not.toMatch(UNSAFE_MARK);
                    }
                    wrapper.unmount();
                });
            }
        }
    }

    it.each(UNSAFE)("links no file of an analysis card at %s", async (url) => {
        const pinia = createPinia();
        setActivePinia(pinia);
        const readable = fileEntry({
            id: uuid(8),
            pairedWith: uuid(9),
            downloadUrl: url,
        });
        const raw = fileEntry({
            id: uuid(9),
            name: "X01_f1v.mca",
            role: "raw",
            dataKind: "file",
            pairedWith: uuid(8),
            downloadUrl: url,
        });
        const other = fileEntry({
            id: uuid(10),
            name: "report.pdf",
            role: "other",
            dataKind: "file",
            downloadUrl: url,
        });
        const payload = analysisPayload({ files: [readable, raw, other] });
        const wrapper = mount(AnalysisCard, {
            attachTo: document.body,
            props: {
                handle: {
                    status: ref<RequestStatus>("ready"),
                    data: shallowRef(payload),
                    loaded: ref(payload.id),
                    retry: () => undefined,
                },
                analysisId: payload.id,
                zone: null,
            },
            global: {
                plugins: [pinia, PrimeVue],
                stubs: { SpectrumPreview: true },
                provide: { [MIRADOR_URL_KEY as symbol]: "" },
            },
        });
        await flushPromises();

        expect(wrapper.text()).toContain("report.pdf");
        for (const bound of boundUrls(images)) {
            expect(bound).not.toMatch(UNSAFE_MARK);
        }
        wrapper.unmount();
    });

    it.each(UNSAFE)("lays no imaging layer on the folio from %s", (url) => {
        const zone = annotation(1, {
            dataKind: "chemical-imaging",
            shape: { type: "rect", x: 0, y: 0, w: 64, h: 32 },
        });
        const laidWith = (image: ImageRef) => {
            const file = imagingEntry({
                layers: imagingEntry().layers.map((layer) => ({
                    ...layer,
                    image,
                })),
            });
            return folioOverlays(
                analysisPayload({ files: [file] }),
                {
                    [`${uuid(101)}:0`]: {
                        element: "Pb",
                        opacity: 0.7,
                        on: true,
                    },
                },
                [zone],
            );
        };
        const safe = {
            service: null,
            url: "https://x/pb.png",
            width: 1,
            height: 1,
        };
        expect(laidWith(safe)).toHaveLength(1);
        expect(laidWith({ ...safe, url })).toEqual([]);
        expect(laidWith({ ...safe, url: null, service: url })).toEqual([]);
    });
});
