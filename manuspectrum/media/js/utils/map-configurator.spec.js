/**
 * Vitest unit spec — utils/map-configurator.js (shadow of the Arches core
 * project hook that `viewmodels/map.js` calls around its map `load` handler).
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

const { archesStub } = vi.hoisted(() => ({
    archesStub: { mapboxApiKey: "", activeLanguage: "en" },
}));

vi.mock("arches", () => ({ default: archesStub }));
vi.mock("mapbox-gl-geocoder", () => ({
    default: class MapboxGeocoder {},
}));

import MapboxGeocoder from "mapbox-gl-geocoder";
import mapConfigurator, { labelField } from "utils/map-configurator";
import { validate } from "mapbox-gl/dist/style-spec/index.es.js";

import positron from "../../../constants/openfreemap_positron_layers.json";

class FakeMap {
    constructor() {
        this.added = [];
        this.layers = [];
        this.set = [];
    }
    getStyle() {
        return { layers: this.layers };
    }
    setLayoutProperty(id, name, value) {
        this.set.push([id, name, value]);
    }
    setStyle(style, options) {
        this.styled = [style, options];
    }
    addControl(control, position) {
        this.added.push([control, position]);
        return this;
    }
}

describe("map-configurator", () => {
    beforeEach(() => {
        archesStub.mapboxApiKey = "";
        archesStub.activeLanguage = "en";
    });

    it("skips the MapboxGeocoder without a Mapbox key and keeps the other controls", () => {
        const map = new FakeMap();
        const navigation = { name: "navigation" };
        mapConfigurator.preConfig(map);
        map.addControl(navigation, "top-left");
        const result = map.addControl(new MapboxGeocoder(), "top-right");
        expect(map.added).toEqual([[navigation, "top-left"]]);
        expect(result).toBe(map);
    });

    it("adds the MapboxGeocoder when a Mapbox key is set", () => {
        archesStub.mapboxApiKey = "pk.example";
        const map = new FakeMap();
        const geocoder = new MapboxGeocoder();
        mapConfigurator.preConfig(map);
        map.addControl(geocoder, "top-right");
        expect(map.added).toEqual([[geocoder, "top-right"]]);
    });

    it("puts the map back as it was in postConfig", () => {
        const map = new FakeMap();
        mapConfigurator.preConfig(map);
        expect(Object.prototype.hasOwnProperty.call(map, "addControl")).toBe(
            true,
        );
        mapConfigurator.postConfig(map);
        expect(Object.prototype.hasOwnProperty.call(map, "addControl")).toBe(
            false,
        );
        const geocoder = new MapboxGeocoder();
        map.addControl(geocoder, "top-right");
        expect(map.added).toEqual([[geocoder, "top-right"]]);
    });

    describe("basemap labels", () => {
        const english = ["coalesce", ["get", "name_en"], ["get", "name"]];
        const nested = [
            "case",
            ["has", "name:nonlatin"],
            ["concat", ["get", "name:latin"], "\n", ["get", "name:nonlatin"]],
            english,
        ];

        it("labelField leaves English and other languages alone", () => {
            expect(labelField("en", english)).toBe(english);
            expect(labelField("de", english)).toBe(english);
            expect(labelField(undefined, english)).toBe(english);
        });

        it("labelField puts name:fr first on a French page and keeps the formatting", () => {
            expect(labelField("fr", english)).toEqual([
                "coalesce",
                ["get", "name:fr"],
                english,
            ]);
            expect(labelField("fr-FR", nested)).toEqual([
                "coalesce",
                ["get", "name:fr"],
                nested,
            ]);
        });

        it("labelField ignores an expression that reads no name", () => {
            const ref = ["to-string", ["get", "ref"]];
            expect(labelField("fr", ref)).toBe(ref);
            expect(labelField("fr", undefined)).toBe(undefined);
        });

        const FONT = ["Noto Sans Regular"];

        const fakeMapOf = (layers) => {
            const map = new FakeMap();
            map.layers = layers;
            return map;
        };

        it("postConfig rewrites only the name symbol layers of the basemap on a French page", () => {
            archesStub.activeLanguage = "fr";
            const map = fakeMapOf([
                {
                    id: "a",
                    type: "symbol",
                    source: "openfreemap",
                    layout: { "text-field": english, "text-font": FONT },
                },
                {
                    id: "ref",
                    type: "symbol",
                    source: "openfreemap",
                    layout: {
                        "text-field": ["to-string", ["get", "ref"]],
                        "text-font": FONT,
                    },
                },
                {
                    id: "icon",
                    type: "symbol",
                    source: "openfreemap",
                    layout: {},
                },
                {
                    id: "other",
                    type: "symbol",
                    source: "resources",
                    layout: { "text-field": english, "text-font": FONT },
                },
                { id: "fill", type: "fill", source: "openfreemap", paint: {} },
            ]);
            mapConfigurator.preConfig(map);
            mapConfigurator.postConfig(map);
            expect(map.set).toEqual([
                ["a", "text-field", ["coalesce", ["get", "name:fr"], english]],
            ]);
        });

        it("labelField does not wrap a label twice", () => {
            const once = labelField("fr", english);
            expect(labelField("fr", once)).toBe(once);
        });

        it("a setStyle after postConfig reaches the map with French labels, once", () => {
            archesStub.activeLanguage = "fr";
            const map = fakeMapOf([]);
            mapConfigurator.postConfig(map);
            const vendored = JSON.parse(JSON.stringify(positron));
            map.setStyle({ version: 8, layers: vendored }, { diff: false });
            const [style, options] = map.styled;
            expect(options).toEqual({ diff: false });
            const labels = style.layers.filter(
                (layer) => layer.layout && layer.layout["text-field"],
            );
            const french = labels.filter(
                (layer) => layer.layout["text-field"][0] === "coalesce",
            );
            expect(french.length).toBeGreaterThan(10);
            const first = JSON.parse(JSON.stringify(style.layers));
            map.setStyle(style);
            expect(map.styled[0].layers).toEqual(first);
            expect(vendored).toEqual(positron);
        });

        it("a setStyle with a URL or on an English page goes through untouched", () => {
            archesStub.activeLanguage = "fr";
            const frMap = fakeMapOf([]);
            mapConfigurator.postConfig(frMap);
            frMap.setStyle("https://style.example/s.json");
            expect(frMap.styled[0]).toBe("https://style.example/s.json");
            archesStub.activeLanguage = "en";
            const enMap = fakeMapOf([]);
            mapConfigurator.postConfig(enMap);
            const style = { version: 8, layers: positron };
            enMap.setStyle(style);
            expect(enMap.styled[0].layers).toEqual(positron);
        });

        it("postConfig sets no label on an English page", () => {
            const map = fakeMapOf([
                {
                    id: "a",
                    type: "symbol",
                    source: "openfreemap",
                    layout: { "text-field": english, "text-font": FONT },
                },
            ]);
            mapConfigurator.postConfig(map);
            expect(map.set).toEqual([]);
        });

        describe("symbol layers without a text-font", () => {
            const clusterCount = {
                id: "resources-cluster-count-1",
                type: "symbol",
                source: "resources",
                layout: { "text-field": "{total}", "text-size": 10 },
            };
            const withFont = {
                id: "kept",
                type: "symbol",
                source: "openfreemap",
                layout: {
                    "text-field": english,
                    "text-font": ["Noto Sans Bold"],
                },
            };
            const icon = {
                id: "icon",
                type: "symbol",
                source: "resources",
                layout: { "icon-image": "pin" },
            };
            const fonts = new Set(
                positron.flatMap((layer) =>
                    layer.layout && layer.layout["text-font"]
                        ? [layer.layout["text-font"][0]]
                        : [],
                ),
            );

            it("the fallback is a font the basemap style uses", () => {
                const map = fakeMapOf([clusterCount]);
                mapConfigurator.postConfig(map);
                expect(fonts.has(map.set[0][2][0])).toBe(true);
            });

            it.each(["en", "fr"])(
                "postConfig sets it on the layers that lack one, on a %s page",
                (language) => {
                    archesStub.activeLanguage = language;
                    const map = fakeMapOf([clusterCount, withFont, icon]);
                    mapConfigurator.postConfig(map);
                    expect(
                        map.set.filter(([, name]) => name === "text-font"),
                    ).toEqual([
                        ["resources-cluster-count-1", "text-font", FONT],
                    ]);
                },
            );

            it.each(["en", "fr"])(
                "a setStyle gives it to the layers that lack one, on a %s page",
                (language) => {
                    archesStub.activeLanguage = language;
                    const map = fakeMapOf([]);
                    mapConfigurator.postConfig(map);
                    const layers = [clusterCount, withFont, icon];
                    map.setStyle({ version: 8, layers });
                    const [counted, kept, pin] = map.styled[0].layers;
                    expect(counted.layout["text-font"]).toEqual(FONT);
                    expect(kept.layout["text-font"]).toEqual([
                        "Noto Sans Bold",
                    ]);
                    expect(pin.layout["text-font"]).toBeUndefined();
                    expect(clusterCount.layout["text-font"]).toBeUndefined();
                },
            );
        });

        it("the rewritten vendored layers are a valid mapbox-gl 1.13 style", () => {
            const map = fakeMapOf(JSON.parse(JSON.stringify(positron)));
            archesStub.activeLanguage = "fr";
            mapConfigurator.postConfig(map);
            expect(map.set.length).toBeGreaterThan(10);
            const byId = new Map(map.set.map(([id, , value]) => [id, value]));
            const layers = map.layers.map((layer) =>
                byId.has(layer.id)
                    ? {
                          ...layer,
                          layout: {
                              ...layer.layout,
                              "text-field": byId.get(layer.id),
                          },
                      }
                    : layer,
            );
            const style = {
                version: 8,
                sources: {
                    openfreemap: {
                        type: "vector",
                        url: "https://tiles.openfreemap.org/planet",
                    },
                },
                sprite: "https://tiles.openfreemap.org/sprites/ofm_f384/ofm",
                glyphs: "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf",
                layers,
            };
            expect(validate(style)).toEqual([]);
        });
    });
});
