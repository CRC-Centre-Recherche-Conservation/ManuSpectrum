import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import PrimeVue from "primevue/config";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CitationBlock from "@/manuspectrum/pages/AnalysisExplorer/components/CitationBlock.vue";
import CopyButton from "@/manuspectrum/pages/AnalysisExplorer/components/CopyButton.vue";
import ShareExportPanel from "@/manuspectrum/pages/AnalysisExplorer/components/ShareExportPanel.vue";

import { forgetPayloads } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { MIRADOR_URL_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    analysisPayload,
    label,
    sharePayload,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";

vi.mock("@/arches/utils/generate-arches-url.ts", () => ({
    generateArchesURL: () => "/en/api/explorer/share",
}));

const DOCUMENT = uuid(1);
const KEY = `an:${uuid(101)}:-`;
const MIRADOR = "https://viewer.example/mirador/";

let answer: (url: string) => Response;
const fetchMock = vi.fn(async (url: string) => answer(url));

beforeEach(() => {
    forgetPayloads();
    fetchMock.mockClear();
    answer = () => jsonResponse(sharePayload());
    vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
});

interface Setup {
    document?: boolean;
    basket?: string[];
    mirador?: string;
}

function mountPanel({
    document: withDocument = true,
    basket = [],
    mirador = "",
}: Setup = {}) {
    const pinia = createPinia();
    setActivePinia(pinia);
    const store = useExplorerStore();
    if (withDocument) store.openDocument(DOCUMENT);
    for (const key of basket) store.addToBasket(key);
    const wrapper = mount(ShareExportPanel, {
        attachTo: document.body,
        global: {
            plugins: [pinia, PrimeVue],
            stubs: { transition: false },
            provide: { [MIRADOR_URL_KEY as symbol]: mirador },
        },
    });
    return { wrapper, store };
}

async function openPanel(setup: Setup = {}) {
    const mounted = mountPanel(setup);
    await mounted.wrapper.find("button.opener").trigger("click");
    await flushPromises();
    return mounted;
}

function drawer(): HTMLElement {
    const element = document.querySelector<HTMLElement>(
        ".explorer-share-drawer",
    );
    expect(element).not.toBeNull();
    return element as HTMLElement;
}

function askedUrls(): string[] {
    return fetchMock.mock.calls.map((call) => String(call[0]));
}

function links(): Record<string, string> {
    return Object.fromEntries(
        [...drawer().querySelectorAll("a")].map((link) => [
            link.textContent?.replace(/\s+/g, " ").trim() ?? "",
            link.getAttribute("href") ?? "",
        ]),
    );
}

describe("ShareExportPanel", () => {
    it("is hidden when the view offers no scope", () => {
        const { wrapper } = mountPanel({ document: false });
        expect(wrapper.find("button.opener").exists()).toBe(false);
        wrapper.unmount();
    });

    it("asks nothing before it opens", async () => {
        const { wrapper } = mountPanel();
        await flushPromises();
        expect(fetchMock).not.toHaveBeenCalled();
        wrapper.unmount();
    });

    it("offers a choice between the document and the Selection", async () => {
        const { wrapper } = await openPanel({ basket: [KEY] });

        const choices = [...drawer().querySelectorAll("label.choice")].map(
            (element) => element.textContent?.trim(),
        );
        expect(choices).toEqual(["This document", "My Selection (1)"]);
        expect(askedUrls()).toEqual([
            `/en/api/explorer/share?document=${DOCUMENT}`,
        ]);

        drawer()
            .querySelectorAll<HTMLInputElement>("input[type=radio]")[1]
            .click();
        await flushPromises();
        expect(askedUrls()[1]).toBe(
            `/en/api/explorer/share?${new URLSearchParams([["ids", KEY]])}`,
        );
        wrapper.unmount();
    });

    it("offers no choice with one scope", async () => {
        const { wrapper } = await openPanel();
        expect(drawer().querySelectorAll("input[type=radio]")).toHaveLength(0);
        wrapper.unmount();
    });

    it("lists one citation per dataset", async () => {
        const second = {
            ...analysisPayload().citation,
            text: "HEU, S. 2024. Parchment data [Dataset].",
        };
        answer = () =>
            jsonResponse(
                sharePayload({
                    citations: [analysisPayload().citation, second],
                }),
            );
        const { wrapper } = await openPanel();

        const blocks = wrapper.findAllComponents(CitationBlock);
        expect(blocks).toHaveLength(2);
        expect(blocks[1].props("citation")).toEqual(second);
        expect(drawer().textContent).toContain(sharePayload().availability);
        wrapper.unmount();
    });

    it("folds a long list of citations after the first three", async () => {
        const citations = [1, 2, 3, 4, 5].map((n) => ({
            ...analysisPayload().citation,
            text: `Citation ${n}`,
        }));
        answer = () => jsonResponse(sharePayload({ citations }));
        const { wrapper } = await openPanel();

        expect(wrapper.findAllComponents(CitationBlock)).toHaveLength(3);
        const more = drawer().querySelector<HTMLButtonElement>("button.more");
        expect(more?.textContent?.trim()).toBe("Show the 2 other citations");

        more?.click();
        await flushPromises();
        expect(wrapper.findAllComponents(CitationBlock)).toHaveLength(5);
        expect(drawer().querySelector("button.more")).toBeNull();
        wrapper.unmount();
    });

    it("puts the availability statement before the citations", async () => {
        const { wrapper } = await openPanel();
        const cite = drawer().querySelector(".group");
        const order = [...(cite?.children ?? [])].map(
            (element) => element.className,
        );
        expect(order.indexOf("availability")).toBeLessThan(
            order.findIndex((name) => name.includes("citation-block")),
        );
        wrapper.unmount();
    });

    it("shows the CSV only when the scope has spectra", async () => {
        const { wrapper } = await openPanel();
        expect(drawer().querySelector("a.series")).toBeNull();
        wrapper.unmount();

        forgetPayloads();
        const csv = {
            url: "http://testserver/api/explorer/series.csv?ids=x&lang=en",
            path: "/api/explorer/series.csv?ids=x&lang=en",
        };
        answer = () =>
            jsonResponse(
                sharePayload({
                    links: { ...sharePayload().links, seriesCsv: csv },
                }),
            );
        const again = await openPanel();
        const link = drawer().querySelector("a.series");
        expect(link?.getAttribute("href")).toBe(csv.path);
        expect(link?.hasAttribute("download")).toBe(true);
        again.wrapper.unmount();
    });

    it("announces the package size", async () => {
        const { wrapper } = await openPanel();
        const link = drawer().querySelector("a.package");
        expect(link?.textContent).toContain("Data package (ZIP, 2.4 MB)");
        expect(link?.getAttribute("href")).toBe(
            sharePayload().links.export.path,
        );
        wrapper.unmount();
    });

    it("proposes one export per document over the limit", async () => {
        const perDocument = [
            {
                id: uuid(1),
                name: label("Ms 59"),
                url: "http://testserver/api/explorer/export?document=a",
                path: "/api/explorer/export?document=a",
            },
            {
                id: uuid(2),
                name: label("Ms 60"),
                url: "http://testserver/api/explorer/export?document=b",
                path: "/api/explorer/export?document=b",
            },
        ];
        answer = () =>
            jsonResponse(
                sharePayload({
                    export: {
                        files: 3000,
                        bytes: 600_000_000,
                        overLimit: true,
                        documents: perDocument,
                    },
                }),
            );
        const { wrapper } = await openPanel();

        expect(drawer().querySelector("a.package")).toBeNull();
        expect(drawer().textContent).toContain(
            "This package (600 MB) is over the export limit: export one document at a time.",
        );
        expect(links()).toMatchObject({
            "Ms 59": perDocument[0].path,
            "Ms 60": perDocument[1].path,
        });
        wrapper.unmount();
    });

    it("says the scope holds drafts", async () => {
        const drafts = sharePayload();
        drafts.scope = { ...drafts.scope, drafts: 2 };
        answer = () => jsonResponse(drafts);
        const { wrapper } = await openPanel();
        expect(drawer().textContent).toContain("Contains drafts (2)");
        wrapper.unmount();
    });

    it("shows the unavailable state on a 404", async () => {
        answer = () => jsonResponse({}, 404);
        const { wrapper } = await openPanel();
        expect(drawer().textContent).toContain(
            "These data are no longer available.",
        );
        expect(drawer().querySelector("a.package")).toBeNull();
        wrapper.unmount();
    });

    it("offers a retry on a service error", async () => {
        answer = () => jsonResponse({}, 503);
        const { wrapper } = await openPanel();
        expect(drawer().querySelector("button.retry")).not.toBeNull();
        wrapper.unmount();
    });

    it("copies the manifest's absolute URL and opens its site path", async () => {
        const { wrapper } = await openPanel();
        const copy = wrapper
            .findAllComponents(CopyButton)
            .find(
                (button) => button.props("label") === "Copy the manifest URL",
            );
        expect(copy?.props("text")).toBe(sharePayload().links.manifest.url);
        const opened = drawer().querySelector("a.manifest");
        expect(opened?.getAttribute("href")).toBe(
            sharePayload().links.manifest.path,
        );
        expect(opened?.getAttribute("target")).toBe("_blank");
        wrapper.unmount();
    });

    it("copies the share link of the Selection with its keys", async () => {
        const { wrapper } = await openPanel({ document: false, basket: [KEY] });
        const copy = wrapper
            .findAllComponents(CopyButton)
            .find((button) => button.props("label") === "Copy the share link");
        const shared = new URL(copy?.props("text") as string);
        expect(shared.searchParams.get("sel")).toBe(KEY);
        expect(shared.origin).toBe(window.location.origin);
        wrapper.unmount();
    });

    it("opens the manifest in Mirador only when a viewer is set", async () => {
        const without = await openPanel();
        expect(drawer().querySelector("a.mirador")).toBeNull();
        without.wrapper.unmount();

        const { wrapper } = await openPanel({ mirador: MIRADOR });
        const href = drawer().querySelector("a.mirador")?.getAttribute("href");
        expect(new URL(href as string).searchParams.get("manifest")).toBe(
            sharePayload().links.manifest.url,
        );
        wrapper.unmount();
    });
});
