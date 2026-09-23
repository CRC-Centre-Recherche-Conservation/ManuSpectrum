import { describe, it, expect } from "vitest";
import ko from "knockout";
import koMapping from "knockout-mapping";
import {
    catalogueFrom,
    licenseToStore,
    noticeParts,
    readLicense,
    reportParts,
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
    const localizedEntry = (extra = {}) => ({ name: "a.csv", title: localized(""), ...extra });

    function mountTile(entries) {
        const data = koMapping.fromJS({ node: entries });
        const tile = { data, _tileData: ko.observable(koMapping.toJSON(data)) };
        const dirty = ko.pureComputed(() => tile._tileData() !== koMapping.toJSON(data));
        const seen = [];
        dirty.subscribe((value) => seen.push(value));
        let arrayNotifications = 0;
        data.node.subscribe(() => (arrayNotifications += 1));
        let snapshotNotifications = 0;
        tile._tileData.subscribe(() => (snapshotNotifications += 1));
        return {
            data,
            tile,
            dirty,
            seen,
            arrayNotifications: () => arrayNotifications,
            snapshotNotifications: () => snapshotNotifications,
        };
    }

    it("adds the key to a mapped entry so the saved tile carries it", () => {
        const mounted = mountTile([localizedEntry()]);

        writeLicense(mounted.data.node()[0], { id: "CC0-1.0", url: "u" }, mounted.tile);

        expect(mounted.dirty()).toBe(true);
        expect(koMapping.toJS(mounted.data).node[0].license).toEqual({ id: "CC0-1.0", url: "u" });
    });

    it("never notifies the file array, and wakes the snapshot only for a new key", () => {
        const mounted = mountTile([localizedEntry()]);
        const entry = mounted.data.node()[0];

        writeLicense(entry, { id: "LicenseRef-custom", url: "", label: "T" }, mounted.tile);
        writeLicense(entry, { id: "LicenseRef-custom", url: "https://e.org/", label: "T" }, mounted.tile);
        writeLicense(entry, { id: "CC0-1.0", url: "u" }, mounted.tile);

        expect(mounted.arrayNotifications()).toBe(0);
        expect(mounted.snapshotNotifications()).toBe(1);
        expect(mounted.dirty()).toBe(true);
        expect(koMapping.toJS(mounted.data).node[0].license).toEqual({ id: "CC0-1.0", url: "u" });
    });

    it("replaces a licence the mapping turned into observables", () => {
        const mounted = mountTile([localizedEntry({ license: { id: "CC0-1.0", url: "u" } })]);

        writeLicense(mounted.data.node()[0], { id: "LicenseRef-custom", url: "https://e.org/", label: "T" }, mounted.tile);

        expect(mounted.dirty()).toBe(true);
        expect(mounted.arrayNotifications()).toBe(0);
        expect(koMapping.toJS(mounted.data).node[0].license).toEqual({
            id: "LicenseRef-custom",
            url: "https://e.org/",
            label: "T",
        });
    });

    it("writes nothing for a missing value", () => {
        const mounted = mountTile([localizedEntry()]);

        writeLicense(mounted.data.node()[0], null, mounted.tile);

        expect("license" in mounted.data.node()[0]).toBe(false);
        expect(mounted.dirty()).toBe(false);
    });
});

describe("readLicense", () => {
    it("follows a key another instance added to the entry", () => {
        const data = koMapping.fromJS({ node: [{ name: "a.csv" }] });
        const tile = { data, _tileData: ko.observable(koMapping.toJSON(data)) };
        const entry = data.node()[0];
        const shown = ko.pureComputed(() => readLicense(entry, tile)?.id);
        const seen = [];
        shown.subscribe((value) => seen.push(value));

        writeLicense(entry, { id: "CC0-1.0", url: "u" }, tile);
        writeLicense(entry, { id: "CC-BY-SA-4.0", url: "v" }, tile);

        expect(seen).toEqual(["CC0-1.0", "CC-BY-SA-4.0"]);
    });
});

describe("without a catalogue", () => {
    const none = catalogueFrom(undefined);

    it("stores nothing and names no licence", () => {
        expect(licenseToStore("CC0-1.0", "", "", none)).toBeNull();
        expect(noticeParts({ title: localized("T") }, none, "en")).toEqual([{ text: "T" }]);
    });
});

describe("reportParts", () => {
    it("names the file and its licence only", () => {
        const entry = { name: "recto.jpg", title: localized("Folio"), attribution: localized("BnF"), license: { id: "CC0-1.0" } };
        expect(reportParts(entry, catalogue)).toEqual([
            { text: "recto.jpg" },
            { text: "CC0 1.0", url: "https://creativecommons.org/publicdomain/zero/1.0/" },
        ]);
    });

    it("shows the default licence for a file without one", () => {
        expect(reportParts(koMapping.fromJS({ name: "a.csv" }), catalogue)).toEqual([
            { text: "a.csv" },
            { text: BY_SA.label, url: BY_SA.url },
        ]);
    });
});
