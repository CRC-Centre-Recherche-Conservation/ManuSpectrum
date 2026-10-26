import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import SafeHtml from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/SafeHtml.vue";

describe("SafeHtml", () => {
    it("keeps the allowed tags", () => {
        const wrapper = mount(SafeHtml, {
            props: {
                html: "<p>260 µm / <em>100 ms</em><sub>2</sub></p>",
                lang: "fr",
            },
        });
        expect(wrapper.html()).toContain("<em>100 ms</em>");
        expect(wrapper.attributes("lang")).toBe("fr");
    });

    it("strips scripts and event handlers", () => {
        const wrapper = mount(SafeHtml, {
            props: {
                html: '<p onclick="x()">a<script>alert(1)</script><img src=x onerror="y()"></p>',
                lang: "en",
            },
        });
        expect(wrapper.html()).not.toContain("script");
        expect(wrapper.html()).not.toContain("onerror");
        expect(wrapper.html()).not.toContain("onclick");
        expect(wrapper.html()).not.toContain("<img");
    });

    it("drops links and their addresses", () => {
        const wrapper = mount(SafeHtml, {
            props: {
                html: '<p><a href="javascript:alert(1)">see</a></p>',
                lang: "en",
            },
        });
        expect(wrapper.html()).not.toContain("<a");
        expect(wrapper.html()).not.toContain("javascript");
        expect(wrapper.text()).toContain("see");
    });
});
