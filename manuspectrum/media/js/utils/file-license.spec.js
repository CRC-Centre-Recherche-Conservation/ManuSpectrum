import { describe, it, expect } from "vitest";
import ko from "knockout";
import koMapping from "knockout-mapping";
import {
    catalogueFrom,
    licenseToStore,
    noticeParts,
    resolveLicense,
    writeLicense,
} from "./file-license";

const RAW = {
    default: "CC-BY-SA-4.0",
    custom: "LicenseRef-custom",
    licenses: [
        { id: "CC-BY-SA-4.0", url: "https://creativecommons.org/licenses/by-sa/4.0/", label: "CC BY-SA 4.0" },
        { id: "CC0-1.0", url: "https://creativecommons.org/publicdomain/zero/1.0/", label: "CC0 1.0" },
        { id: "LicenseRef-custom", url: "", label: "Other licence…" },
    ],
};
const catalogue = catalogueFrom(RAW);
const BY_SA = { id: "CC-BY-SA-4.0", label: "CC BY-SA 4.0", url: "https://creativecommons.org/licenses/by-sa/4.0/" };

const localized = (value) => ({ en: { value, direction: "ltr" } });

describe("catalogueFrom", () => {
    it("falls back to an empty catalogue that still names a default", () => {
        const empty = catalogueFrom(undefined);
        expect(empty.licenses).toEqual([]);
        expect(resolveLicense(undefined, empty)).toBeNull();
    });
});

describe("resolveLicense", () => {
    it("shows the default when the entry has no licence or an unknown id", () => {
        expect(resolveLicense(undefined, catalogue)).toEqual(BY_SA);
        expect(resolveLicense({ id: "GPL-3.0" }, catalogue)).toEqual(BY_SA);
    });

    it("shows the catalogue URL for a catalogue id, whatever is stored", () => {
        expect(resolveLicense({ id: "CC0-1.0", url: "javascript:alert(1)" }, catalogue).url).toBe(
            "https://creativecommons.org/publicdomain/zero/1.0/",
        );
    });

    it("keeps a custom licence with an http(s) URL and a label", () => {
        const custom = { id: "LicenseRef-custom", label: " Terms ", url: " https://example.org/t " };
        expect(resolveLicense(custom, catalogue)).toEqual({
            id: "LicenseRef-custom",
            label: "Terms",
            url: "https://example.org/t",
        });
    });

    it("falls back to the default for a custom licence without a web URL or label", () => {
        for (const url of ["javascript:alert(1)", "ftp://example.org", "", "https://"]) {
            expect(resolveLicense({ id: "LicenseRef-custom", label: "T", url }, catalogue)).toEqual(BY_SA);
        }
        expect(resolveLicense({ id: "LicenseRef-custom", label: " ", url: "https://e.org/" }, catalogue)).toEqual(BY_SA);
    });

    it("reads observables", () => {
        const license = { id: ko.observable("CC0-1.0"), url: ko.observable("") };
        expect(resolveLicense(license, catalogue).id).toBe("CC0-1.0");
    });
});

describe("noticeParts", () => {
    it("lists title, © attribution and the linked licence", () => {
        const entry = {
            title: localized("Folio 12r"),
            attribution: localized("BnF"),
            license: { id: "CC0-1.0" },
        };
        expect(noticeParts(entry, catalogue, "en")).toEqual([
            { text: "Folio 12r" },
            { text: "© BnF" },
            { text: "CC0 1.0", url: "https://creativecommons.org/publicdomain/zero/1.0/" },
        ]);
    });

    it("omits empty parts and does not double an attribution that already carries ©", () => {
        const entry = { title: localized("  "), attribution: localized("© CRC") };
        expect(noticeParts(entry, catalogue, "en")).toEqual([
            { text: "© CRC" },
            { text: BY_SA.label, url: BY_SA.url },
        ]);
    });

    it("survives the metadata Arches leaves null and a missing language", () => {
        const entry = { title: null, attribution: localized("BnF") };
        expect(noticeParts(entry, catalogue, "fr")).toEqual([{ text: BY_SA.label, url: BY_SA.url }]);
    });

    it("reads mapped observables", () => {
        const entry = koMapping.fromJS({ title: localized("T"), attribution: localized(""), license: { id: "CC0-1.0" } });
        expect(noticeParts(entry, catalogue, "en").map((part) => part.text)).toEqual(["T", "CC0 1.0"]);
    });
});

describe("licenseToStore", () => {
    it("stores id and url for a catalogue licence", () => {
        expect(licenseToStore("CC0-1.0", "ignored", "ignored", catalogue)).toEqual({
            id: "CC0-1.0",
            url: "https://creativecommons.org/publicdomain/zero/1.0/",
        });
    });

    it("stores the typed label and url for a custom licence", () => {
        expect(licenseToStore("LicenseRef-custom", " Terms ", " https://e.org/ ", catalogue)).toEqual({
            id: "LicenseRef-custom",
            label: "Terms",
            url: "https://e.org/",
        });
    });

    it("stores the default for an id outside the catalogue", () => {
        expect(licenseToStore("nope", "", "", catalogue)).toEqual({ id: BY_SA.id, url: BY_SA.url });
    });
});

describe("writeLicense", () => {
    it("adds the key to a mapped tile entry so the saved tile carries it", () => {
        const data = koMapping.fromJS({ node: [{ name: "a.csv", title: localized("") }] });
        const dirty = ko.computed(() => koMapping.toJSON(data));
        const before = dirty();

        writeLicense(data.node()[0], { id: "CC0-1.0", url: "u" }, data.node);

        expect(dirty()).not.toBe(before);
        expect(koMapping.toJS(data).node[0].license).toEqual({ id: "CC0-1.0", url: "u" });
    });

    it("replaces a licence the mapping turned into observables", () => {
        const data = koMapping.fromJS({ node: [{ name: "a.csv", license: { id: "CC0-1.0", url: "u" } }] });

        writeLicense(data.node()[0], { id: "LicenseRef-custom", url: "https://e.org/", label: "T" }, data.node);

        expect(koMapping.toJS(data).node[0].license).toEqual({ id: "LicenseRef-custom", url: "https://e.org/", label: "T" });
    });
});
