import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import FileOnlyPreview from "@/manuspectrum/pages/AnalysisExplorer/viewers/FileOnlyPreview.vue";

import {
    analysisPayload,
    fileEntry,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

function mountPreview(downloadUrl: string) {
    return mount(FileOnlyPreview, {
        props: {
            file: fileEntry({ dataKind: "file", name: "raw.mca", downloadUrl }),
            analysis: analysisPayload(),
        },
    });
}

describe("FileOnlyPreview", () => {
    it("links the file for download", () => {
        const wrapper = mountPreview("http://testserver/files/raw.mca");
        expect(wrapper.find("a.download").attributes("href")).toBe(
            "http://testserver/files/raw.mca",
        );
    });

    it("offers no download link for an address that is not http or https", () => {
        const wrapper = mountPreview("javascript:alert(1)");
        expect(wrapper.find("a.download").exists()).toBe(false);
    });
});
