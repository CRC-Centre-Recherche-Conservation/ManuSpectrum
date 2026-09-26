import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";

import DocumentCard from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/DocumentCard.vue";

import {
    documentHit,
    label,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

describe("DocumentCard", () => {
    it("shows what helps to find a document: shelfmark, holding, dates, type, description, counts", () => {
        const hit = documentHit(3, {
            shelfmark: label("Latin 8055"),
            holding: label("BnF"),
            dates: { start: "1301", end: "1400" },
            documentType: label("Manuscript"),
            description: label("Psalter with gilded initials."),
            unpublished: true,
        });
        const wrapper = mount(DocumentCard, { props: { hit, href: "?doc=x" } });
        expect(wrapper.find(".name").text()).toBe("Manuscript 3");
        expect(wrapper.find(".shelfmark").text()).toBe("Latin 8055");
        expect(wrapper.find(".facts").text()).toContain("BnF");
        expect(wrapper.find(".facts").text()).toContain("1301 – 1400");
        expect(wrapper.find(".facts").text()).toContain("Manuscript");
        expect(wrapper.find(".description").text()).toBe(
            "Psalter with gilded initials.",
        );
        expect(wrapper.find(".meta").text()).toContain("3 analyses");
        expect(wrapper.find(".meta").text()).toContain("Draft");
    });

    it("leaves out the fields a document does not have", () => {
        const wrapper = mount(DocumentCard, {
            props: { hit: documentHit(1), href: "?doc=x" },
        });
        expect(wrapper.find(".shelfmark").exists()).toBe(false);
        expect(wrapper.find(".facts").exists()).toBe(false);
        expect(wrapper.find(".description").exists()).toBe(false);
    });

    it("keeps a neutral placeholder when the thumbnail does not load", async () => {
        const wrapper = mount(DocumentCard, {
            props: { hit: documentHit(1), href: "?doc=x" },
        });
        await wrapper.find("img").trigger("error");
        expect(wrapper.find("img").exists()).toBe(false);
        expect(wrapper.find(".thumbnail").exists()).toBe(true);
    });

    it("does not ask again in this tab for a thumbnail that failed", async () => {
        const first = mount(DocumentCard, {
            props: { hit: documentHit(2), href: "?doc=x" },
        });
        await first.find("img").trigger("error");
        const again = mount(DocumentCard, {
            props: { hit: documentHit(2), href: "?doc=x" },
        });
        expect(again.find("img").exists()).toBe(false);
        const other = mount(DocumentCard, {
            props: { hit: documentHit(4), href: "?doc=y" },
        });
        expect(other.find("img").exists()).toBe(true);
    });

    it("draws no thumbnail from an address outside http(s)", () => {
        const wrapper = mount(DocumentCard, {
            props: {
                hit: { ...documentHit(5), thumbnail: "javascript:alert(1)" },
                href: "?doc=x",
            },
        });
        expect(wrapper.find("img").exists()).toBe(false);
    });
});
